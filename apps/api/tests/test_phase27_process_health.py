"""Phase 27 scheduler/worker heartbeats and backlog checks."""
from datetime import timedelta
from unittest.mock import patch

from app.automation_models import ScheduledJob
from app.database import SessionLocal
from app.models import Workspace, utcnow
from app.process_health import ProcessHeartbeat, ROLES, beat, problems, prune, status
from app.production_ops import worker_report

ENV = {"WORKER_STALE_SECONDS": "300", "BACKLOG_MAX_AGE_SECONDS": "900"}


def test_missing_and_stale_roles_are_reported():
    with SessionLocal() as db:
        assert set(problems(status(db), ENV)) == {f"{role}: no heartbeat recorded" for role in ROLES}
    now = utcnow()
    beat("scheduler", 3, instance="scheduler:a", at=now)
    beat("automation-worker", 0, instance="worker:a", at=now - timedelta(minutes=30))
    beat("integration-worker", 1, instance="integration:a", at=now)
    with SessionLocal() as db:
        found = problems(status(db, at=now), ENV)
    assert found == ["automation-worker: last heartbeat 1800s ago"]
    # A fresh beat from any instance of that role clears it; restarts add instances, never collide.
    beat("automation-worker", 2, instance="worker:b", at=now)
    with SessionLocal() as db:
        assert problems(status(db, at=now), ENV) == []
        assert db.get(ProcessHeartbeat, "worker:b").last_processed == 2


def test_required_roles_are_configurable():
    beat("scheduler", 0, instance="scheduler:only")
    with SessionLocal() as db:
        assert problems(status(db), ENV | {"WORKER_REQUIRED_ROLES": "scheduler"}) == []


def test_old_due_work_is_reported_as_backlog():
    now = utcnow()
    for role in ROLES:
        beat(role, 0, instance=role + ":x", at=now)
    with SessionLocal() as db:
        db.add(Workspace(id="tenant-backlog", name="Backlog Trust"))
        db.add(ScheduledJob(tenant_id="tenant-backlog", job_type="OVERDUE_SCAN", idempotency_key="old",
                            status="PENDING", scheduled_for=now - timedelta(hours=1)))
        db.add(ScheduledJob(tenant_id="tenant-backlog", job_type="OVERDUE_SCAN", idempotency_key="dead",
                            status="DEAD_LETTER", scheduled_for=now - timedelta(hours=2)))
        db.commit()
        result = status(db, at=now)
    assert result["due_jobs"] == 1 and result["dead_letter_jobs"] == 1
    assert 3590 <= result["oldest_due_seconds"] <= 3610
    assert problems(result, ENV) == [f"backlog: oldest due job waiting {result['oldest_due_seconds']}s"]


def test_heartbeat_failure_never_stops_the_process():
    with patch("app.process_health.SessionLocal", side_effect=RuntimeError("database down")):
        beat("scheduler", 0)  # logged, not raised


def test_prune_removes_long_stopped_instances():
    beat("scheduler", 0, instance="scheduler:gone", at=utcnow() - timedelta(days=8))
    beat("scheduler", 0, instance="scheduler:live")
    with SessionLocal() as db:
        assert prune(db) == 1
        db.commit()
        assert db.get(ProcessHeartbeat, "scheduler:gone") is None


def test_worker_report_lists_problems(monkeypatch):
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)
    result = worker_report()
    assert result["problems"] and set(result["seconds_since_heartbeat"]) == set(ROLES)


def test_single_runs_record_heartbeats(monkeypatch):
    from app import automation_worker, integration_worker, runtime_scheduler
    monkeypatch.setattr("sys.argv", ["process"])
    monkeypatch.setattr("app.process_control.signal.signal", lambda *args: None)
    runtime_scheduler.main()
    automation_worker.main()
    integration_worker.main()
    with SessionLocal() as db:
        assert problems(status(db), ENV) == []
