from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import smtplib
import ssl
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from .database import SessionLocal
from .models import AuditEvent, AuthAttempt, AuthSession, AuthToken, Subscription, User, Workspace
from .validation import normalize_email, validate_new_password

COOKIE_NAME = "setu_session"
APP_ORIGIN = os.getenv("APP_ORIGIN", "http://localhost:3000").rstrip("/")
PRODUCTION = os.getenv("APP_ENV", "development") == "production"
SECURE_COOKIE = PRODUCTION or APP_ORIGIN.startswith("https://")
ALLOWED_ORIGINS = {APP_ORIGIN} if PRODUCTION else {APP_ORIGIN, "http://localhost:3000", "http://127.0.0.1:3000"}
if PRODUCTION and not APP_ORIGIN.startswith("https://"):
    raise RuntimeError("Production APP_ORIGIN must use HTTPS")


def now() -> datetime:
    return datetime.now(timezone.utc)


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    key = hashlib.scrypt(password.encode(), salt=salt, n=131072, r=8, p=1, maxmem=268435456)
    return f"scrypt$131072$8$1${salt.hex()}${key.hex()}"


def verify_password(password: str, encoded: str | None) -> bool:
    # Do equivalent password work for unknown accounts to limit timing disclosure.
    if not encoded:
        hash_password(password)
        return False
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$")
        if algorithm != "scrypt":
            return False
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), maxmem=268435456)
        return hmac.compare_digest(actual.hex(), expected)
    except (ValueError, TypeError):
        return False


def get_db():
    with SessionLocal() as db:
        yield db


DB = Annotated[Session, Depends(get_db)]


def check_mutation(request: Request):
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    # A custom header forces a CORS preflight; only the configured origin may send it.
    if request.headers.get("x-setu-request") != "1":
        raise HTTPException(403, "Missing request protection header")
    origin = request.headers.get("origin")
    if origin and origin not in ALLOWED_ORIGINS:
        raise HTTPException(403, "Request origin is not allowed")


def current_user(request: Request, db: DB) -> User:
    check_mutation(request)
    token = request.cookies.get(COOKIE_NAME, "")
    session = db.get(AuthSession, digest(token)) if token else None
    user = db.get(User, session.user_id) if session and aware(session.expires_at) > now() else None
    if not user or user.status != "ACTIVE":
        raise HTTPException(401, "Please sign in to continue")
    request.state.actor_name = user.name
    request.state.user_id = user.id
    db.info["actor_name"] = user.name
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def admin_user(user: CurrentUser) -> User:
    if user.role != "ADMIN":
        raise HTTPException(403, "Administrator access is required")
    return user


AdminUser = Annotated[User, Depends(admin_user)]


def tenant_context(request: Request, user: CurrentUser) -> str:
    # Caller-supplied tenant headers never select another workspace.
    requested_tenant = request.headers.get("x-tenant-id")
    if requested_tenant and requested_tenant != user.tenant_id:
        raise HTTPException(403, "Workspace access denied")
    path = request.url.path
    if path.startswith("/api/v1/memberships") and user.role != "ADMIN":
        raise HTTPException(403, "Administrator access is required")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        if user.role == "VIEWER" and not path.endswith("/read"):
            raise HTTPException(403, "This account has read-only access")
        if path.startswith("/api/v1/organizations") and user.role != "ADMIN":
            raise HTTPException(403, "Only administrators can manage organizations")
    return user.tenant_id


def record_event(db: Session, actor: User, action: str, summary: str, entity_id: str | None = None):
    db.add(AuditEvent(tenant_id=actor.tenant_id, actor_name=actor.name, action=action,
                      entity_type="User", entity_id=entity_id or actor.id, summary=summary))


def limit_attempts(db: Session, scope: str, maximum: int, seconds: int = 900):
    key = digest(scope)
    cutoff = now() - timedelta(seconds=seconds)
    count = db.scalar(select(func.count()).select_from(AuthAttempt).where(
        AuthAttempt.scope_hash == key, AuthAttempt.created_at > cutoff)) or 0
    if count >= maximum:
        raise HTTPException(429, "Too many attempts. Please try again later.", headers={"Retry-After": str(seconds)})
    db.execute(delete(AuthAttempt).where(AuthAttempt.created_at < now() - timedelta(days=1)))
    db.add(AuthAttempt(scope_hash=key))
    db.commit()


def request_ip(request: Request) -> str:
    # Do not trust client-supplied forwarding headers.
    return request.client.host if request.client else "unknown"


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EmailInput(InputModel):
    email: str = Field(min_length=3, max_length=200)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str):
        return normalize_email(value)


class PasswordInput(InputModel):
    password: str = Field(min_length=12, max_length=128)

    @field_validator("password")
    @classmethod
    def strong_password(cls, value: str):
        return validate_new_password(value)


class SignupInput(EmailInput, PasswordInput):
    name: str = Field(min_length=2, max_length=120)
    workspace_name: str = Field(min_length=2, max_length=160)
    phone: str = Field(default="", max_length=30)

    @field_validator("name", "workspace_name")
    @classmethod
    def nonblank(cls, value: str):
        if len(value.strip()) < 2:
            raise ValueError("Use at least two non-space characters")
        return value.strip()


class LoginInput(EmailInput):
    password: str = Field(min_length=1, max_length=128)
    remember: bool = False
    admin_only: bool = False


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    email: str
    phone: str
    tenant_id: str
    role: str
    status: str
    created_at: datetime
    has_password: bool


class ProfileInput(InputModel):
    name: str = Field(min_length=2, max_length=120)
    phone: str = Field(default="", max_length=30)

    @field_validator("name")
    @classmethod
    def nonblank(cls, value: str):
        if len(value.strip()) < 2:
            raise ValueError("Enter your name")
        return value.strip()


class ChangePasswordInput(PasswordInput):
    current_password: str = Field(min_length=1, max_length=128)


class TokenInput(PasswordInput):
    token: str = Field(min_length=32, max_length=128)


class InvitationInput(EmailInput):
    name: str = Field(min_length=2, max_length=120)
    role: Literal["ADMIN", "MEMBER", "VIEWER"] = "MEMBER"


class AccessInput(InputModel):
    role: Literal["ADMIN", "MEMBER", "VIEWER"]
    status: Literal["ACTIVE", "DISABLED"]


def issue_session(db: Session, user: User, response: Response, remember: bool = False):
    token = secrets.token_urlsafe(32)
    lifetime = 30 * 86400 if remember else 8 * 3600
    db.execute(delete(AuthSession).where(AuthSession.expires_at < now()))
    db.add(AuthSession(token_hash=digest(token), user_id=user.id, expires_at=now() + timedelta(seconds=lifetime)))
    response.set_cookie(COOKIE_NAME, token, max_age=lifetime if remember else None,
                        httponly=True, secure=SECURE_COOKIE, samesite="lax", path="/")
    response.headers["Cache-Control"] = "no-store"


def revoke_sessions(db: Session, user_id: str):
    db.execute(delete(AuthSession).where(AuthSession.user_id == user_id))


def issue_token(db: Session, user: User, purpose: str, hours: int) -> str:
    db.execute(update(AuthToken).where(AuthToken.user_id == user.id, AuthToken.purpose == purpose,
                                      AuthToken.used_at.is_(None)).values(used_at=now()))
    token = secrets.token_urlsafe(32)
    db.add(AuthToken(token_hash=digest(token), user_id=user.id, purpose=purpose, expires_at=now() + timedelta(hours=hours)))
    return token


router = APIRouter(prefix="/api/v1", dependencies=[Depends(check_mutation)])


@router.post("/auth/signup", response_model=UserOut, status_code=201)
def signup(payload: SignupInput, request: Request, response: Response, db: DB):
    limit_attempts(db, f"signup:{request_ip(request)}", 10, 3600)
    if db.scalar(select(User.id).where(User.email == payload.email)):
        raise HTTPException(409, "Unable to create this account. Try signing in or recovering your password.")
    workspace = Workspace(name=payload.workspace_name)
    db.add(workspace)
    db.flush()
    user = User(tenant_id=workspace.id, name=payload.name, email=payload.email, phone=payload.phone,
                password_hash=hash_password(payload.password), role="ADMIN")
    db.add(user)
    db.flush()
    db.add(Subscription(tenant_id=workspace.id, plan_name="STARTER", user_limit=5,
                        organization_limit=3, storage_limit_gb=1, period_end=date.today() + timedelta(days=30)))
    issue_session(db, user, response)
    record_event(db, user, "ACCOUNT_CREATED", "Created a new workspace administrator account")
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Unable to create this account")
    return user


@router.post("/auth/login", response_model=UserOut)
def login(payload: LoginInput, request: Request, response: Response, db: DB):
    limit_attempts(db, f"login-ip:{request_ip(request)}", 60)
    limit_attempts(db, f"login-email:{payload.email}", 10)
    user = db.scalar(select(User).where(User.email == payload.email))
    valid = verify_password(payload.password, user.password_hash if user else None)
    if not valid or not user or user.status != "ACTIVE":
        raise HTTPException(401, "Email or password is incorrect, or the account is unavailable")
    if payload.admin_only and user.role != "ADMIN":
        raise HTTPException(403, "This account is not a workspace administrator. Use team member sign in.")
    old_token = request.cookies.get(COOKIE_NAME)
    if old_token:
        db.execute(delete(AuthSession).where(AuthSession.token_hash == digest(old_token)))
    issue_session(db, user, response, payload.remember)
    db.execute(delete(AuthAttempt).where(AuthAttempt.scope_hash == digest(f"login-email:{payload.email}")))
    record_event(db, user, "SIGNED_IN", "Signed in to the workspace")
    db.commit()
    return user


@router.get("/auth/me")
def me(user: CurrentUser, db: DB, response: Response):
    workspace = db.get(Workspace, user.tenant_id)
    response.headers["Cache-Control"] = "no-store"
    return {"user": UserOut.model_validate(user), "workspace_name": workspace.name if workspace else "Existing NGO workspace"}


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response, db: DB):
    token = request.cookies.get(COOKIE_NAME)
    if token:
        db.execute(delete(AuthSession).where(AuthSession.token_hash == digest(token)))
        db.commit()
    response.delete_cookie(COOKIE_NAME, path="/", secure=SECURE_COOKIE, httponly=True, samesite="lax")


@router.patch("/auth/profile", response_model=UserOut)
def profile(payload: ProfileInput, user: CurrentUser, db: DB):
    user.name = payload.name
    user.phone = payload.phone.strip()
    record_event(db, user, "PROFILE_UPDATED", "Updated account profile")
    db.commit()
    return user


@router.post("/auth/change-password", status_code=204)
def change_password(payload: ChangePasswordInput, request: Request, response: Response, user: CurrentUser, db: DB):
    limit_attempts(db, f"password:{user.id}", 10)
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(400, "Current password is incorrect")
    if payload.current_password == payload.password:
        raise HTTPException(400, "Choose a different new password")
    user.password_hash = hash_password(payload.password)
    revoke_sessions(db, user.id)
    db.execute(update(AuthToken).where(AuthToken.user_id == user.id).values(used_at=now()))
    record_event(db, user, "PASSWORD_CHANGED", "Changed password and revoked all sign-in sessions")
    db.commit()
    response.delete_cookie(COOKIE_NAME, path="/", secure=SECURE_COOKIE, httponly=True, samesite="lax")


@router.post("/auth/forgot-password")
def forgot_password(payload: EmailInput, request: Request, db: DB):
    limit_attempts(db, f"reset-ip:{request_ip(request)}", 10, 3600)
    smtp_host, smtp_from = os.getenv("SMTP_HOST"), os.getenv("SMTP_FROM")
    if not smtp_host or not smtp_from:
        raise HTTPException(503, "Password recovery email is not configured. Contact your workspace administrator.")
    user = db.scalar(select(User).where(User.email == payload.email, User.status == "ACTIVE"))
    if user:
        token = issue_token(db, user, "RESET", 1)
        message = EmailMessage()
        message["Subject"] = "Reset your Setu password"
        message["From"] = smtp_from
        message["To"] = user.email
        message.set_content(f"Use this single-use link within one hour:\n{APP_ORIGIN}/reset-password#token={token}\n\nIf you did not request this, ignore this email.")
        try:
            with smtplib.SMTP_SSL(smtp_host, int(os.getenv("SMTP_PORT", "465")), timeout=10, context=ssl.create_default_context()) as smtp:
                if os.getenv("SMTP_USER"):
                    smtp.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
                smtp.send_message(message)
            db.commit()
        except (OSError, smtplib.SMTPException, KeyError):
            db.rollback()
            logging.getLogger(__name__).error("Password recovery delivery failed; check SMTP configuration")
            # Same public response for unknown accounts and provider failures.
    return {"message": "If an active account matches, a password-reset link will be sent. Check your inbox and spam folder."}


def redeem_token(db: Session, payload: TokenInput, purpose: str) -> User:
    token = db.get(AuthToken, digest(payload.token))
    if not token or token.purpose != purpose or token.used_at or aware(token.expires_at) <= now():
        raise HTTPException(400, "This link is invalid, expired, or already used")
    user = db.get(User, token.user_id)
    allowed_status = "INVITED" if purpose == "INVITE" else "ACTIVE"
    if not user or user.status != allowed_status:
        raise HTTPException(400, "This link is no longer available")
    # Atomic claim prevents concurrent requests from reusing the same token.
    claimed = db.execute(update(AuthToken).where(AuthToken.token_hash == token.token_hash, AuthToken.used_at.is_(None)).values(used_at=now()))
    if claimed.rowcount != 1:
        raise HTTPException(400, "This link has already been used")
    user.password_hash = hash_password(payload.password)
    user.status = "ACTIVE"
    revoke_sessions(db, user.id)
    record_event(db, user, "INVITATION_ACCEPTED" if purpose == "INVITE" else "PASSWORD_RESET", "Set account password using a single-use link")
    db.commit()
    return user


@router.post("/auth/reset-password", status_code=204)
def reset_password(payload: TokenInput, request: Request, db: DB):
    limit_attempts(db, f"redeem:{request_ip(request)}", 20)
    redeem_token(db, payload, "RESET")


@router.post("/auth/accept-invitation", status_code=204)
def accept_invitation(payload: TokenInput, request: Request, db: DB):
    limit_attempts(db, f"redeem:{request_ip(request)}", 20)
    redeem_token(db, payload, "INVITE")


@router.get("/admin/users", response_model=list[UserOut])
def list_users(admin: AdminUser, db: DB):
    return db.scalars(select(User).where(User.tenant_id == admin.tenant_id).order_by(User.created_at)).all()


@router.post("/admin/users/invite", status_code=201)
def invite_user(payload: InvitationInput, admin: AdminUser, db: DB):
    if db.scalar(select(User.id).where(User.email == payload.email)):
        raise HTTPException(409, "This email already has an account or invitation")
    plan = db.scalar(select(Subscription).where(Subscription.tenant_id == admin.tenant_id))
    count = db.scalar(select(func.count()).select_from(User).where(User.tenant_id == admin.tenant_id, User.status != "DISABLED")) or 0
    if plan and count >= plan.user_limit:
        raise HTTPException(403, "The workspace user limit has been reached")
    user = User(tenant_id=admin.tenant_id, email=payload.email, name=payload.name.strip(), role=payload.role, status="INVITED")
    db.add(user)
    try:
        db.flush()
        token = issue_token(db, user, "INVITE", 48)
        record_event(db, admin, "USER_INVITED", f"Invited {user.email} as {user.role}", user.id)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "This email already has an account or invitation")
    return {"user": UserOut.model_validate(user), "token": token, "expires_in_hours": 48}


@router.post("/admin/users/{user_id}/invitation")
def renew_invitation(user_id: str, admin: AdminUser, db: DB):
    user = db.scalar(select(User).where(User.id == user_id, User.tenant_id == admin.tenant_id))
    if not user or user.password_hash or user.status not in {"INVITED", "DISABLED"}:
        raise HTTPException(404, "Pending invitation not found")
    if user.status == "DISABLED":
        plan = db.scalar(select(Subscription).where(Subscription.tenant_id == admin.tenant_id))
        count = db.scalar(select(func.count()).select_from(User).where(User.tenant_id == admin.tenant_id, User.status != "DISABLED")) or 0
        if plan and count >= plan.user_limit:
            raise HTTPException(403, "The workspace user limit has been reached")
        user.status = "INVITED"
    token = issue_token(db, user, "INVITE", 48)
    record_event(db, admin, "INVITATION_RENEWED", f"Renewed invitation for {user.email}", user.id)
    db.commit()
    return {"user": UserOut.model_validate(user), "token": token, "expires_in_hours": 48}


@router.patch("/admin/users/{user_id}", response_model=UserOut)
def update_access(user_id: str, payload: AccessInput, admin: AdminUser, db: DB):
    user = db.scalar(select(User).where(User.id == user_id, User.tenant_id == admin.tenant_id))
    if not user:
        raise HTTPException(404, "User not found")
    if user.id == admin.id:
        raise HTTPException(409, "You cannot change your own role or account status")
    if payload.status == "ACTIVE" and not user.password_hash:
        raise HTTPException(409, "The user must first accept their invitation")
    if user.status == "DISABLED" and payload.status == "ACTIVE":
        plan = db.scalar(select(Subscription).where(Subscription.tenant_id == admin.tenant_id))
        count = db.scalar(select(func.count()).select_from(User).where(User.tenant_id == admin.tenant_id, User.status != "DISABLED")) or 0
        if plan and count >= plan.user_limit:
            raise HTTPException(403, "The workspace user limit has been reached")
    other_admin = aliased(User)
    remaining_admin = select(other_admin.id).where(
        other_admin.tenant_id == admin.tenant_id, other_admin.id != user.id,
        other_admin.role == "ADMIN", other_admin.status == "ACTIVE",
    ).exists()
    guard = True if payload.role == "ADMIN" and payload.status == "ACTIVE" else or_(
        User.role != "ADMIN", User.status != "ACTIVE", remaining_admin,
    )
    changed = db.execute(update(User).where(User.id == user.id, guard).values(
        role=payload.role, status=payload.status,
    ).execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        raise HTTPException(409, "The workspace must retain an active administrator")
    db.refresh(user)
    revoke_sessions(db, user.id)
    if payload.status == "DISABLED":
        db.execute(update(AuthToken).where(AuthToken.user_id == user.id).values(used_at=now()))
    record_event(db, admin, "ACCESS_UPDATED", f"Changed {user.email} to {user.role}, {user.status}", user.id)
    db.commit()
    return user
