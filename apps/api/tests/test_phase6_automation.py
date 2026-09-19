"""Phase 6 scheduler, lease, recovery, scan, isolation and operations contracts."""
from datetime import date, timedelta
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import digest, now
from app.auth_models import AuthAccount, SessionContext
from app.automation_models import ScheduledJob
from app.automation_service import (
    claim_job,
    execute_job,
    fail_job,
    finish_job,
    queue_job,
    retry_job,
    schedule_scans,
)
from app.database import SessionLocal, engine
from app.main import app
from app.migrate_automation import VERSION, apply
from app.models import (
    AuthSession,
    Compliance,
    ComplianceReminder,
    ComplianceSnapshot,
    Document,
    Notification,
    Organization,
    Task,
    User,
    Workspace,
)
from test_compliance_master import config


def tenant(db, identifier="tenant-a"):
    db.add(Workspace(id=identifier, name=identifier))
    db.add(Organization(id="org-" + identifier[-1], tenant_id=identifier, name=identifier + " NGO", legal_type="TRUST", registration_number="REG-" + identifier))
    db.flush()


def job(db, tenant_id="tenant-a", job_type="TASK_OVERDUE_SCAN", key="one"):
    row, duplicate = queue_job(db, tenant_id, job_type, key)
    assert not duplicate
    db.commit()
    return row


def test_schedule_is_idempotent_and_tenant_scoped():
    with SessionLocal() as db:
        tenant(db, "tenant-a")
        tenant(db, "tenant-b")
        db.commit()
        first = schedule_scans(db, now())
        second = schedule_scans(db, now())
        assert first == {"created": 12, "replayed": 0, "tenants": 2}
        assert second == {"created": 0, "replayed": 12, "tenants": 2}
        assert len(db.scalars(select(ScheduledJob).where(ScheduledJob.tenant_id == "tenant-a")).all()) == 6
        assert len(db.scalars(select(ScheduledJob).where(ScheduledJob.tenant_id == "tenant-b")).all()) == 6


def test_claim_lease_expiration_and_worker_restart_recovery():
    with SessionLocal() as db:
        tenant(db)
        row = job(db)
        first = claim_job(db, "worker-one", at=now(), lease_seconds=60)
        assert first.id == row.id and first.attempt_count == 1
        assert claim_job(db, "worker-two", at=now()) is None
        recovered = claim_job(db, "worker-two", at=now() + timedelta(seconds=61))
        assert recovered.id == row.id and recovered.lease_owner == "worker-two" and recovered.attempt_count == 2
        finish_job(db, recovered, {"events": 0})
        db.commit()
        assert db.get(ScheduledJob, row.id).status == "SUCCEEDED"


def test_retry_dead_letter_and_authorized_reset_state():
    with SessionLocal() as db:
        tenant(db)
        row = job(db)
        for attempt in range(1, 6):
            claimed = claim_job(db, "worker", at=now() + timedelta(hours=attempt))
            assert claimed and claimed.attempt_count == attempt
            fail_job(db, claimed, TimeoutError())
            db.commit()
            if attempt < 5:
                claimed.next_attempt_at = now() - timedelta(seconds=1)
                db.commit()
        assert row.status == "DEAD_LETTER" and row.last_error_code == "JOB_RETRY_EXHAUSTED"
        retry_job(db, row)
        db.commit()
        assert row.status == "PENDING" and row.attempt_count == 0 and not row.last_error_code


def test_overdue_scans_preserve_closed_compliance_and_completed_tasks():
    with SessionLocal() as db:
        tenant(db)
        past = date.today() - timedelta(days=2)
        for identifier, status in (("open", "IN_PROGRESS"), ("complete", "COMPLETED"), ("cancel", "CANCELLED"), ("na", "NOT_APPLICABLE")):
            db.add(Compliance(id=identifier, tenant_id="tenant-a", organization_id="org-a", code=identifier, title=identifier,
                category="TEST", period="2026", statutory_deadline=past, status=status, priority="MEDIUM", owner_name="Owner"))
        db.add(Task(id="task-open", tenant_id="tenant-a", organization_id="org-a", title="Open task", due_at=past, status="TODO", priority="HIGH", assignee_name="Owner"))
        db.add(Task(id="task-done", tenant_id="tenant-a", organization_id="org-a", title="Done task", due_at=past, status="DONE", priority="HIGH", assignee_name="Owner"))
        overdue = job(db, job_type="OVERDUE_COMPLIANCE_SCAN", key="overdue")
        task_scan = job(db, job_type="TASK_OVERDUE_SCAN", key="tasks")
        assert execute_job(db, overdue, date.today()) == {"overdue": 1}
        assert execute_job(db, task_scan, date.today()) == {"events": 1}
        db.commit()
        assert db.get(Compliance, "open").status == "OVERDUE"
        assert {db.get(Compliance, key).status for key in ("complete", "cancel", "na")} == {"COMPLETED", "CANCELLED", "NOT_APPLICABLE"}
        assert db.get(Task, "task-done").status == "DONE"
        assert len(db.scalars(select(Notification).where(Notification.tenant_id == "tenant-a")).all()) == 2
        assert not db.scalars(select(Notification).where(Notification.tenant_id == "tenant-b")).first()


def test_due_reminders_queue_work_once_and_skip_closed():
    with SessionLocal() as db:
        tenant(db)
        past = date.today() - timedelta(days=1)
        for identifier, status in (("active", "IN_PROGRESS"), ("closed", "CANCELLED")):
            db.add(Compliance(id=identifier, tenant_id="tenant-a", organization_id="org-a", code=identifier, title=identifier,
                category="TEST", period="2026", statutory_deadline=date.today(), status=status, priority="MEDIUM", owner_name="Owner"))
            db.add(ComplianceReminder(tenant_id="tenant-a", compliance_id=identifier, event_key=f"tenant-a:{identifier}", scheduled_for=past,
                configuration='{"id":"r1","recipient_role":"COMPLIANCE_OFFICER","text":"Due","escalation_level":0}'))
            db.add(ComplianceSnapshot(compliance_id=identifier, tenant_id="tenant-a", organization_id="org-a", definition_id="definition",
                version_id="version", cycle=identifier, configuration=config().model_dump_json()))
        scan = job(db, job_type="REMINDER_DUE_SCAN", key="reminder")
        assert execute_job(db, scan, date.today()) == {"queued": 1}
        assert execute_job(db, scan, date.today()) == {"queued": 0}
        db.commit()
        assert len(db.scalars(select(Notification)).all()) == 1
        assert all(row.sent_at for row in db.scalars(select(ComplianceReminder)).all())


def test_document_expiry_uses_current_real_version_contract(monkeypatch):
    with SessionLocal() as db:
        tenant(db)
        document = Document(id="doc", tenant_id="tenant-a", organization_id="org-a", name="Registration certificate",
            category="Registration", file_type="PDF", uploaded_by="Owner")
        db.add(document)
        scan = job(db, job_type="DOCUMENT_EXPIRY_SCAN", key="documents")
        monkeypatch.setattr("app.document_service.genuine_file", lambda *_args, **_kwargs: SimpleNamespace(version_id="version-1", expiry_at=date.today() + timedelta(days=5)))
        assert execute_job(db, scan, date.today()) == {"events": 1}
        assert execute_job(db, scan, date.today()) == {"events": 0}
        db.commit()
        assert db.scalar(select(Notification).where(Notification.kind == "DOCUMENT"))


def test_phase6_migration_is_additive_and_platform_retry_is_guarded(monkeypatch):
    assert apply(engine) == VERSION
    assert apply(engine) == VERSION
    monkeypatch.setenv("PLATFORM_ADMIN_EMAILS", "operator@example.test")
    with TestClient(app) as client, SessionLocal() as db:
        tenant(db)
        row = job(db)
        row.status = "FAILED"
        user = User(tenant_id="tenant-a", name="Operator", email="operator@example.test", role="ADMIN")
        db.add(user); db.flush()
        db.add(AuthAccount(user_id=user.id, verified=True, platform_access=True))
        token = "phase-six-operator"
        db.add(AuthSession(token_hash=digest(token), user_id=user.id, expires_at=now() + timedelta(hours=1)))
        db.add(SessionContext(token_hash=digest(token), tenant_id="tenant-a", audience="admin"))
        db.commit()
        client.cookies.set("setu_session", token)
        client.headers["X-Setu-Request"] = "1"
        result = client.get("/api/v1/admin/automation/jobs")
        assert result.status_code == 200 and result.json()["items"][0]["id"] == row.id
        assert "payload" not in result.text and "lease_owner" not in result.text
        retried = client.post(f"/api/v1/admin/automation/jobs/{row.id}/retry")
        assert retried.status_code == 200 and retried.json()["status"] == "PENDING"
