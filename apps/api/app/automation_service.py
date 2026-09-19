"""Queue and execute scheduler work without duplicating compliance domain rules."""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError, OperationalError

from .auth import aware, now
from .automation_models import ScheduledJob
from .compliance_states import CLOSED_STATES, is_open
from .integration_security import IntegrationError
from .models import (
    AuditEvent,
    AutomationReceipt,
    Compliance,
    ComplianceSnapshot,
    Document,
    Notification,
    Organization,
    Task,
    Workspace,
    utcnow,
)

SCAN_TYPES = (
    "COMPLIANCE_GENERATION_SCAN",
    "NEXT_CYCLE_SCAN",
    "REMINDER_DUE_SCAN",
    "OVERDUE_COMPLIANCE_SCAN",
    "TASK_OVERDUE_SCAN",
    "DOCUMENT_EXPIRY_SCAN",
)
RETRYABLE_CODES = {"RATE_LIMITED", "PROVIDER_UNAVAILABLE", "TIMEOUT", "TEMPORARY_DATABASE_CONTENTION", "SECRET_STORE_UNAVAILABLE"}


def queue_job(db, tenant_id: str, job_type: str, idempotency_key: str, *, entity_type: str = "Workspace",
              entity_id: str = "", scheduled_for: datetime | None = None, payload: dict | None = None,
              max_attempts: int = 5) -> tuple[ScheduledJob, bool]:
    """Create durable work once; callers may safely repeat the same transaction."""
    existing = db.scalar(select(ScheduledJob).where(
        ScheduledJob.tenant_id == tenant_id,
        ScheduledJob.idempotency_key == idempotency_key,
    ))
    if existing:
        return existing, True
    row = ScheduledJob(
        tenant_id=tenant_id,
        job_type=job_type,
        entity_type=entity_type,
        entity_id=entity_id,
        idempotency_key=idempotency_key,
        payload=json.dumps(payload or {}, separators=(",", ":"), sort_keys=True),
        scheduled_for=scheduled_for or now(),
        max_attempts=max_attempts,
    )
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
        return row, False
    except IntegrityError:
        existing = db.scalar(select(ScheduledJob).where(
            ScheduledJob.tenant_id == tenant_id,
            ScheduledJob.idempotency_key == idempotency_key,
        ))
        if not existing:
            raise
        return existing, True


def tenant_ids(db) -> list[str]:
    workspace_ids = set(db.scalars(select(Workspace.id)).all())
    workspace_ids.update(db.scalars(select(Organization.tenant_id).distinct()).all())
    return sorted(value for value in workspace_ids if value)


def schedule_scans(db, at: datetime | None = None) -> dict[str, int]:
    """Enqueue current catch-up scans. Re-running the scheduler creates no duplicates."""
    at = at or now()
    bucket = aware(at).astimezone(timezone.utc).date().isoformat()
    created = 0
    replayed = 0
    for tenant_id in tenant_ids(db):
        for job_type in SCAN_TYPES:
            _, duplicate = queue_job(db, tenant_id, job_type, f"scan:{job_type}:{bucket}", scheduled_for=at)
            replayed += int(duplicate)
            created += int(not duplicate)
    db.commit()
    return {"created": created, "replayed": replayed, "tenants": len(tenant_ids(db))}


def queue_applicability_reevaluation(db, tenant_id: str, organization_id: str, fact_revision: str) -> tuple[ScheduledJob, bool]:
    return queue_job(
        db,
        tenant_id,
        "APPLICABILITY_REEVALUATION",
        f"applicability:{organization_id}:{fact_revision}",
        entity_type="Organization",
        entity_id=organization_id,
        payload={"organization_id": organization_id},
    )


def claim_job(db, worker_id: str, *, at: datetime | None = None, lease_seconds: int = 300) -> ScheduledJob | None:
    """Claim one due row. PostgreSQL locks candidates; CAS remains the final guard on every dialect."""
    at = at or now()
    due = or_(
        and_(ScheduledJob.status.in_(("PENDING", "RETRY")),
             or_(ScheduledJob.next_attempt_at.is_(None), ScheduledJob.next_attempt_at <= at)),
        and_(ScheduledJob.status == "RUNNING", ScheduledJob.lease_expires_at <= at),
    )
    query = select(ScheduledJob.id).where(
        due,
        ScheduledJob.scheduled_for <= at,
    ).order_by(ScheduledJob.scheduled_for, ScheduledJob.created_at).limit(20)
    if db.bind and db.bind.dialect.name == "postgresql":
        query = query.with_for_update(skip_locked=True)
    for identifier in db.scalars(query).all():
        claimed = db.execute(update(ScheduledJob).where(
            ScheduledJob.id == identifier,
            or_(
                and_(ScheduledJob.status.in_(("PENDING", "RETRY")),
                     or_(ScheduledJob.next_attempt_at.is_(None), ScheduledJob.next_attempt_at <= at)),
                and_(ScheduledJob.status == "RUNNING", ScheduledJob.lease_expires_at <= at),
            ),
        ).values(
            status="RUNNING",
            lease_owner=worker_id,
            lease_expires_at=at + timedelta(seconds=lease_seconds),
            started_at=at,
            completed_at=None,
            attempt_count=ScheduledJob.attempt_count + 1,
            updated_at=at,
        ).execution_options(synchronize_session=False))
        db.commit()
        if claimed.rowcount == 1:
            db.expire_all()
            return db.get(ScheduledJob, identifier)
    return None


def emit_notice(db, tenant_id: str, event_key: str, event_type: str, title: str, message: str, kind: str) -> bool:
    scoped_key = f"{tenant_id}:{event_key}"
    if db.scalar(select(AutomationReceipt.id).where(AutomationReceipt.event_key == scoped_key)):
        return False
    try:
        with db.begin_nested():
            db.add(AutomationReceipt(tenant_id=tenant_id, event_key=scoped_key, event_type=event_type))
            db.add(Notification(tenant_id=tenant_id, title=title, message=message, kind=kind))
            db.flush()
        return True
    except IntegrityError:
        return False


def _generation_scan(db, job, today: date):
    from .runtime_cycles import generate_due_instances
    generated = 0
    review = 0
    for organization in db.scalars(select(Organization).where(
        Organization.tenant_id == job.tenant_id,
        Organization.status == "ACTIVE",
    )).all():
        items, warnings = generate_due_instances(db, job.tenant_id, organization, as_of=today)
        generated += len(items)
        review += len(warnings)
    return {"generated": generated, "requires_review": review}


def _next_cycle_scan(db, job, today: date):
    from .compliance_template_schema import TemplateConfiguration
    from .runtime_cycles import generate_next_cycle
    generated = replayed = 0
    sources = db.scalars(select(Compliance).join(ComplianceSnapshot, ComplianceSnapshot.compliance_id == Compliance.id).where(
        Compliance.tenant_id == job.tenant_id,
        Compliance.status == "COMPLETED",
    )).all()
    for source in sources:
        snapshot = db.get(ComplianceSnapshot, source.id)
        config = TemplateConfiguration.model_validate_json(snapshot.configuration)
        if config.recurrence.frequency in {"ONE_TIME", "EVENT_BASED"}:
            continue
        organization = db.scalar(select(Organization).where(
            Organization.id == source.organization_id,
            Organization.tenant_id == job.tenant_id,
        ))
        if not organization:
            continue
        try:
            _, duplicate = generate_next_cycle(db, job.tenant_id, organization, source)
            generated += int(not duplicate)
            replayed += int(duplicate)
        except HTTPException as error:
            if error.status_code not in (409, 422):
                raise
    return {"generated": generated, "replayed": replayed}


def _reminder_scan(db, job, today: date):
    from .runtime_cycles import dispatch_due_reminders
    return {"queued": dispatch_due_reminders(db, job.tenant_id, today)}


def _overdue_compliance_scan(db, job, today: date):
    changed = 0
    for item in db.scalars(select(Compliance).where(
        Compliance.tenant_id == job.tenant_id,
        Compliance.statutory_deadline < today,
    )).all():
        if item.status in CLOSED_STATES or not is_open(item.status):
            continue
        if item.status != "OVERDUE":
            previous = item.status
            item.status = "OVERDUE"
            item.updated_at = utcnow()
            db.add(AuditEvent(tenant_id=job.tenant_id, actor_name="Automation worker", action="COMPLIANCE_OVERDUE",
                entity_type="Compliance", entity_id=item.id, summary=f"{previous} -> OVERDUE at stored deadline {item.statutory_deadline}"))
            changed += 1
        emit_notice(db, job.tenant_id, f"compliance-overdue:{item.id}:{item.statutory_deadline}", "COMPLIANCE_OVERDUE",
            f"{item.code} is overdue", f"{item.title} was due on {item.statutory_deadline.isoformat()}.", "WARNING")
    return {"overdue": changed}


def _task_overdue_scan(db, job, today: date):
    produced = 0
    for task in db.scalars(select(Task).where(
        Task.tenant_id == job.tenant_id,
        Task.status != "DONE",
        Task.due_at < today,
    )).all():
        produced += int(emit_notice(db, job.tenant_id, f"task-overdue:{task.id}:{task.due_at}", "TASK_OVERDUE",
            "Task overdue", f"{task.title} was due on {task.due_at.isoformat()}.", "WARNING"))
    return {"events": produced}


def _document_expiry_scan(db, job, today: date):
    from .document_service import genuine_file
    produced = 0
    threshold = max(1, min(365, int(os.getenv("DOCUMENT_EXPIRY_NOTICE_DAYS", "30"))))
    for document in db.scalars(select(Document).where(Document.tenant_id == job.tenant_id)).all():
        blob = genuine_file(db, document, must_be_valid=False)
        if not blob or not blob.expiry_at:
            continue
        days = (blob.expiry_at - today).days
        state = "EXPIRED" if days < 0 else "EXPIRING_SOON" if days <= threshold else "VALID"
        if state == "VALID":
            continue
        produced += int(emit_notice(db, job.tenant_id, f"document-expiry:{document.id}:{blob.version_id}:{state}", "DOCUMENT_EXPIRY",
            "Document expired" if state == "EXPIRED" else "Document expiry approaching",
            f"{document.name} {'expired' if state == 'EXPIRED' else 'expires'} on {blob.expiry_at.isoformat()}.", "DOCUMENT"))
    return {"events": produced}


def _applicability(db, job, _today):
    from .runtime_decisions import evaluate_organization
    organization_id = json.loads(job.payload).get("organization_id")
    organization = db.scalar(select(Organization).where(
        Organization.id == organization_id,
        Organization.tenant_id == job.tenant_id,
    ))
    if not organization:
        raise HTTPException(404, "Organization not found")
    return {"evaluated": len(evaluate_organization(db, job.tenant_id, organization))}


HANDLERS = {
    "COMPLIANCE_GENERATION_SCAN": _generation_scan,
    "NEXT_CYCLE_SCAN": _next_cycle_scan,
    "REMINDER_DUE_SCAN": _reminder_scan,
    "OVERDUE_COMPLIANCE_SCAN": _overdue_compliance_scan,
    "TASK_OVERDUE_SCAN": _task_overdue_scan,
    "DOCUMENT_EXPIRY_SCAN": _document_expiry_scan,
    "APPLICABILITY_REEVALUATION": _applicability,
}


def execute_job(db, job: ScheduledJob, today: date | None = None) -> dict:
    if job.job_type not in HANDLERS:
        raise ValueError("Unsupported scheduled job type")
    db.info.update(actor_id=None, actor_name="Automation worker", job_id=job.id, tenant_id=job.tenant_id)
    # The job's stored tenant is authoritative. Every handler repeats it in database predicates.
    return HANDLERS[job.job_type](db, job, today or date.today())


def error_code(error: Exception) -> tuple[str, bool]:
    if isinstance(error, IntegrationError):
        return error.code, error.code in RETRYABLE_CODES
    if isinstance(error, OperationalError):
        return "TEMPORARY_DATABASE_CONTENTION", True
    if isinstance(error, HTTPException):
        if error.status_code == 429 or error.status_code >= 500:
            return "RATE_LIMITED" if error.status_code == 429 else "TEMPORARY_PROVIDER_FAILURE", True
        return "INVALID_JOB_CONTEXT", False
    if isinstance(error, (TimeoutError, ConnectionError)):
        return "TIMEOUT", True
    if isinstance(error, (ValueError, TypeError, KeyError)):
        return "MALFORMED_PAYLOAD", False
    return "TEMPORARY_JOB_FAILURE", True


def finish_job(db, job: ScheduledJob, result: dict, *, completed_at: datetime | None = None, started_monotonic: float | None = None):
    import time
    completed_at = completed_at or now()
    job.status = "SUCCEEDED"
    job.completed_at = completed_at
    job.updated_at = completed_at
    job.lease_owner = ""
    job.lease_expires_at = None
    job.next_attempt_at = None
    job.last_error_code = ""
    job.result_summary = json.dumps(result, separators=(",", ":"), sort_keys=True)[:500]
    if started_monotonic is not None:
        job.duration_ms = max(0, int((time.monotonic() - started_monotonic) * 1000))


def fail_job(db, job: ScheduledJob, error: Exception, *, failed_at: datetime | None = None, started_monotonic: float | None = None):
    import random
    import time
    failed_at = failed_at or now()
    code, retryable = error_code(error)
    exhausted = job.attempt_count >= job.max_attempts
    job.status = "RETRY" if retryable and not exhausted else "DEAD_LETTER" if retryable else "FAILED"
    job.next_attempt_at = failed_at + timedelta(seconds=min(3600, 30 * 2 ** max(0, job.attempt_count - 1)) + random.randint(0, 15)) if job.status == "RETRY" else None
    job.completed_at = failed_at if job.status in {"FAILED", "DEAD_LETTER"} else None
    job.updated_at = failed_at
    job.lease_owner = ""
    job.lease_expires_at = None
    job.last_error_code = "JOB_RETRY_EXHAUSTED" if job.status == "DEAD_LETTER" else code
    job.result_summary = ""
    if started_monotonic is not None:
        job.duration_ms = max(0, int((time.monotonic() - started_monotonic) * 1000))


def retry_job(db, job: ScheduledJob):
    if job.status not in {"FAILED", "DEAD_LETTER", "CANCELLED"}:
        raise HTTPException(409, "Only terminal failed or cancelled jobs can be retried")
    job.status = "PENDING"
    job.attempt_count = 0
    job.next_attempt_at = now()
    job.completed_at = None
    job.lease_owner = ""
    job.lease_expires_at = None
    job.last_error_code = ""
    job.updated_at = now()


def metrics(db, tenant_id: str | None = None) -> dict:
    filters = [ScheduledJob.tenant_id == tenant_id] if tenant_id else []
    counts = dict(db.execute(select(ScheduledJob.status, func.count()).where(*filters).group_by(ScheduledJob.status)).all())
    durations = db.scalar(select(func.avg(ScheduledJob.duration_ms)).where(ScheduledJob.status == "SUCCEEDED", *filters)) or 0
    oldest = db.scalar(select(func.min(ScheduledJob.scheduled_for)).where(ScheduledJob.status.in_(("PENDING", "RETRY")), *filters))
    queue_age = max(0, int((now() - aware(oldest)).total_seconds())) if oldest else 0
    return {
        "processed": sum(counts.get(state, 0) for state in ("SUCCEEDED", "FAILED", "DEAD_LETTER")),
        "succeeded": counts.get("SUCCEEDED", 0),
        "failed": counts.get("FAILED", 0),
        "retried": db.scalar(select(func.count()).select_from(ScheduledJob).where(ScheduledJob.attempt_count > 1, *filters)) or 0,
        "dead_letter": counts.get("DEAD_LETTER", 0),
        "pending": counts.get("PENDING", 0) + counts.get("RETRY", 0),
        "average_duration_ms": round(float(durations), 2),
        "oldest_queue_age_seconds": queue_age,
        "by_status": counts,
    }
