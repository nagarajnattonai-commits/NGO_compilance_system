"""Additive identity, membership and OAuth state; existing auth tables stay intact."""
from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base
from .models import uid, utcnow

class AuthAccount(Base):
    __tablename__ = "auth_account_details"
    user_id: Mapped[str] = mapped_column(ForeignKey("auth_users.id"), primary_key=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verification_required: Mapped[bool] = mapped_column(Boolean, default=True)
    platform_access: Mapped[bool] = mapped_column(Boolean, default=False)
    organization_type: Mapped[str] = mapped_column(String(40), default="")
    terms_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class WorkspaceAccess(Base):
    __tablename__ = "auth_workspace_access"
    __table_args__ = (UniqueConstraint("user_id","tenant_id",name="uq_auth_workspace_user"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("auth_users.id"), index=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    role: Mapped[str] = mapped_column(String(20), default="MEMBER")
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class SessionContext(Base):
    __tablename__ = "auth_session_context"
    token_hash: Mapped[str] = mapped_column(ForeignKey("auth_sessions.token_hash",ondelete="CASCADE"), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36))
    audience: Mapped[str] = mapped_column(String(20), default="user")
    method: Mapped[str] = mapped_column(String(20), default="password")

class ProviderIdentity(Base):
    __tablename__ = "auth_provider_identities"
    __table_args__ = (UniqueConstraint("provider","subject",name="uq_auth_provider_subject"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("auth_users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(30))
    subject: Mapped[str] = mapped_column(String(255))

class OAuthFlow(Base):
    __tablename__ = "auth_oauth_flows"
    state_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    browser_hash: Mapped[str] = mapped_column(String(64))
    verifier: Mapped[str] = mapped_column(String(128))
    nonce: Mapped[str] = mapped_column(String(128))
    audience: Mapped[str] = mapped_column(String(20))
    intent: Mapped[str] = mapped_column(String(20))
    tenant_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    return_origin: Mapped[str] = mapped_column(String(255))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used: Mapped[bool] = mapped_column(Boolean, default=False)

class OAuthPolicy(Base):
    __tablename__ = "auth_oauth_policy"
    provider: Mapped[str] = mapped_column(String(30), primary_key=True)
    client_id: Mapped[str] = mapped_column(String(255), default="")
    secret_ref: Mapped[str] = mapped_column(Text, default="")
    user_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    signup_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    admin_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

class AuthSecurityEvent(Base):
    __tablename__ = "auth_security_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    event: Mapped[str] = mapped_column(String(40))
    method: Mapped[str] = mapped_column(String(20), default="password")
    audience: Mapped[str] = mapped_column(String(20), default="user")
    ip_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class WorkspaceInvitation(Base):
    __tablename__ = "auth_workspace_invitations"
    token_hash: Mapped[str] = mapped_column(ForeignKey("auth_tokens.token_hash"), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36))
    role: Mapped[str] = mapped_column(String(20), default="MEMBER")

class PendingGoogleIdentity(Base):
    __tablename__ = "auth_pending_google_identities"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(200))
    subject: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(120))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used: Mapped[bool] = mapped_column(Boolean, default=False)
