"""Additive CSR partner, project and configurable due-diligence records."""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .models import uid, utcnow


class CsrPartnerRelationship(Base):
    __tablename__ = "csr_partner_relationships"
    __table_args__ = (
        UniqueConstraint("tenant_id", "organization_id", name="uq_csr_partner_organization"),
        Index("ix_csr_partner_status", "tenant_id", "status", "review_status"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    status: Mapped[str] = mapped_column(String(24), default="PROSPECTIVE", index=True)
    review_status: Mapped[str] = mapped_column(String(24), default="NOT_STARTED", index=True)
    owner_user_id: Mapped[str | None] = mapped_column(ForeignKey("auth_users.id"), nullable=True, index=True)
    onboarding_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    internal_notes: Mapped[str] = mapped_column(Text, default="")
    shared_notes: Mapped[str] = mapped_column(Text, default="")
    collaboration_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("auth_users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CsrPartnerCollaborator(Base):
    __tablename__ = "csr_partner_collaborators"
    __table_args__ = (UniqueConstraint("relationship_id", "user_id", name="uq_csr_partner_collaborator"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    relationship_id: Mapped[str] = mapped_column(ForeignKey("csr_partner_relationships.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("auth_users.id"), index=True)
    role: Mapped[str] = mapped_column(String(24), default="NGO_PARTNER")
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    invited_by: Mapped[str] = mapped_column(ForeignKey("auth_users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CsrProject(Base):
    __tablename__ = "csr_projects"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_csr_project_code"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    relationship_id: Mapped[str] = mapped_column(ForeignKey("csr_partner_relationships.id"), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    code: Mapped[str] = mapped_column(String(60))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(24), default="DRAFT", index=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    owner_user_id: Mapped[str | None] = mapped_column(ForeignKey("auth_users.id"), nullable=True)
    ngo_contact: Mapped[str] = mapped_column(String(160), default="")
    approved_budget: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    category: Mapped[str] = mapped_column(String(100), default="")
    location: Mapped[str] = mapped_column(String(160), default="")
    internal_notes: Mapped[str] = mapped_column(Text, default="")
    shared_with_ngo: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("auth_users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CsrChecklistTemplate(Base):
    __tablename__ = "csr_checklist_templates"
    __table_args__ = (UniqueConstraint("tenant_id", "name", "version", name="uq_csr_template_version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("auth_users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CsrChecklistTemplateItem(Base):
    __tablename__ = "csr_checklist_template_items"
    __table_args__ = (UniqueConstraint("template_id", "position", name="uq_csr_template_item_position"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    template_id: Mapped[str] = mapped_column(ForeignKey("csr_checklist_templates.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    category: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    requirement_type: Mapped[str] = mapped_column(String(30), default="CONFIRMATION")
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    registration_kind: Mapped[str] = mapped_column(String(20), default="")
    expiry_monitoring: Mapped[bool] = mapped_column(Boolean, default=False)
    share_with_ngo: Mapped[bool] = mapped_column(Boolean, default=True)


class CsrDueDiligenceReview(Base):
    __tablename__ = "csr_due_diligence_reviews"
    __table_args__ = (Index("ix_csr_review_scope", "tenant_id", "organization_id", "status"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    relationship_id: Mapped[str] = mapped_column(ForeignKey("csr_partner_relationships.id"), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("csr_projects.id"), nullable=True, index=True)
    template_id: Mapped[str] = mapped_column(ForeignKey("csr_checklist_templates.id"), index=True)
    template_version: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(24), default="NOT_STARTED", index=True)
    reviewer_user_id: Mapped[str | None] = mapped_column(ForeignKey("auth_users.id"), nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    shared_with_ngo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("auth_users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CsrDueDiligenceItem(Base):
    __tablename__ = "csr_due_diligence_items"
    __table_args__ = (
        UniqueConstraint("review_id", "template_item_id", name="uq_csr_review_template_item"),
        Index("ix_csr_item_review", "tenant_id", "organization_id", "status"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    review_id: Mapped[str] = mapped_column(ForeignKey("csr_due_diligence_reviews.id"), index=True)
    template_item_id: Mapped[str] = mapped_column(ForeignKey("csr_checklist_template_items.id"))
    position: Mapped[int] = mapped_column(Integer)
    category: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    requirement_type: Mapped[str] = mapped_column(String(30), default="CONFIRMATION")
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    registration_kind: Mapped[str] = mapped_column(String(20), default="")
    expiry_monitoring: Mapped[bool] = mapped_column(Boolean, default=False)
    shared_with_ngo: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(24), default="NOT_STARTED", index=True)
    reviewer_user_id: Mapped[str | None] = mapped_column(ForeignKey("auth_users.id"), nullable=True)
    response: Mapped[str] = mapped_column(Text, default="")
    internal_notes: Mapped[str] = mapped_column(Text, default="")
    reviewer_comment: Mapped[str] = mapped_column(Text, default="")
    expiry_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CsrEvidenceLink(Base):
    __tablename__ = "csr_evidence_links"
    __table_args__ = (UniqueConstraint("item_id", "version_id", name="uq_csr_item_evidence_version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    relationship_id: Mapped[str] = mapped_column(ForeignKey("csr_partner_relationships.id"), index=True)
    review_id: Mapped[str] = mapped_column(ForeignKey("csr_due_diligence_reviews.id"), index=True)
    item_id: Mapped[str] = mapped_column(ForeignKey("csr_due_diligence_items.id"), index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("csr_projects.id"), nullable=True, index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("document_file_versions.version_id"), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    linked_by: Mapped[str] = mapped_column(ForeignKey("auth_users.id"))
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CsrTaskLink(Base):
    __tablename__ = "csr_task_links"
    __table_args__ = (UniqueConstraint("task_id", "project_id", "item_id", name="uq_csr_task_target"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    relationship_id: Mapped[str] = mapped_column(ForeignKey("csr_partner_relationships.id"), index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("csr_projects.id"), nullable=True, index=True)
    item_id: Mapped[str | None] = mapped_column(ForeignKey("csr_due_diligence_items.id"), nullable=True, index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("compliance_tasks.id"), index=True)
    linked_by: Mapped[str] = mapped_column(ForeignKey("auth_users.id"))
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
