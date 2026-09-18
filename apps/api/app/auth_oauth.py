"""Google authorization-code OIDC via Authlib; no client-supplied identity tokens."""
import base64
import hashlib
import json
import os
import secrets
from datetime import date,timedelta
from typing import Literal
from urllib.parse import urlencode
import requests
from authlib.integrations.requests_client import OAuth2Session
from joserfc import jwt
from joserfc.jwk import KeySet
from fastapi import APIRouter,HTTPException,Request,Response
from fastapi.responses import RedirectResponse
from pydantic import Field,SecretStr
from sqlalchemy import select,update,delete
from sqlalchemy.exc import IntegrityError
from .auth import (DB,CurrentUser,EmailInput,InputModel,APP_ORIGIN,SECURE_COOKIE,COOKIE_NAME,
                   aware,now,digest,issue_session,limit_attempts,request_ip,check_mutation)
from .auth_models import (OAuthPolicy,OAuthFlow,ProviderIdentity,PendingGoogleIdentity,AuthAccount)
from .auth_policy import is_platform_admin
from .auth_experience import (security_event,memberships,select_host_workspace,verified_login,LinkInput)
from .models import User,Workspace,Subscription,AuthSession
from .brand_domains import platform_hosts,active_domain,request_hostname
from .integration_security import secret_store,IntegrationError

router=APIRouter(prefix="/api/v1")
GOOGLE_AUTH="https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN="https://oauth2.googleapis.com/token"
GOOGLE_KEYS="https://www.googleapis.com/oauth2/v3/certs"
BINDING_COOKIE="setu_oauth_browser"
CALLBACK=APP_ORIGIN+"/api/v1/auth/google/callback"

def policy(db):
    return db.get(OAuthPolicy,"google")

def provider_options(db):
    row=policy(db)
    configured=bool(row and row.client_id and row.secret_ref)
    return {"google":{"user":bool(configured and row.user_enabled),
            "signup":bool(configured and row.signup_enabled),"admin":bool(configured and row.admin_enabled)}}

def client(row):
    value=secret_store().get_secret_for_server_use(row.secret_ref)
    session=OAuth2Session(row.client_id,value,scope="openid email profile",redirect_uri=CALLBACK,code_challenge_method="S256",token_endpoint_auth_method="client_secret_post")
    session.trust_env=False
    return session

def validate_identity(encoded,row,nonce):
    with requests.Session() as transport:
        transport.trust_env=False
        response=transport.get(GOOGLE_KEYS,timeout=8,allow_redirects=False)
        response.raise_for_status()
        keys=KeySet.import_key_set(response.json())
    claims=jwt.decode(encoded,keys,algorithms=["RS256"]).claims
    jwt.JWTClaimsRegistry(iss={"essential":True,"values":["https://accounts.google.com","accounts.google.com"]},
        aud={"essential":True,"value":row.client_id},sub={"essential":True},
        exp={"essential":True},iat={"essential":True},nonce={"essential":True,"value":nonce},
        email={"essential":True},email_verified={"essential":True,"value":True}).validate(claims)
    if claims.get("azp",row.client_id)!=row.client_id:raise ValueError("Invalid authorized party")
    from .validation import normalize_email
    claims["email"]=normalize_email(claims["email"])
    if not isinstance(claims["sub"],str) or len(claims["sub"])>255:raise ValueError("Invalid subject")
    return claims

@router.get("/auth/google")
def start(request:Request,db:DB,audience:Literal["user","admin"]="user",intent:Literal["login","signup"]="login",return_host:str=""):
    # Central platform broker binds state on its host before going to Google.
    if request_hostname(request) not in platform_hosts():
        return RedirectResponse(APP_ORIGIN+"/api/v1/auth/google?"+urlencode({"audience":audience,"intent":intent,"return_host":request_hostname(request)}),303)
    row=policy(db);options=provider_options(db)["google"]
    if not options["admin" if audience=="admin" else "signup" if intent=="signup" else "user"]:
        raise HTTPException(503,"Google authentication is not enabled")
    origin=APP_ORIGIN;tenant=None
    if return_host and return_host not in platform_hosts():
        domain=active_domain(db,return_host)
        if audience=="admin" or not domain:raise HTTPException(403,"Domain access denied")
        origin="https://"+domain.hostname;tenant=domain.tenant_id
    if audience=="admin" and intent=="signup":raise HTTPException(403,"Public admin registration is unavailable")
    if audience=="admin" and os.getenv("AUTH_ADMIN_MFA_REQUIRED")=="1":raise HTTPException(503,"Administrator MFA provider is not configured")
    limit_attempts(db,"google-start:"+request_ip(request),30,3600)
    state=secrets.token_urlsafe(32);browser=secrets.token_urlsafe(32);verifier=secrets.token_urlsafe(48);nonce=secrets.token_urlsafe(32)
    try:
        session=client(row)
        url,_=session.create_authorization_url(GOOGLE_AUTH,state=state,nonce=nonce,code_verifier=verifier,prompt="select_account")
    except IntegrationError:raise HTTPException(503,"Google authentication is unavailable") from None
    finally:
        if "session" in locals():session.close()
    db.execute(delete(OAuthFlow).where(OAuthFlow.expires_at<now()).execution_options(synchronize_session=False))
    db.add(OAuthFlow(state_hash=digest(state),browser_hash=digest(browser),verifier=verifier,nonce=nonce,audience=audience,intent=intent,
                     tenant_id=tenant,return_origin=origin,expires_at=now()+timedelta(minutes=10)))
    db.commit()
    response=RedirectResponse(url,303)
    response.set_cookie(BINDING_COOKIE,browser,max_age=600,httponly=True,secure=SECURE_COOKIE,samesite="lax",path="/api/v1/auth/google")
    response.headers["Cache-Control"]="no-store";response.headers["Referrer-Policy"]="no-referrer"
    return response

@router.get("/auth/google/callback")
def callback(request:Request,db:DB,state:str="",code:str="",error:str=""):
    flow=db.get(OAuthFlow,digest(state))
    valid=flow and not flow.used and aware(flow.expires_at)>now() and secrets.compare_digest(flow.browser_hash,digest(request.cookies.get(BINDING_COOKIE,"")))
    if not valid:raise HTTPException(400,"Invalid or expired authentication request")
    if db.execute(update(OAuthFlow).where(OAuthFlow.state_hash==flow.state_hash,OAuthFlow.used.is_(False)).values(used=True)).rowcount!=1:
        raise HTTPException(400,"Authentication request already used")
    db.commit() # Claim before external exchange, including provider cancellation.
    login_path="/admin/login" if flow.audience=="admin" else "/login"
    row=policy(db)
    try:
        if flow.audience=="admin" and os.getenv("AUTH_ADMIN_MFA_REQUIRED")=="1":raise ValueError("MFA policy unavailable")
        if error or not code or not provider_options(db)["google"]["admin" if flow.audience=="admin" else "signup" if flow.intent=="signup" else "user"]:
            raise ValueError("Provider unavailable")
        with client(row) as session:
            token=session.fetch_token(GOOGLE_TOKEN,code=code,code_verifier=flow.verifier,timeout=8)
        claims=validate_identity(token["id_token"],row,flow.nonce)
        identity=db.scalar(select(ProviderIdentity).where(ProviderIdentity.provider=="google",ProviderIdentity.subject==claims["sub"]))
        user=db.get(User,identity.user_id) if identity else db.scalar(select(User).where(User.email==claims["email"]))
        if user:
            if user.status=="INVITED" and flow.audience=="user":
                user.status="ACTIVE"
                invited_account=db.get(AuthAccount,user.id)
                if not invited_account:
                    invited_account=AuthAccount(user_id=user.id,verified=True,verification_required=True);db.add(invited_account);db.flush()
                else:invited_account.verified=True
                security_event(db,request,"INVITATION_ACCEPTED",user,method="google")
            if user.status!="ACTIVE":raise ValueError("Account unavailable")
            account=db.get(AuthAccount,user.id)
            if not identity:
                # Email linking requires an application-verified address and an authoritative Google domain.
                authoritative=claims["email"].endswith("@gmail.com") or bool(claims.get("hd"))
                if not account or not account.verified or not authoritative:
                    if flow.audience=="admin":raise ValueError("Account linking required")
                    ticket=secrets.token_urlsafe(32)
                    db.add(PendingGoogleIdentity(token_hash=digest(ticket),email=claims["email"],subject=claims["sub"],name=user.name,expires_at=now()+timedelta(minutes=10)))
                    db.commit()
                    response=RedirectResponse(APP_ORIGIN+"/auth/link-google#token="+ticket,303)
                    response.delete_cookie(BINDING_COOKIE,path="/api/v1/auth/google",secure=SECURE_COOKIE,httponly=True,samesite="lax")
                    response.headers["Cache-Control"]="no-store";response.headers["Referrer-Policy"]="no-referrer"
                    return response
                db.add(ProviderIdentity(user_id=user.id,provider="google",subject=claims["sub"]))
            verified_login(db,user)
            if flow.audience=="admin" and not is_platform_admin(user):raise ValueError("Admin access denied")
            allowed={item["id"] for item in memberships(db,user)}
            if flow.tenant_id and flow.tenant_id not in allowed:raise ValueError("Workspace access denied")
            tenant=flow.tenant_id or user.tenant_id
            if flow.audience=="user":
                from .auth_experience import workspace_active
                workspace_active(db,tenant)
            response=RedirectResponse("/admin" if flow.audience=="admin" else "/select-workspace" if len(allowed)>1 else "/dashboard",303)
            if flow.return_origin!=APP_ORIGIN:
                # Host-bound single-use handoff delivered in a fragment, consumed by POST.
                handoff=secrets.token_urlsafe(32)
                db.add(OAuthFlow(state_hash=digest(handoff),browser_hash="",verifier="",nonce=user.id,audience="handoff",intent="login",
                     tenant_id=tenant,return_origin=flow.return_origin,expires_at=now()+timedelta(seconds=60)))
                response=RedirectResponse(flow.return_origin+"/auth/complete#token="+handoff,303)
            else:
                old=request.cookies.get(COOKIE_NAME)
                if old:
                    from .auth_models import SessionContext
                    db.execute(delete(SessionContext).where(SessionContext.token_hash==digest(old)))
                    db.execute(delete(AuthSession).where(AuthSession.token_hash==digest(old)))
                issue_session(db,user,response,tenant_id=tenant,audience=flow.audience,method="google")
            security_event(db,request,"ADMIN_LOGIN_SUCCESS" if flow.audience=="admin" else "GOOGLE_LOGIN",user,flow.audience,"google")
        elif flow.intent=="signup" and flow.audience=="user" and not flow.tenant_id and row.signup_enabled:
            ticket=secrets.token_urlsafe(32)
            db.add(PendingGoogleIdentity(token_hash=digest(ticket),email=claims["email"],subject=claims["sub"],
                name=str(claims.get("name",""))[:120],expires_at=now()+timedelta(minutes=10)))
            response=RedirectResponse("/signup#google="+ticket,303)
        else:raise ValueError("Account unavailable")
        db.commit()
    except Exception:
        db.rollback()
        security_event(db,request,"ADMIN_LOGIN_FAILED" if flow.audience=="admin" else "LOGIN_FAILED",audience=flow.audience,method="google");db.commit()
        response=RedirectResponse(flow.return_origin+login_path+"?oauth=failed",303)
    response.delete_cookie(BINDING_COOKIE,path="/api/v1/auth/google",secure=SECURE_COOKIE,httponly=True,samesite="lax")
    response.headers["Cache-Control"]="no-store";response.headers["Referrer-Policy"]="no-referrer"
    return response

@router.post("/auth/google/complete")
def complete(payload:LinkInput,request:Request,response:Response,db:DB):
    check_mutation(request)
    limit_attempts(db,"handoff:"+request_ip(request),30)
    flow=db.get(OAuthFlow,digest(payload.token))
    if not flow or flow.audience!="handoff" or flow.used or aware(flow.expires_at)<=now():raise HTTPException(400,"Invalid or expired authentication request")
    if flow.return_origin!="https://"+request_hostname(request):raise HTTPException(403,"Domain access denied")
    user=db.get(User,flow.nonce)
    if not user or user.status!="ACTIVE":raise HTTPException(403,"Account unavailable")
    verified_login(db,user)
    from .auth_experience import workspace_active
    workspace_active(db,flow.tenant_id)
    from .brand_domains import enforce_request_tenant
    enforce_request_tenant(request,db,flow.tenant_id)
    if flow.tenant_id not in {item["id"] for item in memberships(db,user)}:raise HTTPException(403,"Workspace access denied")
    if db.execute(update(OAuthFlow).where(OAuthFlow.state_hash==flow.state_hash,OAuthFlow.used.is_(False)).values(used=True)).rowcount!=1:raise HTTPException(400,"Already used")
    issue_session(db,user,response,tenant_id=flow.tenant_id,method="google")
    db.commit()
    return {"message":"SIGNED_IN"}

class GoogleSignup(LinkInput):
    name:str=Field(min_length=2,max_length=120)
    workspace_name:str=Field(min_length=2,max_length=160)
    organization_type:Literal["TRUST","SOCIETY","SECTION 8"]
    phone:str=Field(default="",max_length=30)
    terms_accepted:Literal[True]

@router.post("/auth/google/signup",status_code=201)
def google_signup(payload:GoogleSignup,request:Request,response:Response,db:DB):
    check_mutation(request)
    if request_hostname(request) not in platform_hosts() or not provider_options(db)["google"]["signup"]:raise HTTPException(403,"Signup unavailable")
    limit_attempts(db,"google-signup:"+request_ip(request),10,3600)
    pending=db.get(PendingGoogleIdentity,digest(payload.token))
    if not pending or pending.used or aware(pending.expires_at)<=now():raise HTTPException(400,"Invalid or expired authentication request")
    if db.scalar(select(User.id).where(User.email==pending.email)):raise HTTPException(409,"Sign in to your existing account")
    if len(payload.name.strip())<2 or len(payload.workspace_name.strip())<2:raise HTTPException(422,"Name is required")
    if db.execute(update(PendingGoogleIdentity).where(PendingGoogleIdentity.token_hash==pending.token_hash,PendingGoogleIdentity.used.is_(False)).values(used=True)).rowcount!=1:raise HTTPException(400,"Already used")
    workspace=Workspace(name=payload.workspace_name.strip());db.add(workspace);db.flush()
    user=User(name=payload.name.strip(),email=pending.email,phone=payload.phone,tenant_id=workspace.id,role="ADMIN")
    db.add(user);db.flush()
    db.add(AuthAccount(user_id=user.id,verified=True,verification_required=True,organization_type=payload.organization_type,terms_at=now()))
    db.add(ProviderIdentity(user_id=user.id,provider="google",subject=pending.subject))
    db.add(Subscription(tenant_id=workspace.id,plan_name="STARTER",user_limit=5,organization_limit=3,storage_limit_gb=1,period_end=date.today()+timedelta(days=30)))
    issue_session(db,user,response,method="google")
    security_event(db,request,"GOOGLE_LOGIN",user,method="google")
    try:db.commit()
    except IntegrityError:db.rollback();raise HTTPException(409,"Unable to create account") from None
    return {"message":"ACCOUNT_CREATED"}

class PolicyInput(InputModel):
    client_id:str=Field(max_length=255)
    user_enabled:bool=False
    signup_enabled:bool=False
    admin_enabled:bool=False
    secret:SecretStr|None=Field(default=None,max_length=4096)

@router.get("/admin/auth/providers/google")
def read_policy(user:CurrentUser,db:DB):
    from .integration_api import permission
    permission(user,"oauth_clients.manage",platform=True)
    row=policy(db)
    return {"client_id":row.client_id if row else "","user_enabled":row.user_enabled if row else False,
            "signup_enabled":row.signup_enabled if row else False,"admin_enabled":row.admin_enabled if row else False,
            "credential_configured":bool(row and row.secret_ref),"redirect_uri":CALLBACK,
            "secret_store_writable":os.getenv("INTEGRATION_SECRET_BACKEND","environment")=="aws"}

@router.put("/admin/auth/providers/google")
def write_policy(payload:PolicyInput,request:Request,user:CurrentUser,db:DB):
    from .integration_api import permission
    permission(user,"oauth_clients.manage",platform=True)
    if request_hostname(request) not in platform_hosts():raise HTTPException(403,"Platform domain required")
    limit_attempts(db,"google-policy:"+user.id,10,3600)
    row=policy(db)
    if not row:row=OAuthPolicy(provider="google");db.add(row)
    if payload.secret:
        import uuid
        from .integration_api import ensure_https
        ensure_https(request)
        store=secret_store()
        reference=store.reference("__platform__",str(uuid.uuid5(uuid.NAMESPACE_URL,"setu-google-authentication")))
        try:store.update_secret(reference,payload.secret.get_secret_value())
        except IntegrationError:raise HTTPException(503,"Secret store is unavailable") from None
        row.secret_ref=reference
    for name in ("client_id","user_enabled","signup_enabled","admin_enabled"):setattr(row,name,getattr(payload,name))
    if (row.user_enabled or row.signup_enabled or row.admin_enabled) and (not row.client_id or not row.secret_ref):
        raise HTTPException(422,"Google client configuration is required")
    security_event(db,request,"AUTH_PROVIDER_UPDATED",user,"admin")
    db.commit()
    return read_policy(user,db)

class GoogleLink(LinkInput):
    password:str=Field(min_length=1,max_length=128)

@router.post("/auth/google/link")
def link(payload:GoogleLink,request:Request,response:Response,db:DB):
    from .auth import verify_password
    check_mutation(request)
    limit_attempts(db,"google-link:"+request_ip(request),10)
    if not provider_options(db)["google"]["user"]:raise HTTPException(403,"Google authentication disabled")
    pending=db.get(PendingGoogleIdentity,digest(payload.token))
    if not pending or pending.used or aware(pending.expires_at)<=now():raise HTTPException(400,"Invalid or expired authentication request")
    user=db.scalar(select(User).where(User.email==pending.email,User.status=="ACTIVE"))
    if not user or not verify_password(payload.password,user.password_hash):raise HTTPException(401,"Invalid email or password")
    if db.execute(update(PendingGoogleIdentity).where(PendingGoogleIdentity.token_hash==pending.token_hash,PendingGoogleIdentity.used.is_(False)).values(used=True)).rowcount!=1:raise HTTPException(400,"Already used")
    tenant=select_host_workspace(db,user,request)
    account=db.get(AuthAccount,user.id)
    if account:account.verified=True
    else:db.add(AuthAccount(user_id=user.id,verified=True,verification_required=True))
    db.add(ProviderIdentity(user_id=user.id,provider="google",subject=pending.subject))
    issue_session(db,user,response,tenant_id=tenant,method="google")
    security_event(db,request,"GOOGLE_LOGIN",user,method="google")
    try:db.commit()
    except IntegrityError:db.rollback();raise HTTPException(409,"Identity already linked") from None
    return {"message":"SIGNED_IN"}
