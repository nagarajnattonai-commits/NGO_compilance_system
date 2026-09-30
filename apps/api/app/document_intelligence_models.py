"""Version-scoped document intelligence proposals and human review state."""
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .models import uid, utcnow


class DocumentIntelligenceRun(Base):
    __tablename__ = "document_intelligence_runs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "request_key", name="uq_document_intelligence_request"),
        Index("ix_document_intelligence_review", "tenant_id", "organization_id", "status"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("document_file_versions.version_id"), index=True)
    requested_by: Mapped[str] = mapped_column(ForeignKey("auth_users.id"))
    request_key: Mapped[str] = mapped_column(String(160))
    logic_version: Mapped[str] = mapped_column(String(40), default="v1")
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="QUEUED", index=True)
    source_checksum: Mapped[str] = mapped_column(String(64))
    extraction_method: Mapped[str] = mapped_column(String(80), default="")
    proposed_document_type: Mapped[str] = mapped_column(String(80), default="UNKNOWN")
    classification_confidence: Mapped[float] = mapped_column(Float, default=0)
    classification_evidence: Mapped[str] = mapped_column(String(500), default="")
    error_code: Mapped[str] = mapped_column(String(60), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExtractedDocumentFact(Base):
    __tablename__ = "extracted_document_facts"
    __table_args__ = (
        UniqueConstraint("run_id", "fingerprint", name="uq_document_fact_run_fingerprint"),
        UniqueConstraint("applied_key", name="uq_document_fact_applied_key"),
        Index("ix_document_fact_review", "tenant_id", "organization_id", "status"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    run_id: Mapped[str] = mapped_column(ForeignKey("document_intelligence_runs.id"), index=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("document_file_versions.version_id"), index=True)
    fact_type: Mapped[str] = mapped_column(String(120), index=True)
    proposed_value: Mapped[str] = mapped_column(Text)
    reviewed_value: Mapped[str] = mapped_column(Text, default="")
    current_value_snapshot: Mapped[str] = mapped_column(Text, default="")
    source_location: Mapped[str] = mapped_column(String(200), default="document text")
    source_excerpt: Mapped[str] = mapped_column(String(500), default="")
    extraction_method: Mapped[str] = mapped_column(String(80), default="")
    confidence: Mapped[float] = mapped_column(Float)
    validation_state: Mapped[str] = mapped_column(String(32), default="VALID")
    status: Mapped[str] = mapped_column(String(32), default="PROPOSED", index=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    applied_key: Mapped[str | None] = mapped_column(String(180), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("auth_users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    extracted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
