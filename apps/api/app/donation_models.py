"""Phase A donation register: donors, donations, receipts, the yearly statement and donor certificates.

Amounts are integers in paise. Confirmed donations are never deleted; a mistake is
reversed with a reason and entered again. Identity numbers are encrypted
(field_crypto) and kept with a masked suffix and a keyed lookup hash.
"""
from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .models import uid, utcnow


class DonationBankAccount(Base):
    __tablename__ = "donation_bank_accounts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    label: Mapped[str] = mapped_column(String(120))
    bank_name: Mapped[str] = mapped_column(String(120), default="")
    last_four: Mapped[str] = mapped_column(String(4), default="")
    kind: Mapped[str] = mapped_column(String(24), default="DOMESTIC")  # DOMESTIC | FCRA_DESIGNATED | FCRA_UTILISATION
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Donor(Base):
    __tablename__ = "donors"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    donor_type: Mapped[str] = mapped_column(String(24), default="INDIVIDUAL")
    id_type: Mapped[str] = mapped_column(String(12), default="NONE")  # NONE | PAN | AADHAAR
    id_cipher: Mapped[str] = mapped_column(Text, default="")
    id_last4: Mapped[str] = mapped_column(String(4), default="")
    id_lookup: Mapped[str] = mapped_column(String(64), default="", index=True)
    address: Mapped[str] = mapped_column(String(500), default="")
    email: Mapped[str] = mapped_column(String(200), default="")
    phone: Mapped[str] = mapped_column(String(30), default="")
    is_foreign_source: Mapped[bool] = mapped_column(Boolean, default=False)
    consent_to_contact: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Donation(Base):
    __tablename__ = "donations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    donor_id: Mapped[str] = mapped_column(ForeignKey("donors.id"), index=True)
    received_on: Mapped[date] = mapped_column(Date)
    financial_year: Mapped[str] = mapped_column(String(7), index=True)  # e.g. 2026-27
    amount_paise: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    mode: Mapped[str] = mapped_column(String(16))
    donation_type: Mapped[str] = mapped_column(String(16), default="GENERAL")
    purpose: Mapped[str] = mapped_column(String(300), default="")
    reference: Mapped[str] = mapped_column(String(120), default="")
    bank_account_id: Mapped[str | None] = mapped_column(ForeignKey("donation_bank_accounts.id"), nullable=True)
    fcra_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="DRAFT")  # DRAFT | CONFIRMED | REVERSED
    created_by: Mapped[str] = mapped_column(String(36))
    created_by_name: Mapped[str] = mapped_column(String(120), default="")
    confirmed_by: Mapped[str] = mapped_column(String(120), default="")
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reversed_by: Mapped[str] = mapped_column(String(120), default="")
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reversal_reason: Mapped[str] = mapped_column(String(500), default="")
    replaces_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DonationReceipt(Base):
    __tablename__ = "donation_receipts"
    __table_args__ = (UniqueConstraint("organization_id", "receipt_number", name="uq_donation_receipt_number"),
                      UniqueConstraint("donation_id", name="uq_donation_receipt_donation"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    donation_id: Mapped[str] = mapped_column(ForeignKey("donations.id"))
    financial_year: Mapped[str] = mapped_column(String(7))
    sequence: Mapped[int] = mapped_column(Integer)
    receipt_number: Mapped[str] = mapped_column(String(40))
    issued_on: Mapped[date] = mapped_column(Date)
    issued_by: Mapped[str] = mapped_column(String(120))
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DonationStatement(Base):
    __tablename__ = "donation_statements"
    __table_args__ = (UniqueConstraint("organization_id", "financial_year", name="uq_donation_statement_year"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    financial_year: Mapped[str] = mapped_column(String(7))
    status: Mapped[str] = mapped_column(String(16), default="DRAFT")  # DRAFT | FILED
    prepared_by: Mapped[str] = mapped_column(String(120))
    filed_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    acknowledgement_number: Mapped[str] = mapped_column(String(80), default="")
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id"), nullable=True)
    filing_task_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    certificate_task_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DonorCertificate(Base):
    __tablename__ = "donor_certificates"
    __table_args__ = (UniqueConstraint("statement_id", "donor_id", name="uq_donor_certificate"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    statement_id: Mapped[str] = mapped_column(ForeignKey("donation_statements.id"), index=True)
    donor_id: Mapped[str] = mapped_column(ForeignKey("donors.id"))
    amount_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    certificate_number: Mapped[str] = mapped_column(String(80), default="")
    status: Mapped[str] = mapped_column(String(16), default="PENDING")  # PENDING | ISSUED | SENT
    issued_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    sent_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
