"""Focused production communication, callback, retry and isolation contracts."""
import hashlib
import hmac
import json
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.auth import now
from app.automation_models import ScheduledJob
from app.automation_service import claim_job, execute_job, fail_job
from app.database import SessionLocal, engine
from app.integration_models import ConnectionSettings
from app.integration_providers import SMTPAdapter, WhatsAppAdapter
from app.integration_security import IntegrationError
from app.migrate_phase24 import VERSION, apply
from app.models import AuditEvent, IntegrationConnection, Notification, User
from app.notification_models import NotificationDelivery, UserNotificationPreference
from app.notification_service import distribute_notification
from test_integrations import BASE, MemorySecretStore, client_for


@pytest.fixture
def communication_store(monkeypatch):
    store = MemorySecretStore()
    for module in ("integration_api", "integration_service", "communication_api"):
        monkeypatch.setattr("app." + module + ".secret_store", lambda: store)
    monkeypatch.setenv("PLATFORM_ADMIN_EMAILS", "admin@tenant-a.test")
    return store


def _whatsapp_connection(client, store):
    response = client.post(BASE + "/tenant/connections", json={
        "provider_key": "meta_whatsapp", "display_name": "Transactional WhatsApp",
        "environment": "PRODUCTION", "configuration": {
            "phone_number_id": "123456789", "business_account_id": "987654321",
            "api_version": "v23.0", "default_language": "en_US",
            "template_namespace": "", "allow_freeform_text": False, "timeout_seconds": 15,
        },
    })
    assert response.status_code == 201, response.text
    row = response.json()
    secret = json.dumps({"access_token": "wa-token-must-not-leak", "app_secret": "callback-secret",
                         "verify_token": "verify-me"})
    assert client.put(BASE + f"/tenant/connections/{row['id']}/credential", json={"secret": secret}).status_code == 200
    with SessionLocal() as db:
        connection = db.get(IntegrationConnection, row["id"])
        state = db.get(ConnectionSettings, row["id"])
        connection.status = "CONNECTED"
        state.last_success_at = now()
        db.commit()
    return row, secret


def test_smtp_requires_secure_transport_and_maps_safe_failures(monkeypatch):
    with client_for("tenant-mail") as client:
        response = client.post(BASE + "/tenant/connections", json={
            "provider_key": "smtp", "display_name": "Unsafe SMTP", "environment": "PRODUCTION",
            "configuration": {"host": "mail.example.org", "port": 25, "security": "PLAIN",
                              "username": "mailer", "from_address": "notify@example.org"},
        })
        assert response.status_code == 422 and "password" not in response.text.lower()

    monkeypatch.setenv("INTEGRATION_SMTP_HOSTS", "mail.example.org")
    monkeypatch.setattr("app.integration_providers.smtplib.SMTP_SSL",
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError("smtp-secret")))
    adapter = SMTPAdapter({"host": "mail.example.org", "port": 465, "security": "SSL",
                           "timeout_seconds": 5, "username": "mailer", "from_address": "notify@example.org"},
                          "smtp-secret")
    with pytest.raises(IntegrationError) as error:
        adapter.test_connection()
    assert error.value.code == "TIMEOUT" and "smtp-secret" not in str(error.value)


def test_whatsapp_structured_template_recipient_and_provider_id(monkeypatch):
    calls = []
    monkeypatch.setattr("app.integration_security.safe_json_http", lambda url, **values:
                        (calls.append((url, values)) or (200, 60, {"messages": [{"id": "wamid.safe-1"}]})))
    adapter = WhatsAppAdapter({"phone_number_id": "123", "api_version": "v23.0",
        "default_language": "en_US", "allow_freeform_text": False, "timeout_seconds": 10},
        json.dumps({"access_token": "wa-token-must-not-leak", "app_secret": "secret"}))
    assert adapter.send_template("+91 99999-99999", "deadline_notice", components=[]) == "wamid.safe-1"
    assert calls[0][1]["body"]["to"] == "919999999999"
    with pytest.raises(IntegrationError) as malformed:
        adapter.send_template("not-a-number", "deadline_notice")
    assert malformed.value.code == "INVALID_RECIPIENT"
    with pytest.raises(IntegrationError) as unauthorized:
        adapter.send_message("919999999999", "free form")
    assert unauthorized.value.code == "INVALID_TEMPLATE"
    assert "wa-token-must-not-leak" not in "wamid.safe-1"


def test_preferences_are_rechecked_and_manual_retry_is_scoped_and_audited(monkeypatch):
    tenant_id = "tenant-operations"
    monkeypatch.setattr("app.notification_service.deliver_email",
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(IntegrationError("INVALID_RECIPIENT")))
    with client_for(tenant_id) as client:
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.tenant_id == tenant_id))
            notice = Notification(tenant_id=tenant_id, title="Task overdue", message="Review task", kind="WARNING")
            db.add(notice); db.flush()
            distribute_notification(db, notice, event_type="task.overdue", category="TASK",
                                    user_ids=(user.id,), channels=("EMAIL",))
            db.commit()
            job = claim_job(db, "communication-worker", at=now())
            with pytest.raises(IntegrationError) as caught:
                execute_job(db, job)
            db.rollback(); job = db.get(ScheduledJob, job.id); fail_job(db, job, caught.value); db.commit()
            delivery = db.scalar(select(NotificationDelivery).where(NotificationDelivery.channel == "EMAIL"))
            assert delivery.status == "FAILED"
            delivery_id = delivery.id
        retried = client.post(f"/api/v1/admin/notification-deliveries/{delivery_id}/retry")
        assert retried.status_code == 202 and retried.json()["status"] == "QUEUED"
        with SessionLocal() as db:
            audit = db.scalar(select(AuditEvent).where(AuditEvent.action == "NOTIFICATION_DELIVERY_RETRIED"))
            assert audit and "@" not in audit.summary
            preference = db.scalar(select(UserNotificationPreference).where(UserNotificationPreference.tenant_id == tenant_id))
            preference.email_enabled = False
            job = claim_job(db, "communication-worker", at=now() + timedelta(seconds=1))
            result = execute_job(db, job)
            assert result["status"] == "CANCELLED"
    with client_for("tenant-b") as outsider:
        assert outsider.post(f"/api/v1/admin/notification-deliveries/{delivery_id}/retry").status_code == 404


def test_whatsapp_callback_signature_tenant_binding_and_idempotency(communication_store):
    tenant_id = "tenant-callback"
    with client_for(tenant_id) as client:
        connection, raw_secret = _whatsapp_connection(client, communication_store)
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.tenant_id == tenant_id))
            notice = Notification(tenant_id=tenant_id, title="Deadline", message="Due", kind="REMINDER")
            db.add(notice); db.flush()
            delivery = NotificationDelivery(tenant_id=tenant_id, notification_id=notice.id, user_id=user.id,
                channel="WHATSAPP", recipient_address="919999999999", locale="en-IN", frozen_subject="Deadline",
                frozen_text="Due", status="SENT", provider_key="meta_whatsapp",
                provider_connection_id=connection["id"], provider_message_id="wamid.bound")
            db.add(delivery); db.commit(); delivery_id = delivery.id
        payload = {"tenant_id": "tenant-b", "entry": [{"changes": [{"value": {"statuses": [
            {"id": "wamid.bound", "status": "delivered", "timestamp": "1790812800"}
        ]}}]}]}
        body = json.dumps(payload, separators=(",", ":")).encode()
        signature = "sha256=" + hmac.new("callback-secret".encode(), body, hashlib.sha256).hexdigest()
        path = f"/api/v1/integration-callbacks/whatsapp/{connection['id']}"
        assert client.get(path, params={"hub.mode": "subscribe", "hub.verify_token": "wrong",
                                       "hub.challenge": "73"}).status_code == 403
        verification = client.get(path, params={"hub.mode": "subscribe", "hub.verify_token": "verify-me",
                                                "hub.challenge": "73"})
        assert verification.status_code == 200 and verification.json() == 73
        assert client.post(path, content=body, headers={"X-Hub-Signature-256": "sha256=bad"}).status_code == 401
        first = client.post(path, content=body, headers={"X-Hub-Signature-256": signature})
        assert first.json() == {"accepted": True, "updated": 1}
        assert client.post(path, content=body, headers={"X-Hub-Signature-256": signature}).json()["updated"] == 0
        assert raw_secret not in first.text
        with SessionLocal() as db:
            saved = db.get(NotificationDelivery, delivery_id)
            assert saved.tenant_id == tenant_id and saved.status == "DELIVERED" and saved.delivered_at


def test_phase24_migration_is_idempotent():
    assert apply(engine) == VERSION
    assert apply(engine) == VERSION
