"""Additive organization facts; legacy organization and revenue rows remain authoritative."""
from datetime import date, datetime
from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base
from .models import uid, utcnow

class OrganizationDetails(Base):
    __tablename__ = "organization_details"
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    facts: Mapped[str] = mapped_column(Text, default="{}")
    updated_by: Mapped[str] = mapped_column(ForeignKey("auth_users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class OrganizationRegistration(Base):
    __tablename__ = "organization_registrations"
    __table_args__ = (UniqueConstraint("organization_id", "kind", name="uq_org_registration_kind"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    kind: Mapped[str] = mapped_column(String(12))
    status: Mapped[str] = mapped_column(String(24), default="UNKNOWN")
    number: Mapped[str] = mapped_column(String(100), default="")
    registration_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    renewal_status: Mapped[str] = mapped_column(String(24), default="UNKNOWN")
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id"), nullable=True)
