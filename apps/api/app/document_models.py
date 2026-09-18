"""Immutable private file references extend the existing document/version register."""
from datetime import date, datetime
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base
from .models import uid, utcnow
class DocumentBlob(Base):
    __tablename__="document_file_versions"
    __table_args__=(UniqueConstraint("document_id","version_number",name="uq_document_file_number"),)
    version_id:Mapped[str]=mapped_column(ForeignKey("document_versions.id"),primary_key=True)
    tenant_id:Mapped[str]=mapped_column(ForeignKey("workspaces.id"),index=True)
    organization_id:Mapped[str]=mapped_column(ForeignKey("organizations.id"),index=True)
    document_id:Mapped[str]=mapped_column(ForeignKey("documents.id"),index=True)
    version_number:Mapped[int]=mapped_column(Integer)
    provider:Mapped[str]=mapped_column(String(24))
    locator:Mapped[str]=mapped_column(Text,default="{}")
    storage_key:Mapped[str]=mapped_column(String(500),unique=True)
    original_filename:Mapped[str]=mapped_column(String(255))
    safe_filename:Mapped[str]=mapped_column(String(100))
    mime_type:Mapped[str]=mapped_column(String(100))
    size_bytes:Mapped[int]=mapped_column(Integer)
    checksum:Mapped[str]=mapped_column(String(64))
    uploaded_by:Mapped[str]=mapped_column(ForeignKey("auth_users.id"))
    uploaded_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)
    effective_at:Mapped[date|None]=mapped_column(Date,nullable=True)
    expiry_at:Mapped[date|None]=mapped_column(Date,nullable=True)
    status:Mapped[str]=mapped_column(String(24),default="AVAILABLE",index=True)
    scan_status:Mapped[str]=mapped_column(String(24),default="NOT_SCANNED")
class DocumentCurrent(Base):
    __tablename__="document_current_files"
    document_id:Mapped[str]=mapped_column(ForeignKey("documents.id"),primary_key=True)
    tenant_id:Mapped[str]=mapped_column(ForeignKey("workspaces.id"),index=True)
    version_id:Mapped[str|None]=mapped_column(ForeignKey("document_file_versions.version_id"),nullable=True)
    archived:Mapped[bool]=mapped_column(Boolean,default=False)
class DocumentUploadReceipt(Base):
    __tablename__="document_upload_receipts"
    __table_args__=(UniqueConstraint("tenant_id","request_id",name="uq_document_upload_request"),)
    id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    tenant_id:Mapped[str]=mapped_column(ForeignKey("workspaces.id"),index=True)
    request_id:Mapped[str]=mapped_column(String(36))
    fingerprint:Mapped[str]=mapped_column(String(64))
    version_id:Mapped[str|None]=mapped_column(ForeignKey("document_file_versions.version_id"),nullable=True)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)
class DocumentEvidenceLink(Base):
    __tablename__="document_evidence_links"
    id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    tenant_id:Mapped[str]=mapped_column(ForeignKey("workspaces.id"),index=True)
    organization_id:Mapped[str]=mapped_column(ForeignKey("organizations.id"),index=True)
    document_id:Mapped[str]=mapped_column(ForeignKey("documents.id"),index=True)
    version_id:Mapped[str]=mapped_column(ForeignKey("document_file_versions.version_id"),index=True)
    compliance_id:Mapped[str|None]=mapped_column(ForeignKey("compliance_instances.id"),nullable=True,index=True)
    task_id:Mapped[str|None]=mapped_column(ForeignKey("compliance_tasks.id"),nullable=True,index=True)
    submission_id:Mapped[str|None]=mapped_column(ForeignKey("submissions.id"),nullable=True,index=True)
    active:Mapped[bool]=mapped_column(Boolean,default=True)
    linked_by:Mapped[str]=mapped_column(ForeignKey("auth_users.id"))
    linked_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)
