from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import smtplib
from datetime import date, datetime, timedelta, timezone
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
        from .brand_domains import custom_origin_allowed
        if not custom_origin_allowed(request, origin):
            raise HTTPException(403, "Request origin is not allowed")


def current_user(request: Request, db: DB) -> User:
    check_mutation(request)
    token = request.cookies.get(COOKIE_NAME, "")
    session = db.get(AuthSession, digest(token)) if token else None
    user = db.get(User, session.user_id) if session and aware(session.expires_at) > now() else None
    if not user or user.status != "ACTIVE":
        raise HTTPException(401, "Please sign in to continue")
    from .brand_domains import request_hostname,platform_hosts
    user._platform_host=request_hostname(request) in platform_hosts()
    from .auth_experience import apply_context
    auth_context=apply_context(db, user, session)
    user._admin_audience=auth_context is None or auth_context.audience=="admin"
    from .brand_domains import enforce_request_tenant
    enforce_request_tenant(request, db, user.tenant_id)
    request.state.actor_name = user.name
    request.state.user_id = user.id
    db.info["actor_name"] = user.name
    db.info["actor_id"] = user.id
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
    from .integration_service import quota
    quota(db,"auth:"+scope,maximum,seconds)


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
    organization_type: Literal["TRUST", "SOCIETY", "SECTION 8"] | None = None
    terms_accepted: bool | None = None
    verify_email: bool = False

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


def issue_session(db: Session, user: User, response: Response, remember: bool = False, *, tenant_id=None, audience="user", method="password"):
    token = secrets.token_urlsafe(32)
    lifetime = 30 * 86400 if remember else 8 * 3600
    from .auth_models import SessionContext
    expired=select(AuthSession.token_hash).where(AuthSession.expires_at<now())
    db.execute(delete(SessionContext).where(SessionContext.token_hash.in_(expired)))
    db.execute(delete(AuthSession).where(AuthSession.expires_at < now()).execution_options(synchronize_session=False))
    db.add(AuthSession(token_hash=digest(token), user_id=user.id, expires_at=now() + timedelta(seconds=lifetime)))
    from .auth_models import SessionContext
    db.flush()
    db.add(SessionContext(token_hash=digest(token),tenant_id=tenant_id or user.tenant_id,audience=audience,method=method))
    response.set_cookie(COOKIE_NAME, token, max_age=lifetime if remember else None,
                        httponly=True, secure=SECURE_COOKIE, samesite="lax", path="/")
    response.headers["Cache-Control"] = "no-store"
    return token


def revoke_sessions(db: Session, user_id: str):
    from .auth_models import SessionContext
    hashes=select(AuthSession.token_hash).where(AuthSession.user_id==user_id)
    db.execute(delete(SessionContext).where(SessionContext.token_hash.in_(hashes)))
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
    from .brand_domains import platform_hosts, request_hostname
    if request_hostname(request) not in platform_hosts():
        raise HTTPException(403, "New workspaces must be created on the platform domain")
    verification = payload.verify_email or PRODUCTION or os.getenv("AUTH_REQUIRE_EMAIL_VERIFICATION") == "1"
    if verification and (payload.terms_accepted is not True or not payload.organization_type):
        raise HTTPException(422, "Terms acceptance and organization type are required")
    if verification:
        from .integration_notifications import email_available
        if not email_available(db): raise HTTPException(503, "Authentication email is not configured")
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
    from .auth_models import AuthAccount
    db.add(AuthAccount(user_id=user.id,verified=not verification,verification_required=verification,
           organization_type=payload.organization_type or "",terms_at=now() if payload.terms_accepted else None))
    if verification:
        from .auth_experience import send_identity_email
        from .integration_security import IntegrationError
        try: send_identity_email(db,user)
        except IntegrationError:
            db.rollback()
            raise HTTPException(503,"Authentication email is unavailable") from None
    else: issue_session(db, user, response)
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
        from .auth_experience import security_event
        security_event(db,request,"ADMIN_LOGIN_FAILED" if payload.admin_only else "LOGIN_FAILED",user,"admin" if payload.admin_only else "user")
        db.commit()
        raise HTTPException(401, "Email or password is incorrect, or the account is unavailable")
    from .auth_experience import verified_login, select_host_workspace, security_event
    verified_login(db,user)
    from .auth_policy import is_platform_admin
    from .brand_domains import request_hostname, platform_hosts
    if payload.admin_only and os.getenv("AUTH_ADMIN_MFA_REQUIRED")=="1":
        raise HTTPException(503,"Administrator MFA provider is not configured")
    if payload.admin_only and (not is_platform_admin(user) or request_hostname(request) not in platform_hosts()):
        security_event(db,request,"ADMIN_LOGIN_FAILED",user,"admin");db.commit()
        raise HTTPException(403, "Platform administrator access is required")
    tenant_id = select_host_workspace(db,user,request)
    old_token = request.cookies.get(COOKIE_NAME)
    if old_token:
        from .auth_models import SessionContext
        db.execute(delete(SessionContext).where(SessionContext.token_hash == digest(old_token)))
        db.execute(delete(AuthSession).where(AuthSession.token_hash == digest(old_token)))
    issue_session(db, user, response, payload.remember, tenant_id=tenant_id,audience="admin" if payload.admin_only else "user")
    security_event(db,request,"ADMIN_LOGIN_SUCCESS" if payload.admin_only else "LOGIN_SUCCESS",user,"admin" if payload.admin_only else "user")
    from .integration_models import IntegrationQuota
    db.execute(delete(IntegrationQuota).where(IntegrationQuota.id.like(digest("auth:login-email:"+payload.email)+":%")))
    record_event(db, user, "SIGNED_IN", "Signed in to the workspace")
    db.commit()
    return user


@router.post("/admin/auth/login", response_model=UserOut)
def platform_login(payload:LoginInput,request:Request,response:Response,db:DB):
    payload.admin_only=True
    return login(payload,request,response,db)


@router.get("/auth/me")
def me(user: CurrentUser, db: DB, response: Response):
    workspace = db.get(Workspace, user.tenant_id)
    response.headers["Cache-Control"] = "no-store"
    return {"user": UserOut.model_validate(user), "workspace_name": workspace.name if workspace else "Existing NGO workspace"}


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response, db: DB):
    token = request.cookies.get(COOKIE_NAME)
    if token:
        from .auth_models import SessionContext
        session=db.get(AuthSession,digest(token))
        user=db.get(User,session.user_id) if session else None
        if user:
            from .auth_experience import security_event
            security_event(db,request,"LOGOUT",user)
        db.execute(delete(SessionContext).where(SessionContext.token_hash==digest(token)))
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
    from .integration_notifications import email_available, deliver_email
    from .integration_security import IntegrationError
    if not email_available(db):
        raise HTTPException(503, "Password recovery email is not configured. Contact your workspace administrator.")
    user = db.scalar(select(User).where(User.email == payload.email, User.status == "ACTIVE"))
    if user:
        token = issue_token(db, user, "RESET", 1)
        from .brand_outputs import render_email, site_origin
        from .auth_experience import security_event
        security_event(db,request,"PASSWORD_RESET_REQUESTED",user)
        from .models import UserPreference
        preference = db.get(UserPreference, user.id)
        email = render_email(db, user.tenant_id, "auth.passwordReset", {
            "userName": user.name, "link": f"{site_origin(db, user.tenant_id)}/reset-password#token={token}"
        }, preference.locale if preference else None)
        try:
            deliver_email(db,user.tenant_id,user.email,email["subject"],email["text"],email["html"],email["sender_name"],email["reply_to"])
            db.commit()
        except IntegrationError:
            db.rollback()
            logging.getLogger(__name__).error("Password recovery delivery failed; check email integration configuration")
            # Same public response for unknown accounts and provider failures.
    return {"message": "If an active account matches, a password-reset link will be sent. Check your inbox and spam folder."}


def redeem_token(db: Session, payload: TokenInput, purpose: str, request: Request) -> User:
    token = db.get(AuthToken, digest(payload.token))
    if not token or token.purpose != purpose or token.used_at or aware(token.expires_at) <= now():
        raise HTTPException(400, "This link is invalid, expired, or already used")
    user = db.get(User, token.user_id)
    allowed_status = "INVITED" if purpose == "INVITE" else "ACTIVE"
    if not user or user.status != allowed_status:
        raise HTTPException(400, "This link is no longer available")
    from .brand_domains import enforce_request_tenant
    enforce_request_tenant(request, db, user.tenant_id)
    # Atomic claim prevents concurrent requests from reusing the same token.
    claimed = db.execute(update(AuthToken).where(AuthToken.token_hash == token.token_hash, AuthToken.used_at.is_(None)).values(used_at=now()))
    if claimed.rowcount != 1:
        raise HTTPException(400, "This link has already been used")
    user.password_hash = hash_password(payload.password)
    user.status = "ACTIVE"
    revoke_sessions(db, user.id)
    from .auth_models import AuthAccount
    account=db.get(AuthAccount,user.id)
    if account and purpose=="INVITE":account.verified=True
    from .auth_experience import security_event
    security_event(db,request,"INVITATION_ACCEPTED" if purpose=="INVITE" else "PASSWORD_RESET_COMPLETED",user)
    record_event(db, user, "INVITATION_ACCEPTED" if purpose == "INVITE" else "PASSWORD_RESET", "Set account password using a single-use link")
    db.commit()
    return user


@router.post("/auth/reset-password", status_code=204)
def reset_password(payload: TokenInput, request: Request, db: DB):
    limit_attempts(db, f"redeem:{request_ip(request)}", 20)
    redeem_token(db, payload, "RESET", request)


@router.post("/auth/accept-invitation", status_code=204)
def accept_invitation(payload: TokenInput, request: Request, db: DB):
    limit_attempts(db, f"redeem:{request_ip(request)}", 20)
    redeem_token(db, payload, "INVITE", request)


@router.get("/admin/users", response_model=list[UserOut])
def list_users(admin: AdminUser, db: DB):
    from .auth_models import WorkspaceAccess
    result=[UserOut.model_validate(user) for user in db.scalars(select(User).where(User.tenant_id==admin.tenant_id).order_by(User.created_at)).all()]
    for access,user in db.execute(select(WorkspaceAccess,User).join(User,User.id==WorkspaceAccess.user_id).where(WorkspaceAccess.tenant_id==admin.tenant_id,User.tenant_id!=admin.tenant_id)):
        result.append(UserOut.model_validate(user).model_copy(update={"tenant_id":admin.tenant_id,"role":access.role,"status":"ACTIVE" if access.active else "DISABLED"}))
    return result


@router.post("/admin/users/invite", status_code=201)
def invite_user(payload: InvitationInput, admin: AdminUser, db: DB):
    from .auth_experience import seat_available,invitation_email
    seat_available(db,admin.tenant_id)
    existing=db.scalar(select(User).where(User.email==payload.email))
    if existing:
        from .auth_models import WorkspaceAccess,WorkspaceInvitation
        if existing.status!="ACTIVE" or existing.tenant_id==admin.tenant_id or db.scalar(select(WorkspaceAccess.id).where(WorkspaceAccess.user_id==existing.id,WorkspaceAccess.tenant_id==admin.tenant_id)):
            raise HTTPException(409,"This email already has an account or invitation")
        token=issue_token(db,existing,"JOIN",48);db.flush()
        db.add(WorkspaceInvitation(token_hash=digest(token),tenant_id=admin.tenant_id,role=payload.role))
        invitation_email(db,existing,token,admin.tenant_id)
        record_event(db,admin,"USER_INVITED","Invited an existing identity to the workspace",existing.id);db.commit()
        return {"user":UserOut.model_validate(existing),"token":token,"expires_in_hours":48}
    plan = db.scalar(select(Subscription).where(Subscription.tenant_id == admin.tenant_id))
    count = db.scalar(select(func.count()).select_from(User).where(User.tenant_id == admin.tenant_id, User.status != "DISABLED")) or 0
    if plan and count >= plan.user_limit:
        raise HTTPException(403, "The workspace user limit has been reached")
    user = User(tenant_id=admin.tenant_id, email=payload.email, name=payload.name.strip(), role=payload.role, status="INVITED")
    db.add(user)
    try:
        db.flush()
        token = issue_token(db, user, "INVITE", 48)
        invitation_email(db,user,token,admin.tenant_id)
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
    from .auth_experience import invitation_email
    invitation_email(db,user,token,admin.tenant_id)
    record_event(db, admin, "INVITATION_RENEWED", f"Renewed invitation for {user.email}", user.id)
    db.commit()
    return {"user": UserOut.model_validate(user), "token": token, "expires_in_hours": 48}


@router.patch("/admin/users/{user_id}", response_model=UserOut)
def update_access(user_id: str, payload: AccessInput, admin: AdminUser, db: DB):
    user = db.scalar(select(User).where(User.id == user_id, User.tenant_id == admin.tenant_id))
    if not user:
        from .auth_models import WorkspaceAccess
        access=db.scalar(select(WorkspaceAccess).where(WorkspaceAccess.user_id==user_id,WorkspaceAccess.tenant_id==admin.tenant_id))
        if not access:raise HTTPException(404,"User not found")
        identity=db.get(User,user_id)
        if not access.active and payload.status=="ACTIVE":
            from .auth_experience import seat_available
            seat_available(db,admin.tenant_id)
        access.role=payload.role;access.active=payload.status=="ACTIVE"
        revoke_sessions(db,user_id)
        record_event(db,admin,"ACCESS_UPDATED","Updated workspace membership",user_id);db.commit()
        return UserOut.model_validate(identity).model_copy(update={"tenant_id":admin.tenant_id,"role":access.role,"status":payload.status})
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


@router.post("/admin/auth/forgot-password")
def admin_forgot(payload:EmailInput,request:Request,db:DB):
    from .auth_policy import is_platform_admin
    from .brand_domains import request_hostname, platform_hosts
    from .auth_experience import send_identity_email,security_event
    from .integration_notifications import email_available
    from .integration_security import IntegrationError
    if request_hostname(request) not in platform_hosts():raise HTTPException(403,"Platform domain required")
    limit_attempts(db,"admin-reset:"+request_ip(request),5,3600)
    if not email_available(db):raise HTTPException(503,"Authentication email is not configured")
    user=db.scalar(select(User).where(User.email==payload.email,User.status=="ACTIVE"))
    if user and is_platform_admin(user):
        try:
            send_identity_email(db,user,"ADMIN_RESET",True)
            security_event(db,request,"PASSWORD_RESET_REQUESTED",user,"admin")
            db.commit()
        except IntegrationError:db.rollback()
    return {"message":"If an account exists for this email, password reset instructions have been sent."}

@router.post("/admin/auth/reset-password",status_code=204)
def admin_reset(payload:TokenInput,request:Request,db:DB):
    from .auth_policy import is_platform_admin
    from .brand_domains import request_hostname,platform_hosts
    token=db.get(AuthToken,digest(payload.token))
    user=db.get(User,token.user_id) if token else None
    if request_hostname(request) not in platform_hosts() or not user or not is_platform_admin(user):
        raise HTTPException(400,"This link is invalid, expired, or already used")
    limit_attempts(db,"admin-redeem:"+request_ip(request),10)
    redeem_token(db,payload,"ADMIN_RESET",request)
