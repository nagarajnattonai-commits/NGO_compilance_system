"""Additive metadata for the existing connection register; secrets never live here."""
from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base
from .models import uid, utcnow

class IntegrationProvider(Base):
    __tablename__ = "integration_providers"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class ConnectionSettings(Base):
    __tablename__ = "integration_connection_settings"
    connection_id: Mapped[str] = mapped_column(ForeignKey("integration_connections.id"), primary_key=True)
    scope: Mapped[str] = mapped_column(String(20))
    display_name: Mapped[str] = mapped_column(String(120))
    environment: Mapped[str] = mapped_column(String(20), default="SANDBOX")
    configuration: Mapped[str] = mapped_column(Text, default="{}")
    credential_reference: Mapped[str] = mapped_column(String(255), default="")
    credential_suffix: Mapped[str] = mapped_column(String(4), default="")
    fallback_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    blocked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str] = mapped_column(String(50), default="")
    created_by: Mapped[str] = mapped_column(String(120))
    updated_by: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class IntegrationOperation(Base):
    __tablename__ = "integration_operation_logs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    connection_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    provider_key: Mapped[str] = mapped_column(String(80))
    operation: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(30))
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str] = mapped_column(String(50), default="")
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class IntegrationHealthCheck(Base):
    __tablename__ = "integration_health_checks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    connection_id: Mapped[str] = mapped_column(ForeignKey("integration_connections.id"), index=True)
    health: Mapped[str] = mapped_column(String(20))
    error_code: Mapped[str] = mapped_column(String(50), default="")
    duration_ms: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class WebhookSubscription(Base):
    __tablename__ = "webhook_subscriptions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(120))
    direction: Mapped[str] = mapped_column(String(20))
    endpoint_url: Mapped[str] = mapped_column(String(2000), default="")
    secret_reference: Mapped[str] = mapped_column(String(255), default="")
    event_types: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    __table_args__ = (UniqueConstraint("subscription_id", "external_id", name="uq_webhook_event"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    subscription_id: Mapped[str] = mapped_column(ForeignKey("webhook_subscriptions.id"))
    external_id: Mapped[str] = mapped_column(String(120))
    event_type: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[str] = mapped_column(String(36), default="")
    status: Mapped[str] = mapped_column(String(20), default="QUEUED")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"
    __table_args__ = (UniqueConstraint("subscription_id", "event_id", name="uq_webhook_delivery"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    subscription_id: Mapped[str] = mapped_column(ForeignKey("webhook_subscriptions.id"))
    event_id: Mapped[str] = mapped_column(String(120))
    event_type: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[str] = mapped_column(String(36), default="")
    status: Mapped[str] = mapped_column(String(20), default="QUEUED", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str] = mapped_column(String(50), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class ApiApplication(Base):
    __tablename__ = "api_applications"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(500), default="")
    created_by: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class ApiKey(Base):
    __tablename__ = "api_keys"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("api_applications.id"))
    name: Mapped[str] = mapped_column(String(120))
    key_prefix: Mapped[str] = mapped_column(String(20))
    key_suffix: Mapped[str] = mapped_column(String(4))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    scopes: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rate_window: Mapped[int] = mapped_column(Integer, default=0)
    rate_count: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class ApiUsage(Base):
    __tablename__ = "api_usage_records"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    api_key_id: Mapped[str] = mapped_column(ForeignKey("api_keys.id"), index=True)
    route: Mapped[str] = mapped_column(String(100))
    status: Mapped[int] = mapped_column(Integer)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

class IntegrationQuota(Base):
    __tablename__ = "integration_rate_windows"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    window: Mapped[int] = mapped_column(Integer, index=True)
    count: Mapped[int] = mapped_column(Integer, default=1)

class IntegrationSchemaVersion(Base):
    __tablename__ = "integration_schema_versions"
    version: Mapped[str] = mapped_column(String(80), primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
