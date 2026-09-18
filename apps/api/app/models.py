from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from decimal import Decimal
from sqlalchemy.orm import Mapped, mapped_column, object_session

from .database import Base


def uid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(200))
    legal_type: Mapped[str] = mapped_column(String(40))
    registration_number: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    city: Mapped[str] = mapped_column(String(100), default="")
    pan: Mapped[str] = mapped_column(String(20), default="")
    fcra_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OrganizationComplianceProfile(Base):
    """Explicitly entered financial facts; no guessed revenue or legal thresholds."""
    __tablename__ = "organization_compliance_profiles"
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    annual_revenue: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    revenue_period: Mapped[str] = mapped_column(String(30), default="")
    updated_by: Mapped[str] = mapped_column(String(120))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Compliance(Base):
    __tablename__ = "compliance_instances"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    code: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(220))
    category: Mapped[str] = mapped_column(String(60))
    period: Mapped[str] = mapped_column(String(30))
    statutory_deadline: Mapped[date] = mapped_column(Date)
    internal_target: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="NOT_STARTED", index=True)
    priority: Mapped[str] = mapped_column(String(20), default="MEDIUM")
    owner_name: Mapped[str] = mapped_column(String(120))
    owner_initials: Mapped[str] = mapped_column(String(8), default="")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    legal_reference: Mapped[str] = mapped_column(String(180), default="")
    risk_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    @property
    def template_version_id(self) -> str | None:
        from sqlalchemy import select
        session = object_session(self)
        return session.scalar(select(ComplianceSnapshot.version_id).where(ComplianceSnapshot.compliance_id == self.id)) if session else None


class Task(Base):
    __tablename__ = "compliance_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    compliance_id: Mapped[str | None] = mapped_column(ForeignKey("compliance_instances.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(220))
    due_at: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(25), default="TODO")
    priority: Mapped[str] = mapped_column(String(20), default="MEDIUM")
    assignee_name: Mapped[str] = mapped_column(String(120))
    assignee_initials: Mapped[str] = mapped_column(String(8), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    compliance_id: Mapped[str | None] = mapped_column(ForeignKey("compliance_instances.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(80))
    file_type: Mapped[str] = mapped_column(String(20), default="PDF")
    version: Mapped[int] = mapped_column(Integer, default=1)
    size_label: Mapped[str] = mapped_column(String(30), default="—")
    expiry_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    uploaded_by: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    title: Mapped[str] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(30), default="INFO")
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    @property
    def template_key(self) -> str | None:
        from sqlalchemy import select
        session = object_session(self)
        return session.scalar(select(ComplianceNotificationTemplate.template_key).where(ComplianceNotificationTemplate.notification_id == self.id)) if session else None

    @property
    def template_variables(self) -> dict:
        import json
        from sqlalchemy import select
        session = object_session(self)
        value = session.scalar(select(ComplianceNotificationTemplate.variables).where(ComplianceNotificationTemplate.notification_id == self.id)) if session else None
        return json.loads(value) if value else {}


class ComplianceNotificationTemplate(Base):
    __tablename__ = "compliance_notification_templates"
    notification_id: Mapped[str] = mapped_column(ForeignKey("notifications.id"), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    template_key: Mapped[str] = mapped_column(String(100), default="compliance.deadlineReminder")
    variables: Mapped[str] = mapped_column(Text)


class ComplianceComment(Base):
    __tablename__ = "compliance_comments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    compliance_id: Mapped[str] = mapped_column(ForeignKey("compliance_instances.id"), index=True)
    author_name: Mapped[str] = mapped_column(String(120))
    body: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(30), default="COMMENT")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PortfolioRecord(Base):
    __tablename__ = "portfolio_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    record_type: Mapped[str] = mapped_column(String(30), index=True)
    title: Mapped[str] = mapped_column(String(220))
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE")
    owner_name: Mapped[str] = mapped_column(String(120), default="Unassigned")
    value_label: Mapped[str] = mapped_column(String(80), default="")
    due_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IntegrationConnection(Base):
    __tablename__ = "integration_connections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    provider: Mapped[str] = mapped_column(String(80))
    category: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(30), default="AVAILABLE")
    description: Mapped[str] = mapped_column(String(240), default="")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AutomationReceipt(Base):
    __tablename__ = "automation_receipts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    event_key: Mapped[str] = mapped_column(String(220), unique=True, index=True)
    event_type: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    actor_name: Mapped[str] = mapped_column(String(120))
    action: Mapped[str] = mapped_column(String(80))
    entity_type: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[str] = mapped_column(String(36))
    summary: Mapped[str] = mapped_column(String(280))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ComplianceDefinition(Base):
    __tablename__ = "compliance_definitions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    code: Mapped[str] = mapped_column(String(40), index=True)
    title: Mapped[str] = mapped_column(String(220))
    category: Mapped[str] = mapped_column(String(60))
    legal_reference: Mapped[str] = mapped_column(String(180), default="")
    applicable_legal_types: Mapped[str] = mapped_column(String(160), default="ALL")
    requires_fcra: Mapped[bool] = mapped_column(Boolean, default=False)
    deadline_month: Mapped[int] = mapped_column(Integer)
    deadline_day: Mapped[int] = mapped_column(Integer)
    internal_lead_days: Mapped[int] = mapped_column(Integer, default=14)
    priority: Mapped[str] = mapped_column(String(20), default="MEDIUM")
    rule_version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")


class ComplianceCategory(Base):
    __tablename__ = "compliance_categories"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(60), unique=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class ComplianceMaster(Base):
    """Global identity extending the existing definition, not a second catalogue."""
    __tablename__ = "compliance_master"
    id: Mapped[str] = mapped_column(ForeignKey("compliance_definitions.id"), primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    category_id: Mapped[str] = mapped_column(ForeignKey("compliance_categories.id"))
    current_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ComplianceTemplateVersion(Base):
    __tablename__ = "compliance_definition_versions"
    __table_args__ = (UniqueConstraint("definition_id", "version", name="uq_compliance_template_version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    definition_id: Mapped[str] = mapped_column(ForeignKey("compliance_master.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", index=True)
    configuration: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(String(220), default="")
    category_id: Mapped[str] = mapped_column(ForeignKey("compliance_categories.id"))
    jurisdiction: Mapped[str] = mapped_column(String(100), default="")
    frequency: Mapped[str] = mapped_column(String(30), default="ANNUAL")
    risk_level: Mapped[str] = mapped_column(String(20), default="MEDIUM")
    search_text: Mapped[str] = mapped_column(Text, default="")
    organization_types: Mapped[str] = mapped_column(String(500), default="")
    change_summary: Mapped[str] = mapped_column(String(500), default="Initial configuration")
    created_by: Mapped[str] = mapped_column(String(120))
    updated_by: Mapped[str] = mapped_column(String(120))
    reviewed_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    published_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ComplianceSnapshot(Base):
    __tablename__ = "compliance_instance_snapshots"
    __table_args__ = (UniqueConstraint("tenant_id", "organization_id", "definition_id", "cycle", name="uq_template_instance_cycle"),)
    compliance_id: Mapped[str] = mapped_column(ForeignKey("compliance_instances.id"), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"))
    definition_id: Mapped[str] = mapped_column(ForeignKey("compliance_master.id"))
    version_id: Mapped[str] = mapped_column(ForeignKey("compliance_definition_versions.id"))
    cycle: Mapped[str] = mapped_column(String(80))
    configuration: Mapped[str] = mapped_column(Text)
    checklist_tasks: Mapped[str] = mapped_column(Text, default="[]")
    owner_required: Mapped[bool] = mapped_column(Boolean, default=False)


class ComplianceReminder(Base):
    __tablename__ = "compliance_reminder_schedule"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    compliance_id: Mapped[str] = mapped_column(ForeignKey("compliance_instances.id"), index=True)
    event_key: Mapped[str] = mapped_column(String(220), unique=True)
    scheduled_for: Mapped[date] = mapped_column(Date, index=True)
    configuration: Mapped[str] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Membership(Base):
    __tablename__ = "memberships"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    organization_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(200), index=True)
    role: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default="INVITED")
    invited_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DocumentVersion(Base):
    __tablename__ = "document_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    file_type: Mapped[str] = mapped_column(String(20), default="PDF")
    size_label: Mapped[str] = mapped_column(String(30), default="-")
    uploaded_by: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Submission(Base):
    __tablename__ = "submissions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    compliance_id: Mapped[str] = mapped_column(ForeignKey("compliance_instances.id"), index=True)
    acknowledgement_ref: Mapped[str] = mapped_column(String(160))
    proof_document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id"), nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    plan_name: Mapped[str] = mapped_column(String(40), default="BUSINESS")
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    user_limit: Mapped[int] = mapped_column(Integer, default=25)
    organization_limit: Mapped[int] = mapped_column(Integer, default=10)
    storage_limit_gb: Mapped[int] = mapped_column(Integer, default=25)
    period_end: Mapped[date] = mapped_column(Date)


class TenantLocale(Base):
    __tablename__ = "tenant_locales"
    __table_args__ = (UniqueConstraint("tenant_id", "locale_code", name="uq_tenant_locale"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    locale_code: Mapped[str] = mapped_column(String(16))
    display_name: Mapped[str] = mapped_column(String(80))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class UserPreference(Base):
    __tablename__ = "user_preferences"

    user_id: Mapped[str] = mapped_column(ForeignKey("auth_users.id"), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    locale: Mapped[str | None] = mapped_column(String(16), nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    time_format: Mapped[str] = mapped_column(String(8), default="12h")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TranslationOverride(Base):
    __tablename__ = "translation_overrides"
    __table_args__ = (UniqueConstraint("tenant_id", "locale_code", "translation_key", name="uq_translation_override"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    locale_code: Mapped[str] = mapped_column(String(16), index=True)
    translation_key: Mapped[str] = mapped_column(String(180), index=True)
    translation_value: Mapped[str] = mapped_column(Text)
    updated_by: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TenantEntitlement(Base):
    __tablename__ = "tenant_entitlements"
    __table_args__ = (UniqueConstraint("tenant_id", "feature_key", name="uq_tenant_feature"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    feature_key: Mapped[str] = mapped_column(String(80))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_by: Mapped[str] = mapped_column(String(120), default="System")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TenantBranding(Base):
    __tablename__ = "tenant_branding"

    tenant_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), default="DISABLED")
    revision: Mapped[int] = mapped_column(Integer, default=0)
    draft_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    published_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BrandingVersion(Base):
    __tablename__ = "tenant_branding_versions"
    __table_args__ = (UniqueConstraint("tenant_id", "version", name="uq_brand_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    version: Mapped[int] = mapped_column(Integer)
    configuration: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    published_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BrandAsset(Base):
    __tablename__ = "tenant_brand_assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    asset_type: Mapped[str] = mapped_column(String(30))
    storage_key: Mapped[str] = mapped_column(String(255), unique=True)
    mime_type: Mapped[str] = mapped_column(String(60))
    file_size: Mapped[int] = mapped_column(Integer)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    created_by: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TenantDomain(Base):
    __tablename__ = "tenant_domains"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    hostname: Mapped[str] = mapped_column(String(253), unique=True, index=True)
    verification_token: Mapped[str] = mapped_column(String(100))
    verification_method: Mapped[str] = mapped_column(String(20), default="DNS_TXT")
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    ssl_status: Mapped[str] = mapped_column(String(20), default="PENDING")
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    platform_suspended: Mapped[bool] = mapped_column(Boolean, default=False)
    routing_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class User(Base):
    __tablename__ = "auth_users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    phone: Mapped[str] = mapped_column(String(30), default="")
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    role: Mapped[str] = mapped_column(String(20), default="MEMBER")
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    @property
    def has_password(self) -> bool:
        return bool(self.password_hash)


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("auth_users.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuthToken(Base):
    __tablename__ = "auth_tokens"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("auth_users.id"), index=True)
    purpose: Mapped[str] = mapped_column(String(20))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuthAttempt(Base):
    __tablename__ = "auth_attempts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    scope_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
