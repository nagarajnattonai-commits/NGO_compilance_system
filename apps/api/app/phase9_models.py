"""Durable Phase 9 workflow decisions; frozen template rules remain authoritative."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .models import uid, utcnow


class ComplianceReview(Base):
    __tablename__ = "compliance_reviews"
    __table_args__ = (
        UniqueConstraint("compliance_id", "revision", name="uq_compliance_review_revision"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    compliance_id: Mapped[str] = mapped_column(ForeignKey("compliance_instances.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    submitted_by: Mapped[str] = mapped_column(ForeignKey("auth_users.id"))
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reviewer_id: Mapped[str | None] = mapped_column(ForeignKey("auth_users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision: Mapped[str] = mapped_column(String(30), default="PENDING")
    comments: Mapped[str] = mapped_column(Text, default="")


class ComplianceApproval(Base):
    __tablename__ = "compliance_approvals"
    __table_args__ = (
        UniqueConstraint("compliance_id", "revision", name="uq_compliance_approval_revision"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    compliance_id: Mapped[str] = mapped_column(ForeignKey("compliance_instances.id"), index=True)
    review_id: Mapped[str | None] = mapped_column(ForeignKey("compliance_reviews.id"), nullable=True, index=True)
    revision: Mapped[int] = mapped_column(Integer)
    target_status: Mapped[str] = mapped_column(String(30), default="READY_TO_FILE")
    requested_by: Mapped[str] = mapped_column(ForeignKey("auth_users.id"))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    approver_id: Mapped[str | None] = mapped_column(ForeignKey("auth_users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision: Mapped[str] = mapped_column(String(30), default="PENDING")
    comments: Mapped[str] = mapped_column(Text, default="")
