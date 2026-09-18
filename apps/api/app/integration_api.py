"""Separated platform and tenant connection management."""
import hashlib
import hmac
import json
import os
import secrets
from datetime import timedelta
from typing import Annotated, Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import case, func, or_, select
from .auth import CurrentUser, DB, aware, now, tenant_context
from .features import can_use_feature
from .models import IntegrationConnection, TenantEntitlement, Workspace, uid
from .permissions import has_permission, INTEGRATION_PERMISSIONS
from .integration_models import ConnectionSettings, IntegrationProvider, IntegrationOperation
from .integration_providers import CATEGORIES, REGISTRY, get_provider
from .integration_security import IntegrationError, public_error, secret_store
from .integration_service import PLATFORM_OWNER, EVENT_TYPES, owned_connection, provider_enabled, connection_output, audit, test_connection, quota

router=APIRouter(prefix="/api/v1")
PUBLIC_SCOPES=("organization.read","compliance.read","tasks.read","documents.read")
Tenant=Annotated[str,Depends(tenant_context)]

class Strict(BaseModel):
    model_config=ConfigDict(extra="forbid",str_strip_whitespace=True)
class ConnectionInput(Strict):
    provider_key: str=Field(max_length=80)
    display_name: str=Field(min_length=1,max_length=120)
    environment: Literal["SANDBOX","PRODUCTION"]="SANDBOX"
    configuration: dict
    fallback_allowed: bool=False
class ConnectionChange(Strict):
    display_name: str=Field(min_length=1,max_length=120)
    environment: Literal["SANDBOX","PRODUCTION"]
    configuration: dict
    fallback_allowed: bool=False
class CredentialInput(Strict):
    secret: SecretStr=Field(min_length=1,max_length=16000)
class EnabledInput(Strict):
    enabled: bool
class FeatureInput(EnabledInput):
    feature_key: str

def platform_user(user):
    allowlist={email.strip().lower() for email in os.getenv("PLATFORM_ADMIN_EMAILS","").split(",") if email.strip()}
    if user.role!="ADMIN" or user.email.lower() not in allowlist:
        raise HTTPException(403,"Platform administrator access is required")
def permission(user,name,platform=False):
    if platform:
        platform_user(user)
    if not has_permission(user,name):
        raise HTTPException(403,"Required integration permission is missing")
def owner_for(user,scope):
    if scope=="platform":
        platform_user(user)
        return PLATFORM_OWNER
    return user.tenant_id
def feature(db,owner,key):
    if owner!=PLATFORM_OWNER and not can_use_feature(db,owner,key):
        raise HTTPException(403,"This capability is not enabled for the workspace subscription")
def definition_for(db,owner,key):
    try:definition=get_provider(key)
    except IntegrationError:raise HTTPException(422,"Unknown provider") from None
    if not provider_enabled(db,key):
        raise HTTPException(409,"This provider is disabled")
    if owner!=PLATFORM_OWNER:
        if not definition.tenant_configurable:
            raise HTTPException(403,"This provider is platform-only")
        feature(db,owner,definition.entitlement_key)
    return definition
def validate_config(definition,configuration):
    try:return definition.configuration_schema.model_validate(configuration).model_dump()
    except Exception:raise HTTPException(422,"Invalid non-secret provider configuration. Check the required fields.") from None
def ensure_https(request):
    if os.getenv("APP_ENV")=="production" and request.url.scheme!="https":
        # Accept only the existing keyed internal Next.js proxy behind the HTTPS edge.
        key=os.getenv("BRAND_PROXY_KEY","")
        if not key or not request.headers.get("x-setu-host") or not hmac.compare_digest(request.headers.get("x-setu-proxy-key",""),key):
            raise HTTPException(400,"Submit credentials over the trusted HTTPS edge")
def store_write(db,user,request,reference,value,entity_id,action):
    ensure_https(request)
    quota(db,"credential:"+user.id,6,3600)
    try:secret_store().update_secret(reference,value)
    except IntegrationError as error:public_error(error)
    audit(db,user,action,entity_id)

@router.get("/integrations-management/access")
def access(user:CurrentUser,tenant:Tenant,db:DB):
    allowed=user.role=="ADMIN" and user.email.lower() in {x.strip().lower() for x in os.getenv("PLATFORM_ADMIN_EMAILS","").split(",")}
    writable=os.getenv("INTEGRATION_SECRET_BACKEND","environment")=="aws"
    return {"platform_allowed":allowed,"permissions":sorted(p for p in INTEGRATION_PERMISSIONS if has_permission(user,p)),
        "entitlements":{key:can_use_feature(db,tenant,key) for key in sorted({x.entitlement_key for x in REGISTRY.values()}|{"custom_webhooks","public_api"})},
        "secret_store_writable":writable,"categories":CATEGORIES,"scopes":PUBLIC_SCOPES,"event_types":EVENT_TYPES}

@router.get("/integrations-management/{scope}/providers")
def providers(scope:Literal["platform","tenant"],db:DB,user:CurrentUser,tenant:Tenant):
    permission(user,"integrations."+scope+".view",scope=="platform")
    owner=owner_for(user,scope)
    result=[]
    for item in REGISTRY.values():
        if scope=="tenant" and (not item.tenant_configurable or not can_use_feature(db,owner,item.entitlement_key)):continue
        result.append({"key":item.key,"category":item.category,"enabled":provider_enabled(db,item.key),
            "tenant_configurable":item.tenant_configurable,"platform_configurable":item.platform_configurable,"entitlement_key":item.entitlement_key,
            "capabilities":item.capabilities,"configuration_schema":item.configuration_schema.model_json_schema()})
    return result

@router.put("/integrations-management/platform/providers/{key}")
def set_provider(key:str,payload:EnabledInput,db:DB,user:CurrentUser):
    permission(user,"integrations.platform.manage",True)
    if key not in REGISTRY:raise HTTPException(404,"Provider not found")
    row=db.get(IntegrationProvider,key)
    if not row:row=IntegrationProvider(key=key);db.add(row)
    row.enabled=payload.enabled;row.updated_at=now()
    audit(db,user,"PROVIDER_ENABLED" if row.enabled else "PROVIDER_DISABLED",key)
    db.commit();return {"key":key,"enabled":row.enabled}

@router.get("/integrations-management/platform/tenants")
def platform_tenants(db:DB,user:CurrentUser):
    permission(user,"integrations.platform.view",True)
    from .models import Subscription
    from datetime import date
    rows=db.scalars(select(Workspace).order_by(Workspace.name).limit(200)).all()
    ids=[row.id for row in rows]
    subscriptions={row.tenant_id:row for row in db.scalars(select(Subscription).where(Subscription.tenant_id.in_(ids)))}
    grants={(row.tenant_id,row.feature_key):row for row in db.scalars(select(TenantEntitlement).where(TenantEntitlement.tenant_id.in_(ids)))}
    keys=sorted({p.entitlement_key for p in REGISTRY.values()}|{"public_api","custom_webhooks"})
    result=[]
    for row in rows:
        subscription=subscriptions.get(row.id)
        active=bool(subscription and subscription.status=="ACTIVE" and subscription.period_end>=date.today())
        flags={}
        for key in keys:
            grant=grants.get((row.id,key))
            flags[key]=bool(active and grant and grant.enabled and (not grant.expires_at or aware(grant.expires_at)>now()))
        result.append({"id":row.id,"name":row.name,"entitlements":flags})
    return result

@router.put("/integrations-management/platform/tenants/{tenant_id}/entitlement")
def set_feature(tenant_id:str,payload:FeatureInput,db:DB,user:CurrentUser):
    permission(user,"integrations.platform.manage",True)
    keys={x.entitlement_key for x in REGISTRY.values()}|{"custom_webhooks","public_api"}
    if payload.feature_key not in keys:raise HTTPException(422,"Unknown integration entitlement")
    if not db.get(Workspace,tenant_id):raise HTTPException(404,"Workspace not found")
    row=db.scalar(select(TenantEntitlement).where(TenantEntitlement.tenant_id==tenant_id,TenantEntitlement.feature_key==payload.feature_key))
    if not row:row=TenantEntitlement(tenant_id=tenant_id,feature_key=payload.feature_key);db.add(row)
    row.enabled=payload.enabled;row.expires_at=None;row.updated_by=user.name;row.updated_at=now()
    audit(db,user,"INTEGRATION_ENTITLEMENT_CHANGED",tenant_id,tenant_id)
    db.commit();return {"feature_key":row.feature_key,"enabled":row.enabled}

@router.get("/integrations-management/{scope}/connections")
def connections(scope:Literal["platform","tenant"],db:DB,user:CurrentUser,tenant:Tenant,category:str="",status:str="",environment:str="",page:int=Query(1,ge=1),tenant_filter:str=""):
    permission(user,"integrations."+scope+".view",scope=="platform")
    owner=owner_for(user,scope)
    query=select(IntegrationConnection,ConnectionSettings).join(ConnectionSettings,ConnectionSettings.connection_id==IntegrationConnection.id)
    if scope=="tenant":query=query.where(IntegrationConnection.tenant_id==owner,ConnectionSettings.scope=="TENANT")
    elif tenant_filter:query=query.where(IntegrationConnection.tenant_id==tenant_filter)
    if category:query=query.where(IntegrationConnection.category==category)
    if status:query=query.where(IntegrationConnection.status==status)
    if environment:query=query.where(ConnectionSettings.environment==environment)
    total=db.scalar(select(func.count()).select_from(query.subquery()))
    rows=db.execute(query.order_by(ConnectionSettings.updated_at.desc()).offset((page-1)*25).limit(25)).all()
    disabled=set(db.scalars(select(IntegrationProvider.key).where(IntegrationProvider.enabled.is_(False))))
    return {"items":[connection_output(c,s,c.provider not in disabled) for c,s in rows],"total":total,"page":page}

@router.post("/integrations-management/{scope}/connections",status_code=201)
def create_connection(scope:Literal["platform","tenant"],payload:ConnectionInput,db:DB,user:CurrentUser,tenant:Tenant):
    permission(user,"integrations."+scope+".manage",scope=="platform")
    owner=owner_for(user,scope);definition=definition_for(db,owner,payload.provider_key)
    if owner!=PLATFORM_OWNER and payload.fallback_allowed:raise HTTPException(422,"Only platform administrators can authorize platform fallback")
    config=validate_config(definition,payload.configuration)
    connection=IntegrationConnection(id=uid(),tenant_id=owner,provider=definition.key,category=definition.category,status="NOT_CONFIGURED")
    try:reference=secret_store().reference(owner,connection.id)
    except IntegrationError as error:public_error(error)
    state=ConnectionSettings(connection_id=connection.id,scope=scope.upper(),display_name=payload.display_name,environment=payload.environment,
        configuration=json.dumps(config),credential_reference=reference,fallback_allowed=payload.fallback_allowed,created_by=user.name,updated_by=user.name)
    db.add(connection);db.flush();db.add(state)
    audit(db,user,"CONNECTION_CREATED",connection.id);db.commit();return connection_output(connection,state)

@router.patch("/integrations-management/{scope}/connections/{connection_id}")
def edit_connection(scope:Literal["platform","tenant"],connection_id:str,payload:ConnectionChange,db:DB,user:CurrentUser,tenant:Tenant):
    permission(user,"integrations."+scope+".manage",scope=="platform")
    owner=owner_for(user,scope);connection,state=owned_connection(db,owner,connection_id)
    definition=definition_for(db,owner,connection.provider)
    if owner!=PLATFORM_OWNER and payload.fallback_allowed:raise HTTPException(422,"Only platform administrators can authorize platform fallback")
    state.configuration=json.dumps(validate_config(definition,payload.configuration))
    state.display_name=payload.display_name;state.environment=payload.environment;state.fallback_allowed=payload.fallback_allowed
    state.updated_by=user.name;state.updated_at=now();state.last_success_at=None;state.blocked_until=None;connection.status="CONFIGURED"
    audit(db,user,"CONNECTION_CHANGED",connection_id);db.commit();return connection_output(connection,state)

@router.put("/integrations-management/{scope}/connections/{connection_id}/credential")
def replace_credential(scope:Literal["platform","tenant"],connection_id:str,payload:CredentialInput,request:Request,db:DB,user:CurrentUser,tenant:Tenant):
    permission(user,"integrations."+scope+".manage",scope=="platform");permission(user,"integrations.credentials.rotate")
    owner=owner_for(user,scope);connection,state=owned_connection(db,owner,connection_id);definition_for(db,owner,connection.provider)
    store_write(db,user,request,state.credential_reference,payload.secret.get_secret_value(),connection_id,"CREDENTIAL_REPLACED")
    state.credential_suffix=hashlib.sha256(payload.secret.get_secret_value().encode()).hexdigest()[-4:]
    state.last_success_at=None;state.blocked_until=None;state.failure_count=0;state.error_code=""
    state.updated_at=now();state.updated_by=user.name;connection.status="CONFIGURED";db.commit();return connection_output(connection,state)

@router.delete("/integrations-management/{scope}/connections/{connection_id}/credential",status_code=204)
def delete_credential(scope:Literal["platform","tenant"],connection_id:str,db:DB,user:CurrentUser,tenant:Tenant):
    permission(user,"integrations."+scope+".manage",scope=="platform");permission(user,"integrations.credentials.rotate")
    connection,state=owned_connection(db,owner_for(user,scope),connection_id)
    try:secret_store().delete_secret(state.credential_reference)
    except IntegrationError as error:public_error(error)
    connection.status="NOT_CONFIGURED";state.last_success_at=None;state.credential_suffix=""
    audit(db,user,"CREDENTIAL_DELETED",connection_id);db.commit()

@router.post("/integrations-management/{scope}/connections/{connection_id}/{action}")
def connection_action(scope:Literal["platform","tenant"],connection_id:str,action:Literal["test","activate","disconnect"],db:DB,user:CurrentUser,tenant:Tenant):
    permission(user,"integrations."+scope+".manage",scope=="platform")
    owner=owner_for(user,scope);connection,state=owned_connection(db,owner,connection_id)
    if action=="disconnect":
        connection.status="DISABLED";state.last_success_at=None
        audit(db,user,"CONNECTION_DISCONNECTED",connection_id);db.commit();return connection_output(connection,state)
    definition_for(db,owner,connection.provider)
    if action=="test":
        result=test_connection(db,connection,state,user.tenant_id)
        audit(db,user,"CONNECTION_TESTED",connection_id);db.commit();return result
    if connection.status!="CONFIGURED" or not state.last_success_at or state.error_code or aware(state.last_success_at)<now()-timedelta(minutes=15):
        raise HTTPException(409,"Test the current configuration successfully before activation")
    connection.status="CONNECTED";state.updated_at=now()
    audit(db,user,"CONNECTION_ACTIVATED",connection_id);db.commit();return connection_output(connection,state)

@router.get("/integrations-management/{scope}/health")
def health(scope:Literal["platform","tenant"],db:DB,user:CurrentUser,tenant:Tenant):
    permission(user,"integrations.health.view",scope=="platform");permission(user,"integrations."+scope+".view")
    query=select(IntegrationConnection,ConnectionSettings).join(ConnectionSettings,ConnectionSettings.connection_id==IntegrationConnection.id)
    if scope=="tenant":query=query.where(IntegrationConnection.tenant_id==tenant)
    rows=db.execute(query.order_by(ConnectionSettings.updated_at.desc()).limit(200)).all()
    disabled=set(db.scalars(select(IntegrationProvider.key).where(IntegrationProvider.enabled.is_(False))))
    outputs=[connection_output(c,s,c.provider not in disabled) for c,s in rows]
    health_value=case((or_(IntegrationConnection.status=="DISABLED",IntegrationProvider.enabled.is_(False)),"DISABLED"),
        (IntegrationConnection.status=="CONNECTED","OPERATIONAL"),(ConnectionSettings.failure_count>=3,"OUTAGE"),
        (IntegrationConnection.status.in_(("ERROR","DEGRADED")),"DEGRADED"),else_="UNKNOWN")
    counts=select(health_value,func.count()).select_from(IntegrationConnection).join(ConnectionSettings,ConnectionSettings.connection_id==IntegrationConnection.id).outerjoin(IntegrationProvider,IntegrationProvider.key==IntegrationConnection.provider)
    if scope=="tenant":counts=counts.where(IntegrationConnection.tenant_id==tenant)
    summary=dict(db.execute(counts.group_by(health_value)).all())
    log_query=select(IntegrationOperation.status,func.count(),func.avg(IntegrationOperation.duration_ms)).where(IntegrationOperation.created_at>=now()-timedelta(days=1))
    if scope=="tenant":log_query=log_query.where(IntegrationOperation.tenant_id==tenant)
    metrics=[{"status":status,"count":count,"average_duration_ms":round(latency or 0)} for status,count,latency in db.execute(log_query.group_by(IntegrationOperation.status))]
    return {"items":outputs,"summary":{key:summary.get(key,0) for key in ("OPERATIONAL","DEGRADED","OUTAGE","UNKNOWN","DISABLED")},"metrics":metrics}


@router.get("/integrations-management/{scope}/logs")
def logs(scope:Literal["platform","tenant"],db:DB,user:CurrentUser,tenant:Tenant,page:int=Query(1,ge=1),provider_key:str="",status:str=""):
    permission(user,"integrations.logs.view",scope=="platform");permission(user,"integrations."+scope+".view")
    query=select(IntegrationOperation)
    if scope=="tenant":query=query.where(IntegrationOperation.tenant_id==tenant)
    if provider_key:query=query.where(IntegrationOperation.provider_key==provider_key)
    if status:query=query.where(IntegrationOperation.status==status)
    total=db.scalar(select(func.count()).select_from(query.subquery()))
    rows=db.scalars(query.order_by(IntegrationOperation.created_at.desc()).offset((page-1)*25).limit(25))
    return {"total":total,"page":page,"items":[{"id":row.id,"tenant_id":None if row.tenant_id==PLATFORM_OWNER else row.tenant_id,"provider_key":row.provider_key,
        "operation":row.operation,"status":row.status,"duration_ms":row.duration_ms,"error_code":row.error_code,"retry_count":row.retry_count,"created_at":aware(row.created_at),"completed_at":aware(row.completed_at)} for row in rows]}

@router.get("/integrations-management/platform/webhooks")
def platform_webhooks(db:DB,user:CurrentUser):
    from .integration_models import WebhookSubscription
    from .developer_api import webhook_output
    permission(user,"integrations.platform.view",True)
    return [dict(webhook_output(row),tenant_id=row.tenant_id) for row in db.scalars(select(WebhookSubscription)
        .where(WebhookSubscription.deleted_at.is_(None)).order_by(WebhookSubscription.created_at.desc()).limit(200))]

@router.get("/integrations-management/{scope}/audit")
def integration_audit(scope:Literal["platform","tenant"],db:DB,user:CurrentUser,tenant:Tenant):
    from .models import AuditEvent
    permission(user,"integrations.logs.view",scope=="platform")
    permission(user,"integrations."+scope+".view")
    query=select(AuditEvent).where(AuditEvent.entity_type=="Integration")
    if scope=="tenant":query=query.where(AuditEvent.tenant_id==tenant)
    return [{"id":row.id,"action":row.action,"actor_name":row.actor_name,"created_at":aware(row.created_at)} for row in db.scalars(
        query.order_by(AuditEvent.created_at.desc()).limit(100))]
