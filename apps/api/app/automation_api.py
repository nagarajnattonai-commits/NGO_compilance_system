"""Platform operations API for scheduled jobs; payloads and secrets are never returned."""
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from .auth import CurrentUser, DB, aware
from .auth_policy import is_platform_admin
from .automation_models import ScheduledJob
from .automation_service import metrics, retry_job
from .models import AuditEvent, Workspace
from .permissions import has_permission

router = APIRouter(prefix="/api/v1/admin/automation", tags=["Automation operations"])


def require(user, action: str):
    if not is_platform_admin(user) or not has_permission(user, "scheduler." + action):
        raise HTTPException(403, "Platform scheduler permission is required")


def output(row: ScheduledJob, tenant_name: str = ""):
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "tenant_name": tenant_name,
        "job_type": row.job_type,
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "status": row.status,
        "attempt_count": row.attempt_count,
        "max_attempts": row.max_attempts,
        "scheduled_for": aware(row.scheduled_for),
        "started_at": aware(row.started_at) if row.started_at else None,
        "completed_at": aware(row.completed_at) if row.completed_at else None,
        "next_attempt_at": aware(row.next_attempt_at) if row.next_attempt_at else None,
        "lease_expires_at": aware(row.lease_expires_at) if row.lease_expires_at else None,
        "last_error_code": row.last_error_code,
        "duration_ms": row.duration_ms,
        "result_summary": row.result_summary,
        "correlation_id": row.correlation_id,
        "created_at": aware(row.created_at),
    }


@router.get("/jobs")
def jobs(db: DB, user: CurrentUser, status: str = "", job_type: str = "", tenant_id: str = "",
         page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100)):
    require(user, "view")
    filters = []
    if status:
        if status not in {"PENDING", "RUNNING", "SUCCEEDED", "FAILED", "RETRY", "DEAD_LETTER", "CANCELLED"}:
            raise HTTPException(422, "Invalid job status")
        filters.append(ScheduledJob.status == status)
    if job_type:
        filters.append(ScheduledJob.job_type == job_type[:80])
    if tenant_id:
        filters.append(ScheduledJob.tenant_id == tenant_id[:36])
    query = select(ScheduledJob).where(*filters)
    total = len(db.scalars(query.with_only_columns(ScheduledJob.id)).all())
    rows = db.scalars(query.order_by(ScheduledJob.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    names = {row.id: row.name for row in db.scalars(select(Workspace)).all()}
    return {"items": [output(row, names.get(row.tenant_id, "")) for row in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/metrics")
def job_metrics(db: DB, user: CurrentUser, tenant_id: str = ""):
    require(user, "view")
    return metrics(db, tenant_id[:36] or None)


@router.post("/jobs/{job_id}/retry")
def manual_retry(job_id: str, db: DB, user: CurrentUser):
    require(user, "manage")
    row = db.get(ScheduledJob, job_id)
    if not row:
        raise HTTPException(404, "Scheduled job not found")
    previous = row.status
    retry_job(db, row)
    db.add(AuditEvent(tenant_id=row.tenant_id, actor_name=user.name, action="SCHEDULED_JOB_RETRIED",
        entity_type="ScheduledJob", entity_id=row.id, summary=f"Manual retry requested from {previous}"))
    db.commit()
    return output(row, db.get(Workspace, row.tenant_id).name if db.get(Workspace, row.tenant_id) else "")
