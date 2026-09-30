"""Tenant-scoped AI configuration and immutable document-index metadata."""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .models import uid, utcnow


class AiProviderConfiguration(Base):
    __tablename__ = "ai_provider_configurations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), unique=True, index=True)
    provider: Mapped[str] = mapped_column(String(60))
    generation_model: Mapped[str] = mapped_column(String(120))
    embedding_model: Mapped[str] = mapped_column(String(120))
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=30)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    credential_reference: Mapped[str] = mapped_column(String(255), default="")
    updated_by: Mapped[str] = mapped_column(String(120), default="System")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DocumentExtraction(Base):
    __tablename__ = "ai_document_extractions"
    version_id: Mapped[str] = mapped_column(ForeignKey("document_file_versions.version_id"), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    status: Mapped[str] = mapped_column(String(24), default="PENDING", index=True)
    normalized_text: Mapped[str] = mapped_column(Text, default="")
    text_checksum: Mapped[str] = mapped_column(String(64), default="")
    extractor: Mapped[str] = mapped_column(String(80), default="")
    error_code: Mapped[str] = mapped_column(String(60), default="")
    index_status: Mapped[str] = mapped_column(String(24), default="PENDING", index=True)
    index_error_code: Mapped[str] = mapped_column(String(60), default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DocumentChunk(Base):
    __tablename__ = "ai_document_chunks"
    __table_args__ = (UniqueConstraint("version_id", "chunk_index", name="uq_ai_document_chunk_order"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("document_file_versions.version_id"), index=True)
    compliance_id: Mapped[str | None] = mapped_column(ForeignKey("compliance_instances.id"), nullable=True, index=True)
    source_type: Mapped[str] = mapped_column(String(24), default="DOCUMENT", index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    embedding: Mapped[str] = mapped_column(Text, default="")
    embedding_model: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(24), default="PENDING", index=True)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
