"""Additive runtime records; frozen templates and instance history are retained."""
from datetime import date, datetime
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base
from .models import uid, utcnow

class ComplianceOwnership(Base):
    __tablename__ = "compliance_ownership"
    compliance_id: Mapped[str] = mapped_column(ForeignKey("compliance_instances.id"), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("auth_users.id"))
    assigned_by: Mapped[str | None] = mapped_column(ForeignKey("auth_users.id"), nullable=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    manual: Mapped[bool] = mapped_column(Boolean, default=False)

class OrganizationEventFact(Base):
    __tablename__ = "organization_event_facts"
    __table_args__ = (UniqueConstraint("tenant_id", "organization_id", "template_id", "event_key", "event_date", name="uq_organization_event"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    template_id: Mapped[str] = mapped_column(ForeignKey("compliance_master.id"))
    event_key: Mapped[str] = mapped_column(String(80))
    event_date: Mapped[date] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(500))
    created_by: Mapped[str] = mapped_column(ForeignKey("auth_users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class ApplicabilityOverride(Base):
    __tablename__ = "compliance_applicability_overrides"
    __table_args__ = (Index("ix_applicability_override_scope", "tenant_id", "organization_id", "template_id", "created_at"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    template_id: Mapped[str] = mapped_column(ForeignKey("compliance_master.id"))
    version_id: Mapped[str] = mapped_column(ForeignKey("compliance_definition_versions.id"))
    decision: Mapped[str] = mapped_column(String(30))
    reason: Mapped[str] = mapped_column(String(1000))
    actor_id: Mapped[str] = mapped_column(ForeignKey("auth_users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class ApplicabilityDecision(Base):
    __tablename__ = "compliance_applicability_decisions"
    __table_args__ = (Index("ix_applicability_decision_scope", "tenant_id", "organization_id", "template_id", "evaluated_at"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    template_id: Mapped[str] = mapped_column(ForeignKey("compliance_master.id"))
    version_id: Mapped[str] = mapped_column(ForeignKey("compliance_definition_versions.id"))
    evaluated_by: Mapped[str | None] = mapped_column(ForeignKey("auth_users.id"), nullable=True)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    rule_result: Mapped[str] = mapped_column(String(30))
    effective_result: Mapped[str] = mapped_column(String(30))
    override_key: Mapped[str] = mapped_column(String(36), default="")
    facts_hash: Mapped[str] = mapped_column(String(64))
    facts_snapshot: Mapped[str] = mapped_column(Text)
    explanations: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(String(1000))
    comparison: Mapped[str] = mapped_column(String(30))

class NextCycleGeneration(Base):
    __tablename__ = "compliance_next_cycle_receipts"
    source_id: Mapped[str] = mapped_column(ForeignKey("compliance_instances.id"), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    target_id: Mapped[str | None] = mapped_column(ForeignKey("compliance_instances.id"), nullable=True)
    requested_by: Mapped[str | None] = mapped_column(ForeignKey("auth_users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
