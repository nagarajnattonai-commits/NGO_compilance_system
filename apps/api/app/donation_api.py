"""Phase A donation register API (design: NGO Operations Modules, approved 21 Nov 2026).

Routes live under /api/v1/donations, not /api/v1/organizations, because members with
organization access record donations; only workspace admins manage organizations.
Legal thresholds here are marked pending CA review and only ever produce warnings.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import CurrentUser, get_db, tenant_context
from .donation_models import Donation, DonationBankAccount, DonationReceipt, DonationStatement, Donor, DonorCertificate
from .field_crypto import decrypt, encrypt, lookup_hash
from .models import AuditEvent, Document, Organization, Task, TenantEntitlement, User, utcnow
from .organization_access import organization_access_role, require_organization_access, workspace_role
from .organization_models import OrganizationRegistration

DB = Annotated[Session, Depends(get_db)]
Tenant = Annotated[str, Depends(tenant_context)]
router = APIRouter(prefix="/api/v1/donations", tags=["Donations"])

# Pending CA review: 80G deduction is not allowed for cash donations above this amount.
CASH_DEDUCTION_LIMIT_PAISE = 2_000_00
RULES_STATUS = "PENDING_CA_REVIEW"
PAN_PATTERN = re.compile(r"[A-Z]{5}[0-9]{4}[A-Z]")
AADHAAR_PATTERN = re.compile(r"[0-9]{12}")
DONOR_TYPES = Literal["INDIVIDUAL", "COMPANY", "TRUST", "FOREIGN_SOURCE", "ANONYMOUS", "OTHER"]
MODES = Literal["CASH", "CHEQUE", "BANK_TRANSFER", "UPI", "CARD", "IN_KIND"]
DONATION_TYPES = Literal["CORPUS", "SPECIFIC_GRANT", "GENERAL"]
ACCOUNT_KINDS = Literal["DOMESTIC", "FCRA_DESIGNATED", "FCRA_UTILISATION"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ---------- shared helpers ----------

def financial_year(day: date) -> str:
    start = day.year if day.month >= 4 else day.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


def statement_due(year: str) -> date:
    return date(int(year[:4]) + 1, 5, 31)


def ensure_enabled(db, tenant_id: str) -> None:
    row = db.scalar(select(TenantEntitlement).where(TenantEntitlement.tenant_id == tenant_id,
                                                    TenantEntitlement.feature_key == "donation_register"))
    if row is not None and not row.enabled:
        raise HTTPException(403, "UPGRADE_REQUIRED:donation_register")


def organization(db, tenant_id: str, organization_id: str, *, write: bool = False) -> Organization:
    ensure_enabled(db, tenant_id)
    row = db.scalar(select(Organization).where(Organization.id == organization_id, Organization.tenant_id == tenant_id))
    if not row:
        raise HTTPException(404, "Organization not found in this workspace")
    require_organization_access(db, tenant_id, organization_id, write=write)
    return row


def is_admin(db, tenant_id: str, user) -> bool:
    return workspace_role(db, tenant_id, user.id) == "ADMIN"


def audit(db, tenant_id: str, actor, action: str, entity_type: str, entity_id: str, summary: str) -> None:
    db.add(AuditEvent(tenant_id=tenant_id, actor_name=actor.name, action=action, entity_type=entity_type,
                      entity_id=entity_id, summary=summary[:280]))


def owned(db, model, tenant_id: str, record_id: str, label: str):
    row = db.get(model, record_id)
    if not row or row.tenant_id != tenant_id:
        raise HTTPException(404, f"{label} not found")
    return row


def check_document(db, tenant_id: str, organization_id: str, document_id: str | None) -> None:
    if document_id and not db.scalar(select(Document.id).where(
            Document.id == document_id, Document.tenant_id == tenant_id, Document.organization_id == organization_id)):
        raise HTTPException(404, "Document not found in this organization")


def make_task(db, tenant_id: str, organization_id: str, title: str, due: date, assignee: User | None, priority="HIGH") -> Task:
    name = assignee.name if assignee else "Unassigned"
    task = Task(tenant_id=tenant_id, organization_id=organization_id, title=title[:220], due_at=due, priority=priority,
                assignee_name=name, assignee_initials="".join(part[0] for part in name.split()[:2]).upper(),
                assignee_user_id=assignee.id if assignee else None)
    db.add(task); db.flush()
    return task


def registration(db, tenant_id: str, organization_id: str, kind: str) -> OrganizationRegistration | None:
    return db.scalar(select(OrganizationRegistration).where(OrganizationRegistration.tenant_id == tenant_id,
                                                            OrganizationRegistration.organization_id == organization_id,
                                                            OrganizationRegistration.kind == kind))


def responsible(db, row: OrganizationRegistration | None) -> User | None:
    return db.get(User, row.responsible_user_id) if row and row.responsible_user_id else None


# ---------- bank accounts ----------

class BankAccountInput(Strict):
    organization_id: str = Field(max_length=36)
    label: str = Field(min_length=2, max_length=120)
    bank_name: str = Field(default="", max_length=120)
    last_four: str = Field(default="", pattern=r"^([0-9]{4})?$")
    kind: ACCOUNT_KINDS = "DOMESTIC"


class BankAccountPatch(Strict):
    label: str | None = Field(default=None, min_length=2, max_length=120)
    active: bool | None = None


def account_out(row: DonationBankAccount) -> dict:
    return {"id": row.id, "organization_id": row.organization_id, "label": row.label, "bank_name": row.bank_name,
            "last_four": row.last_four, "kind": row.kind, "active": row.active}


@router.get("/bank-accounts")
def list_accounts(organization_id: str, db: DB, tenant_id: Tenant, user: CurrentUser):
    organization(db, tenant_id, organization_id)
    return [account_out(row) for row in db.scalars(select(DonationBankAccount).where(
        DonationBankAccount.tenant_id == tenant_id, DonationBankAccount.organization_id == organization_id
    ).order_by(DonationBankAccount.label)).all()]


@router.post("/bank-accounts", status_code=201)
def create_account(payload: BankAccountInput, db: DB, tenant_id: Tenant, user: CurrentUser):
    organization(db, tenant_id, payload.organization_id, write=True)
    row = DonationBankAccount(tenant_id=tenant_id, **payload.model_dump())
    db.add(row); db.flush()
    audit(db, tenant_id, user, "DONATION_ACCOUNT_CREATED", "DonationBankAccount", row.id, f"Bank account {row.label} ({row.kind})")
    db.commit()
    return account_out(row)


@router.patch("/bank-accounts/{account_id}")
def update_account(account_id: str, payload: BankAccountPatch, db: DB, tenant_id: Tenant, user: CurrentUser):
    row = owned(db, DonationBankAccount, tenant_id, account_id, "Bank account")
    organization(db, tenant_id, row.organization_id, write=True)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    audit(db, tenant_id, user, "DONATION_ACCOUNT_UPDATED", "DonationBankAccount", row.id, f"Bank account {row.label} updated")
    db.commit()
    return account_out(row)


# ---------- donors ----------

class DonorInput(Strict):
    organization_id: str = Field(max_length=36)
    name: str = Field(min_length=2, max_length=200)
    donor_type: DONOR_TYPES = "INDIVIDUAL"
    id_type: Literal["NONE", "PAN", "AADHAAR"] = "NONE"
    id_number: str = Field(default="", max_length=20)
    address: str = Field(default="", max_length=500)
    email: str = Field(default="", max_length=200)
    phone: str = Field(default="", max_length=30)
    is_foreign_source: bool = False
    consent_to_contact: bool = False


class DonorPatch(Strict):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    donor_type: DONOR_TYPES | None = None
    id_type: Literal["NONE", "PAN", "AADHAAR"] | None = None
    id_number: str | None = Field(default=None, max_length=20)
    address: str | None = Field(default=None, max_length=500)
    email: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=30)
    is_foreign_source: bool | None = None
    consent_to_contact: bool | None = None


def normalized_identity(id_type: str, number: str) -> str:
    value = re.sub(r"[\s-]", "", number or "").upper()
    if id_type == "NONE":
        if value:
            raise HTTPException(422, "Choose PAN or Aadhaar before entering an identity number")
        return ""
    if id_type == "PAN" and not PAN_PATTERN.fullmatch(value):
        raise HTTPException(422, "PAN must be 10 characters: 5 letters, 4 digits, 1 letter")
    if id_type == "AADHAAR" and not AADHAAR_PATTERN.fullmatch(value):
        raise HTTPException(422, "Aadhaar must be 12 digits")
    return value


def set_identity(db, donor: Donor, id_type: str, number: str) -> None:
    value = normalized_identity(id_type, number)
    lookup = lookup_hash(id_type + ":" + value) if value else ""
    if lookup and db.scalar(select(Donor.id).where(Donor.tenant_id == donor.tenant_id, Donor.organization_id == donor.organization_id,
                                                  Donor.id_lookup == lookup, Donor.id != donor.id).limit(1)):
        raise HTTPException(409, "A donor with this identity number already exists in this organization")
    donor.id_type = id_type if value else "NONE"
    donor.id_cipher = encrypt(value) if value else ""
    donor.id_last4 = value[-4:] if value else ""
    donor.id_lookup = lookup


def donor_out(row: Donor, full: bool) -> dict:
    data = {"id": row.id, "organization_id": row.organization_id, "name": row.name, "donor_type": row.donor_type,
            "id_type": row.id_type, "has_identity": bool(row.id_cipher), "is_foreign_source": row.is_foreign_source}
    if full:
        data |= {"id_masked": ("••••••" + row.id_last4) if row.id_last4 else "", "address": row.address,
                 "email": row.email, "phone": row.phone, "consent_to_contact": row.consent_to_contact}
    return data


def can_see_contacts(db, tenant_id: str, organization_id: str, user) -> bool:
    return organization_access_role(db, tenant_id, organization_id, user.id) in {"CONTRIBUTOR", "MANAGER"} and user.role != "VIEWER"


@router.get("/donors")
def list_donors(db: DB, tenant_id: Tenant, user: CurrentUser, organization_id: str,
                q: str = Query(default="", max_length=100)):
    organization(db, tenant_id, organization_id)
    statement = select(Donor).where(Donor.tenant_id == tenant_id, Donor.organization_id == organization_id)
    if q.strip():
        pattern = f"%{q.strip().lower()}%"
        statement = statement.where(or_(func.lower(Donor.name).like(pattern), func.lower(Donor.email).like(pattern)))
    full = can_see_contacts(db, tenant_id, organization_id, user)
    return [donor_out(row, full) for row in db.scalars(statement.order_by(Donor.name).limit(500)).all()]


@router.post("/donors", status_code=201)
def create_donor(payload: DonorInput, db: DB, tenant_id: Tenant, user: CurrentUser):
    organization(db, tenant_id, payload.organization_id, write=True)
    values = payload.model_dump(exclude={"id_type", "id_number"})
    values["email"] = values["email"].lower()
    if values["email"] and db.scalar(select(Donor.id).where(
            Donor.tenant_id == tenant_id, Donor.organization_id == payload.organization_id,
            func.lower(Donor.name) == payload.name.lower(), Donor.email == values["email"]).limit(1)):
        raise HTTPException(409, "A donor with this name and email already exists in this organization")
    donor = Donor(tenant_id=tenant_id, created_by=user.id, **values)
    if payload.donor_type == "FOREIGN_SOURCE":
        donor.is_foreign_source = True
    set_identity(db, donor, payload.id_type, payload.id_number)
    db.add(donor); db.flush()
    audit(db, tenant_id, user, "DONOR_CREATED", "Donor", donor.id, f"Donor {donor.name} added")
    db.commit()
    return donor_out(donor, True)


@router.patch("/donors/{donor_id}")
def update_donor(donor_id: str, payload: DonorPatch, db: DB, tenant_id: Tenant, user: CurrentUser):
    donor = owned(db, Donor, tenant_id, donor_id, "Donor")
    organization(db, tenant_id, donor.organization_id, write=True)
    changes = payload.model_dump(exclude_unset=True)
    id_type, id_number = changes.pop("id_type", None), changes.pop("id_number", None)
    if id_type is not None or id_number is not None:
        set_identity(db, donor, id_type or donor.id_type, id_number if id_number is not None else "")
    for key, value in changes.items():
        setattr(donor, key, value.lower() if key == "email" else value)
    if donor.donor_type == "FOREIGN_SOURCE":
        donor.is_foreign_source = True
    donor.updated_at = utcnow()
    fields = sorted(set(changes) | ({"identity"} if id_type is not None or id_number is not None else set()))
    audit(db, tenant_id, user, "DONOR_UPDATED", "Donor", donor.id, f"Donor {donor.name} updated: {', '.join(fields)}")
    db.commit()
    return donor_out(donor, True)


@router.post("/donors/{donor_id}/reveal-identity")
def reveal_identity(donor_id: str, db: DB, tenant_id: Tenant, user: CurrentUser):
    donor = owned(db, Donor, tenant_id, donor_id, "Donor")
    organization(db, tenant_id, donor.organization_id)
    if not is_admin(db, tenant_id, user):
        raise HTTPException(403, "Only workspace administrators can reveal identity numbers")
    audit(db, tenant_id, user, "DONOR_IDENTITY_REVEALED", "Donor", donor.id, f"{donor.id_type} revealed for donor {donor.name}")
    db.commit()
    return {"id_type": donor.id_type, "id_number": decrypt(donor.id_cipher)}


# ---------- donations ----------

class DonationInput(Strict):
    organization_id: str = Field(max_length=36)
    donor_id: str = Field(max_length=36)
    received_on: date
    amount_paise: int = Field(gt=0, le=10_000_000_000_00)
    currency: str = Field(default="INR", pattern=r"^[A-Z]{3}$")
    mode: MODES
    donation_type: DONATION_TYPES = "GENERAL"
    purpose: str = Field(default="", max_length=300)
    reference: str = Field(default="", max_length=120)
    bank_account_id: str | None = Field(default=None, max_length=36)
    replaces_id: str | None = Field(default=None, max_length=36)


class DonationPatch(Strict):
    donor_id: str | None = Field(default=None, max_length=36)
    received_on: date | None = None
    amount_paise: int | None = Field(default=None, gt=0, le=10_000_000_000_00)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    mode: MODES | None = None
    donation_type: DONATION_TYPES | None = None
    purpose: str | None = Field(default=None, max_length=300)
    reference: str | None = Field(default=None, max_length=120)
    bank_account_id: str | None = Field(default=None, max_length=36)


class ReverseInput(Strict):
    reason: str = Field(min_length=5, max_length=500)


class ReceiptInput(Strict):
    issued_on: date | None = None
    document_id: str | None = Field(default=None, max_length=36)


def donation_warnings(db, row: Donation, donor: Donor, account: DonationBankAccount | None) -> list[str]:
    warnings = []
    if row.mode == "CASH" and row.amount_paise > CASH_DEDUCTION_LIMIT_PAISE:
        warnings.append("CASH_ABOVE_DEDUCTION_LIMIT")
    if (donor.is_foreign_source or row.currency != "INR") and (account is None or account.kind == "DOMESTIC"):
        warnings.append("FOREIGN_SOURCE_TO_DOMESTIC_ACCOUNT")
    if not donor.id_cipher and donor.donor_type != "ANONYMOUS":
        warnings.append("DONOR_IDENTITY_MISSING")
    if not donor.address:
        warnings.append("DONOR_ADDRESS_MISSING")
    return warnings


def registration_warning(db, row: Donation) -> str | None:
    reg = registration(db, row.tenant_id, row.organization_id, "80G")
    if not reg or reg.status != "ACTIVE" or reg.verification_status != "VERIFIED":
        return "REGISTRATION_80G_NOT_ACTIVE_AND_VERIFIED"
    if reg.expiry_date and reg.expiry_date < row.received_on:
        return "REGISTRATION_80G_EXPIRED_ON_DATE"
    return None


def donation_out(db, row: Donation, donors: dict, accounts: dict, receipts: dict) -> dict:
    donor = donors.get(row.donor_id) or db.get(Donor, row.donor_id)
    account = accounts.get(row.bank_account_id) if row.bank_account_id else None
    receipt = receipts.get(row.id)
    return {"id": row.id, "organization_id": row.organization_id, "donor_id": row.donor_id, "donor_name": donor.name,
            "received_on": row.received_on.isoformat(), "financial_year": row.financial_year,
            "amount_paise": row.amount_paise, "currency": row.currency, "mode": row.mode,
            "donation_type": row.donation_type, "purpose": row.purpose, "reference": row.reference,
            "bank_account_id": row.bank_account_id, "bank_account_label": account.label if account else "",
            "fcra_flag": row.fcra_flag, "status": row.status, "created_by_name": row.created_by_name,
            "confirmed_by": row.confirmed_by, "reversed_by": row.reversed_by, "reversal_reason": row.reversal_reason,
            "replaces_id": row.replaces_id,
            "receipt": {"receipt_number": receipt.receipt_number, "issued_on": receipt.issued_on.isoformat(),
                        "document_id": receipt.document_id} if receipt else None,
            "warnings": donation_warnings(db, row, donor, account)}


def resolve_links(db, tenant_id: str, organization_id: str, donor_id: str, account_id: str | None):
    donor = db.get(Donor, donor_id)
    if not donor or donor.tenant_id != tenant_id or donor.organization_id != organization_id:
        raise HTTPException(404, "Donor not found in this organization")
    account = None
    if account_id:
        account = db.get(DonationBankAccount, account_id)
        if not account or account.tenant_id != tenant_id or account.organization_id != organization_id or not account.active:
            raise HTTPException(404, "Active bank account not found in this organization")
    return donor, account


def apply_derived(row: Donation, donor: Donor, account: DonationBankAccount | None) -> None:
    if row.received_on > date.today():
        raise HTTPException(422, "A donation cannot be dated in the future")
    row.financial_year = financial_year(row.received_on)
    # Never typed freely: foreign status follows the donor and the receiving account.
    row.fcra_flag = bool(donor.is_foreign_source or (account and account.kind != "DOMESTIC"))


def flag_foreign_to_domestic(db, row: Donation, donor: Donor, account, user) -> None:
    if "FOREIGN_SOURCE_TO_DOMESTIC_ACCOUNT" not in donation_warnings(db, row, donor, account):
        return
    owner = responsible(db, registration(db, row.tenant_id, row.organization_id, "FCRA"))
    make_task(db, row.tenant_id, row.organization_id,
              f"Check foreign-source donation from {donor.name} received in a domestic account", date.today(), owner, "CRITICAL")


@router.get("")
def list_donations(db: DB, tenant_id: Tenant, user: CurrentUser, organization_id: str,
                   financial_year_filter: str | None = Query(default=None, alias="financial_year", pattern=r"^[0-9]{4}-[0-9]{2}$"),
                   status: Literal["DRAFT", "CONFIRMED", "REVERSED"] | None = None):
    organization(db, tenant_id, organization_id)
    statement = select(Donation).where(Donation.tenant_id == tenant_id, Donation.organization_id == organization_id)
    if financial_year_filter:
        statement = statement.where(Donation.financial_year == financial_year_filter)
    if status:
        statement = statement.where(Donation.status == status)
    rows = db.scalars(statement.order_by(Donation.received_on.desc(), Donation.created_at.desc()).limit(1000)).all()
    donors = {row.id: row for row in db.scalars(select(Donor).where(Donor.id.in_({r.donor_id for r in rows}))).all()} if rows else {}
    accounts = {row.id: row for row in db.scalars(select(DonationBankAccount).where(
        DonationBankAccount.tenant_id == tenant_id, DonationBankAccount.organization_id == organization_id)).all()}
    receipts = {row.donation_id: row for row in db.scalars(select(DonationReceipt).where(
        DonationReceipt.donation_id.in_([r.id for r in rows]))).all()} if rows else {}
    return [donation_out(db, row, donors, accounts, receipts) for row in rows]


@router.post("", status_code=201)
def create_donation(payload: DonationInput, db: DB, tenant_id: Tenant, user: CurrentUser):
    organization(db, tenant_id, payload.organization_id, write=True)
    donor, account = resolve_links(db, tenant_id, payload.organization_id, payload.donor_id, payload.bank_account_id)
    if payload.replaces_id:
        original = owned(db, Donation, tenant_id, payload.replaces_id, "Donation being corrected")
        if original.organization_id != payload.organization_id or original.status != "REVERSED":
            raise HTTPException(422, "Only a reversed donation in this organization can be replaced")
    row = Donation(tenant_id=tenant_id, created_by=user.id, created_by_name=user.name, **payload.model_dump())
    apply_derived(row, donor, account)
    db.add(row); db.flush()
    flag_foreign_to_domestic(db, row, donor, account, user)
    audit(db, tenant_id, user, "DONATION_RECORDED", "Donation", row.id,
          f"Draft donation {row.amount_paise / 100:.2f} {row.currency} from {donor.name}")
    db.commit()
    return donation_out(db, row, {donor.id: donor}, {account.id: account} if account else {}, {})


@router.patch("/{donation_id}")
def update_donation(donation_id: str, payload: DonationPatch, db: DB, tenant_id: Tenant, user: CurrentUser):
    row = owned(db, Donation, tenant_id, donation_id, "Donation")
    organization(db, tenant_id, row.organization_id, write=True)
    if row.status != "DRAFT":
        raise HTTPException(409, "Confirmed donations are locked; reverse it and record a new entry")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    donor, account = resolve_links(db, tenant_id, row.organization_id, row.donor_id, row.bank_account_id)
    apply_derived(row, donor, account)
    row.updated_at = utcnow()
    audit(db, tenant_id, user, "DONATION_UPDATED", "Donation", row.id, f"Draft donation from {donor.name} updated")
    db.commit()
    return donation_out(db, row, {donor.id: donor}, {account.id: account} if account else {}, {})


@router.delete("/{donation_id}", status_code=204)
def delete_draft(donation_id: str, db: DB, tenant_id: Tenant, user: CurrentUser):
    row = owned(db, Donation, tenant_id, donation_id, "Donation")
    organization(db, tenant_id, row.organization_id, write=True)
    if row.status != "DRAFT":
        raise HTTPException(409, "Only drafts can be deleted; confirmed donations are reversed instead")
    audit(db, tenant_id, user, "DONATION_DRAFT_DELETED", "Donation", row.id, f"Draft donation of {row.amount_paise / 100:.2f} deleted")
    db.delete(row); db.commit()


@router.post("/{donation_id}/confirm")
def confirm_donation(donation_id: str, db: DB, tenant_id: Tenant, user: CurrentUser):
    row = owned(db, Donation, tenant_id, donation_id, "Donation")
    organization(db, tenant_id, row.organization_id, write=True)
    admin = is_admin(db, tenant_id, user)
    if not admin and organization_access_role(db, tenant_id, row.organization_id, user.id) != "MANAGER":
        raise HTTPException(403, "Confirming donations needs the organization manager role")
    if not admin and row.created_by == user.id:
        raise HTTPException(403, "A second person must confirm a donation you recorded")
    if row.status != "DRAFT":
        raise HTTPException(409, "Only draft donations can be confirmed")
    if row.received_on > date.today():
        raise HTTPException(422, "A donation cannot be dated in the future")
    row.status, row.confirmed_by, row.confirmed_at, row.updated_at = "CONFIRMED", user.name, utcnow(), utcnow()
    audit(db, tenant_id, user, "DONATION_CONFIRMED", "Donation", row.id, f"Donation of {row.amount_paise / 100:.2f} {row.currency} confirmed")
    db.commit()
    return list_one(db, row)


@router.post("/{donation_id}/reverse")
def reverse_donation(donation_id: str, payload: ReverseInput, db: DB, tenant_id: Tenant, user: CurrentUser):
    row = owned(db, Donation, tenant_id, donation_id, "Donation")
    organization(db, tenant_id, row.organization_id, write=True)
    if not is_admin(db, tenant_id, user):
        raise HTTPException(403, "Only workspace administrators can reverse a confirmed donation")
    if row.status != "CONFIRMED":
        raise HTTPException(409, "Only confirmed donations can be reversed")
    filed = db.scalar(select(DonationStatement.status).where(DonationStatement.organization_id == row.organization_id,
                                                            DonationStatement.financial_year == row.financial_year))
    row.status, row.reversed_by, row.reversed_at, row.reversal_reason, row.updated_at = (
        "REVERSED", user.name, utcnow(), payload.reason, utcnow())
    audit(db, tenant_id, user, "DONATION_REVERSED", "Donation", row.id,
          f"Donation of {row.amount_paise / 100:.2f} reversed: {payload.reason}")
    if filed == "FILED":
        make_task(db, tenant_id, row.organization_id, f"Revise the filed donation statement for {row.financial_year}: a donation was reversed",
                  date.today(), user)
    db.commit()
    return list_one(db, row)


@router.post("/{donation_id}/receipt", status_code=201)
def issue_receipt(donation_id: str, payload: ReceiptInput, db: DB, tenant_id: Tenant, user: CurrentUser):
    row = owned(db, Donation, tenant_id, donation_id, "Donation")
    organization(db, tenant_id, row.organization_id, write=True)
    if row.status != "CONFIRMED":
        raise HTTPException(409, "Confirm the donation before issuing a receipt")
    if db.scalar(select(DonationReceipt.id).where(DonationReceipt.donation_id == row.id)):
        raise HTTPException(409, "A receipt has already been issued for this donation")
    check_document(db, tenant_id, row.organization_id, payload.document_id)
    for _ in range(3):
        sequence = (db.scalar(select(func.max(DonationReceipt.sequence)).where(
            DonationReceipt.organization_id == row.organization_id, DonationReceipt.financial_year == row.financial_year)) or 0) + 1
        receipt = DonationReceipt(tenant_id=tenant_id, organization_id=row.organization_id, donation_id=row.id,
                                  financial_year=row.financial_year, sequence=sequence,
                                  receipt_number=f"RCPT/{row.financial_year}/{sequence:04d}",
                                  issued_on=payload.issued_on or date.today(), issued_by=user.name, document_id=payload.document_id)
        try:
            with db.begin_nested():
                db.add(receipt)
            break
        except IntegrityError:
            continue
    else:
        raise HTTPException(409, "Receipt number was taken by another request; try again")
    warning = registration_warning(db, row)
    audit(db, tenant_id, user, "DONATION_RECEIPT_ISSUED", "Donation", row.id, f"Receipt {receipt.receipt_number} issued")
    db.commit()
    result = list_one(db, row)
    result["receipt_warning"] = warning
    return result


def list_one(db, row: Donation) -> dict:
    donor = db.get(Donor, row.donor_id)
    account = db.get(DonationBankAccount, row.bank_account_id) if row.bank_account_id else None
    receipt = db.scalar(select(DonationReceipt).where(DonationReceipt.donation_id == row.id))
    return donation_out(db, row, {donor.id: donor}, {account.id: account} if account else {}, {row.id: receipt} if receipt else {})


# ---------- yearly statement (Form 10BD / Form 113) and certificates (Form 10BE / Form 114) ----------

class StatementInput(Strict):
    organization_id: str = Field(max_length=36)
    financial_year: str = Field(pattern=r"^[0-9]{4}-[0-9]{2}$")


class StatementPatch(Strict):
    status: Literal["DRAFT", "FILED"] | None = None
    filed_on: date | None = None
    acknowledgement_number: str | None = Field(default=None, max_length=80)
    document_id: str | None = Field(default=None, max_length=36)


class CertificatePatch(Strict):
    status: Literal["PENDING", "ISSUED", "SENT"] | None = None
    certificate_number: str | None = Field(default=None, max_length=80)
    issued_on: date | None = None
    sent_on: date | None = None
    document_id: str | None = Field(default=None, max_length=36)


def valid_year(year: str) -> str:
    start = int(year[:4])
    if f"{(start + 1) % 100:02d}" != year[5:]:
        raise HTTPException(422, "Financial year must look like 2026-27")
    return year


def certificate_out(row: DonorCertificate, donor: Donor) -> dict:
    return {"id": row.id, "donor_id": row.donor_id, "donor_name": donor.name, "amount_paise": row.amount_paise,
            "certificate_number": row.certificate_number, "status": row.status,
            "issued_on": row.issued_on.isoformat() if row.issued_on else None,
            "sent_on": row.sent_on.isoformat() if row.sent_on else None, "document_id": row.document_id}


def statement_summary(db, tenant_id: str, organization_id: str, year: str) -> dict:
    rows = db.scalars(select(Donation).where(Donation.tenant_id == tenant_id, Donation.organization_id == organization_id,
                                             Donation.financial_year == year)).all()
    confirmed = [row for row in rows if row.status == "CONFIRMED"]
    donors = {row.id: row for row in db.scalars(select(Donor).where(Donor.id.in_({r.donor_id for r in rows}))).all()} if rows else {}
    by_mode: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for row in confirmed:
        by_mode[row.mode] = by_mode.get(row.mode, 0) + row.amount_paise
        by_type[row.donation_type] = by_type.get(row.donation_type, 0) + row.amount_paise
    issues = []
    for donor_id in sorted({row.donor_id for row in confirmed}):
        donor = donors[donor_id]
        missing = [label for label, ok in (("IDENTITY", bool(donor.id_cipher)), ("ADDRESS", bool(donor.address))) if not ok]
        if missing and donor.donor_type != "ANONYMOUS":
            issues.append({"donor_id": donor.id, "donor_name": donor.name, "missing": missing})
    record = db.scalar(select(DonationStatement).where(DonationStatement.tenant_id == tenant_id,
                                                       DonationStatement.organization_id == organization_id,
                                                       DonationStatement.financial_year == year))
    certificates = []
    if record:
        cert_rows = db.scalars(select(DonorCertificate).where(DonorCertificate.statement_id == record.id)).all()
        cert_donors = {row.id: row for row in db.scalars(select(Donor).where(Donor.id.in_({c.donor_id for c in cert_rows}))).all()} if cert_rows else {}
        certificates = [certificate_out(row, cert_donors[row.donor_id]) for row in sorted(cert_rows, key=lambda c: cert_donors[c.donor_id].name)]
    return {
        "organization_id": organization_id, "financial_year": year, "due_on": statement_due(year).isoformat(),
        "rules_status": RULES_STATUS,
        "totals": {"confirmed_count": len(confirmed), "confirmed_paise": sum(r.amount_paise for r in confirmed),
                   "draft_count": sum(r.status == "DRAFT" for r in rows), "reversed_count": sum(r.status == "REVERSED" for r in rows),
                   "foreign_count": sum(r.fcra_flag for r in confirmed),
                   "cash_above_limit": sum(r.mode == "CASH" and r.amount_paise > CASH_DEDUCTION_LIMIT_PAISE for r in confirmed)},
        "by_mode": by_mode, "by_type": by_type, "donor_issues": issues,
        "statement": {"id": record.id, "status": record.status, "prepared_by": record.prepared_by,
                      "filed_on": record.filed_on.isoformat() if record.filed_on else None,
                      "acknowledgement_number": record.acknowledgement_number, "document_id": record.document_id} if record else None,
        "certificates": certificates,
    }


@router.get("/statement")
def get_statement(db: DB, tenant_id: Tenant, user: CurrentUser, organization_id: str,
                  financial_year_value: str = Query(alias="financial_year", pattern=r"^[0-9]{4}-[0-9]{2}$")):
    organization(db, tenant_id, organization_id)
    return statement_summary(db, tenant_id, organization_id, valid_year(financial_year_value))


@router.post("/statement", status_code=201)
def prepare_statement(payload: StatementInput, db: DB, tenant_id: Tenant, user: CurrentUser):
    organization(db, tenant_id, payload.organization_id, write=True)
    year = valid_year(payload.financial_year)
    record = db.scalar(select(DonationStatement).where(DonationStatement.tenant_id == tenant_id,
                                                       DonationStatement.organization_id == payload.organization_id,
                                                       DonationStatement.financial_year == year))
    if not record:
        owner = responsible(db, registration(db, tenant_id, payload.organization_id, "80G")) or db.get(User, user.id)
        due = statement_due(year)
        filing = make_task(db, tenant_id, payload.organization_id, f"File donation statement (Form 10BD / Form 113) for {year}", due, owner)
        certificates = make_task(db, tenant_id, payload.organization_id, f"Issue donor certificates (Form 10BE / Form 114) for {year}", due, owner)
        record = DonationStatement(tenant_id=tenant_id, organization_id=payload.organization_id, financial_year=year,
                                   prepared_by=user.name, filing_task_id=filing.id, certificate_task_id=certificates.id)
        db.add(record); db.flush()
        audit(db, tenant_id, user, "DONATION_STATEMENT_PREPARED", "DonationStatement", record.id, f"Donation statement for {year} prepared")
        db.commit()
    return statement_summary(db, tenant_id, payload.organization_id, year)


def complete_task(db, task_id: str | None) -> None:
    task = db.get(Task, task_id) if task_id else None
    if task and task.status != "DONE":
        task.status, task.completed_at, task.updated_at = "DONE", utcnow(), utcnow()


@router.patch("/statement/{statement_id}")
def update_statement(statement_id: str, payload: StatementPatch, db: DB, tenant_id: Tenant, user: CurrentUser):
    record = owned(db, DonationStatement, tenant_id, statement_id, "Donation statement")
    organization(db, tenant_id, record.organization_id, write=True)
    changes = payload.model_dump(exclude_unset=True)
    check_document(db, tenant_id, record.organization_id, changes.get("document_id"))
    for key, value in changes.items():
        setattr(record, key, value)
    if record.status == "FILED":
        if not record.filed_on or not record.acknowledgement_number:
            raise HTTPException(422, "Record the filing date and acknowledgement number before marking the statement filed")
        complete_task(db, record.filing_task_id)
        totals: dict[str, int] = {}
        for donation in db.scalars(select(Donation).where(Donation.organization_id == record.organization_id,
                                                          Donation.financial_year == record.financial_year,
                                                          Donation.status == "CONFIRMED")).all():
            totals[donation.donor_id] = totals.get(donation.donor_id, 0) + donation.amount_paise
        existing = {row.donor_id: row for row in db.scalars(select(DonorCertificate).where(DonorCertificate.statement_id == record.id)).all()}
        for donor_id, amount in totals.items():
            donor = db.get(Donor, donor_id)
            if not donor.id_cipher:
                continue  # the portal issues certificates only for donors reported with an identity number
            if donor_id in existing:
                existing[donor_id].amount_paise = amount
            else:
                db.add(DonorCertificate(tenant_id=tenant_id, organization_id=record.organization_id, statement_id=record.id,
                                        donor_id=donor_id, amount_paise=amount))
    record.updated_at = utcnow()
    audit(db, tenant_id, user, "DONATION_STATEMENT_UPDATED", "DonationStatement", record.id,
          f"Donation statement for {record.financial_year}: {record.status}")
    db.commit()
    return statement_summary(db, tenant_id, record.organization_id, record.financial_year)


@router.patch("/certificates/{certificate_id}")
def update_certificate(certificate_id: str, payload: CertificatePatch, db: DB, tenant_id: Tenant, user: CurrentUser):
    row = owned(db, DonorCertificate, tenant_id, certificate_id, "Certificate")
    organization(db, tenant_id, row.organization_id, write=True)
    changes = payload.model_dump(exclude_unset=True)
    check_document(db, tenant_id, row.organization_id, changes.get("document_id"))
    for key, value in changes.items():
        setattr(row, key, value)
    if row.status in {"ISSUED", "SENT"} and not row.certificate_number:
        raise HTTPException(422, "Enter the certificate number from the income tax portal")
    if row.status in {"ISSUED", "SENT"} and not row.issued_on:
        row.issued_on = date.today()
    if row.status == "SENT" and not row.sent_on:
        row.sent_on = date.today()
    row.updated_at = utcnow()
    record = db.get(DonationStatement, row.statement_id)
    db.flush()
    statuses = db.scalars(select(DonorCertificate.status).where(DonorCertificate.statement_id == record.id)).all()
    if statuses and all(status == "SENT" for status in statuses):
        complete_task(db, record.certificate_task_id)
    audit(db, tenant_id, user, "DONOR_CERTIFICATE_UPDATED", "DonorCertificate", row.id, f"Certificate {row.certificate_number or '-'}: {row.status}")
    db.commit()
    return statement_summary(db, tenant_id, row.organization_id, record.financial_year)
