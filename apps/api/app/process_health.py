"""Phase 27 liveness and backlog visibility for the separately supervised background processes.

The job queue is already durable in the database (idempotent enqueue, compare-and-swap
leases, retries and dead letters). This adds what was missing for operations: each
scheduler/worker records a heartbeat, and `python -m app.production_ops --check-workers`
fails when a role has stopped or due work is waiting too long.
"""
from __future__ import annotations

import logging
import os
import socket
from datetime import datetime, timedelta

from sqlalchemy import DateTime, Integer, String, func, select
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base, SessionLocal
from .models import utcnow

logger = logging.getLogger("setu.process_health")
ROLES = ("scheduler", "automation-worker", "integration-worker")


class ProcessHeartbeat(Base):
    __tablename__ = "process_heartbeats"
    instance_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    role: Mapped[str] = mapped_column(String(40), index=True)
    host: Mapped[str] = mapped_column(String(120), default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    last_processed: Mapped[int] = mapped_column(Integer, default=0)


def instance_id(role: str) -> str:
    return f"{role}:{socket.gethostname()}:{os.getpid()}"[:160]


def beat(role: str, processed: int = 0, instance: str | None = None, at: datetime | None = None) -> None:
    """Record liveness. A heartbeat failure is logged and never stops the process."""
    instance = instance or instance_id(role)
    try:
        with SessionLocal() as db:
            row = db.get(ProcessHeartbeat, instance)
            stamp = at or utcnow()
            if row is None:
                db.add(ProcessHeartbeat(instance_id=instance, role=role, host=socket.gethostname()[:120],
                                        started_at=stamp, last_seen_at=stamp, last_processed=processed))
            else:
                row.last_seen_at, row.last_processed = stamp, processed
            db.commit()
    except Exception:  # noqa: BLE001 - liveness must not take the worker down
        logger.warning("Could not record %s heartbeat", role)


def _aware(value: datetime | None) -> datetime | None:
    from .auth import aware
    return aware(value) if value else None


def status(db, at: datetime | None = None) -> dict:
    from .automation_models import ScheduledJob
    at = at or utcnow()
    roles = {}
    for role in ROLES:
        last = _aware(db.scalar(select(func.max(ProcessHeartbeat.last_seen_at)).where(ProcessHeartbeat.role == role)))
        roles[role] = None if last is None else int((at - last).total_seconds())
    due = (ScheduledJob.status.in_(("PENDING", "RETRY")) & (ScheduledJob.scheduled_for <= at)
           & ((ScheduledJob.next_attempt_at.is_(None)) | (ScheduledJob.next_attempt_at <= at)))
    oldest = _aware(db.scalar(select(func.min(ScheduledJob.scheduled_for)).where(due)))
    return {
        "seconds_since_heartbeat": roles,
        "due_jobs": db.scalar(select(func.count()).select_from(ScheduledJob).where(due)) or 0,
        "oldest_due_seconds": 0 if oldest is None else int((at - oldest).total_seconds()),
        "dead_letter_jobs": db.scalar(select(func.count()).select_from(ScheduledJob).where(ScheduledJob.status == "DEAD_LETTER")) or 0,
    }


def problems(result: dict, environment=None) -> list[str]:
    values = os.environ if environment is None else environment
    stale = int(values.get("WORKER_STALE_SECONDS", "300"))
    backlog = int(values.get("BACKLOG_MAX_AGE_SECONDS", "900"))
    required = [r.strip() for r in values.get("WORKER_REQUIRED_ROLES", ",".join(ROLES)).split(",") if r.strip()]
    found = []
    for role in required:
        age = result["seconds_since_heartbeat"].get(role)
        if age is None:
            found.append(f"{role}: no heartbeat recorded")
        elif age > stale:
            found.append(f"{role}: last heartbeat {age}s ago")
    if result["oldest_due_seconds"] > backlog:
        found.append(f"backlog: oldest due job waiting {result['oldest_due_seconds']}s")
    return found


def prune(db, older_than: timedelta = timedelta(days=7)) -> int:
    """Drop heartbeats of processes that stopped long ago (restarts create new instance ids)."""
    from sqlalchemy import delete
    return db.execute(delete(ProcessHeartbeat).where(ProcessHeartbeat.last_seen_at < utcnow() - older_than)).rowcount or 0
