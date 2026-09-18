from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .validation import normalize_email


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class OrganizationOut(ORMModel):
    id: str
    name: str
    legal_type: str
    registration_number: str
    status: str
    city: str
    pan: str
    fcra_active: bool


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=3, max_length=200)
    legal_type: Literal["TRUST", "SOCIETY", "SECTION 8"]
    registration_number: str = Field(min_length=2, max_length=80)
    city: str = Field(min_length=2, max_length=100)
    pan: str = Field(default="", max_length=20)
    fcra_active: bool = False
    generate_compliance_plan: bool = True


class OrganizationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=3, max_length=200)
    status: Literal["DRAFT", "ACTIVE", "SUSPENDED", "ARCHIVED"] | None = None
    city: str | None = Field(default=None, min_length=2, max_length=100)
    pan: str | None = Field(default=None, max_length=20)
    fcra_active: bool | None = None


class ComplianceCreate(BaseModel):
    organization_id: str
    code: str = Field(min_length=2, max_length=40)
    title: str = Field(min_length=3, max_length=220)
    category: str
    period: str
    statutory_deadline: date
    internal_target: date | None = None
    priority: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "MEDIUM"
    owner_name: str
    owner_initials: str = ""
    legal_reference: str = ""

    @model_validator(mode="after")
    def internal_target_precedes_deadline(self):
        if self.internal_target and self.internal_target > self.statutory_deadline:
            raise ValueError("Internal target must be on or before the statutory deadline")
        return self


class ComplianceUpdate(BaseModel):
    status: Literal[
        "NOT_STARTED", "IN_PROGRESS", "UNDER_REVIEW", "READY_TO_FILE", "FILED", "COMPLETED", "ON_HOLD"
    ] | None = None
    progress: int | None = Field(default=None, ge=0, le=100)
    owner_name: str | None = None
    internal_target: date | None = None


class ComplianceTransition(BaseModel):
    target_status: Literal[
        "IN_PROGRESS", "UNDER_REVIEW", "CHANGES_REQUESTED", "READY_TO_FILE",
        "FILED", "COMPLETED", "NOT_APPLICABLE", "ON_HOLD"
    ]
    reason: str | None = Field(default=None, max_length=500)
    submission_reference: str | None = Field(default=None, max_length=160)
    proof_document_id: str | None = None


class ComplianceOut(ORMModel):
    id: str
    template_version_id: str | None = None
    organization_id: str
    code: str
    title: str
    category: str
    period: str
    statutory_deadline: date
    internal_target: date | None
    status: str
    priority: str
    owner_name: str
    owner_initials: str
    progress: int
    legal_reference: str
    risk_note: str
    created_at: datetime
    updated_at: datetime


class TaskUpdate(BaseModel):
    status: Literal["TODO", "IN_PROGRESS", "DONE"]


class TaskCreate(BaseModel):
    organization_id: str
    compliance_id: str | None = None
    title: str = Field(min_length=3, max_length=220)
    due_at: date
    priority: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "MEDIUM"
    assignee_name: str = Field(min_length=2, max_length=120)
    assignee_initials: str = Field(default="", max_length=8)


class TaskOut(ORMModel):
    id: str
    organization_id: str
    compliance_id: str | None
    title: str
    due_at: date
    status: str
    priority: str
    assignee_name: str
    assignee_initials: str


class DocumentCreate(BaseModel):
    organization_id: str
    compliance_id: str | None = None
    name: str = Field(min_length=3, max_length=255)
    category: str
    file_type: str = "PDF"
    size_label: str = "—"
    expiry_at: date | None = None
    uploaded_by: str = "Demo User"


class DocumentOut(ORMModel):
    id: str
    organization_id: str
    compliance_id: str | None
    name: str
    category: str
    file_type: str
    version: int
    size_label: str
    expiry_at: date | None
    uploaded_by: str
    created_at: datetime


class DocumentVersionCreate(BaseModel):
    file_type: str = Field(default="PDF", max_length=20)
    size_label: str = Field(default="-", max_length=30)
    uploaded_by: str = Field(default="Demo User", min_length=2, max_length=120)


class DocumentVersionOut(ORMModel):
    id: str
    document_id: str
    version: int
    file_type: str
    size_label: str
    uploaded_by: str
    created_at: datetime


class ComplianceDefinitionOut(ORMModel):
    id: str
    code: str
    title: str
    category: str
    legal_reference: str
    applicable_legal_types: str
    requires_fcra: bool
    deadline_month: int | None
    deadline_day: int | None
    internal_lead_days: int
    priority: str
    rule_version: int
    status: str


class MembershipCreate(BaseModel):
    organization_id: str | None = None
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=5, max_length=200)
    role: Literal[
        "TENANT_ADMIN", "ORGANIZATION_ADMIN", "COMPLIANCE_OFFICER", "ACCOUNTANT",
        "AUDITOR", "CONSULTANT", "MANAGEMENT", "VIEWER"
    ]

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str):
        return normalize_email(value)


class MembershipUpdate(BaseModel):
    role: Literal[
        "TENANT_ADMIN", "ORGANIZATION_ADMIN", "COMPLIANCE_OFFICER", "ACCOUNTANT",
        "AUDITOR", "CONSULTANT", "MANAGEMENT", "VIEWER"
    ] | None = None
    status: Literal["INVITED", "ACTIVE", "INACTIVE"] | None = None


class MembershipOut(ORMModel):
    id: str
    organization_id: str | None
    name: str
    email: str
    role: str
    status: str
    invited_at: datetime
    accepted_at: datetime | None


class SubscriptionOut(ORMModel):
    id: str
    plan_name: str
    status: str
    user_limit: int
    organization_limit: int
    storage_limit_gb: int
    period_end: date


SupportedLocale = Literal["en-IN", "hi-IN", "kn-IN", "mr-IN"]


class TenantLocaleInput(BaseModel):
    locale_code: SupportedLocale
    display_name: str = Field(min_length=2, max_length=80)
    enabled: bool = True
    is_default: bool = False
    sort_order: int = Field(ge=0, le=100)


class TenantLocaleOut(ORMModel):
    id: str
    locale_code: str
    display_name: str
    enabled: bool
    is_default: bool
    sort_order: int


class UserPreferenceUpdate(BaseModel):
    locale: SupportedLocale | None = None
    timezone: Literal["Asia/Kolkata", "Asia/Calcutta", "Asia/Dubai", "Europe/London", "America/New_York", "UTC"] = "Asia/Kolkata"
    time_format: Literal["12h", "24h"] = "12h"


class UserPreferenceOut(ORMModel):
    user_id: str
    locale: str | None
    timezone: str
    time_format: str
    updated_at: datetime


class LocalizationSettingsOut(BaseModel):
    locales: list[TenantLocaleOut]
    preference: UserPreferenceOut


class TranslationOverrideInput(BaseModel):
    locale_code: SupportedLocale
    translation_key: str = Field(pattern=r"^[a-zA-Z0-9_.-]+$", min_length=3, max_length=180)
    translation_value: str = Field(min_length=1, max_length=4000)


class TranslationOverrideOut(ORMModel):
    id: str
    locale_code: str
    translation_key: str
    translation_value: str
    updated_by: str
    created_at: datetime
    updated_at: datetime


class OrganizationOnboardingOut(BaseModel):
    organization: OrganizationOut
    generated_compliances: list[ComplianceOut]


class NotificationOut(ORMModel):
    id: str
    template_key: str | None = None
    template_variables: dict = Field(default_factory=dict)
    title: str
    message: str
    kind: str
    is_read: bool
    created_at: datetime


class AuditOut(ORMModel):
    id: str
    actor_name: str
    action: str
    entity_type: str
    entity_id: str
    summary: str
    created_at: datetime


class ComplianceCommentCreate(BaseModel):
    body: str = Field(min_length=2, max_length=2000)
    kind: Literal["COMMENT", "CORRECTION", "EXCEPTION", "RECOVERY_PLAN"] = "COMMENT"


class ComplianceCommentOut(ORMModel):
    id: str
    compliance_id: str
    author_name: str
    body: str
    kind: str
    created_at: datetime


class PortfolioRecordCreate(BaseModel):
    organization_id: str
    record_type: Literal[
        "GRANT", "DONOR", "CSR_PROJECT", "VOLUNTEER",
        "MEMBERSHIP", "VOLUNTEER_ACTIVITY", "EVENT", "CAMPAIGN", "DONATION",
        "INQUIRY", "MESSAGE", "CERTIFICATE", "NEWS", "SPONSOR", "TESTIMONIAL",
        "MANAGEMENT_MEMBER", "GALLERY_ITEM", "DOCUMENT_TEMPLATE", "TRAINING_VIDEO",
        "CONTENT_PAGE",
    ]
    title: str = Field(min_length=2, max_length=220)
    status: str = Field(default="ACTIVE", min_length=2, max_length=30)
    owner_name: str = Field(default="Unassigned", min_length=2, max_length=120)
    value_label: str = Field(default="", max_length=80)
    due_at: date | None = None
    notes: str = Field(default="", max_length=2000)


class PortfolioRecordUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=220)
    status: str | None = Field(default=None, min_length=2, max_length=30)
    owner_name: str | None = Field(default=None, min_length=2, max_length=120)
    value_label: str | None = Field(default=None, max_length=80)
    due_at: date | None = None
    notes: str | None = Field(default=None, max_length=2000)


class PortfolioRecordOut(ORMModel):
    id: str
    organization_id: str
    record_type: str
    title: str
    status: str
    owner_name: str
    value_label: str
    due_at: date | None
    notes: str
    created_at: datetime
    updated_at: datetime


class IntegrationOut(ORMModel):
    id: str
    provider: str
    category: str
    status: str
    description: str
    last_synced_at: datetime | None


class IntegrationUpdate(BaseModel):
    status: Literal["AVAILABLE", "CONNECTED", "PAUSED"]


class AssistantInput(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    organization_id: str | None = None
