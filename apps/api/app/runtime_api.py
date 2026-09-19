"""Tenant-authorized controls and complete runtime detail."""
import json
from datetime import date
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import Field
from sqlalchemy import select, or_
from .auth import CurrentUser
from .organization_profile import DB, Tenant, Strict, owned_org
from .models import AuditEvent, Compliance, ComplianceSnapshot, ComplianceReminder, Task, Submission, utcnow
from .schemas import ComplianceOut, TaskOut
from .runtime_models import ComplianceOwnership, OrganizationEventFact, ApplicabilityOverride, ApplicabilityDecision
from .runtime_membership import workspace_members
from .runtime_decisions import serialize_writes, latest_override, evaluate_organization, decision_data, material_facts
from .runtime_cycles import generate_due_instances, generate_next_cycle
from .compliance_engine import published_templates
from .compliance_template_schema import TemplateConfiguration
router = APIRouter(prefix="/api/v1", tags=["Compliance runtime"])

def admin(actor):
    if actor.role != "ADMIN": raise HTTPException(403, "Workspace administrator access is required")
def owned_compliance(db, tenant, identifier):
    row = db.scalar(select(Compliance).where(Compliance.id == identifier, Compliance.tenant_id == tenant))
    if not row: raise HTTPException(404, "Compliance not found")
    owned_org(db, tenant, row.organization_id)
    return row
def template_pair(db, identifier):
    pair = next(((m,v) for m,v in published_templates(db) if m.id == identifier), None)
    if not pair: raise HTTPException(404, "Published template not found")
    return pair
def event_data(row):
    return {"id": row.id, "template_id": row.template_id, "event_key": row.event_key, "event_date": row.event_date, "source": row.source, "created_by": row.created_by, "created_at": row.created_at}
class EventInput(Strict):
    template_id: str = Field(min_length=1, max_length=36)
    event_key: str = Field(min_length=1, max_length=80)
    event_date: date
    source: str = Field(min_length=3, max_length=500)
class OverrideInput(Strict):
    decision: Literal["FORCE_APPLICABLE", "FORCE_NOT_APPLICABLE", "CLEAR_OVERRIDE"]
    reason: str = Field(min_length=5, max_length=1000)
    expected_override_id: str | None = Field(default=None, max_length=36)
class OwnerInput(Strict):
    owner_id: str = Field(min_length=1, max_length=36)
    expected_owner_id: str | None = Field(default=None, max_length=36)
    reason: str = Field(min_length=3, max_length=500)

@router.get("/organizations/{organization_id}/events")
def events(organization_id: str, db: DB, tenant: Tenant):
    owned_org(db, tenant, organization_id)
    return [event_data(r) for r in db.scalars(select(OrganizationEventFact).where(OrganizationEventFact.tenant_id == tenant, OrganizationEventFact.organization_id == organization_id).order_by(OrganizationEventFact.created_at.desc())).all()]
@router.post("/organizations/{organization_id}/events", status_code=201)
def capture_event(organization_id: str, payload: EventInput, db: DB, tenant: Tenant, actor: CurrentUser):
    admin(actor); org = owned_org(db, tenant, organization_id); serialize_writes(db, org)
    master, version = template_pair(db, payload.template_id)
    config = TemplateConfiguration.model_validate_json(version.configuration)
    if config.deadline.strategy != "EVENT_DATE_PLUS_DAYS" or payload.event_key != (config.deadline.event_key or master.code):
        raise HTTPException(422, "Event key must match the published template event input")
    row = db.scalar(select(OrganizationEventFact).where(OrganizationEventFact.tenant_id == tenant, OrganizationEventFact.organization_id == org.id, OrganizationEventFact.template_id == master.id, OrganizationEventFact.event_key == payload.event_key, OrganizationEventFact.event_date == payload.event_date))
    if not row:
        row = OrganizationEventFact(tenant_id=tenant, organization_id=org.id, created_by=actor.id, **payload.model_dump()); db.add(row); db.flush()
        db.add(AuditEvent(tenant_id=tenant, actor_name=actor.name, action="ORGANIZATION_EVENT_CAPTURED", entity_type="Organization", entity_id=org.id, summary=f"Recorded {payload.event_key} on {payload.event_date}; source retained in event record"))
    db.commit(); return event_data(row)
@router.post("/organizations/{organization_id}/events/{event_id}/generate")
def generate_event(organization_id: str, event_id: str, db: DB, tenant: Tenant, actor: CurrentUser):
    admin(actor); org = owned_org(db, tenant, organization_id)
    event = db.scalar(select(OrganizationEventFact).where(OrganizationEventFact.id == event_id, OrganizationEventFact.tenant_id == tenant, OrganizationEventFact.organization_id == org.id))
    if not event: raise HTTPException(404, "Event not found")
    items, review = generate_due_instances(db, tenant, org, event_date=event.event_date, template_id=event.template_id)
    db.commit(); return {"generated_ids": [i.id for i in items], "requires_review": review}
@router.get("/organizations/{organization_id}/applicability-history")
def history(organization_id: str, db: DB, tenant: Tenant):
    org = owned_org(db, tenant, organization_id)
    return [decision_data(r) for r in db.scalars(select(ApplicabilityDecision).where(ApplicabilityDecision.tenant_id == tenant, ApplicabilityDecision.organization_id == org.id).order_by(ApplicabilityDecision.evaluated_at.desc(), ApplicabilityDecision.id.desc())).all()]
@router.post("/organizations/{organization_id}/templates/{template_id}/override")
def override(organization_id: str, template_id: str, payload: OverrideInput, db: DB, tenant: Tenant, actor: CurrentUser):
    admin(actor); org = owned_org(db, tenant, organization_id); serialize_writes(db, org)
    master, version = template_pair(db, template_id); previous = latest_override(db, org, template_id)
    if (previous.id if previous else None) != payload.expected_override_id: raise HTTPException(409, "Applicability override changed; reload before saving")
    row = ApplicabilityOverride(tenant_id=tenant, organization_id=org.id, template_id=master.id, version_id=version.id, actor_id=actor.id, decision=payload.decision, reason=payload.reason)
    db.add(row); db.flush()
    db.add(AuditEvent(tenant_id=tenant, actor_name=actor.name, action="APPLICABILITY_OVERRIDE_CLEARED" if payload.decision == "CLEAR_OVERRIDE" else "APPLICABILITY_OVERRIDE_CREATED", entity_type="Organization", entity_id=org.id, summary=f"{master.code}: {payload.decision}; {payload.reason}"[:280]))
    results = evaluate_organization(db, tenant, org); db.commit()
    return {"override_id": row.id, "results": results, "policy": "EXISTING_INSTANCES_RETAINED"}
@router.get("/compliances/{compliance_id}/owner-candidates")
def owner_candidates(compliance_id: str, db: DB, tenant: Tenant):
    owned_compliance(db, tenant, compliance_id)
    return [{"id": u.id, "name": u.name, "role": role} for u, role in workspace_members(db, tenant) if role != "VIEWER"]
@router.post("/compliances/{compliance_id}/owner")
def assign_owner(compliance_id: str, payload: OwnerInput, db: DB, tenant: Tenant, actor: CurrentUser):
    admin(actor); item = owned_compliance(db, tenant, compliance_id); org = owned_org(db, tenant, item.organization_id); serialize_writes(db, org)
    owner = next((u for u, role in workspace_members(db, tenant) if u.id == payload.owner_id and role != "VIEWER"), None)
    if not owner: raise HTTPException(422, "Owner must be an active authorized workspace member with write access")
    row = db.get(ComplianceOwnership, item.id)
    if (row.owner_id if row else None) != payload.expected_owner_id: raise HTTPException(409, "Owner changed; reload before assigning")
    previous = row.owner_id if row else "UNASSIGNED"
    if not row: row = ComplianceOwnership(compliance_id=item.id, tenant_id=tenant, owner_id=owner.id); db.add(row)
    row.owner_id, row.assigned_by, row.assigned_at, row.manual = owner.id, actor.id, utcnow(), True
    item.owner_name = owner.name; item.owner_initials = "".join(s[0] for s in owner.name.split())[:3]; item.updated_at = utcnow()
    snapshot = db.get(ComplianceSnapshot, item.id)
    if snapshot: snapshot.owner_required = False
    db.add(AuditEvent(tenant_id=tenant, actor_name=actor.name, action="COMPLIANCE_OWNER_REASSIGNED", entity_type="Compliance", entity_id=item.id, summary=f"Owner {previous} -> {owner.id}; {payload.reason}"[:280]))
    db.commit(); return ComplianceOut.model_validate(item)
@router.post("/compliances/{compliance_id}/next-cycle")
def next_cycle(compliance_id: str, db: DB, tenant: Tenant, actor: CurrentUser):
    admin(actor); source = owned_compliance(db, tenant, compliance_id); org = owned_org(db, tenant, source.organization_id)
    target, replayed = generate_next_cycle(db, tenant, org, source)
    if not replayed: db.add(AuditEvent(tenant_id=tenant, actor_name=actor.name, action="COMPLIANCE_NEXT_CYCLE_GENERATED", entity_type="Compliance", entity_id=source.id, summary="Next cycle linked to " + target.id))
    db.commit(); return {"compliance": ComplianceOut.model_validate(target), "replayed": replayed}
@router.get("/compliances/{compliance_id}/runtime-detail")
def runtime_detail(compliance_id: str, db: DB, tenant: Tenant):
    from .compliance_master import snapshot as snapshot_data
    from .document_models import DocumentEvidenceLink
    item = owned_compliance(db, tenant, compliance_id); org = owned_org(db, tenant, item.organization_id)
    frozen = db.get(ComplianceSnapshot, item.id); owner = db.get(ComplianceOwnership, item.id)
    candidates = {u.id: u for u, _ in workspace_members(db, tenant)}
    owner_valid = bool(owner and any(u.id == owner.owner_id and role != "VIEWER" for u, role in workspace_members(db, tenant)))
    tasks = db.scalars(select(Task).where(Task.tenant_id == tenant, Task.compliance_id == item.id)).all()
    submissions = db.scalars(select(Submission).where(Submission.tenant_id == tenant, Submission.compliance_id == item.id).order_by(Submission.submitted_at.desc())).all()
    links = db.scalars(select(DocumentEvidenceLink).where(DocumentEvidenceLink.tenant_id == tenant, DocumentEvidenceLink.organization_id == org.id, or_(DocumentEvidenceLink.compliance_id == item.id, DocumentEvidenceLink.task_id.in_([t.id for t in tasks]), DocumentEvidenceLink.submission_id.in_([s.id for s in submissions])))).all()
    decisions = db.scalars(select(ApplicabilityDecision).where(ApplicabilityDecision.tenant_id == tenant, ApplicabilityDecision.organization_id == org.id, ApplicabilityDecision.template_id == frozen.definition_id).order_by(ApplicabilityDecision.evaluated_at.desc(), ApplicabilityDecision.id.desc())).all() if frozen else []
    current = next((v.id for m,v in published_templates(db) if frozen and m.id == frozen.definition_id), None)
    override_events = db.scalars(select(ApplicabilityOverride).where(ApplicabilityOverride.tenant_id == tenant, ApplicabilityOverride.organization_id == org.id, ApplicabilityOverride.template_id == frozen.definition_id).order_by(ApplicabilityOverride.created_at.desc(), ApplicabilityOverride.id.desc())).all() if frozen else []
    override_row = override_events[0] if override_events and override_events[0].decision != "CLEAR_OVERRIDE" else None
    stale = bool(frozen and (not decisions or decisions[0].facts_hash != material_facts(db, org)[1] or decisions[0].version_id != current))
    entity_ids = [org.id, item.id] + [t.id for t in tasks] + [s.id for s in submissions] + [l.document_id for l in links]
    audit = db.scalars(select(AuditEvent).where(AuditEvent.tenant_id == tenant, AuditEvent.entity_id.in_(entity_ids)).order_by(AuditEvent.created_at.desc())).all()
    reminders = db.scalars(select(ComplianceReminder).where(ComplianceReminder.tenant_id == tenant, ComplianceReminder.compliance_id == item.id).order_by(ComplianceReminder.scheduled_for)).all()
    return {"compliance": ComplianceOut.model_validate(item), "organization": {"id": org.id, "name": org.name}, "snapshot": snapshot_data(item.id, db, tenant) if frozen else None,
        "owner": {"owner_id": owner.owner_id, "assigned_by": owner.assigned_by, "assigned_at": owner.assigned_at, "name": candidates[owner.owner_id].name if owner.owner_id in candidates else item.owner_name, "valid": owner_valid} if owner else None, "owner_required": not owner_valid,
        "decisions": [decision_data(d) for d in decisions], "requires_reevaluation": stale,
        "override": {"id": override_row.id, "decision": override_row.decision, "reason": override_row.reason, "created_at": override_row.created_at, "actor_id": override_row.actor_id} if override_row else None,
        "override_history": [{"id": r.id, "decision": r.decision, "reason": r.reason, "created_at": r.created_at, "actor_id": r.actor_id, "version_id": r.version_id} for r in override_events],
        "tasks": [TaskOut.model_validate(t) for t in tasks],
        "submissions": [{"id": s.id, "reference": s.acknowledgement_ref, "proof_document_id": s.proof_document_id, "submitted_at": s.submitted_at} for s in submissions],
        "evidence_links": [{"id": l.id, "document_id": l.document_id, "version_id": l.version_id, "submission_id": l.submission_id, "active": l.active} for l in links],
        "reminders": [{"id": r.id, "scheduled_for": r.scheduled_for, "sent_at": r.sent_at, "configuration": json.loads(r.configuration)} for r in reminders],
        "audit": [{"id": a.id, "action": a.action, "summary": a.summary, "actor_name": a.actor_name, "created_at": a.created_at} for a in audit]}
