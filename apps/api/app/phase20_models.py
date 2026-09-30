"""Durable, tenant-scoped bulk import jobs and row outcomes."""
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .models import uid


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ImportJob(Base):
    __tablename__ = "import_jobs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "import_type", "file_sha256", name="uq_import_file_tenant_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("auth_users.id"), index=True)
    import_type: Mapped[str] = mapped_column(String(30), index=True)
    status: Mapped[str] = mapped_column(String(30), default="UPLOADED", index=True)
    filename: Mapped[str] = mapped_column(String(200))
    file_format: Mapped[str] = mapped_column(String(10))
    file_sha256: Mapped[str] = mapped_column(String(64))
    headers_json: Mapped[str] = mapped_column(Text, default="[]")
    mapping_json: Mapped[str] = mapped_column(Text, default="{}")
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    valid_rows: Mapped[int] = mapped_column(Integer, default=0)
    invalid_rows: Mapped[int] = mapped_column(Integer, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, default=0)
    created_count: Mapped[int] = mapped_column(Integer, default=0)
    mapped_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class ImportRowResult(Base):
    __tablename__ = "import_row_results"
    __table_args__ = (UniqueConstraint("job_id", "row_number", name="uq_import_job_row"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    job_id: Mapped[str] = mapped_column(ForeignKey("import_jobs.id"), index=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    row_number: Mapped[int] = mapped_column(Integer)
    source_json: Mapped[str] = mapped_column(Text)
    normalized_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(30), default="PENDING", index=True)
    resolution: Mapped[str] = mapped_column(String(20), default="")
    existing_organization_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_entity_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    errors_json: Mapped[str] = mapped_column(Text, default="[]")
    warnings_json: Mapped[str] = mapped_column(Text, default="[]")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
