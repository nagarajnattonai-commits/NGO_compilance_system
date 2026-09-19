"""Explicit, transaction-scoped scheduler entry points; no background loop."""
from datetime import date, timedelta
from fastapi import HTTPException
from sqlalchemy import select
from .models import AuditEvent, Compliance, ComplianceSnapshot, Document
from .organization_models import OrganizationRegistration
from .runtime_models import OrganizationEventFact, NextCycleGeneration
from .runtime_decisions import serialize_writes
from .compliance_template_schema import TemplateConfiguration

def certificate_expiry(db, tenant, organization_id, config):
    from .document_service import genuine_file
    if config.deadline.strategy != "CERTIFICATE_EXPIRY_MINUS_DAYS": return None
    registration = db.scalar(select(OrganizationRegistration).where(OrganizationRegistration.tenant_id == tenant, OrganizationRegistration.organization_id == organization_id, OrganizationRegistration.kind == config.deadline.document_type))
    if registration and registration.expiry_date:
        if registration.document_id:
            doc = db.get(Document, registration.document_id)
            blob = genuine_file(db, doc, must_be_valid=False) if doc and doc.tenant_id == tenant and doc.organization_id == organization_id else None
            if not blob: raise ValueError("Registration certificate must have an available original file")
            if blob.expiry_at and blob.expiry_at != registration.expiry_date: raise ValueError("Registration and certificate expiry disagree; review the source dates")
        return registration.expiry_date
    dates = set()
    for doc in db.scalars(select(Document).where(Document.tenant_id == tenant, Document.organization_id == organization_id, Document.category == config.deadline.document_type)):
        blob = genuine_file(db, doc, must_be_valid=False)
        if blob and blob.expiry_at: dates.add(blob.expiry_at)
    if len(dates) > 1: raise ValueError("Multiple certificate expiry dates; select the registration certificate explicitly")
    return next(iter(dates), None)

def generate_due_instances(db, tenant_id, organization, as_of=None, event_date=None, template_id=None):
    from .compliance_engine import published_templates, generate_master_plan
    serialize_writes(db, organization)
    templates = [(m,v) for m,v in published_templates(db) if template_id is None or m.id == template_id]
    event_templates = [(m,v) for m,v in templates if TemplateConfiguration.model_validate_json(v.configuration).deadline.strategy == "EVENT_DATE_PLUS_DAYS"]
    if event_date and len(event_templates) != 1: raise HTTPException(422, "Select a single event template and record its event fact")
    generated, review = [], []
    for master, version in templates:
        config = TemplateConfiguration.model_validate_json(version.configuration)
        key = config.deadline.event_key or master.code
        events = db.scalars(select(OrganizationEventFact).where(OrganizationEventFact.tenant_id == tenant_id, OrganizationEventFact.organization_id == organization.id, OrganizationEventFact.template_id == master.id, OrganizationEventFact.event_key == key).order_by(OrganizationEventFact.event_date)).all() if config.deadline.strategy == "EVENT_DATE_PLUS_DAYS" else []
        if event_date:
            events = [e for e in events if e.event_date == event_date]
            if config.deadline.strategy == "EVENT_DATE_PLUS_DAYS" and not events:
                if not db.info.get("actor_id"): raise HTTPException(422, "Capture an event fact before system generation")
                event = OrganizationEventFact(tenant_id=tenant_id, organization_id=organization.id, template_id=master.id, event_key=key, event_date=event_date, source="Explicit authenticated plan-generation request", created_by=db.info["actor_id"])
                db.add(event); db.flush(); events = [event]
                db.add(AuditEvent(tenant_id=tenant_id, actor_name=db.info.get("actor_name", "System"), action="ORGANIZATION_EVENT_CAPTURED", entity_type="Organization", entity_id=organization.id, summary=f"{key}: explicit request date {event_date}"))
        for value in [e.event_date for e in events] or [None]:
            items, errors = generate_master_plan(db, tenant_id, organization, as_of, value, template_ids={master.id})
            generated.extend(items); review.extend(errors)
    return generated, review

def generate_next_cycle(db, tenant_id, organization, source):
    from .compliance_engine import published_templates, calculate_deadline, generate_master_plan
    if source.tenant_id != tenant_id or source.organization_id != organization.id: raise HTTPException(404, "Compliance not found")
    serialize_writes(db, organization)
    receipt = db.get(NextCycleGeneration, source.id)
    if receipt and receipt.tenant_id == tenant_id and receipt.target_id: return db.get(Compliance, receipt.target_id), True
    snapshot = db.get(ComplianceSnapshot, source.id)
    if not snapshot: raise HTTPException(409, "A template snapshot is required for next-cycle generation")
    pair = next(((m,v) for m,v in published_templates(db) if m.id == snapshot.definition_id), None)
    if not pair: raise HTTPException(409, "Publish an active template before generating its next cycle")
    master, version = pair
    config = TemplateConfiguration.model_validate_json(version.configuration)
    if config.recurrence.frequency in {"ONE_TIME", "EVENT_BASED"}: raise HTTPException(409, "Capture a new event fact or use a recurring template")
    old_config = TemplateConfiguration.model_validate_json(snapshot.configuration)
    as_of = date.fromisoformat(snapshot.cycle.split(":")[-1]) + timedelta(days=1) if old_config.deadline.strategy in {"PERIOD_END_PLUS_DAYS", "FINANCIAL_YEAR_END_PLUS_DAYS"} else source.statutory_deadline + timedelta(days=1)
    try: dates = calculate_deadline(config, as_of, expiry=certificate_expiry(db, tenant_id, organization.id, config))
    except (ValueError, OverflowError) as error: raise HTTPException(422, str(error)) from None
    if dates["cycle"] == snapshot.cycle: raise HTTPException(409, "Capture renewed certificate expiry before generating another cycle")
    if dates["statutory_deadline"] <= source.statutory_deadline: raise HTTPException(409, "Review the changed recurrence; next cycle must advance the deadline")
    if not receipt:
        receipt = NextCycleGeneration(source_id=source.id, tenant_id=tenant_id, requested_by=db.info.get("actor_id")); db.add(receipt); db.flush()
    _, review = generate_master_plan(db, tenant_id, organization, as_of, template_ids={master.id})
    target_id = db.scalar(select(ComplianceSnapshot.compliance_id).where(ComplianceSnapshot.tenant_id == tenant_id, ComplianceSnapshot.organization_id == organization.id, ComplianceSnapshot.definition_id == master.id, ComplianceSnapshot.cycle == dates["cycle"]))
    if not target_id: raise HTTPException(409, review[0]["reason"] if review else "Template is not effectively applicable")
    receipt.target_id = target_id
    return db.get(Compliance, target_id), False

def dispatch_due_reminders(db, tenant_id, today=None):
    from .compliance_engine import dispatch_master_reminders
    connection = db.connection()
    if connection.dialect.name == "sqlite" and not connection.connection.driver_connection.in_transaction:
        from sqlalchemy import text
        db.execute(text("BEGIN IMMEDIATE"))
    return dispatch_master_reminders(db, tenant_id, today or date.today())
