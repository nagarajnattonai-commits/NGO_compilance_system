"""Public API credentials and generic signed webhooks; separate from provider connections."""
import hashlib
import hmac
import json
import re
import secrets
import time
from datetime import timedelta
from typing import Literal
from fastapi import APIRouter, HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool
from pydantic import Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from .auth import CurrentUser, DB, aware, now
from .models import Organization, Compliance, Task, Document, uid
from .integration_models import ApiApplication, ApiKey, ApiUsage, WebhookSubscription, WebhookEvent, WebhookDelivery
from .integration_api import Strict, EnabledInput, Tenant, PUBLIC_SCOPES, permission, feature, ensure_https, store_write
from .integration_security import IntegrationError, public_error, secret_store, validate_url
from .integration_service import EVENT_TYPES, audit, quota

router=APIRouter(prefix="/api/v1")
class WebhookInput(Strict):
    name: str=Field(min_length=1,max_length=120)
    direction: Literal["INBOUND","OUTBOUND"]="OUTBOUND"
    endpoint_url: str=Field(default="",max_length=2000)
    event_types: list[str]=Field(min_length=1,max_length=20)
class ApplicationInput(Strict):
    name: str=Field(min_length=1,max_length=120)
    description: str=Field(default="",max_length=500)
class KeyInput(Strict):
    application_id: str
    name: str=Field(min_length=1,max_length=120)
    scopes: list[str]=Field(min_length=1,max_length=4)
    expires_in_days: int=Field(default=90,ge=1,le=365)
    @field_validator("scopes")
    @classmethod
    def known_scopes(cls,scopes):
        if set(scopes)-set(PUBLIC_SCOPES) or len(scopes)!=len(set(scopes)):
            raise ValueError("Select unique supported read scopes")
        return scopes

def webhook_owned(db,tenant,id):
    row=db.scalar(select(WebhookSubscription).where(WebhookSubscription.id==id,WebhookSubscription.tenant_id==tenant,WebhookSubscription.deleted_at.is_(None)))
    if not row:raise HTTPException(404,"Webhook not found")
    return row
def webhook_output(row):
    return {"id":row.id,"name":row.name,"direction":row.direction,"endpoint_url":row.endpoint_url,"event_types":json.loads(row.event_types),
            "enabled":row.enabled,"created_at":aware(row.created_at),"inbound_path":"/api/v1/inbound-webhooks/"+row.id if row.direction=="INBOUND" else None}

@router.get("/developer/webhooks")
def webhooks(db:DB,user:CurrentUser,tenant:Tenant):
    permission(user,"integrations.tenant.view")
    return [webhook_output(x) for x in db.scalars(select(WebhookSubscription).where(WebhookSubscription.tenant_id==tenant,WebhookSubscription.deleted_at.is_(None)).limit(100))]
@router.post("/developer/webhooks",status_code=201)
def create_webhook(payload:WebhookInput,request:Request,db:DB,user:CurrentUser,tenant:Tenant):
    permission(user,"integrations.webhooks.manage");feature(db,tenant,"custom_webhooks")
    if set(payload.event_types)-set(EVENT_TYPES) or len(set(payload.event_types))!=len(payload.event_types):
        raise HTTPException(422,"Choose unique supported webhook events")
    if payload.direction=="OUTBOUND":
        try:validate_url(payload.endpoint_url)
        except IntegrationError:raise HTTPException(422,"Use a public HTTPS endpoint without credentials, query parameters or fragments") from None
    elif payload.endpoint_url:raise HTTPException(422,"Inbound webhooks use the generated server endpoint")
    row=WebhookSubscription(id=uid(),tenant_id=tenant,name=payload.name,direction=payload.direction,endpoint_url=payload.endpoint_url,
        event_types=json.dumps(payload.event_types),created_by=user.name)
    raw=secrets.token_urlsafe(48)
    try:
        store=secret_store();row.secret_reference=store.reference(tenant,row.id)
        ensure_https(request);quota(db,"credential:"+user.id,6,3600);store.create_secret(row.secret_reference,raw)
    except IntegrationError as error:public_error(error)
    db.add(row);audit(db,user,"WEBHOOK_CREATED",row.id);db.commit()
    return dict(webhook_output(row),signing_secret=raw)

@router.patch("/developer/webhooks/{id}")
def toggle_webhook(id:str,payload:EnabledInput,db:DB,user:CurrentUser,tenant:Tenant):
    permission(user,"integrations.webhooks.manage");row=webhook_owned(db,tenant,id)
    if payload.enabled:feature(db,tenant,"custom_webhooks")
    row.enabled=payload.enabled;row.updated_at=now()
    audit(db,user,"WEBHOOK_CHANGED",id);db.commit();return webhook_output(row)
@router.post("/developer/webhooks/{id}/rotate")
def rotate_webhook(id:str,request:Request,db:DB,user:CurrentUser,tenant:Tenant):
    permission(user,"integrations.webhooks.manage");permission(user,"integrations.credentials.rotate");feature(db,tenant,"custom_webhooks")
    row=webhook_owned(db,tenant,id);raw=secrets.token_urlsafe(48)
    store_write(db,user,request,row.secret_reference,raw,id,"WEBHOOK_SECRET_ROTATED");db.commit()
    return {"signing_secret":raw}
@router.delete("/developer/webhooks/{id}",status_code=204)
def delete_webhook(id:str,db:DB,user:CurrentUser,tenant:Tenant):
    permission(user,"integrations.webhooks.manage");row=webhook_owned(db,tenant,id)
    try:secret_store().delete_secret(row.secret_reference)
    except IntegrationError as error:public_error(error)
    row.enabled=False;row.deleted_at=now()
    audit(db,user,"WEBHOOK_DELETED",id);db.commit()
@router.post("/developer/webhooks/{id}/test",status_code=202)
def webhook_test(id:str,db:DB,user:CurrentUser,tenant:Tenant):
    permission(user,"integrations.webhooks.manage");feature(db,tenant,"custom_webhooks");row=webhook_owned(db,tenant,id)
    if row.direction!="OUTBOUND" or not row.enabled:raise HTTPException(409,"Enable an outbound webhook before testing")
    quota(db,"webhook-test:"+tenant,10)
    event=uid();db.add(WebhookDelivery(tenant_id=tenant,subscription_id=id,event_id=event,event_type="webhook.test"))
    audit(db,user,"WEBHOOK_TEST_QUEUED",id);db.commit();return {"event_id":event,"status":"QUEUED"}
@router.get("/developer/webhooks/{id}/deliveries")
def deliveries(id:str,db:DB,user:CurrentUser,tenant:Tenant):
    permission(user,"integrations.logs.view");webhook_owned(db,tenant,id)
    return [{"id":x.id,"event_id":x.event_id,"event_type":x.event_type,"status":x.status,"attempt_count":x.attempt_count,"next_attempt_at":x.next_attempt_at,
        "response_status":x.response_status,"error_code":x.error_code} for x in db.scalars(select(WebhookDelivery).where(WebhookDelivery.tenant_id==tenant,WebhookDelivery.subscription_id==id).order_by(WebhookDelivery.created_at.desc()).limit(100))]

@router.post("/inbound-webhooks/{id}")
async def inbound_webhook(id:str,request:Request,db:DB):
    row=db.scalar(select(WebhookSubscription).where(WebhookSubscription.id==id,WebhookSubscription.direction=="INBOUND",
        WebhookSubscription.enabled.is_(True),WebhookSubscription.deleted_at.is_(None)))
    if not row:raise HTTPException(404,"Webhook not found")
    feature(db,row.tenant_id,"custom_webhooks")
    chunks=[];size=0
    async for chunk in request.stream():
        size+=len(chunk)
        if size>16384:raise HTTPException(413,"Webhook payload exceeds the limit")
        chunks.append(chunk)
    body=b"".join(chunks)
    return await run_in_threadpool(accept_signed_metadata,db,row,body,request.headers.get("x-setu-timestamp",""),request.headers.get("x-setu-signature",""))

def accept_signed_metadata(db,row,body,timestamp,signature):
    if not timestamp.isdigit() or len(timestamp)>12 or abs(int(time.time())-int(timestamp))>300:
        raise HTTPException(401,"Invalid webhook authentication")
    try:raw=secret_store().get_secret_for_server_use(row.secret_reference)
    except IntegrationError as error:public_error(error)
    expected=hmac.new(raw.encode(),timestamp.encode()+b"."+body,hashlib.sha256).hexdigest()
    if not hmac.compare_digest("sha256="+expected,signature):raise HTTPException(401,"Invalid webhook authentication")
    quota(db,"inbound:"+row.tenant_id,120)
    try:
        data=json.loads(body)
        if not isinstance(data,dict) or set(data)!={"id","type","entity_id"} or not isinstance(data["id"],str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,120}",data["id"]) or not isinstance(data["type"],str) or data["type"] not in json.loads(row.event_types) or not isinstance(data["entity_id"],str) or not re.fullmatch(r"[A-Za-z0-9_-]{0,36}",data["entity_id"]):
            raise ValueError()
    except (ValueError,TypeError,KeyError):raise HTTPException(422,"Invalid webhook event metadata") from None
    # The endpoint admits metadata only. It cannot approve compliance or payments.
    db.add(WebhookEvent(tenant_id=row.tenant_id,subscription_id=row.id,external_id=data["id"],event_type=data["type"],entity_id=data["entity_id"]))
    try:db.commit()
    except IntegrityError:
        db.rollback();return {"accepted":True,"duplicate":True}
    return {"accepted":True,"duplicate":False}

@router.get("/developer/applications")
def applications(db:DB,user:CurrentUser,tenant:Tenant):
    permission(user,"api_keys.view")
    return [{"id":x.id,"name":x.name,"description":x.description,"created_at":aware(x.created_at)} for x in db.scalars(select(ApiApplication).where(ApiApplication.tenant_id==tenant).limit(100))]
@router.post("/developer/applications",status_code=201)
def create_application(payload:ApplicationInput,db:DB,user:CurrentUser,tenant:Tenant):
    permission(user,"api_keys.create");feature(db,tenant,"public_api")
    row=ApiApplication(tenant_id=tenant,created_by=user.name,**payload.model_dump())
    db.add(row);db.flush();audit(db,user,"API_APPLICATION_CREATED",row.id);db.commit()
    return {"id":row.id,"name":row.name,"description":row.description}
def key_output(row):
    return {"id":row.id,"application_id":row.application_id,"name":row.name,"key_prefix":row.key_prefix,"key_suffix":row.key_suffix,
        "scopes":json.loads(row.scopes),"expires_at":aware(row.expires_at),"last_used_at":aware(row.last_used_at) if row.last_used_at else None,
        "status":"REVOKED" if row.revoked_at else "EXPIRED" if aware(row.expires_at)<=now() else "ACTIVE","created_at":aware(row.created_at)}
@router.get("/developer/api-keys")
def keys(db:DB,user:CurrentUser,tenant:Tenant):
    permission(user,"api_keys.view")
    return [key_output(x) for x in db.scalars(select(ApiKey).where(ApiKey.tenant_id==tenant).order_by(ApiKey.created_at.desc()).limit(100))]
@router.post("/developer/api-keys",status_code=201)
def create_key(payload:KeyInput,request:Request,db:DB,user:CurrentUser,tenant:Tenant):
    permission(user,"api_keys.create");feature(db,tenant,"public_api");ensure_https(request)
    application=db.scalar(select(ApiApplication).where(ApiApplication.id==payload.application_id,ApiApplication.tenant_id==tenant))
    if not application:raise HTTPException(404,"API application not found")
    quota(db,"create-key:"+tenant,20,3600)
    raw="setu_"+secrets.token_urlsafe(40)
    row=ApiKey(tenant_id=tenant,application_id=application.id,name=payload.name,key_prefix=raw[:12],key_suffix=raw[-4:],
        key_hash=hashlib.sha256(raw.encode()).hexdigest(),scopes=json.dumps(payload.scopes),expires_at=now()+timedelta(days=payload.expires_in_days),created_by=user.name)
    db.add(row);db.flush();audit(db,user,"API_KEY_CREATED",row.id);db.commit();return dict(key_output(row),key=raw)
@router.post("/developer/api-keys/{id}/revoke")
def revoke_key(id:str,db:DB,user:CurrentUser,tenant:Tenant):
    permission(user,"api_keys.revoke");row=db.scalar(select(ApiKey).where(ApiKey.id==id,ApiKey.tenant_id==tenant))
    if not row:raise HTTPException(404,"API key not found")
    row.revoked_at=now();audit(db,user,"API_KEY_REVOKED",id);db.commit();return key_output(row)
@router.get("/developer/usage")
def usage(db:DB,user:CurrentUser,tenant:Tenant):
    permission(user,"api_keys.view")
    rows=db.scalars(select(ApiUsage).where(ApiUsage.tenant_id==tenant).order_by(ApiUsage.created_at.desc()).limit(100)).all()
    today=db.scalar(select(func.count()).select_from(ApiUsage).where(ApiUsage.tenant_id==tenant,ApiUsage.created_at>=now().replace(hour=0,minute=0,second=0,microsecond=0)))
    return {"requests_today":today,"items":[{"id":x.id,"api_key_id":x.api_key_id,"route":x.route,"status":x.status,"duration_ms":x.duration_ms,"created_at":aware(x.created_at)} for x in rows]}
@router.get("/developer/documentation")
def documentation(user:CurrentUser,tenant:Tenant):
    permission(user,"api_keys.view")
    return {"authentication":"Authorization: Bearer <one-time API key>","base_path":"/api/v1/public","scopes":PUBLIC_SCOPES,
        "endpoints":{"/organizations":"organization.read","/compliances":"compliance.read","/tasks":"tasks.read","/documents":"documents.read"},
        "rate_limits":{"per_key_per_minute":60,"per_tenant_per_minute":300},
        "webhook_headers":["X-Setu-Timestamp","X-Setu-Signature"],"signature":"sha256=HMAC_SHA256(secret, timestamp + '.' + exact_body)",
        "oauth":{"available":False,"reason":"Use an approved identity provider; custom OAuth clients and callbacks are not implemented."}}

@router.get("/public/{resource}")
def public_records(resource:Literal["organizations","compliances","tasks","documents"],request:Request,db:DB,page:int=Query(1,ge=1),page_size:int=Query(25,ge=1,le=100)):
    started=time.perf_counter();auth=request.headers.get("authorization","");raw=auth[7:] if auth.startswith("Bearer ") else ""
    if len(raw)<40 or len(raw)>100:raise HTTPException(401,"Invalid or expired API key")
    row=db.scalar(select(ApiKey).where(ApiKey.key_hash==hashlib.sha256(raw.encode()).hexdigest()))
    if not row or row.revoked_at or aware(row.expires_at)<=now():raise HTTPException(401,"Invalid or expired API key")
    from .brand_domains import enforce_request_tenant
    enforce_request_tenant(request,db,row.tenant_id)
    scope={"organizations":"organization.read","compliances":"compliance.read","tasks":"tasks.read","documents":"documents.read"}[resource]
    try:
        feature(db,row.tenant_id,"public_api")
        if request.headers.get("x-tenant-id") not in (None,row.tenant_id):raise HTTPException(403,"Workspace access denied")
        if scope not in json.loads(row.scopes):raise HTTPException(403,"The API key lacks the required scope")
        quota(db,"api-key:"+row.id,60);quota(db,"api-tenant:"+row.tenant_id,300);quota(db,"api-platform",6000)
    except HTTPException as error:
        db.add(ApiUsage(tenant_id=row.tenant_id,api_key_id=row.id,route="/public/"+resource,status=error.status_code,duration_ms=int((time.perf_counter()-started)*1000)))
        db.commit();raise
    model={"organizations":Organization,"compliances":Compliance,"tasks":Task,"documents":Document}[resource]
    items=db.scalars(select(model).where(model.tenant_id==row.tenant_id).order_by(model.id).offset((page-1)*page_size).limit(page_size)).all()
    fields={"organizations":("id","name","legal_type","status","city"),"compliances":("id","organization_id","code","title","status","statutory_deadline"),
        "tasks":("id","organization_id","title","status","due_at"),"documents":("id","organization_id","name","category","version","expiry_at")}[resource]
    result=[{field:getattr(item,field,None) for field in fields} for item in items]
    total=db.scalar(select(func.count()).select_from(model).where(model.tenant_id==row.tenant_id))
    row.last_used_at=now();db.add(ApiUsage(tenant_id=row.tenant_id,api_key_id=row.id,route="/public/"+resource,status=200,duration_ms=int((time.perf_counter()-started)*1000)));db.commit()
    return {"items":result,"total":total,"page":page,"page_size":page_size}

@router.get("/integrations-management/platform/developer/{section}")
def platform_developer(section:Literal["applications","api-keys","usage"],db:DB,user:CurrentUser):
    permission(user,"integrations.platform.view",True);permission(user,"api_keys.view")
    if section=="applications":
        return [dict(id=row.id,name=row.name,description=row.description,tenant_id=row.tenant_id) for row in db.scalars(select(ApiApplication).order_by(ApiApplication.created_at.desc()).limit(200))]
    if section=="api-keys":
        return [dict(key_output(row),tenant_id=row.tenant_id) for row in db.scalars(select(ApiKey).order_by(ApiKey.created_at.desc()).limit(200))]
    count=db.scalar(select(func.count()).select_from(ApiUsage).where(ApiUsage.created_at>=now().replace(hour=0,minute=0,second=0,microsecond=0)))
    rows=db.scalars(select(ApiUsage).order_by(ApiUsage.created_at.desc()).limit(100))
    return {"requests_today":count,"items":[{"id":row.id,"route":row.route,"status":row.status,"duration_ms":row.duration_ms,"created_at":aware(row.created_at)} for row in rows]}
