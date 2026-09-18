"""Validated tenant-scoped organization facts shared with onboarding and the rule engine."""
import json
import re
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from urllib.parse import urlparse
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .auth import CurrentUser, get_db, tenant_context
from .models import AuditEvent, Document, Organization, OrganizationComplianceProfile, utcnow
from .organization_models import OrganizationDetails, OrganizationRegistration
from .schemas import OrganizationOut
from .validation import normalize_email

KINDS = ("12A", "12AB", "80G", "FCRA", "GST", "CSR")
DB = Annotated[Session, Depends(get_db)]
Tenant = Annotated[str, Depends(tenant_context)]
router = APIRouter(prefix="/api/v1", tags=["Organization profile"])

class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

class DetailsInput(Strict):
    registration_date: date | None = None
    registration_authority: str = Field(default="", max_length=200)
    establishment_date: date | None = None
    financial_year: str = Field(default="", max_length=30)
    website: str = Field(default="", max_length=255)
    notes: str = Field(default="", max_length=2000)
    tan: str = Field(default="", max_length=10)
    address_line_1: str = Field(default="", max_length=200)
    address_line_2: str = Field(default="", max_length=200)
    district: str = Field(default="", max_length=100)
    state: str = Field(default="", max_length=100)
    postal_code: str = Field(default="", max_length=12)
    country: str = Field(default="India", max_length=80)
    contact_name: str = Field(default="", max_length=120)
    contact_email: str = Field(default="", max_length=254)
    contact_phone: str = Field(default="", max_length=25)

    @field_validator("tan")
    @classmethod
    def valid_tan(cls, value):
        value = value.upper()
        if value and not re.fullmatch(r"[A-Z]{4}[0-9]{5}[A-Z]", value):
            raise ValueError("TAN must contain four letters, five digits and one letter")
        return value

    @field_validator("contact_email")
    @classmethod
    def email(cls, value):
        return normalize_email(value) if value else ""

    @field_validator("website")
    @classmethod
    def website_url(cls, value):
        if value:
            parsed = urlparse(value)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("Website must be a valid HTTPS URL without credentials")
        return value

    @field_validator("postal_code", "contact_phone")
    @classmethod
    def bounded_contact(cls, value, info):
        if value and not re.fullmatch(r"[0-9 +()\-]{4,25}" if info.field_name == "contact_phone" else r"[A-Za-z0-9 -]{3,12}", value):
            raise ValueError("Invalid contact or postal format")
        return value

class CoreInput(Strict):
    name: str = Field(min_length=3, max_length=200)
    legal_type: Literal["TRUST", "SOCIETY", "SECTION 8", "SECTION_8"]
    registration_number: str = Field(min_length=2, max_length=80)
    status: Literal["DRAFT", "ACTIVE", "SUSPENDED", "ARCHIVED"]
    city: str = Field(min_length=2, max_length=100)
    pan: str = Field(default="", max_length=10)

    @field_validator("pan")
    @classmethod
    def valid_pan(cls, value):
        value = value.upper()
        if value and not re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", value):
            raise ValueError("PAN must contain five letters, four digits and one letter")
        return value

class RegistrationInput(Strict):
    kind: Literal["12A", "12AB", "80G", "FCRA", "GST", "CSR"]
    status: Literal["UNKNOWN", "NOT_REGISTERED", "PENDING", "ACTIVE", "SUSPENDED", "EXPIRED"] = "UNKNOWN"
    number: str = Field(default="", max_length=100)
    registration_date: date | None = None
    effective_date: date | None = None
    expiry_date: date | None = None
    renewal_status: Literal["UNKNOWN", "NOT_REQUIRED", "PENDING", "RENEWED"] = "UNKNOWN"
    document_id: str | None = Field(default=None, max_length=36)

    @model_validator(mode="after")
    def date_order(self):
        start = self.effective_date or self.registration_date
        if start and self.expiry_date and self.expiry_date < start:
            raise ValueError("Expiry cannot precede the effective or registration date")
        if self.kind == "GST" and self.number and not re.fullmatch(r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][A-Z0-9]Z[A-Z0-9]", self.number):
            raise ValueError("Invalid GSTIN format")
        return self

class FinancialInput(Strict):
    annual_revenue: Decimal | None = Field(default=None, ge=0, max_digits=20, decimal_places=2)
    revenue_period: str = Field(default="", max_length=30)

    @model_validator(mode="after")
    def period_required(self):
        if self.annual_revenue is not None and not self.revenue_period:
            raise ValueError("Revenue period is required when annual revenue is entered")
        return self

class ProfileInput(Strict):
    expected_revision: int = Field(ge=0)
    core: CoreInput | None = None
    details: DetailsInput | None = None
    registrations: list[RegistrationInput] | None = Field(default=None, max_length=6)
    financial: FinancialInput | None = None

    @model_validator(mode="after")
    def unique_kinds(self):
        if self.registrations and len({r.kind for r in self.registrations}) != len(self.registrations):
            raise ValueError("Each registration kind may occur only once")
        return self

def owned_org(db, tenant, organization_id):
    row = db.scalar(select(Organization).where(Organization.id == organization_id, Organization.tenant_id == tenant))
    if not row:
        raise HTTPException(404, "Organization not found in this workspace")
    return row

def registration_rows(db, org):
    return db.scalars(select(OrganizationRegistration).where(OrganizationRegistration.organization_id == org.id, OrganizationRegistration.tenant_id == org.tenant_id)).all()

def profile_data(db, org):
    details = db.get(OrganizationDetails, org.id)
    financial = db.get(OrganizationComplianceProfile, org.id)
    if details and details.tenant_id != org.tenant_id or financial and financial.tenant_id != org.tenant_id:
        raise HTTPException(409, "Organization profile ownership is inconsistent")
    registrations = {row.kind: row for row in registration_rows(db, org)}
    return {"organization_id": org.id, "revision": details.revision if details else 0,
        "core": OrganizationOut.model_validate(org).model_dump(),
        "details": DetailsInput.model_validate_json(details.facts).model_dump(mode="json") if details else DetailsInput().model_dump(mode="json"),
        "registrations": [RegistrationInput.model_validate({key: getattr(registrations[kind], key) for key in RegistrationInput.model_fields}).model_dump(mode="json") if kind in registrations else RegistrationInput(kind=kind).model_dump(mode="json") for kind in KINDS],
        "financial": {"annual_revenue": str(financial.annual_revenue) if financial and financial.annual_revenue is not None else None, "revenue_period": financial.revenue_period if financial else ""}}

def completeness(db, org):
    data = profile_data(db, org); d = data["details"]; regs = data["registrations"]
    from .document_service import genuine_file
    stored_documents = db.scalars(select(Document).where(Document.tenant_id == org.tenant_id, Document.organization_id == org.id)).all()
    checks = {"basic": (30, [bool(org.name), bool(org.legal_type), bool(org.city)]),
        "registration": (15, [bool(org.registration_number), bool(d["registration_date"]), bool(d["registration_authority"])]),
        "tax": (10, [bool(org.pan)]),
        "registrations": (15, [r["status"] != "UNKNOWN" for r in regs]),
        "contact": (15, [bool(d["contact_name"]), bool(d["contact_email"]), bool(d["address_line_1"]), bool(d["state"]), bool(d["postal_code"])]),
        "financial": (10, [data["financial"]["annual_revenue"] is not None, bool(data["financial"]["revenue_period"])]),
        "documents": (5, [any(genuine_file(db, doc) for doc in stored_documents)])}
    sections = {key: {"percentage": round(sum(values)/len(values)*100), "status": "COMPLETE" if all(values) else "IN_PROGRESS" if any(values) else "NOT_STARTED"} for key, (_, values) in checks.items()}
    missing = [key for key in ("name", "legal_type", "registration_number", "city") if not getattr(org, key)]
    return {"percentage": round(sum(weight * sum(values)/len(values) for weight, values in checks.values())), "sections": sections,
        "missing_required_facts": missing, "next_action": next((key for key in checks if sections[key]["status"] != "COMPLETE"), "review"),
        "purpose": "SETUP_COMPLETENESS_NOT_LEGAL_HEALTH"}

def expanded_facts(db, org):
    data = profile_data(db, org); d = data["details"]
    facts = {"organization.legal_type": org.legal_type.replace(" ", "_"),
        "organization.registration_date": date.fromisoformat(d["registration_date"]) if d["registration_date"] else None,
        "organization.pan_present": bool(org.pan), "organization.tan_present": bool(d["tan"]),
        "financial.annual_revenue": Decimal(data["financial"]["annual_revenue"]) if data["financial"]["annual_revenue"] is not None else None}
    for row in data["registrations"]:
        key = "organization."+row["kind"].lower()
        facts[key+".status"] = row["status"] if row["status"] != "UNKNOWN" else None
        facts[key+".expiry_date"] = date.fromisoformat(row["expiry_date"]) if row["expiry_date"] else None
        if row["kind"] == "GST":
            facts["organization.gst.registered"] = None if row["status"] == "UNKNOWN" else row["status"] != "NOT_REGISTERED"
    return facts

@router.get("/organizations/{organization_id}/profile")
def get_profile(organization_id: str, db: DB, tenant: Tenant):
    org = owned_org(db, tenant, organization_id)
    return {**profile_data(db, org), "completeness": completeness(db, org)}

@router.get("/organizations/{organization_id}/profile-completeness")
def get_completeness(organization_id: str, db: DB, tenant: Tenant):
    return completeness(db, owned_org(db, tenant, organization_id))

def save_profile(organization_id, payload, db, tenant, actor, commit=True):
    org = owned_org(db, tenant, organization_id)
    details = db.get(OrganizationDetails, org.id)
    if not details:
        details = OrganizationDetails(organization_id=org.id, tenant_id=tenant, updated_by=actor.id, revision=0)
        db.add(details)
        try: db.flush()
        except IntegrityError:
            db.rollback(); raise HTTPException(409, "Profile changed; reload before saving") from None
    if details.tenant_id != tenant:
        raise HTTPException(409, "Organization profile ownership is inconsistent")
    claimed = db.execute(update(OrganizationDetails).where(OrganizationDetails.organization_id == org.id, OrganizationDetails.revision == payload.expected_revision).values(revision=OrganizationDetails.revision+1, updated_by=actor.id, updated_at=utcnow()).execution_options(synchronize_session=False))
    if claimed.rowcount != 1:
        db.rollback(); raise HTTPException(409, "Profile changed; reload before saving")
    changed = []
    if payload.core:
        values = payload.core.model_dump(); values["legal_type"] = values["legal_type"].replace("_", " ")
        duplicates = [func.lower(Organization.registration_number) == values["registration_number"].lower()]
        if values["pan"]: duplicates.append(func.lower(Organization.pan) == values["pan"].lower())
        if db.scalar(select(Organization.id).where(Organization.tenant_id == tenant, Organization.id != org.id, or_(*duplicates)).limit(1)):
            raise HTTPException(409, "Registration number or PAN already exists in this workspace")
        for key, value in values.items():
            if getattr(org, key) != value: changed.append(key); setattr(org, key, value)
    if payload.details:
        previous = json.loads(details.facts)
        values = DetailsInput.model_validate({**previous, **payload.details.model_dump(mode="json", exclude_unset=True)}).model_dump(mode="json")
        changed.extend(key for key, value in values.items() if previous.get(key) != value)
        details.facts = json.dumps(values)
    if payload.registrations is not None:
        existing = {r.kind:r for r in registration_rows(db, org)}
        for value in payload.registrations:
            if value.document_id:
                document = db.scalar(select(Document).where(Document.id == value.document_id, Document.tenant_id == tenant, Document.organization_id == org.id))
                if not document: raise HTTPException(404, "Registration document not found in this organization")
            row = existing.get(value.kind) or OrganizationRegistration(tenant_id=tenant, organization_id=org.id, kind=value.kind)
            for key, field in value.model_dump().items(): setattr(row, key, field)
            db.add(row); changed.append(value.kind+"_registration")
            if value.kind == "FCRA" and value.status != "UNKNOWN": org.fcra_active = value.status == "ACTIVE"
    if payload.financial:
        financial = db.get(OrganizationComplianceProfile, org.id) or OrganizationComplianceProfile(tenant_id=tenant, organization_id=org.id, updated_by=actor.name)
        if financial.tenant_id != tenant: raise HTTPException(409, "Financial profile ownership is inconsistent")
        financial.annual_revenue = payload.financial.annual_revenue; financial.revenue_period = payload.financial.revenue_period
        financial.updated_by = actor.name; financial.updated_at = utcnow(); db.add(financial); changed.append("financial")
    db.add(AuditEvent(tenant_id=tenant, actor_name=actor.name, action="ORGANIZATION_PROFILE_UPDATED", entity_type="Organization", entity_id=org.id, summary="Updated profile fields: "+", ".join(sorted(set(changed)))))
    if commit: db.commit()
    else: db.flush()
    db.expire(details)
    return {**profile_data(db, org), "completeness": completeness(db, org)}

@router.patch("/organizations/{organization_id}/profile")
def patch_profile(organization_id: str, payload: ProfileInput, db: DB, tenant: Tenant, actor: CurrentUser):
    return save_profile(organization_id, payload, db, tenant, actor)
