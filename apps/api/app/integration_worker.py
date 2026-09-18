"""Persistent SQL outbox worker. Run once or supervise --loop; no request-thread sends."""
import argparse
import hashlib
import hmac
import json
import random
import time
from datetime import timedelta
from sqlalchemy import delete, or_, select, update
from .auth import aware, now
from .database import SessionLocal
from .features import can_use_feature
from .models import AuditEvent
from .integration_models import WebhookSubscription, WebhookDelivery, WebhookEvent, IntegrationOperation, IntegrationQuota
from .integration_security import IntegrationError, safe_http, secret_store
from .integration_service import quota
from fastapi import HTTPException

def process_batch(limit=25):
    processed=0
    with SessionLocal() as db:
        ids=db.scalars(select(WebhookDelivery.id).where(WebhookDelivery.status.in_(("QUEUED","RETRY","PROCESSING")),WebhookDelivery.next_attempt_at<=now())
            .order_by(WebhookDelivery.next_attempt_at).limit(limit)).all()
        for id in ids:
            # Compare-and-swap lease: PostgreSQL/SQLite workers cannot both claim a due row.
            claim=db.execute(update(WebhookDelivery).where(WebhookDelivery.id==id,WebhookDelivery.status.in_(("QUEUED","RETRY","PROCESSING")),
                WebhookDelivery.next_attempt_at<=now()).values(status="PROCESSING",next_attempt_at=now()+timedelta(minutes=5),
                last_attempt_at=now(),attempt_count=WebhookDelivery.attempt_count+1))
            db.commit()
            if not claim.rowcount:continue
            row=db.get(WebhookDelivery,id)
            subscription=db.get(WebhookSubscription,row.subscription_id)
            if not subscription or not subscription.enabled or subscription.deleted_at or not can_use_feature(db,row.tenant_id,"custom_webhooks"):
                row.status="CANCELLED";db.commit();continue
            if row.attempt_count>5:
                row.status="FAILED";row.error_code="PROVIDER_UNAVAILABLE";db.commit();continue
            timestamp=str(int(time.time()))
            body=json.dumps({"id":row.event_id,"type":row.event_type,"tenant_id":row.tenant_id,"entity_id":row.entity_id},
                separators=(",",":"),sort_keys=True).encode()
            started=time.perf_counter()
            error=None
            try:
                try:quota(db,"webhook-delivery:"+row.tenant_id,60)
                except HTTPException:raise IntegrationError("RATE_LIMITED") from None
                raw=secret_store().get_secret_for_server_use(subscription.secret_reference)
                signature=hmac.new(raw.encode(),timestamp.encode()+b"."+body,hashlib.sha256).hexdigest()
                status,retry=safe_http(subscription.endpoint_url,"POST",{"Content-Type":"application/json",
                    "X-Setu-Timestamp":timestamp,"X-Setu-Signature":"sha256="+signature,"X-Setu-Event-ID":row.event_id},body)
                row.response_status=status
                if 200<=status<300:row.status="SUCCESS"
                else:
                    code="RATE_LIMITED" if status==429 else "PROVIDER_UNAVAILABLE" if status>=500 or status in (408,425) else "AUTHENTICATION_FAILED" if status in (401,403) else "INVALID_CONFIGURATION"
                    error=IntegrationError(code,retry)
            except IntegrationError as problem:error=problem
            except Exception:error=IntegrationError("PROVIDER_UNAVAILABLE")
            if error:
                row.error_code=error.code
                retryable=error.code in {"RATE_LIMITED","PROVIDER_UNAVAILABLE","TIMEOUT","SECRET_STORE_UNAVAILABLE"}
                row.status="RETRY" if retryable and row.attempt_count<5 else "FAILED"
                delay=max(error.retry_after, min(3600,30*2**(row.attempt_count-1)))+random.randint(0,15)
                row.next_attempt_at=now()+timedelta(seconds=delay)
            else:row.error_code=""
            db.add(IntegrationOperation(tenant_id=row.tenant_id,provider_key="outbound_webhook",operation="webhook_delivery",status=row.status,
                duration_ms=int((time.perf_counter()-started)*1000),error_code=row.error_code,retry_count=row.attempt_count-1))
            db.commit();processed+=1
        # Verified generic inbound metadata is audited only: never mutate financial/compliance state.
        events=db.scalars(select(WebhookEvent.id).where(WebhookEvent.status=="QUEUED").limit(limit)).all()
        for id in events:
            claimed=db.execute(update(WebhookEvent).where(WebhookEvent.id==id,WebhookEvent.status=="QUEUED").values(status="RECEIVED"))
            if claimed.rowcount:
                row=db.get(WebhookEvent,id)
                db.add(AuditEvent(tenant_id=row.tenant_id,actor_name="Webhook service",action="WEBHOOK_RECEIVED",entity_type="Webhook",
                    entity_id=row.subscription_id,summary="Verified event metadata received: "+row.event_type))
                processed+=1
            db.commit()
    return processed

def prune_rate_windows():
    with SessionLocal() as db:
        # Stored windows include minute/hour quotas; keep at least 48 hours of either.
        cutoff=int(time.time())-172800
        db.execute(delete(IntegrationQuota).where(IntegrationQuota.window<cutoff))
        db.commit()

def main():
    parser=argparse.ArgumentParser(description="Process integration webhook jobs")
    parser.add_argument("--loop",action="store_true")
    args=parser.parse_args()
    last_cleanup=0
    while True:
        if time.time()-last_cleanup>3600:
            prune_rate_windows();last_cleanup=time.time()
        process_batch()
        if not args.loop:break
        time.sleep(5)
if __name__=="__main__":main()
