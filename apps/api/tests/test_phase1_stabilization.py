from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from app.auth import digest, now
from app.auth_models import AuthAccount, SessionContext
from app.compliance_states import is_open, counts_toward_completion
from app.database import SessionLocal
from app.main import app
from app.models import AuditEvent, AuthSession, Compliance, User
from test_compliance_master import create, platform_client, publish


def test_configured_cancellation_is_terminal_audited_and_requires_reason(monkeypatch):
    with platform_client(monkeypatch) as client:
        row = create(client)
        configuration = row["configuration"]
        configuration["workflow"]["stages"].insert(-1, {"id": "cancel", "state": "CANCELLED"})
        configuration["workflow"]["transitions"].append({"from_state": "NOT_STARTED", "to_state": "CANCELLED", "allowed_roles": ["TENANT_ADMIN"]})
        row = client.patch(f"/api/v1/admin/compliance-templates/{row['id']}", json={"expected_revision": 0, "configuration": configuration, "change_summary": "Allow controlled cancellation"}).json()
        publish(client, row)
        instance = next(c for c in client.post("/api/v1/organizations/org-udaan/generate-plan").json() if c["code"] == row["code"])
        path = f"/api/v1/compliances/{instance['id']}/transitions"
        assert client.post(path, json={"target_status": "CANCELLED"}).status_code == 422
        assert client.post(path, json={"target_status": "CANCELLED", "reason": "Work cancelled with authority"}).json()["status"] == "CANCELLED"
        assert client.get(f"/api/v1/compliances/{instance['id']}/template-snapshot").json()["available_transitions"] == []
        assert client.post(path, json={"target_status": "IN_PROGRESS", "reason": "Try unsupported reopening"}).status_code == 409
        with SessionLocal() as db:
            event = db.scalar(select(AuditEvent).where(AuditEvent.entity_id == instance["id"], AuditEvent.action == "STATUS_CHANGED"))
            assert "CANCELLED" in event.summary


def test_closed_states_do_not_count_as_active_risk_or_overdue(monkeypatch):
    assert all(not is_open(s) for s in ("COMPLETED", "CANCELLED", "NOT_APPLICABLE"))
    assert counts_toward_completion("COMPLETED") and not counts_toward_completion("CANCELLED")
    with platform_client(monkeypatch) as client:
        with SessionLocal() as db:
            for status in ("COMPLETED", "CANCELLED", "NOT_APPLICABLE"):
                db.add(Compliance(tenant_id="tenant-demo", organization_id="org-udaan", code=status, title=status, category="Test", period="Test", statutory_deadline=date.today()-timedelta(days=20), status=status, priority="CRITICAL", owner_name="Test owner", owner_initials="TO", progress=100))
            db.commit()
        summary = client.get("/api/v1/dashboard").json()["summary"]
        assert summary["cancelled"] == 1 and summary["not_applicable"] == 1
        with SessionLocal() as db:
            rows = db.scalars(select(Compliance)).all()
            assert summary["open"] == sum(is_open(c.status) for c in rows)
            assert summary["high_risk"] == sum(is_open(c.status) and c.priority in {"HIGH", "CRITICAL"} for c in rows)


def test_allowlisted_legacy_account_or_session_cannot_enter_platform(monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_EMAILS", "legacy@example.test")
    with TestClient(app) as client:
        with SessionLocal() as db:
            user = User(tenant_id="tenant-demo", name="Legacy", email="legacy@example.test", role="ADMIN")
            db.add(user); db.flush()
            db.add(AuthSession(token_hash=digest("legacy-session"), user_id=user.id, expires_at=now()+timedelta(hours=1)))
            db.commit(); identity = user.id
        client.cookies.set("setu_session", "legacy-session")
        assert client.get("/api/v1/admin/auth/access").json()["allowed"] is False
        with SessionLocal() as db:
            db.add(AuthAccount(user_id=identity, verified=True, platform_access=True)); db.commit()
        assert client.get("/api/v1/admin/auth/access").json()["allowed"] is False
        with SessionLocal() as db:
            db.add(SessionContext(token_hash=digest("legacy-session"), tenant_id="tenant-demo", audience="user")); db.commit()
        assert client.get("/api/v1/admin/auth/access").json()["allowed"] is False
        assert client.get("/api/v1/admin/compliance-templates").status_code == 403
