from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.auth import digest
from app.database import SessionLocal
from app.models import AuthSession, Compliance, ComplianceReminder, Organization, User
from test_compliance_master import config, create, platform_client, publish


def test_real_other_tenant_cannot_read_snapshot_or_organization_facts(monkeypatch):
    with platform_client(monkeypatch) as client:
        row = publish(client, create(client))
        generated = client.post("/api/v1/organizations/org-udaan/generate-plan").json()
        instance = next(item for item in generated if item["code"] == row["code"])
        with SessionLocal() as db:
            user = User(name="Other tenant", email="other-tenant@example.test", tenant_id="other-tenant", role="ADMIN")
            db.add(user)
            db.flush()
            db.add(AuthSession(token_hash=digest("other-master-test"), user_id=user.id, expires_at=datetime.now(timezone.utc) + timedelta(hours=1)))
            db.commit()
        client.cookies.set("setu_session", "other-master-test")
        assert client.get(f"/api/v1/compliances/{instance['id']}/template-snapshot").status_code == 404
        assert client.get("/api/v1/organizations/org-udaan/compliance-profile").status_code == 404
        assert client.post("/api/v1/organizations/org-udaan/generate-plan").status_code == 404
        assert client.patch(f"/api/v1/compliances/{instance['id']}", json={"status": "IN_PROGRESS"}).status_code == 404
        assert client.get(f"/api/v1/admin/compliance-templates/{row['id']}/versions").status_code == 403
        # Global published configuration is deliberately shared; history and tenant instances are not.
        assert client.get("/api/v1/compliance-templates").json()[0]["code"] == row["code"]


def test_event_generation_missing_fact_then_explicit_event_and_idempotency(monkeypatch):
    with platform_client(monkeypatch) as client:
        row = create(client, "SAMPLE-EVENT")
        row["configuration"]["recurrence"]["frequency"] = "EVENT_BASED"
        row["configuration"]["deadline"].update(strategy="EVENT_DATE_PLUS_DAYS", fixed_date=None, offset_days=10)
        saved = client.patch(f"/api/v1/admin/compliance-templates/{row['id']}", json={"expected_revision": 0, "configuration": row["configuration"], "change_summary": "Sample event-driven policy"}).json()
        publish(client, saved)
        assert not any(item["code"] == "SAMPLE-EVENT" for item in client.post("/api/v1/organizations/org-udaan/generate-plan").json())
        generated = client.post("/api/v1/organizations/org-udaan/generate-plan", json={"event_date": "2026-09-17"}).json()
        event = next(item for item in generated if item["code"] == "SAMPLE-EVENT")
        assert event["statutory_deadline"] == "2026-09-27"
        assert not any(item["code"] == "SAMPLE-EVENT" for item in client.post("/api/v1/organizations/org-udaan/generate-plan", json={"event_date": "2026-09-17"}).json())


def test_reminders_freeze_locale_variables_and_role_transition_enforcement(monkeypatch):
    with platform_client(monkeypatch) as client:
        row = publish(client, create(client))
        generated = client.post("/api/v1/organizations/org-udaan/generate-plan").json()
        instance = next(item for item in generated if item["code"] == row["code"])
        with SessionLocal() as db:
            reminder = db.scalar(select(ComplianceReminder).where(ComplianceReminder.compliance_id == instance["id"]))
            reminder.scheduled_for = date.today()
            db.commit()
        assert client.post("/api/v1/automation/run").json()["template_reminders"] == 1
        notification = next(item for item in client.get("/api/v1/notifications").json() if item["template_key"] == "compliance.deadlineReminder")
        assert notification["template_variables"]["names"]["kn-IN"] == row["configuration"]["translations"]["kn-IN"]["name"]
        assert notification["template_variables"]["templateVersionId"] == instance["template_version_id"]
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.email == "master@example.test"))
            user.role = "MEMBER"
            db.commit()
        assert client.get(f"/api/v1/compliances/{instance['id']}/template-snapshot").json()["available_transitions"] == []
        assert client.post(f"/api/v1/compliances/{instance['id']}/transitions", json={"target_status": "IN_PROGRESS"}).status_code == 403


def test_unsafe_identifier_and_unsupported_channel_are_rejected(monkeypatch):
    with platform_client(monkeypatch) as client:
        row = create(client)
        for patch in ({"reminders": [{"id": "unsafe", "channel": "EMAIL"}]}, {"checklist": [{"id": "__proto__", "title": "Unsafe identifier"}]}):
            response = client.patch(f"/api/v1/admin/compliance-templates/{row['id']}", json={"expected_revision": 0, "configuration": {**row["configuration"], **patch}, "change_summary": "Invalid sample configuration"})
            assert response.status_code == 422
