"""Security contracts for integrations. Provider credentials never leave test memory."""
import hashlib
import hmac
import json
import time
from contextlib import contextmanager
from datetime import date, timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import app
from app.database import SessionLocal
from app.auth import digest, now
from app.models import User, AuthSession, Workspace, Subscription, TenantEntitlement, IntegrationConnection, AuditEvent
from app.integration_models import ConnectionSettings, ApiKey, WebhookDelivery, WebhookEvent, IntegrationOperation
from app.integration_security import IntegrationError, EnvironmentSecretStore, validate_url
from app.integration_service import resolve_integration, enqueue_event, PLATFORM_OWNER
from app.integration_worker import process_batch

SECRET="provider-secret-must-never-appear-2026"
BASE="/api/v1/integrations-management"
CONFIG={"host":"mail.example.org","username":"mailer","from_address":"notify@example.org","port":465}

class MemorySecretStore:
    writable=True
    def __init__(self):self.values={}
    def reference(self,tenant,id):return "test://"+tenant+"/"+id
    def get_secret_for_server_use(self,ref):
        if ref not in self.values:raise IntegrationError("INTEGRATION_NOT_CONFIGURED")
        return self.values[ref]
    def create_secret(self,ref,value):self.values[ref]=value
    update_secret=create_secret
    def delete_secret(self,ref):self.values.pop(ref,None)

@pytest.fixture
def store(monkeypatch):
    store=MemorySecretStore()
    for module in ("integration_api","integration_service","developer_api","integration_worker"):
        monkeypatch.setattr("app."+module+".secret_store",lambda:store)
    monkeypatch.setenv("PLATFORM_ADMIN_EMAILS","admin@tenant-a.test")
    monkeypatch.setattr("app.integration_providers.SMTPAdapter.test_connection",lambda self:None)
    monkeypatch.setattr("app.integration_security.socket.getaddrinfo",lambda *a,**k:[(2,1,6,"",("93.184.216.34",443))])
    return store

@contextmanager
def client_for(tenant="tenant-a",role="ADMIN",entitled=True):
    with TestClient(app) as client:
        with SessionLocal() as db:
            if not db.get(Workspace,tenant):
                db.add(Workspace(id=tenant,name=tenant))
                db.add(Subscription(tenant_id=tenant,period_end=date.today()+timedelta(days=30)))
                for feature in ("custom_email","custom_storage","whatsapp_integration","google_calendar_integration","custom_webhooks","public_api"):
                    db.add(TenantEntitlement(tenant_id=tenant,feature_key=feature,enabled=entitled))
            user=User(tenant_id=tenant,name="Test integration administrator",email=role.lower()+"@"+tenant+".test",role=role)
            db.add(user);db.flush()
            token=tenant+"-"+role
            db.add(AuthSession(token_hash=digest(token),user_id=user.id,expires_at=now()+timedelta(hours=1)));db.commit()
        client.cookies.set("setu_session",token);client.headers["X-Setu-Request"]="1"
        yield client

def create(client,scope="tenant",**changes):
    response=client.post(BASE+"/"+scope+"/connections",json=dict(provider_key="smtp",display_name="Branded email",environment="PRODUCTION",configuration=CONFIG,**changes))
    assert response.status_code==201,response.text
    return response.json()
def credential(client,id,scope="tenant"):
    response=client.put(BASE+"/"+scope+"/connections/"+id+"/credential",json={"secret":SECRET})
    assert response.status_code==200,response.text
def api_key(client,scopes=None):
    app_response=client.post("/api/v1/developer/applications",json={"name":"ERP"})
    assert app_response.status_code==201,app_response.text
    response=client.post("/api/v1/developer/api-keys",json={"application_id":app_response.json()["id"],"name":"Read records","scopes":scopes or ["organization.read"],"expires_in_days":30})
    assert response.status_code==201,response.text
    return response.json()
def webhook(client,direction="INBOUND"):
    response=client.post("/api/v1/developer/webhooks",json={"name":"ERP events","direction":direction,
        "endpoint_url":"https://hooks.example.org/events" if direction=="OUTBOUND" else "","event_types":["compliance.created","webhook.test"]})
    assert response.status_code==201,response.text
    return response.json()
def signed(secret,payload,timestamp=None):
    body=json.dumps(payload,separators=(",",":")).encode();timestamp=str(timestamp or int(time.time()))
    return body,{"X-Setu-Timestamp":timestamp,"X-Setu-Signature":"sha256="+hmac.new(secret.encode(),timestamp.encode()+b"."+body,hashlib.sha256).hexdigest()}

def test_test_before_activation_rotation_and_secret_redaction(store):
    with client_for() as client:
        row=create(client);id=row["id"];path=BASE+"/tenant/connections/"+id
        assert client.post(path+"/activate").status_code==409
        credential(client,id)
        assert client.get(path+"/credential").status_code in (404,405)
        result=client.post(path+"/test").json()
        assert result["success"] and result["connection"]["status"]=="CONFIGURED"
        assert result["request_id"]
        assert client.post(path+"/activate").json()["status"]=="CONNECTED"
        credential(client,id)
        assert client.post(path+"/activate").status_code==409
        for route in (BASE+"/tenant/connections",BASE+"/tenant/logs",BASE+"/tenant/health","/api/v1/audit-events"):
            assert SECRET not in client.get(route).text
        with SessionLocal() as db:
            assert SECRET not in db.get(ConnectionSettings,id).configuration
            assert SECRET not in db.get(ConnectionSettings,id).credential_reference
        assert client.patch("/api/v1/integrations/"+id,json={"status":"CONNECTED"}).status_code==409

@pytest.mark.parametrize("role",["MEMBER","VIEWER"])
def test_non_admin_denied_backend_and_legacy_list(store,role):
    with client_for(role=role) as client:
        assert client.get(BASE+"/tenant/providers").status_code==403
        assert client.get(BASE+"/tenant/connections").status_code==403
        assert client.get("/api/v1/developer/api-keys").status_code==403
        assert client.get("/api/v1/integrations").json()==[]
        assert client.post(BASE+"/tenant/connections",json={"provider_key":"smtp","display_name":"X","configuration":CONFIG}).status_code==403

def test_tenant_isolation_all_mutations_and_platform_gate(store):
    with client_for() as a:
        row=create(a);key=api_key(a);hook=webhook(a)
    with client_for("tenant-b") as b:
        path=BASE+"/tenant/connections/"+row["id"]
        assert b.post(path+"/test").status_code==404
        assert b.post(path+"/disconnect").status_code==404
        assert b.put(path+"/credential",json={"secret":"new-secret"}).status_code==404
        assert b.delete(path+"/credential").status_code==404
        assert b.patch(path,json={"display_name":"X","environment":"PRODUCTION","configuration":CONFIG}).status_code==404
        assert b.get(BASE+"/tenant/connections").json()["items"]==[]
        assert b.post("/api/v1/developer/api-keys/"+key["id"]+"/revoke").status_code==404
        assert b.get("/api/v1/developer/webhooks/"+hook["id"]+"/deliveries").status_code==404
        assert b.post("/api/v1/developer/webhooks/"+hook["id"]+"/rotate").status_code==404
        assert b.delete("/api/v1/developer/webhooks/"+hook["id"]).status_code==404
        assert b.get(BASE+"/platform/providers").status_code==403
        assert b.get(BASE+"/tenant/connections",headers={"X-Tenant-ID":"tenant-a"}).status_code==403

def test_entitlements_and_config_secrets_fail_closed(store):
    with client_for(entitled=False) as client:
        assert client.get(BASE+"/tenant/providers").json()==[]
        assert client.post(BASE+"/tenant/connections",json={"provider_key":"smtp","display_name":"X","configuration":CONFIG}).status_code==403
        assert client.post("/api/v1/developer/applications",json={"name":"ERP"}).status_code==403
    with client_for("tenant-b") as client:
        response=client.post(BASE+"/tenant/connections",json={"provider_key":"smtp","display_name":"X","configuration":dict(CONFIG,password=SECRET)})
        assert response.status_code==422 and SECRET not in response.text
        response=client.post(BASE+"/tenant/connections",json={"provider_key":"smtp","display_name":"X","configuration":CONFIG,"tenant_id":"tenant-a"})
        assert response.status_code==422

def test_explicit_category_fallback_and_resolution(store):
    with client_for() as client:
        platform=create(client,"platform")
        credential(client,platform["id"],"platform")
        path=BASE+"/platform/connections/"+platform["id"]
        client.post(path+"/test");client.post(path+"/activate")
        with SessionLocal() as db:
            with pytest.raises(IntegrationError):resolve_integration(db,"tenant-b","EMAIL","email.send")
        client.patch(path,json={"display_name":"Platform fallback","environment":"PRODUCTION","configuration":CONFIG,"fallback_allowed":True})
        client.post(path+"/test");client.post(path+"/activate")
        tenant=create(client);credential(client,tenant["id"])
        tpath=BASE+"/tenant/connections/"+tenant["id"]
        client.post(tpath+"/test");client.post(tpath+"/activate")
        with SessionLocal() as db:
            assert resolve_integration(db,"tenant-a","EMAIL","email.send")[0].id==tenant["id"]
            assert resolve_integration(db,"tenant-b","EMAIL","email.send")[0].id==platform["id"]
            with pytest.raises(IntegrationError):resolve_integration(db,"tenant-a","WHATSAPP","whatsapp.send")
        assert client.put(BASE+"/platform/providers/smtp",json={"enabled":False}).status_code==200
        with SessionLocal() as db:
            with pytest.raises(IntegrationError):resolve_integration(db,"tenant-a","EMAIL","email.send")

def test_connection_failure_sanitized_and_cooling_down(store,monkeypatch):
    def fail(self):raise RuntimeError("Authorization: "+SECRET)
    monkeypatch.setattr("app.integration_providers.SMTPAdapter.test_connection",fail)
    with client_for() as client:
        row=create(client);credential(client,row["id"]);path=BASE+"/tenant/connections/"+row["id"]
        response=client.post(path+"/test")
        assert SECRET not in response.text
        assert response.json()["error_code"]=="INVALID_CONFIGURATION"
        assert client.post(path+"/test").status_code==429
        assert client.post(path+"/activate").status_code==409
        assert SECRET not in client.get(BASE+"/tenant/logs").text

def test_api_key_only_hash_stored_scope_revocation_expiration_and_usage(store):
    with client_for() as client:
        row=api_key(client);raw=row["key"]
        assert raw not in client.get("/api/v1/developer/api-keys").text
        with SessionLocal() as db:
            saved=db.get(ApiKey,row["id"])
            assert saved.key_hash==hashlib.sha256(raw.encode()).hexdigest()
        headers={"Authorization":"Bearer "+raw}
        assert client.get("/api/v1/public/organizations",headers=headers).status_code==200
        assert client.get("/api/v1/public/tasks",headers=headers).status_code==403
        assert client.get("/api/v1/public/organizations",headers=dict(headers,**{"X-Tenant-ID":"tenant-b"})).status_code==403
        assert client.get("/api/v1/developer/usage").json()["requests_today"]==3
        assert client.post("/api/v1/developer/api-keys/"+row["id"]+"/revoke").status_code==200
        assert client.get("/api/v1/public/organizations",headers=headers).status_code==401
        expired=api_key(client)
        with SessionLocal() as db:
            db.get(ApiKey,expired["id"]).expires_at=now()-timedelta(seconds=1);db.commit()
        assert client.get("/api/v1/public/organizations",headers={"Authorization":"Bearer "+expired["key"]}).status_code==401
        assert client.get("/api/v1/oauth/callback?code=untrusted").status_code==404

def test_api_key_rate_limit_and_entitlement_revocation(store):
    with client_for() as client:
        row=api_key(client);headers={"Authorization":"Bearer "+row["key"]}
        for _ in range(60):assert client.get("/api/v1/public/organizations",headers=headers).status_code==200
        response=client.get("/api/v1/public/organizations",headers=headers)
        assert response.status_code==429 and response.headers["Retry-After"]=="60"
        with SessionLocal() as db:
            entitlement=db.scalar(select(TenantEntitlement).where(TenantEntitlement.tenant_id=="tenant-a",TenantEntitlement.feature_key=="public_api"))
            entitlement.enabled=False;db.commit()
        assert client.get("/api/v1/public/organizations",headers=headers).status_code==403

def test_inbound_signature_duplicate_replay_and_bounded_metadata(store):
    with client_for() as client:
        row=webhook(client);path="/api/v1/inbound-webhooks/"+row["id"]
        body,headers=signed(row["signing_secret"],{"id":"external-1","type":"compliance.created","entity_id":"cmp-1"})
        assert client.post(path,content=body,headers=headers).json()=={"accepted":True,"duplicate":False}
        assert client.post(path,content=body,headers=headers).json()["duplicate"]
        assert client.post(path,content=body,headers=dict(headers,**{"X-Setu-Signature":"sha256=bad"})).status_code==401
        expired,old=signed(row["signing_secret"],{"id":"external-2","type":"compliance.created","entity_id":"cmp-1"},int(time.time())-301)
        assert client.post(path,content=expired,headers=old).status_code==401
        assert client.post(path,content=b"x"*16385,headers=headers).status_code==413
        invalid,bad=signed(row["signing_secret"],{"id":"external-3","type":"payment.paid","entity_id":"invoice-1"})
        assert client.post(path,content=invalid,headers=bad).status_code==422
        assert process_batch()==1
        with SessionLocal() as db:
            assert len(db.scalars(select(WebhookEvent)).all())==1
            assert db.scalar(select(WebhookEvent)).status=="RECEIVED"
        assert row["signing_secret"] not in client.get("/api/v1/developer/webhooks").text

@pytest.mark.parametrize("url",["http://example.org/hook","https://127.0.0.1/hook","https://169.254.169.254/latest","https://localhost/hook",
    "https://user:pass@example.org/hook","https://example.org/hook?token=secret","https://example.org:8443/hook","https://example.org/hook#secret","https://[::1]/hook"])
def test_malicious_webhook_urls_denied(url):
    with pytest.raises(IntegrationError):validate_url(url,resolve=False)

def test_dns_rebinding_denied(store,monkeypatch):
    monkeypatch.setattr("app.integration_security.socket.getaddrinfo",lambda *a,**k:[(2,1,6,"",("10.0.0.1",443))])
    with pytest.raises(IntegrationError):validate_url("https://hooks.example.org/events")

def test_outbox_idempotency_retry_signature_and_permanent_error(store,monkeypatch):
    calls=[]
    def transport(url,method,headers,body):
        calls.append((headers,body))
        return (503,60) if len(calls)==1 else (204,60)
    monkeypatch.setattr("app.integration_worker.safe_http",transport)
    with client_for() as client:
        row=webhook(client,"OUTBOUND")
        with SessionLocal() as db:
            enqueue_event(db,"tenant-a","compliance.created","cmp-1","same-event")
            db.flush();enqueue_event(db,"tenant-a","compliance.created","cmp-1","same-event");db.commit()
            assert len(db.scalars(select(WebhookDelivery)).all())==1
        assert process_batch()==1
        with SessionLocal() as db:
            delivery=db.scalar(select(WebhookDelivery));assert delivery.status=="RETRY" and delivery.attempt_count==1
            delivery.next_attempt_at=now()-timedelta(seconds=1);db.commit()
        assert process_batch()==1
        headers,body=calls[-1]
        assert headers["X-Setu-Signature"]=="sha256="+hmac.new(row["signing_secret"].encode(),headers["X-Setu-Timestamp"].encode()+b"."+body,hashlib.sha256).hexdigest()
        with SessionLocal() as db:
            assert db.scalar(select(WebhookDelivery)).status=="SUCCESS"
        monkeypatch.setattr("app.integration_worker.safe_http",lambda *args:(401,60))
        assert client.post("/api/v1/developer/webhooks/"+row["id"]+"/test").status_code==202
        assert process_batch()==1
        with SessionLocal() as db:
            assert db.scalar(select(WebhookDelivery).where(WebhookDelivery.event_type=="webhook.test")).status=="FAILED"
        assert row["signing_secret"] not in client.get(BASE+"/tenant/logs").text

def test_environment_store_read_only_and_non_arbitrary_references(monkeypatch):
    store=EnvironmentSecretStore()
    with pytest.raises(IntegrationError):store.get_secret_for_server_use("env://AWS_SECRET_ACCESS_KEY")
    with pytest.raises(IntegrationError):store.create_secret("env://SETU_SECRET_"+"A"*32,SECRET)
    monkeypatch.setenv("SETU_SECRET_"+"A"*32,SECRET)
    assert store.get_secret_for_server_use("env://SETU_SECRET_"+"A"*32)==SECRET

def test_additive_migration_preserves_existing_register_and_is_idempotent():
    from sqlalchemy import create_engine, inspect, text
    from app.migrate_integrations import apply
    target=create_engine("sqlite:///:memory:")
    IntegrationConnection.__table__.create(target)
    with target.begin() as conn:
        conn.execute(IntegrationConnection.__table__.insert().values(id="legacy",tenant_id="legacy-tenant",provider="Existing provider",category="Documents",status="AVAILABLE"))
    before=[col["name"] for col in inspect(target).get_columns("integration_connections")]
    assert apply(target)==apply(target)
    assert before==[col["name"] for col in inspect(target).get_columns("integration_connections")]
    with target.connect() as conn:
        assert conn.execute(text("SELECT provider FROM integration_connections WHERE id='legacy'")).scalar()=="Existing provider"
        assert conn.execute(text("SELECT COUNT(*) FROM integration_schema_versions")).scalar()==1

def test_provider_http_errors_and_smtp_allowlist_are_safe(monkeypatch):
    from app.integration_providers import SMTPAdapter, GoogleCalendarAdapter
    from app.integration_security import require_success
    with pytest.raises(IntegrationError) as error:require_success(401)
    assert error.value.code=="AUTHENTICATION_FAILED"
    with pytest.raises(IntegrationError) as error:require_success(429,300)
    assert error.value.code=="RATE_LIMITED" and error.value.retry_after==300
    monkeypatch.delenv("SMTP_HOST",raising=False)
    monkeypatch.setenv("INTEGRATION_SMTP_HOSTS","approved.example.org")
    with pytest.raises(IntegrationError):SMTPAdapter(CONFIG,SECRET)._client()
    calls=[]
    monkeypatch.setattr("app.integration_providers.safe_http",lambda *args,**kwargs:(calls.append((args,kwargs)) or (204,60)))
    calendar=GoogleCalendarAdapter({"calendar_id":"tenant@calendar.example"},SECRET)
    calendar.test_connection();calendar.create_event("abcdef123456",{"summary":"Meeting"});calendar.update_event("abcdef123456",{"summary":"Changed"});calendar.cancel_event("abcdef123456")
    assert len(calls)==4 and all(call[0][0].startswith("https://www.googleapis.com/calendar/v3/") for call in calls)

def test_failed_secret_store_write_never_activates_connection(store,monkeypatch):
    def fail(ref,value):raise IntegrationError("SECRET_STORE_UNAVAILABLE")
    store.update_secret=fail
    with client_for() as client:
        row=create(client)
        response=client.put(BASE+"/tenant/connections/"+row["id"]+"/credential",json={"secret":SECRET})
        assert response.status_code==503 and SECRET not in response.text
        assert client.post(BASE+"/tenant/connections/"+row["id"]+"/activate").status_code==409

def test_named_permissions_independent_of_admin_role(store,monkeypatch):
    from app.permissions import ROLE_PERMISSIONS
    monkeypatch.setitem(ROLE_PERMISSIONS,"ADMIN",{"integrations.tenant.view","integrations.platform.view"})
    with client_for() as client:
        assert client.get(BASE+"/tenant/connections").status_code==200
        assert client.get(BASE+"/tenant/health").status_code==403
        assert client.get(BASE+"/tenant/logs").status_code==403
        assert client.post(BASE+"/tenant/connections",json={"provider_key":"smtp","display_name":"X","configuration":CONFIG}).status_code==403
        assert client.get(BASE+"/platform/developer/api-keys").status_code==403

def test_managed_platform_policy_cannot_be_bypassed_by_legacy_smtp(store,monkeypatch):
    from app.integration_notifications import deliver_email
    monkeypatch.setenv("SMTP_HOST","legacy.example.org");monkeypatch.setenv("SMTP_FROM","legacy@example.org")
    with client_for() as client:
        row=create(client,"platform")
        credential(client,row["id"],"platform")
        path=BASE+"/platform/connections/"+row["id"]
        client.post(path+"/test");client.post(path+"/activate")
        with SessionLocal() as db:
            with pytest.raises(IntegrationError):deliver_email(db,"tenant-a","person@example.org","Test","Text")

def test_worker_reclaims_expired_lease_and_cancels_disabled_subscription(store,monkeypatch):
    monkeypatch.setattr("app.integration_worker.safe_http",lambda *args:(204,60))
    with client_for() as client:
        row=webhook(client,"OUTBOUND")
        with SessionLocal() as db:
            db.add(WebhookDelivery(tenant_id="tenant-a",subscription_id=row["id"],event_id="stale-lease",event_type="compliance.created",
                status="PROCESSING",attempt_count=1,next_attempt_at=now()-timedelta(seconds=1)))
            db.commit()
        assert process_batch()==1
        with SessionLocal() as db:
            item=db.scalar(select(WebhookDelivery))
            assert item.status=="SUCCESS" and item.attempt_count==2
        client.post("/api/v1/developer/webhooks/"+row["id"]+"/test")
        client.patch("/api/v1/developer/webhooks/"+row["id"],json={"enabled":False})
        process_batch()
        with SessionLocal() as db:
            assert db.scalar(select(WebhookDelivery).where(WebhookDelivery.event_type=="webhook.test")).status=="CANCELLED"

def test_legacy_catalog_cannot_claim_an_untested_live_connection(store):
    with client_for() as client:
        with SessionLocal() as db:
            db.add(IntegrationConnection(id="legacy-placeholder",tenant_id="tenant-a",provider="Legacy provider",category="Notifications"))
            db.commit()
        response=client.patch("/api/v1/integrations/legacy-placeholder",json={"status":"CONNECTED"})
        assert response.status_code==409
        assert client.patch("/api/v1/integrations/legacy-placeholder",json={"status":"PAUSED"}).status_code==200
        managed=create(client)
        assert managed["id"] not in {row["id"] for row in client.get("/api/v1/integrations").json()}

def test_health_summary_metrics_and_three_failure_alert(store,monkeypatch):
    def fail(self):raise IntegrationError("AUTHENTICATION_FAILED")
    monkeypatch.setattr("app.integration_providers.SMTPAdapter.test_connection",fail)
    with client_for() as client:
        row=create(client);credential(client,row["id"]);path=BASE+"/tenant/connections/"+row["id"]
        for attempt in range(3):
            with SessionLocal() as db:
                db.get(ConnectionSettings,row["id"]).blocked_until=None;db.commit()
            assert not client.post(path+"/test").json()["success"]
        response=client.get(BASE+"/tenant/health")
        assert response.status_code==200,response.text
        result=response.json()
        assert result["summary"]["OUTAGE"]==1
        assert result["metrics"][0]["status"]=="FAILED" and result["metrics"][0]["count"]==3
        notes=client.get("/api/v1/notifications").json()
        alerts=[item for item in notes if item.get("template_key")=="integration.providerAlert"]
        assert len(alerts)==1
