"""Durable, tenant-scoped jobs used by the separately deployed scheduler and workers."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .models import uid, utcnow


class ScheduledJob(Base):
    __tablename__ = "scheduled_jobs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_scheduled_job_idempotency"),
        Index("ix_scheduled_job_claim", "status", "next_attempt_at", "scheduled_for"),
        Index("ix_scheduled_job_tenant_status", "tenant_id", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    job_type: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str] = mapped_column(String(60), default="Workspace")
    entity_id: Mapped[str] = mapped_column(String(36), default="")
    idempotency_key: Mapped[str] = mapped_column(String(220))
    payload: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    lease_owner: Mapped[str] = mapped_column(String(120), default="")
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    last_error_code: Mapped[str] = mapped_column(String(80), default="")
    result_summary: Mapped[str] = mapped_column(String(500), default="")
    correlation_id: Mapped[str] = mapped_column(String(36), default=uid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
