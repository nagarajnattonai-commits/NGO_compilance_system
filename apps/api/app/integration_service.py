"""Central resolver, bounded tests, scoped logs, outbox, and quota primitives."""
import hashlib
import json
import os
import time
from datetime import timedelta
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from .auth import aware, now
from .features import can_use_feature
from .models import AuditEvent, IntegrationConnection, Notification, ComplianceNotificationTemplate, uid
from .integration_models import ConnectionSettings, IntegrationProvider, IntegrationOperation, IntegrationHealthCheck, IntegrationQuota, WebhookSubscription, WebhookDelivery
from .integration_providers import REGISTRY, get_provider
from .integration_security import IntegrationError, secret_store

PLATFORM_OWNER = "__platform__"
EVENT_TYPES = ("compliance.created","compliance.completed","compliance.overdue","task.completed","document.uploaded","document.expiring","user.created","webhook.test")
EVENT_ACTIONS = {"COMPLIANCE_CREATED":"compliance.created","COMPLIANCE_GENERATED":"compliance.created","COMPLIANCE_OVERDUE":"compliance.overdue","DOCUMENT_UPLOADED":"document.uploaded"}

def audit(db,user,action,entity_id,tenant_id=None):
    db.add(AuditEvent(tenant_id=tenant_id or user.tenant_id,actor_name=user.name,action=action,
        entity_type="Integration",entity_id=entity_id,summary=action.replace("_"," ")))
def provider_enabled(db,key):
    row=db.get(IntegrationProvider,key)
    return key in REGISTRY and (not row or row.enabled)
def quota(db,scope,maximum,seconds=60):
    window=int(time.time())//seconds
    key=hashlib.sha256(scope.encode()).hexdigest()+":"+str(window)
    result=db.execute(update(IntegrationQuota).where(IntegrationQuota.id==key,IntegrationQuota.count<maximum).values(count=IntegrationQuota.count+1))
    if result.rowcount:
        db.commit()
        return
    if not db.get(IntegrationQuota,key):
        try:
            with db.begin_nested():
                db.add(IntegrationQuota(id=key,window=window*seconds))
                db.flush()
            db.commit()
            return
        except IntegrityError:
            pass
        result=db.execute(update(IntegrationQuota).where(IntegrationQuota.id==key,IntegrationQuota.count<maximum).values(count=IntegrationQuota.count+1))
        if result.rowcount:
            db.commit()
            return
    db.commit()
    raise HTTPException(429,"Rate limit reached. Please try again later.",headers={"Retry-After":str(seconds)})

def connection_output(connection,state,enabled=True):
    health = "DISABLED" if not enabled or connection.status=="DISABLED" else ("OPERATIONAL" if connection.status=="CONNECTED" else "OUTAGE" if state.failure_count>=3 else "DEGRADED" if connection.status in {"ERROR","DEGRADED"} else "UNKNOWN")
    return {"id":connection.id,"tenant_id":None if state.scope=="PLATFORM" else connection.tenant_id,"provider_key":connection.provider,"category":connection.category,
        "scope":state.scope,"display_name":state.display_name,"configuration":json.loads(state.configuration),"environment":state.environment,
        "status":connection.status,"health":health,"fallback_allowed":state.fallback_allowed,
        "credential_suffix":state.credential_suffix,"credential_configured":bool(state.last_success_at or state.credential_suffix),
        "failure_count":state.failure_count,"error_code":state.error_code,"last_tested_at":aware(state.last_tested_at) if state.last_tested_at else None,"last_success_at":aware(state.last_success_at) if state.last_success_at else None,
        "last_error_at":aware(state.last_error_at) if state.last_error_at else None,"created_at":aware(state.created_at) if state.created_at else None,"updated_at":aware(state.updated_at) if state.updated_at else None}

def owned_connection(db,owner,connection_id):
    result=db.execute(select(IntegrationConnection,ConnectionSettings).join(ConnectionSettings,ConnectionSettings.connection_id==IntegrationConnection.id)
        .where(IntegrationConnection.id==connection_id,IntegrationConnection.tenant_id==owner)).first()
    if not result:
        raise HTTPException(404,"Connection not found")
    return result

def adapter_for(db,connection,state):
    if not provider_enabled(db,connection.provider):
        raise IntegrationError("INTEGRATION_NOT_CONFIGURED")
    definition=get_provider(connection.provider)
    config=definition.configuration_schema.model_validate_json(state.configuration).model_dump()
    secret=secret_store().get_secret_for_server_use(state.credential_reference)
    return definition.adapter(config,secret)

def resolve_integration(db,tenant_id,category,capability,environment="PRODUCTION"):
    """Tenant first; platform fallback opt-in on each platform connection."""
    definitions=[item for item in REGISTRY.values() if item.category==category and capability in item.capabilities]
    keys=[item.key for item in definitions]
    for owner in (tenant_id,PLATFORM_OWNER):
        rows=db.execute(select(IntegrationConnection,ConnectionSettings).join(ConnectionSettings,ConnectionSettings.connection_id==IntegrationConnection.id)
            .where(IntegrationConnection.tenant_id==owner,IntegrationConnection.provider.in_(keys),IntegrationConnection.status=="CONNECTED",
                   ConnectionSettings.environment==environment)
            .order_by(ConnectionSettings.created_at)).all()
        for connection,state in rows:
            expected_scope="TENANT" if owner==tenant_id else "PLATFORM"
            if state.scope!=expected_scope or (owner==PLATFORM_OWNER and not state.fallback_allowed):
                continue
            if owner==tenant_id and not can_use_feature(db,tenant_id,get_provider(connection.provider).entitlement_key):
                continue
            if state.blocked_until and aware(state.blocked_until)>now():
                continue
            try:
                return connection,state,adapter_for(db,connection,state)
            except IntegrationError:
                continue
    raise IntegrationError("INTEGRATION_NOT_CONFIGURED")

def log_operation(db,connection,operation,status,duration,error_code=""):
    row=IntegrationOperation(id=uid(),tenant_id=connection.tenant_id,connection_id=connection.id,provider_key=connection.provider,operation=operation,
        status=status,duration_ms=max(0,int(duration)),error_code=error_code)
    db.add(row)
    return row

def test_connection(db,connection,state,alert_tenant_id=None):
    if state.blocked_until and aware(state.blocked_until)>now():
        raise HTTPException(429,"The connection is cooling down. Please try again later.",headers={"Retry-After":str(max(1,int((aware(state.blocked_until)-now()).total_seconds())))})
    quota(db,"provider-test:"+connection.tenant_id+":"+connection.provider,10)
    started=time.perf_counter()
    error=None
    try:
        adapter_for(db,connection,state).test_connection()
    except IntegrationError as problem:
        error=problem
    except Exception:
        error=IntegrationError("INVALID_CONFIGURATION")
    state.last_tested_at=now()
    if error:
        state.last_error_at=now()
        state.failure_count+=1
        state.error_code=error.code
        connection.status="ERROR"
        state.blocked_until=now()+timedelta(seconds=error.retry_after if error.code=="RATE_LIMITED" else 300 if state.failure_count>=3 else 5)
        if state.failure_count==3:
            alert=Notification(id=uid(),tenant_id=connection.tenant_id if state.scope=="TENANT" else (alert_tenant_id or os.getenv("PLATFORM_ALERT_TENANT_ID",connection.tenant_id)),
                title="Integration requires attention",message="A configured integration has failed three consecutive connection checks.",kind="WARNING")
            db.add(alert);db.flush()
            db.add(ComplianceNotificationTemplate(notification_id=alert.id,tenant_id=alert.tenant_id,template_key="integration.providerAlert",variables="{}"))

    else:
        state.last_success_at=now()
        state.failure_count=0
        state.error_code=""
        state.blocked_until=None
        connection.status="CONFIGURED"
    duration=int((time.perf_counter()-started)*1000)
    log=log_operation(db,connection,"test_connection","FAILED" if error else "SUCCESS",duration,state.error_code)
    db.add(IntegrationHealthCheck(connection_id=connection.id,health="OUTAGE" if state.failure_count>=3 else "DEGRADED" if error else "OPERATIONAL",
                                  error_code=state.error_code,duration_ms=duration))
    return {"success":not error,"error_code":state.error_code,"request_id":log.id,"connection":connection_output(connection,state)}

def enqueue_event(db,tenant_id,event_type,entity_id,event_id=None):
    """Metadata only, committed in the same transaction as the business change."""
    event_id=event_id or uid()
    for subscription in db.scalars(select(WebhookSubscription).where(WebhookSubscription.tenant_id==tenant_id,WebhookSubscription.direction=="OUTBOUND",
        WebhookSubscription.enabled.is_(True),WebhookSubscription.deleted_at.is_(None))):
        if event_type not in json.loads(subscription.event_types):
            continue
        if not db.scalar(select(WebhookDelivery.id).where(WebhookDelivery.subscription_id==subscription.id,WebhookDelivery.event_id==event_id)):
            db.add(WebhookDelivery(tenant_id=tenant_id,subscription_id=subscription.id,event_id=event_id,event_type=event_type,entity_id=entity_id))
    return event_id
