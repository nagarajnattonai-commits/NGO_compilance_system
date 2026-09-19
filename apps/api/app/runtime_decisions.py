"""Persist material applicability changes alongside the existing rule engine."""
import hashlib
import json
from sqlalchemy import select, text
from .models import Organization, AuditEvent
from .runtime_models import ApplicabilityDecision, ApplicabilityOverride
from .compliance_template_schema import FIELDS, TemplateConfiguration

def serialize_writes(db, organization):
    connection = db.connection()
    if connection.dialect.name == "sqlite" and not connection.connection.driver_connection.in_transaction:
        db.execute(text("BEGIN IMMEDIATE"))
    db.execute(select(Organization.id).where(Organization.id == organization.id, Organization.tenant_id == organization.tenant_id).with_for_update()).first()

def latest_override(db, org, template_id):
    return db.scalar(select(ApplicabilityOverride).where(ApplicabilityOverride.tenant_id == org.tenant_id, ApplicabilityOverride.organization_id == org.id, ApplicabilityOverride.template_id == template_id).order_by(ApplicabilityOverride.created_at.desc(), ApplicabilityOverride.id.desc()).limit(1))

def material_facts(db, org):
    from .compliance_engine import organization_facts
    facts = organization_facts(db, org)
    facts.update({field: getattr(org, field, None) for field in FIELDS if not field.startswith(("organization.", "financial.")) and field not in facts})
    # Preserve a fingerprint for comparison without retaining sensitive identifiers.
    for key in ("pan", "tan"):
        if key in facts:
            facts[key] = {"present": bool(facts[key]), "sha256": hashlib.sha256(str(facts[key] or "").encode()).hexdigest()}
    encoded = json.dumps(facts, sort_keys=True, default=str, separators=(",", ":"))
    return encoded, hashlib.sha256(encoded.encode()).hexdigest()

def safe_explanations(result):
    value = json.loads(json.dumps(result, default=str))
    for group in value.get("groups", []):
        for condition in group["conditions"]:
            if condition["field"] in {"pan", "tan"}:
                condition["actual"] = "REDACTED"; condition["expected"] = "REDACTED"
    return value

def decision_data(row):
    return {"id": row.id, "template_id": row.template_id, "version_id": row.version_id, "evaluated_at": row.evaluated_at, "evaluated_by": row.evaluated_by, "rule_result": row.rule_result, "effective_result": row.effective_result, "override_id": row.override_key or None, "reason": row.reason, "comparison": row.comparison, "facts_hash": row.facts_hash, "explanations": json.loads(row.explanations)}

def evaluate_decision(db, org, master, version):
    from .compliance_engine import evaluate_rules, organization_facts
    result = evaluate_rules(TemplateConfiguration.model_validate_json(version.configuration), org, organization_facts(db, org))
    rule = "REQUIRES_REVIEW" if result.get("requires_review") else "APPLICABLE" if result["applicable"] else "NOT_APPLICABLE"
    override_event = latest_override(db, org, master.id)
    override = override_event if override_event and override_event.decision != "CLEAR_OVERRIDE" else None
    key = override_event.id if override_event else ""
    effective = {"FORCE_APPLICABLE": "APPLICABLE", "FORCE_NOT_APPLICABLE": "NOT_APPLICABLE"}.get(override.decision if override else "", rule)
    encoded, fingerprint = material_facts(db, org)
    previous = db.scalar(select(ApplicabilityDecision).where(ApplicabilityDecision.tenant_id == org.tenant_id, ApplicabilityDecision.organization_id == org.id, ApplicabilityDecision.template_id == master.id).order_by(ApplicabilityDecision.evaluated_at.desc(), ApplicabilityDecision.id.desc()).limit(1))
    comparison = "REQUIRES_REVIEW" if effective == "REQUIRES_REVIEW" else "STILL_APPLICABLE" if effective == "APPLICABLE" and previous and previous.effective_result == "APPLICABLE" else "NEWLY_APPLICABLE" if effective == "APPLICABLE" else "NO_LONGER_APPLICABLE" if previous and previous.effective_result == "APPLICABLE" else "STILL_NOT_APPLICABLE"
    if previous and (previous.version_id, previous.facts_hash, previous.override_key) == (version.id, fingerprint, key):
        saved = previous
    else:
        reason = override.reason if override and override.decision != "CLEAR_OVERRIDE" else result.get("requires_review") or "Configured rule evaluation"
        saved = ApplicabilityDecision(tenant_id=org.tenant_id, organization_id=org.id, template_id=master.id, version_id=version.id, evaluated_by=db.info.get("actor_id"), rule_result=rule, effective_result=effective, override_key=key, facts_hash=fingerprint, facts_snapshot=encoded, explanations=json.dumps(safe_explanations(result)), reason=reason, comparison=comparison)
        db.add(saved); db.flush()
        db.add(AuditEvent(tenant_id=org.tenant_id, actor_name=db.info.get("actor_name", "System"), action="APPLICABILITY_EVALUATED", entity_type="Organization", entity_id=org.id, summary=f"{master.code}: {rule} -> {effective}; {comparison}"))
    response = {**safe_explanations(result), "applicable": effective == "APPLICABLE", "rule_result": rule, "effective_result": effective, "override": override.decision if override else None, "override_reason": override.reason if override else None, "decision_id": saved.id, "comparison": comparison}
    if effective != "REQUIRES_REVIEW": response.pop("requires_review", None)
    return response

def evaluate_organization(db, tenant_id, organization):
    from .compliance_engine import published_templates
    if organization.tenant_id != tenant_id:
        from fastapi import HTTPException
        raise HTTPException(404, "Organization not found")
    serialize_writes(db, organization)
    return [{"id": m.id, "code": m.code, "name": TemplateConfiguration.model_validate_json(v.configuration).name, "version": v.version, **evaluate_decision(db, organization, m, v)} for m, v in published_templates(db)]
