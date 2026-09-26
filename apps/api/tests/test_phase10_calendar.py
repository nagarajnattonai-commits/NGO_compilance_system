"""Phase 10 Google Calendar contracts use controlled adapters, never live credentials."""
import json
import time
from datetime import date, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import func, select

from app.auth import digest, now
from app.auth_models import SessionContext
from app.automation_models import ScheduledJob
from app.automation_worker import process_batch, process_one
from app.calendar_service import queue_entity_sync
from app.database import SessionLocal, engine
from app.integration_models import ConnectionSettings, IntegrationOperation
from app.integration_security import IntegrationError
from app.migrate_phase10 import VERSION, apply
from app.models import AuthSession, Compliance, Organization, Task, User
from app.phase10_models import CalendarEventMapping, CalendarOAuthState, CalendarSyncPolicy
from app.phase8_models import OrganizationAccess
from test_integrations import client_for

ACCESS_TOKEN = "calendar-access-token-must-stay-server-side"
REFRESH_TOKEN = "calendar-refresh-token-must-stay-server-side"
BASE = "/api/v1/integrations-management/tenant/connections"


class MemorySecretStore:
    writable = True

    def __init__(self):
        self.values = {"test://calendar-client": "oauth-client-secret"}

    def reference(self, tenant_id, resource_id):
        return f"test://{tenant_id}/{resource_id}"

    def get_secret_for_server_use(self, reference):
        if reference not in self.values:
            raise IntegrationError("INTEGRATION_NOT_CONFIGURED")
        return self.values[reference]

    def update_secret(self, reference, value):
        self.values[reference] = value

    create_secret = update_secret

    def delete_secret(self, reference):
        self.values.pop(reference, None)


class FakeOAuth:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def close(self):
        pass

    def create_authorization_url(self, url, **values):
        return url + "?state=" + values["state"], values["state"]

    def fetch_token(self, *_args, **_kwargs):
        return {"access_token": ACCESS_TOKEN, "refresh_token": REFRESH_TOKEN,
                "expires_at": time.time() + 3600, "token_type": "Bearer"}

    def refresh_token(self, *_args, **_kwargs):
        return {"access_token": ACCESS_TOKEN + "-refreshed", "refresh_token": REFRESH_TOKEN,
                "expires_at": time.time() + 3600, "token_type": "Bearer"}


@pytest.fixture
def calendar_store(monkeypatch):
    store = MemorySecretStore()
    for module in ("integration_api", "integration_service", "calendar_service", "phase10_api"):
        monkeypatch.setattr("app." + module + ".secret_store", lambda: store)
    monkeypatch.setattr("app.phase10_api.oauth_client", lambda **_kwargs: FakeOAuth())
    monkeypatch.setattr("app.calendar_service.oauth_client", lambda **_kwargs: FakeOAuth())
    monkeypatch.setattr("app.integration_providers.GoogleCalendarAdapter.test_connection", lambda self: None)
    monkeypatch.setattr("app.phase10_api.safe_http", lambda *_args, **_kwargs: (200, 60))
    monkeypatch.setenv("GOOGLE_CALENDAR_CLIENT_ID", "calendar-client-id")
    monkeypatch.setenv("GOOGLE_CALENDAR_CLIENT_SECRET_REF", "test://calendar-client")
    monkeypatch.setenv("PLATFORM_ADMIN_EMAILS", "admin@tenant-a.test")
    return store


def connect(client, store, calendar_id="primary"):
    created = client.post(BASE, json={
        "provider_key": "google_calendar", "display_name": "Compliance calendar",
        "environment": "PRODUCTION", "configuration": {"calendar_id": calendar_id},
    })
    assert created.status_code == 201, created.text
    connection = created.json()
    started = client.post(f"/api/v1/calendar/connections/{connection['id']}/oauth/start")
    assert started.status_code == 200, started.text
    state = parse_qs(urlparse(started.json()["authorization_url"]).query)["state"][0]
    callback = client.get(f"/api/v1/calendar/google/callback?state={state}&code=controlled-code", follow_redirects=False)
    assert callback.status_code == 303 and "calendar=connected" in callback.headers["location"]
    tested = client.post(f"/api/v1/calendar/connections/{connection['id']}/test")
    assert tested.status_code == 200 and tested.json()["success"]
    activated = client.post(f"{BASE}/{connection['id']}/activate")
    assert activated.status_code == 200 and activated.json()["status"] == "CONNECTED"
    with SessionLocal() as db:
        settings = db.get(ConnectionSettings, connection["id"])
        assert settings.credential_reference in store.values
        token = json.loads(store.values[settings.credential_reference])
        assert token["access_token"] == ACCESS_TOKEN and token["refresh_token"] == REFRESH_TOKEN
    return connection


def create_entities(client):
    organization = client.post("/api/v1/organizations", json={
        "name": "Calendar Test Foundation", "legal_type": "TRUST", "registration_number": "CAL-2026",
        "city": "Pune", "generate_compliance_plan": False,
    })
    assert organization.status_code == 201, organization.text
    organization_id = organization.json()["organization"]["id"]
    compliance = client.post("/api/v1/compliances", json={
        "organization_id": organization_id, "code": "CAL-01", "title": "Annual calendar compliance",
        "category": "Governance", "period": "2026-27", "statutory_deadline": "2027-03-31",
        "internal_target": "2027-03-15", "priority": "HIGH", "owner_name": "Calendar owner",
    })
    assert compliance.status_code == 201, compliance.text
    task = client.post("/api/v1/tasks", json={
        "organization_id": organization_id, "compliance_id": compliance.json()["id"],
        "title": "Prepare calendar filing", "due_at": "2027-03-10", "priority": "HIGH",
        "assignee_name": "Calendar owner",
    })
    assert task.status_code == 201, task.text
    return organization_id, compliance.json(), task.json()


def test_oauth_state_callback_credential_status_and_disconnect(calendar_store):
    with client_for() as client:
        created = client.post(BASE, json={
            "provider_key": "google_calendar", "display_name": "Compliance calendar",
            "environment": "PRODUCTION", "configuration": {"calendar_id": "primary"},
        }).json()
        forged = client.get("/api/v1/calendar/google/callback?state=forged&code=x", follow_redirects=False)
        assert forged.status_code == 400, forged.text
        started = client.post(f"/api/v1/calendar/connections/{created['id']}/oauth/start")
        state = parse_qs(urlparse(started.json()["authorization_url"]).query)["state"][0]
        assert client.get(f"/api/v1/calendar/google/callback?state={state}&code=ok", follow_redirects=False).status_code == 303
        assert client.get(f"/api/v1/calendar/google/callback?state={state}&code=replay", follow_redirects=False).status_code == 400
        status = client.get("/api/v1/calendar/status")
        assert status.status_code == 200 and status.json()["connections"][0]["oauth_connected"]
        with SessionLocal() as db:
            settings = db.get(ConnectionSettings, created["id"])
            stored = json.loads(calendar_store.values[settings.credential_reference])
            stored["expires_at"] = time.time() - 1
            calendar_store.values[settings.credential_reference] = json.dumps(stored)
        refreshed = client.post(f"/api/v1/calendar/connections/{created['id']}/test")
        assert refreshed.status_code == 200 and refreshed.json()["success"]
        with SessionLocal() as db:
            settings = db.get(ConnectionSettings, created["id"])
            assert json.loads(calendar_store.values[settings.credential_reference])["access_token"].endswith("-refreshed")
            assert db.get(CalendarSyncPolicy, created["id"])
        for secret in (ACCESS_TOKEN, REFRESH_TOKEN):
            assert secret not in status.text and secret not in client.get("/api/v1/integrations-management/tenant/logs").text
        disconnected = client.post(f"/api/v1/calendar/connections/{created['id']}/disconnect")
        assert disconnected.status_code == 200 and not disconnected.json()["oauth_connected"]
        with SessionLocal() as db:
            settings = db.get(ConnectionSettings, created["id"])
            assert settings.credential_reference not in calendar_store.values
            assert db.get(CalendarOAuthState, digest(state)).used_at


def test_event_create_update_and_duplicate_prevention(calendar_store, monkeypatch):
    calls = []
    monkeypatch.setattr("app.integration_providers.GoogleCalendarAdapter.create_event",
                        lambda self, event_id, payload: calls.append(("create", event_id, payload)))
    monkeypatch.setattr("app.integration_providers.GoogleCalendarAdapter.update_event",
                        lambda self, event_id, payload: calls.append(("update", event_id, payload)))
    monkeypatch.setattr("app.integration_providers.GoogleCalendarAdapter.cancel_event",
                        lambda self, event_id: calls.append(("cancel", event_id, {})))
    with client_for() as client:
        connection = connect(client, calendar_store)
        organization_id, compliance, task = create_entities(client)
        assert process_batch(20, "calendar-worker") == 3
        assert [call[0] for call in calls].count("create") == 3
        compliance_payload = next(call[2] for call in calls if call[2]["summary"].startswith("Annual calendar"))
        assert "Calendar Test Foundation" in compliance_payload["summary"]
        assert "/compliances/" in compliance_payload["description"]
        assert "document" not in json.dumps(compliance_payload).lower()
        with SessionLocal() as db:
            saved = db.get(Compliance, compliance["id"])
            assert queue_entity_sync(db, saved) == 0
            db.commit()
            assert db.scalar(select(func.count()).select_from(CalendarEventMapping)) == 3
        assert process_batch(20, "calendar-worker") == 0

        changed = client.patch(f"/api/v1/compliances/{compliance['id']}", json={"internal_target": "2027-03-14"})
        assert changed.status_code == 200, changed.text
        changed_task = client.patch(f"/api/v1/tasks/{task['id']}", json={"due_at": "2027-03-09"})
        assert changed_task.status_code == 200, changed_task.text
        assert process_batch(20, "calendar-worker") == 3
        assert [call[0] for call in calls].count("update") == 3
        assert len({call[1] for call in calls}) == 3
        policy = client.patch(f"/api/v1/calendar/connections/{connection['id']}/policy", json={
            "calendar_id": "primary", "sync_statutory_deadlines": True,
            "sync_internal_targets": False, "sync_tasks": True, "closed_behavior": "UPDATE",
        })
        assert policy.status_code == 200 and policy.json()["queued"] >= 1
        assert process_batch(20, "calendar-worker") >= 1


def test_completed_cancelled_and_not_applicable_follow_cancel_policy(calendar_store, monkeypatch):
    calls = []
    monkeypatch.setattr("app.integration_providers.GoogleCalendarAdapter.create_event",
                        lambda self, event_id, payload: calls.append(("create", event_id)))
    monkeypatch.setattr("app.integration_providers.GoogleCalendarAdapter.update_event",
                        lambda self, event_id, payload: calls.append(("update", event_id)))
    monkeypatch.setattr("app.integration_providers.GoogleCalendarAdapter.cancel_event",
                        lambda self, event_id: calls.append(("cancel", event_id)))
    with client_for() as client:
        connection = connect(client, calendar_store)
        policy = client.patch(f"/api/v1/calendar/connections/{connection['id']}/policy", json={
            "calendar_id": "primary", "sync_statutory_deadlines": True,
            "sync_internal_targets": False, "sync_tasks": False, "closed_behavior": "CANCEL",
        })
        assert policy.status_code == 200
        organization_id, first, _ = create_entities(client)
        identifiers = [first["id"]]
        for index in range(2):
            response = client.post("/api/v1/compliances", json={
                "organization_id": organization_id, "code": f"CLOSE-{index}", "title": f"Closed state {index}",
                "category": "Governance", "period": "2026-27", "statutory_deadline": "2027-04-30",
                "priority": "MEDIUM", "owner_name": "Calendar owner",
            })
            identifiers.append(response.json()["id"])
        assert process_batch(20, "calendar-worker") == 3
        with SessionLocal() as db:
            for identifier, status in zip(identifiers, ("COMPLETED", "CANCELLED", "NOT_APPLICABLE")):
                item = db.get(Compliance, identifier)
                item.status = status
                item.updated_at = now()
                queue_entity_sync(db, item)
            db.commit()
        assert process_batch(20, "calendar-worker") == 3
        assert [call[0] for call in calls].count("cancel") == 3
        with SessionLocal() as db:
            assert {row.sync_status for row in db.scalars(select(CalendarEventMapping)).all()} >= {"CANCELLED"}


def test_provider_failures_retry_without_failing_business_mutations(calendar_store, monkeypatch):
    failures = [IntegrationError("PROVIDER_UNAVAILABLE")]

    def create_event(self, event_id, payload):
        if failures:
            raise failures.pop(0)

    monkeypatch.setattr("app.integration_providers.GoogleCalendarAdapter.create_event", create_event)
    monkeypatch.setattr("app.integration_providers.GoogleCalendarAdapter.update_event", lambda *_args: None)
    with client_for() as client:
        connection = connect(client, calendar_store)
        assert client.patch(f"/api/v1/calendar/connections/{connection['id']}/policy", json={
            "calendar_id": "primary", "sync_statutory_deadlines": True,
            "sync_internal_targets": False, "sync_tasks": True, "closed_behavior": "UPDATE",
        }).status_code == 200
        _, compliance, task = create_entities(client)
        assert process_one("failure-worker")
        with SessionLocal() as db:
            job = db.scalar(select(ScheduledJob).where(ScheduledJob.entity_id == compliance["id"]))
            mapping = db.scalar(select(CalendarEventMapping).where(CalendarEventMapping.entity_id == compliance["id"]))
            assert job.status == "RETRY" and mapping.sync_status == "RETRY"
            job.next_attempt_at = now()
            db.commit()
        assert process_one("failure-worker")
        with SessionLocal() as db:
            assert db.scalar(select(CalendarEventMapping).where(CalendarEventMapping.entity_id == compliance["id"])).sync_status == "SYNCED"

        monkeypatch.setattr("app.integration_providers.GoogleCalendarAdapter.create_event",
                            lambda *_args: (_ for _ in ()).throw(IntegrationError("AUTHENTICATION_FAILED")))
        changed = client.patch(f"/api/v1/tasks/{task['id']}", json={"due_at": "2027-03-08"})
        assert changed.status_code == 200  # provider work remains outside the business transaction
        assert process_one("failure-worker")
        with SessionLocal() as db:
            failed = db.scalar(select(ScheduledJob).where(
                ScheduledJob.entity_id == task["id"], ScheduledJob.status == "FAILED"
            ).order_by(ScheduledJob.created_at.desc()))
            mapping = db.scalar(select(CalendarEventMapping).where(CalendarEventMapping.entity_id == task["id"]))
            assert failed and mapping.sync_status == "FAILED" and mapping.error_code == "AUTHENTICATION_FAILED"
            assert all(ACCESS_TOKEN not in (row.error_code or "") for row in db.scalars(select(IntegrationOperation)))


def test_calendar_tenant_and_organization_isolation_and_migration(calendar_store, monkeypatch):
    with client_for() as client:
        connection = connect(client, calendar_store)
        organization_id, compliance, _ = create_entities(client)
        assert process_batch(20, "calendar-worker") == 3
        with SessionLocal() as db:
            mapping = db.scalar(select(CalendarEventMapping).where(CalendarEventMapping.entity_id == compliance["id"]))
            mapping_id = mapping.id
            admin = db.scalar(select(User).where(User.email == "admin@tenant-a.test"))
            other_org = Organization(tenant_id="tenant-a", name="Other organization", legal_type="TRUST",
                                     registration_number="OTHER-ORG", city="Pune")
            db.add(other_org)
            restricted = User(tenant_id="tenant-a", name="Restricted calendar user",
                              email="restricted.calendar@tenant-a.test", role="MEMBER")
            db.add(restricted)
            db.flush()
            db.add(OrganizationAccess(tenant_id="tenant-a", organization_id=other_org.id,
                                      user_id=restricted.id, access_role="CONTRIBUTOR", granted_by=admin.id))
            db.add(AuthSession(token_hash=digest("calendar-restricted"), user_id=restricted.id,
                               expires_at=now() + timedelta(hours=1)))
            db.add(SessionContext(token_hash=digest("calendar-restricted"), tenant_id="tenant-a", audience="user"))
            db.commit()
        client.cookies.set("setu_session", "calendar-restricted")
        assert client.post(f"/api/v1/calendar/connections/{connection['id']}/disconnect").status_code == 403
        assert client.patch(f"/api/v1/calendar/connections/{connection['id']}/policy", json={
            "calendar_id": "primary", "sync_statutory_deadlines": True,
            "sync_internal_targets": True, "sync_tasks": True, "closed_behavior": "UPDATE",
        }).status_code == 403
        monkeypatch.setattr("app.phase10_api.has_permission", lambda *_args: True)
        assert client.post(f"/api/v1/calendar/mappings/{mapping_id}/retry").status_code == 403
        assert client.post("/api/v1/calendar/mappings/00000000-0000-0000-0000-000000000000/retry").status_code == 404
        visible = client.get("/api/v1/calendar/status").json()["connections"][0]["mappings"]
        assert visible == []

    with client_for("tenant-b") as other:
        assert other.post(f"/api/v1/calendar/mappings/{mapping_id}/retry").status_code == 404
        assert other.post(f"/api/v1/calendar/connections/{connection['id']}/disconnect").status_code == 404
    assert apply(engine) == VERSION
    assert apply(engine) == VERSION
