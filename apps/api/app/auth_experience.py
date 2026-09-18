"""Shared identity policy, verified email and per-session workspace context."""
import os
from datetime import timedelta
from typing import Literal, get_args
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import Field,field_validator
from sqlalchemy import select, update
from sqlalchemy.orm.attributes import set_committed_value
from .auth import (DB, CurrentUser, AdminUser, EmailInput, InputModel, COOKIE_NAME, aware,
                   digest, now, issue_token, issue_session, limit_attempts, request_ip, record_event)
from .auth_models import AuthAccount, WorkspaceAccess, SessionContext, AuthSecurityEvent
from .models import User, Workspace, AuthSession, AuthToken
from .brand_domains import enforce_request_tenant, request_hostname, platform_hosts
from .integration_notifications import email_available, deliver_email
from .integration_security import IntegrationError
from .auth_policy import is_platform_admin

router=APIRouter(prefix="/api/v1")

def security_event(db, request, event, user=None, audience="user", method="password"):
    db.add(AuthSecurityEvent(user_id=user.id if user else None,event=event,audience=audience,
          method=method,ip_hash=digest(request_ip(request))))

def memberships(db,user):
    home=db.get(Workspace,user.tenant_id)
    result=[{"id":user.tenant_id,"role":user.role,"name":home.name if home else "Workspace"}]
    for access,workspace in db.execute(select(WorkspaceAccess,Workspace).join(Workspace,Workspace.id==WorkspaceAccess.tenant_id).where(WorkspaceAccess.user_id==user.id,WorkspaceAccess.active.is_(True))):
        if access.tenant_id!=user.tenant_id:
            result.append({"id":access.tenant_id,"role":access.role,"name":workspace.name})
    return result

def workspace_active(db,tenant):
    from .models import Subscription
    row=db.scalar(select(Subscription).where(Subscription.tenant_id==tenant))
    if row and row.status in {"SUSPENDED","DISABLED"}:raise HTTPException(403,"Workspace is unavailable")

def seat_available(db,tenant):
    from .models import Subscription
    from sqlalchemy import func
    plan=db.scalar(select(Subscription).where(Subscription.tenant_id==tenant))
    count=db.scalar(select(func.count()).select_from(User).where(User.tenant_id==tenant,User.status!="DISABLED")) or 0
    count+=db.scalar(select(func.count()).select_from(WorkspaceAccess).where(WorkspaceAccess.tenant_id==tenant,WorkspaceAccess.active.is_(True))) or 0
    if plan and count>=plan.user_limit:raise HTTPException(403,"The workspace user limit has been reached")

def apply_context(db,user,session):
    account=db.get(AuthAccount,user.id)
    if account and account.verification_required and not account.verified:
        raise HTTPException(403,"EMAIL_NOT_VERIFIED")
    context=db.get(SessionContext,session.token_hash)
    if context and context.tenant_id!=user.tenant_id:
        access=db.scalar(select(WorkspaceAccess).where(WorkspaceAccess.user_id==user.id,WorkspaceAccess.tenant_id==context.tenant_id,WorkspaceAccess.active.is_(True)))
        if not access:raise HTTPException(403,"Workspace access denied")
        # Request-local committed attributes preserve identity columns when profile changes flush.
        user._identity_tenant_id=user.tenant_id
        user._identity_role=user.role
        set_committed_value(user,"tenant_id",access.tenant_id)
        set_committed_value(user,"role",access.role)
    if context and context.audience=="admin" and not is_platform_admin(user):
        raise HTTPException(403,"Platform administrator access is required")
    if not context or context.audience!="admin":workspace_active(db,user.tenant_id)
    return context

def select_host_workspace(db,user,request):
    for workspace in memberships(db,user):
        try:
            workspace_active(db,workspace["id"])
            enforce_request_tenant(request,db,workspace["id"])
        except HTTPException:continue
        return workspace["id"]
    raise HTTPException(403,"This domain is not authorized for this workspace")

def send_identity_email(db,user,purpose="VERIFY",admin=False):
    from .brand_outputs import render_email,site_origin
    from .models import UserPreference
    if not email_available(db):
        raise HTTPException(503,"Authentication email is not configured")
    token=issue_token(db,user,purpose,24 if purpose=="VERIFY" else 1)
    path="/verify-email" if purpose=="VERIFY" else "/admin/reset-password" if admin else "/reset-password"
    from .auth import APP_ORIGIN
    origin=APP_ORIGIN if admin else site_origin(db,user.tenant_id)
    pref=db.get(UserPreference,user.id)
    email=render_email(db,user.tenant_id,"auth.emailVerification" if purpose=="VERIFY" else "auth.passwordReset",
                       {"userName":user.name,"link":origin+path+"#token="+token},pref.locale if pref else None,platform=admin)
    deliver_email(db,user.tenant_id,user.email,email["subject"],email["text"],email["html"],email["sender_name"],email["reply_to"])

def verified_login(db,user):
    account=db.get(AuthAccount,user.id)
    if account and account.verification_required and not account.verified:
        raise HTTPException(403,"EMAIL_NOT_VERIFIED")

class LinkInput(InputModel):
    token:str=Field(min_length=32,max_length=128)
class WorkspaceInput(InputModel):
    tenant_id:str=Field(min_length=1,max_length=36)

@router.post("/auth/resend-verification")
def resend(payload:EmailInput,request:Request,db:DB):
    from .auth import check_mutation
    check_mutation(request)
    limit_attempts(db,"verify-ip:"+request_ip(request),10,3600)
    limit_attempts(db,"verify-email:"+payload.email,3,3600)
    if not email_available(db):raise HTTPException(503,"Authentication email is not configured")
    user=db.scalar(select(User).where(User.email==payload.email,User.status=="ACTIVE"))
    account=db.get(AuthAccount,user.id) if user else None
    if account and not account.verified:
        try:send_identity_email(db,user);db.commit()
        except IntegrationError:db.rollback()
    return {"message":"VERIFICATION_SENT"}

@router.post("/auth/verify-email")
def verify(payload:LinkInput,request:Request,db:DB):
    from .auth import check_mutation
    check_mutation(request)
    limit_attempts(db,"verify-redeem:"+request_ip(request),20)
    token=db.get(AuthToken,digest(payload.token))
    if not token or token.purpose!="VERIFY" or token.used_at or aware(token.expires_at)<=now():
        raise HTTPException(400,"This link is invalid, expired, or already used")
    user=db.get(User,token.user_id)
    if not user or user.status!="ACTIVE":raise HTTPException(400,"This link is no longer available")
    enforce_request_tenant(request,db,user.tenant_id)
    claimed=db.execute(update(AuthToken).where(AuthToken.token_hash==token.token_hash,AuthToken.used_at.is_(None)).values(used_at=now()))
    if claimed.rowcount!=1:raise HTTPException(400,"This link has already been used")
    account=db.get(AuthAccount,user.id)
    if not account:raise HTTPException(400,"This link is no longer available")
    account.verified=True
    security_event(db,request,"EMAIL_VERIFIED",user)
    record_event(db,user,"EMAIL_VERIFIED","Verified account email")
    db.commit()
    return {"message":"EMAIL_VERIFIED"}

@router.get("/auth/workspaces")
def workspaces(user:CurrentUser,db:DB):
    # Context-mutated users still resolve the original identity's home membership.
    tenant=getattr(user,"_identity_tenant_id",user.tenant_id)
    role=getattr(user,"_identity_role",user.role)
    set_committed_value(user,"tenant_id",tenant);set_committed_value(user,"role",role)
    return memberships(db,user)

@router.post("/auth/workspace")
def switch_workspace(payload:WorkspaceInput,request:Request,response:Response,user:CurrentUser,db:DB):
    old=request.cookies.get(COOKIE_NAME,"")
    identity=db.get(User,user.id)
    tenant=getattr(user,"_identity_tenant_id",user.tenant_id);role=getattr(user,"_identity_role",user.role)
    set_committed_value(identity,"tenant_id",tenant);set_committed_value(identity,"role",role)
    if payload.tenant_id not in {row["id"] for row in memberships(db,identity)}:raise HTTPException(403,"Workspace access denied")
    workspace_active(db,payload.tenant_id)
    enforce_request_tenant(request,db,payload.tenant_id)
    session=db.get(AuthSession,digest(old))
    remaining=aware(session.expires_at)-now()
    persistent=aware(session.expires_at)-aware(session.created_at)>timedelta(hours=8)
    context=db.get(SessionContext,session.token_hash)
    method=context.method if context else "password"
    # Rotate bearer session and retain the original expiry; switching never extends it.
    raw=issue_session(db,identity,response,False,tenant_id=payload.tenant_id,method=method)
    db.get(AuthSession,digest(raw)).expires_at=now()+remaining
    if persistent:
        from .auth import SECURE_COOKIE
        response.set_cookie(COOKIE_NAME,raw,max_age=max(1,int(remaining.total_seconds())),httponly=True,secure=SECURE_COOKIE,samesite="lax",path="/")
    if context:db.delete(context);db.flush()
    db.delete(session)
    security_event(db,request,"WORKSPACE_SWITCHED",user)
    db.commit()
    return {"message":"WORKSPACE_SELECTED"}

@router.get("/admin/auth/access")
def admin_access(user:CurrentUser,db:DB,request:Request):
    context=db.get(SessionContext,digest(request.cookies.get(COOKIE_NAME,"")))
    return {"allowed":is_platform_admin(user) and request_hostname(request) in platform_hosts() and (context is None or context.audience=="admin")}

@router.get("/auth/security-events")
def security_events(user:CurrentUser,db:DB):
    rows=db.scalars(select(AuthSecurityEvent).where(AuthSecurityEvent.user_id==user.id).order_by(AuthSecurityEvent.created_at.desc()).limit(50)).all()
    return [{"id":r.id,"event":r.event,"method":r.method,"audience":r.audience,"created_at":r.created_at} for r in rows]

@router.get("/auth/sessions")
def sessions(user:CurrentUser,request:Request,db:DB):
    current=digest(request.cookies.get(COOKIE_NAME,""))
    return [{"id":digest(r.token_hash), "current":r.token_hash==current,"created_at":r.created_at,"expires_at":r.expires_at}
            for r in db.scalars(select(AuthSession).where(AuthSession.user_id==user.id,AuthSession.expires_at>now())).all()]

@router.delete("/auth/sessions/{session_id}",status_code=204)
def revoke(session_id:str,user:CurrentUser,db:DB):
    for row in db.scalars(select(AuthSession).where(AuthSession.user_id==user.id)).all():
        if digest(row.token_hash)==session_id:
            context=db.get(SessionContext,row.token_hash)
            if context:db.delete(context);db.flush()
            db.delete(row);db.commit();return
    raise HTTPException(404,"Session not found")

@router.get("/auth/options")
def options(db:DB):
    from .schemas import OrganizationCreate
    from .auth_oauth import provider_options
    return {"organization_types":list(get_args(OrganizationCreate.model_fields["legal_type"].annotation)),
            "providers":provider_options(db),"terms_url":os.getenv("AUTH_TERMS_URL",""),"privacy_url":os.getenv("AUTH_PRIVACY_URL","")}


class ChangeEmail(EmailInput):
    new_email:str=Field(min_length=3,max_length=200)
    password:str=Field(min_length=1,max_length=128)
    @field_validator("new_email")
    @classmethod
    def normalize(cls,value):
        from .validation import normalize_email
        return normalize_email(value)

@router.post("/auth/change-unverified-email")
def change_email(payload:ChangeEmail,request:Request,db:DB):
    from .auth import check_mutation,verify_password
    from sqlalchemy.exc import IntegrityError
    check_mutation(request)
    limit_attempts(db,"change-email:"+request_ip(request),10,3600)
    user=db.scalar(select(User).where(User.email==payload.email,User.status=="ACTIVE"))
    if not user or not verify_password(payload.password,user.password_hash):raise HTTPException(401,"Invalid email or password")
    account=db.get(AuthAccount,user.id)
    if not account or account.verified:raise HTTPException(403,"Only unverified registrations can change email here")
    enforce_request_tenant(request,db,user.tenant_id)
    if db.scalar(select(User.id).where(User.email==payload.new_email,User.id!=user.id)):raise HTTPException(409,"Email change unavailable")
    user.email=payload.new_email
    try:send_identity_email(db,user);db.commit()
    except IntegrationError:db.rollback();raise HTTPException(503,"Authentication email is unavailable") from None
    except IntegrityError:db.rollback();raise HTTPException(409,"Email change unavailable") from None
    return {"message":"VERIFICATION_SENT"}

@router.post("/auth/invitation-info")
def invitation_info(payload:LinkInput,request:Request,db:DB):
    from .auth import check_mutation
    check_mutation(request)
    limit_attempts(db,"invite-info:"+request_ip(request),60)
    row=db.get(AuthToken,digest(payload.token))
    if not row or row.purpose not in {"JOIN","INVITE"} or row.used_at or aware(row.expires_at)<=now():raise HTTPException(400,"Invalid or expired invitation")
    return {"existing_account":row.purpose=="JOIN"}

class JoinWorkspace(LinkInput):
    password:str=Field(min_length=1,max_length=128)

@router.post("/auth/accept-workspace-invitation")
def join_workspace(payload:JoinWorkspace,request:Request,response:Response,db:DB):
    from .auth import check_mutation,verify_password
    from .auth_models import WorkspaceInvitation
    check_mutation(request)
    limit_attempts(db,"join:"+request_ip(request),10)
    token=db.get(AuthToken,digest(payload.token))
    invitation=db.get(WorkspaceInvitation,digest(payload.token))
    if not token or token.purpose!="JOIN" or not invitation or token.used_at or aware(token.expires_at)<=now():raise HTTPException(400,"Invalid or expired invitation")
    user=db.get(User,token.user_id)
    if not user or user.status!="ACTIVE" or not verify_password(payload.password,user.password_hash):raise HTTPException(401,"Invalid credentials")
    verified_login(db,user)
    enforce_request_tenant(request,db,invitation.tenant_id)
    if db.execute(update(AuthToken).where(AuthToken.token_hash==token.token_hash,AuthToken.used_at.is_(None)).values(used_at=now())).rowcount!=1:raise HTTPException(400,"Invitation already used")
    workspace_active(db,invitation.tenant_id);seat_available(db,invitation.tenant_id)
    db.add(WorkspaceAccess(user_id=user.id,tenant_id=invitation.tenant_id,role=invitation.role))
    issue_session(db,user,response,tenant_id=invitation.tenant_id)
    security_event(db,request,"INVITATION_ACCEPTED",user)
    db.commit()
    return {"message":"INVITATION_ACCEPTED"}


def invitation_email(db,user,token,tenant):
    from .auth import PRODUCTION
    if not email_available(db):
        if PRODUCTION:raise HTTPException(503,"Authentication email is not configured")
        return
    from .brand_outputs import render_email,site_origin
    from .models import UserPreference
    preference=db.get(UserPreference,user.id)
    output=render_email(db,tenant,"auth.invitation",{"userName":user.name,"link":site_origin(db,tenant)+"/accept-invitation#token="+token},preference.locale if preference else None)
    try:deliver_email(db,tenant,user.email,output["subject"],output["text"],output["html"],output["sender_name"],output["reply_to"])
    except IntegrationError:raise HTTPException(503,"Invitation email is unavailable") from None
