"""Durable, recipient-specific notification preferences and delivery history."""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .models import uid, utcnow


class NotificationContext(Base):
    __tablename__ = "notification_contexts"

    notification_id: Mapped[str] = mapped_column(ForeignKey("notifications.id"), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    category: Mapped[str] = mapped_column(String(40), default="COMPLIANCE", index=True)
    organization_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)
    entity_type: Mapped[str] = mapped_column(String(60), default="")
    entity_id: Mapped[str] = mapped_column(String(36), default="")
    correlation_id: Mapped[str] = mapped_column(String(36), default=uid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class NotificationRecipient(Base):
    __tablename__ = "notification_recipients"
    __table_args__ = (
        UniqueConstraint("notification_id", "user_id", name="uq_notification_recipient"),
        Index("ix_notification_recipient_inbox", "tenant_id", "user_id", "read_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    notification_id: Mapped[str] = mapped_column(ForeignKey("notifications.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("auth_users.id"), index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"
    __table_args__ = (
        UniqueConstraint("notification_id", "user_id", "channel", name="uq_notification_delivery_channel"),
        Index("ix_notification_delivery_status", "tenant_id", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    notification_id: Mapped[str] = mapped_column(ForeignKey("notifications.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("auth_users.id"), index=True)
    channel: Mapped[str] = mapped_column(String(20), index=True)
    recipient_address: Mapped[str] = mapped_column(String(254), default="")
    locale: Mapped[str] = mapped_column(String(16), default="en-IN")
    template_key: Mapped[str] = mapped_column(String(100), default="")
    provider_template: Mapped[str] = mapped_column(String(100), default="")
    frozen_subject: Mapped[str] = mapped_column(String(240))
    frozen_text: Mapped[str] = mapped_column(Text)
    frozen_html: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    attempt_count: Mapped[int] = mapped_column(default=0)
    provider_message_id: Mapped[str] = mapped_column(String(200), default="")
    last_error_code: Mapped[str] = mapped_column(String(80), default="")
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UserNotificationPreference(Base):
    __tablename__ = "user_notification_preferences"

    user_id: Mapped[str] = mapped_column(ForeignKey("auth_users.id"), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    in_app_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    email_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    whatsapp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    compliance_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    task_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    document_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    system_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WorkspaceNotificationPolicy(Base):
    __tablename__ = "workspace_notification_policies"

    tenant_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), primary_key=True)
    mandatory_channels: Mapped[str] = mapped_column(Text, default='["IN_APP"]')
    updated_by: Mapped[str] = mapped_column(String(120), default="System")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
