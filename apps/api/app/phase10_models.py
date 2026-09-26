"""Tenant calendar OAuth, policy and persistent provider-event mappings."""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .models import uid, utcnow


class CalendarOAuthState(Base):
    __tablename__ = "calendar_oauth_states"

    state_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("auth_users.id"), index=True)
    connection_id: Mapped[str] = mapped_column(ForeignKey("integration_connections.id"), index=True)
    verifier: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CalendarSyncPolicy(Base):
    __tablename__ = "calendar_sync_policies"

    connection_id: Mapped[str] = mapped_column(ForeignKey("integration_connections.id"), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    sync_statutory_deadlines: Mapped[bool] = mapped_column(Boolean, default=True)
    sync_internal_targets: Mapped[bool] = mapped_column(Boolean, default=True)
    sync_tasks: Mapped[bool] = mapped_column(Boolean, default=True)
    closed_behavior: Mapped[str] = mapped_column(String(20), default="UPDATE")
    updated_by: Mapped[str] = mapped_column(ForeignKey("auth_users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CalendarEventMapping(Base):
    __tablename__ = "calendar_event_mappings"
    __table_args__ = (
        UniqueConstraint("tenant_id", "connection_id", "entity_type", "entity_id", "event_kind",
                         name="uq_calendar_event_mapping"),
        Index("ix_calendar_mapping_entity", "tenant_id", "organization_id", "entity_type", "entity_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    connection_id: Mapped[str] = mapped_column(ForeignKey("integration_connections.id"), index=True)
    entity_type: Mapped[str] = mapped_column(String(30))
    entity_id: Mapped[str] = mapped_column(String(36))
    event_kind: Mapped[str] = mapped_column(String(30))
    calendar_id: Mapped[str] = mapped_column(String(200))
    provider_event_id: Mapped[str] = mapped_column(String(64))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sync_status: Mapped[str] = mapped_column(String(30), default="PENDING", index=True)
    sync_hash: Mapped[str] = mapped_column(String(64), default="")
    error_code: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
