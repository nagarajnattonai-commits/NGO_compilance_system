"""Language-neutral, bounded configuration. Drafts can be incomplete, never unsafe."""
from __future__ import annotations

import re
import math
from decimal import Decimal
from datetime import date
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ROLES = {"TENANT_ADMIN", "ORGANIZATION_ADMIN", "COMPLIANCE_OFFICER", "ACCOUNTANT", "AUDITOR", "CONSULTANT", "MANAGEMENT", "VIEWER"}
STATES = {"NOT_STARTED", "IN_PROGRESS", "UNDER_REVIEW", "CHANGES_REQUESTED", "READY_TO_FILE", "FILED", "COMPLETED", "ON_HOLD", "NOT_APPLICABLE", "CANCELLED"}
FIELDS = {"legal_type": "text", "fcra_active": "boolean", "status": "text", "city": "text", "pan": "text", "registration_number": "text", "annual_revenue": "number", "revenue_period": "text", "created_at": "date"}
FIELDS.update({"organization.legal_type": "text", "organization.registration_date": "date", "organization.pan_present": "boolean", "organization.tan_present": "boolean", "organization.gst.registered": "boolean", "financial.annual_revenue": "number"})
for _kind in ("12a", "12ab", "80g", "fcra", "gst", "csr"):
    FIELDS.update({f"organization.{_kind}.status": "text", f"organization.{_kind}.expiry_date": "date"})
OPERATORS = {
    "text": ["EQUALS", "NOT_EQUALS", "CONTAINS", "NOT_CONTAINS", "IS_EMPTY", "IS_NOT_EMPTY", "IN", "NOT_IN"],
    "boolean": ["EQUALS", "NOT_EQUALS", "IS_TRUE", "IS_FALSE"],
    "number": ["EQUALS", "NOT_EQUALS", "GREATER_THAN", "GREATER_THAN_OR_EQUAL", "LESS_THAN", "LESS_THAN_OR_EQUAL", "IS_EMPTY", "IS_NOT_EMPTY"],
    "date": ["EQUALS", "NOT_EQUALS", "GREATER_THAN", "GREATER_THAN_OR_EQUAL", "LESS_THAN", "LESS_THAN_OR_EQUAL", "IS_EMPTY", "IS_NOT_EMPTY"],
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @field_validator("id", check_fields=False)
    @classmethod
    def safe_item_identifier(cls, value):
        if value in {"__proto__", "constructor", "prototype"} or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", value):
            raise ValueError("Unsafe configuration item identifier")
        return value


class Condition(StrictModel):
    id: str = Field(min_length=1, max_length=40)
    field: str
    operator: str
    value: str | bool | int | float | list[str] | None = None

    @model_validator(mode="after")
    def valid_condition(self):
        if self.field not in FIELDS or self.operator not in OPERATORS[FIELDS[self.field]]:
            raise ValueError("Unsupported applicability field or operator")
        if self.operator in {"IS_EMPTY", "IS_NOT_EMPTY", "IS_TRUE", "IS_FALSE"}:
            self.value = None
            return self
        # Incomplete typed conditions are safe drafts, never publishable.
        if self.value is None:
            return self
        if FIELDS[self.field] == "boolean" and not isinstance(self.value, bool):
            raise ValueError("Boolean fields require a boolean value")
        if FIELDS[self.field] == "number" and (isinstance(self.value, bool) or not isinstance(self.value, (int, float)) or abs(self.value) > 1e18 or not math.isfinite(self.value)):
            raise ValueError("Numeric fields require a finite numeric value")
        if FIELDS[self.field] == "date":
            if self.value == "":
                return self
            if not isinstance(self.value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", self.value):
                raise ValueError("Date fields require an ISO date")
            date.fromisoformat(self.value)
        if FIELDS[self.field] == "text":
            if self.operator in {"IN", "NOT_IN"}:
                if not isinstance(self.value, list) or len(self.value) > 50 or any(not x or len(x) > 200 for x in self.value):
                    raise ValueError("In/Not In requires a bounded list of nonempty text values")
            elif not isinstance(self.value, str) or len(self.value) > 200:
                raise ValueError("Text operators require a bounded text value")
        return self


class RuleGroup(StrictModel):
    id: str = Field(min_length=1, max_length=40)
    operator: Literal["AND", "OR"] = "AND"
    conditions: list[Condition] = Field(default_factory=list, max_length=30)


class Applicability(StrictModel):
    match_all: bool = False
    operator: Literal["AND", "OR"] = "AND"
    groups: list[RuleGroup] = Field(default_factory=list, max_length=10)


class Recurrence(StrictModel):
    frequency: Literal["ONE_TIME", "MONTHLY", "QUARTERLY", "HALF_YEARLY", "ANNUAL", "CUSTOM", "EVENT_BASED"] = "ANNUAL"
    anchor_date: date | None = None
    interval_months: int = Field(default=12, ge=1, le=120)
    fiscal_start_month: int = Field(default=4, ge=1, le=12)


class Deadline(StrictModel):
    strategy: Literal["FIXED_DATE", "PERIOD_END_PLUS_DAYS", "EVENT_DATE_PLUS_DAYS", "CERTIFICATE_EXPIRY_MINUS_DAYS", "FINANCIAL_YEAR_END_PLUS_DAYS"] = "FIXED_DATE"
    fixed_date: date | None = None
    offset_days: int = Field(default=0, ge=0, le=3660)
    internal_lead_days: int = Field(default=0, ge=0, le=3660)
    document_type: str = Field(default="", max_length=80)


class Stage(StrictModel):
    id: str = Field(min_length=1, max_length=40)
    state: str
    label: str = Field(default="", max_length=120)

    @field_validator("state")
    @classmethod
    def known_state(cls, value):
        if value not in STATES:
            raise ValueError("Use an existing language-neutral workflow state")
        return value


class Transition(StrictModel):
    from_state: str
    to_state: str
    allowed_roles: list[str] = Field(default_factory=list, max_length=8)
    required_evidence: bool = False
    required_approval: bool = False

    @field_validator("allowed_roles")
    @classmethod
    def known_roles(cls, value):
        if not value or any(role not in ROLES for role in value):
            raise ValueError("A transition needs known allowed roles")
        return value


class Workflow(StrictModel):
    stages: list[Stage] = Field(default_factory=list, max_length=20)
    transitions: list[Transition] = Field(default_factory=list, max_length=60)


class ChecklistItem(StrictModel):
    id: str = Field(min_length=1, max_length=40)
    title: str = Field(default="", max_length=220)
    description: str = Field(default="", max_length=2000)
    instructions: str = Field(default="", max_length=2000)
    required: bool = True
    responsible_role: str = "COMPLIANCE_OFFICER"
    relative_due_days: int = Field(default=0, ge=-3660, le=0)


class DocumentRequirement(StrictModel):
    id: str = Field(min_length=1, max_length=40)
    document_type: str = Field(default="", max_length=80)
    required: bool = True
    minimum_count: int = Field(default=1, ge=1, le=100)
    must_be_valid: bool = True
    instructions: str = Field(default="", max_length=2000)


class Responsibility(StrictModel):
    owner_role: str = "COMPLIANCE_OFFICER"
    fallback_role: str = "ORGANIZATION_ADMIN"
    reviewer_role: str = "AUDITOR"
    approver_role: str = "ORGANIZATION_ADMIN"

    @model_validator(mode="after")
    def known_roles(self):
        if any(value not in ROLES for value in self.model_dump().values()):
            raise ValueError("Unknown responsibility role")
        return self


class ReminderRule(StrictModel):
    id: str = Field(min_length=1, max_length=40)
    offset_days: int = Field(default=0, ge=-3660, le=3660)
    channel: Literal["IN_APP"] = "IN_APP"
    recipient_role: str = "COMPLIANCE_OFFICER"
    escalation_level: int = Field(default=0, ge=0, le=10)
    enabled: bool = True
    text: str = Field(default="", max_length=2000)


class TemplateTranslation(StrictModel):
    name: str = Field(default="", max_length=220)
    description: str = Field(default="", max_length=4000)
    instructions: str = Field(default="", max_length=4000)
    checklist: dict[str, str] = Field(default_factory=dict, max_length=100)
    checklist_descriptions: dict[str, str] = Field(default_factory=dict, max_length=100)
    checklist_instructions: dict[str, str] = Field(default_factory=dict, max_length=100)
    document_instructions: dict[str, str] = Field(default_factory=dict, max_length=100)
    reminder_text: dict[str, str] = Field(default_factory=dict, max_length=100)

    @model_validator(mode="after")
    def bounded_text(self):
        for mapping in (self.checklist, self.checklist_descriptions, self.checklist_instructions, self.document_instructions, self.reminder_text):
            if any(len(key) > 40 or len(value) > 4000 for key, value in mapping.items()):
                raise ValueError("Translation is too long")
        return self


class TemplateConfiguration(StrictModel):
    name: str = Field(default="", max_length=220)
    category_id: str = Field(default="", max_length=36)
    subcategory: str = Field(default="", max_length=100)
    jurisdiction: str = Field(default="", max_length=100)
    description: str = Field(default="", max_length=4000)
    purpose: str = Field(default="", max_length=4000)
    instructions: str = Field(default="", max_length=4000)
    legal_reference: str = Field(default="", max_length=180)
    authority: str = Field(default="", max_length=200)
    portal_url: str = Field(default="", max_length=1000)
    tags: list[str] = Field(default_factory=list, max_length=30)
    internal_notes: str = Field(default="", max_length=4000)
    applicability: Applicability = Field(default_factory=Applicability)
    recurrence: Recurrence = Field(default_factory=Recurrence)
    deadline: Deadline = Field(default_factory=Deadline)
    workflow: Workflow = Field(default_factory=Workflow)
    checklist: list[ChecklistItem] = Field(default_factory=list, max_length=100)
    documents: list[DocumentRequirement] = Field(default_factory=list, max_length=100)
    responsibility: Responsibility = Field(default_factory=Responsibility)
    reminders: list[ReminderRule] = Field(default_factory=list, max_length=100)
    risk_level: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "MEDIUM"
    priority: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "MEDIUM"
    translations: dict[str, TemplateTranslation] = Field(default_factory=dict, max_length=30)

    @model_validator(mode="after")
    def safe_configuration(self):
        if self.portal_url:
            parsed = urlparse(self.portal_url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("Portal URL must be an HTTPS URL without credentials")
        if any(len(tag) > 80 for tag in self.tags):
            raise ValueError("Tag too long")
        for collection in (self.checklist, self.documents, self.reminders, self.workflow.stages, self.applicability.groups):
            ids = [item.id for item in collection]
            if len(ids) != len(set(ids)):
                raise ValueError("Configuration item IDs must be unique")
        for group in self.applicability.groups:
            ids = [item.id for item in group.conditions]
            if len(ids) != len(set(ids)):
                raise ValueError("Rule IDs must be unique in a group")
        for item in [*self.checklist, *self.reminders]:
            role = item.responsible_role if isinstance(item, ChecklistItem) else item.recipient_role
            if role not in ROLES:
                raise ValueError("Unknown checklist or reminder role")
        if any(not re.fullmatch(r"[a-z]{2,3}-[A-Z]{2}", locale) for locale in self.translations):
            raise ValueError("Invalid translation locale")
        return self


class CreateTemplate(StrictModel):
    code: str = Field(min_length=1, max_length=40)
    configuration: TemplateConfiguration
    change_summary: str = Field(default="Initial configuration", min_length=3, max_length=500)

    @field_validator("code")
    @classmethod
    def stable_code(cls, value):
        value = value.upper()
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{0,39}", value):
            raise ValueError("Code must contain only letters, numbers, hyphens or underscores")
        return value


class UpdateTemplate(StrictModel):
    expected_revision: int = Field(ge=0)
    configuration: TemplateConfiguration
    change_summary: str = Field(min_length=3, max_length=500)


class TemplateAction(StrictModel):
    expected_revision: int = Field(ge=0)
    change_summary: str = Field(default="", max_length=500)


class CloneTemplate(CreateTemplate):
    pass


class CategoryInput(StrictModel):
    name: str = Field(min_length=1, max_length=60)
    sort_order: int = Field(default=0, ge=0, le=10000)
    enabled: bool = True


class ApplicabilityTest(StrictModel):
    organization_id: str
    as_of: date | None = None
    event_date: date | None = None
    configuration: TemplateConfiguration | None = None


class ComplianceProfileInput(StrictModel):
    annual_revenue: Decimal | None = Field(default=None, ge=0, le=Decimal("999999999999999999"), max_digits=20, decimal_places=2)
    revenue_period: str = Field(default="", max_length=30)

    @model_validator(mode="after")
    def period_required(self):
        if self.annual_revenue is not None and not self.revenue_period:
            raise ValueError("Revenue requires its financial period")
        return self


class GeneratePlanInput(StrictModel):
    event_date: date | None = None
