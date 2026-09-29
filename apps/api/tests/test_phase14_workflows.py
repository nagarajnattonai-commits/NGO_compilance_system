"""Focused Phase 14 workflow, scheduler, authorization and isolation contracts."""
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select

from app.auth import COOKIE_NAME, digest
from app.auth_models import AuthAccount, SessionContext
from app.automation_models import ScheduledJob
from app.automation_service import execute_job, fail_job, finish_job
from app.database import Base, SessionLocal
from app.main import app
from app.migrate_phase14 import VERSION, apply
from app.models import AuthSession, Compliance, Subscription, Task, User, Workspace
from app.phase14_models import AutomationActionExecution, AutomationDefinition, AutomationExecution
from app.workflow_service import queue_workflow_event


@contextmanager
def workflow_client(role="ADMIN", tenant_id="tenant-demo", audience="user"):
    with TestClient(app) as client:
        marker = uuid4().hex; token = "workflow-" + marker
        with SessionLocal() as db:
            if not db.get(Workspace, tenant_id): db.add(Workspace(id=tenant_id, name=tenant_id))
            if not db.scalar(select(Subscription).where(Subscription.tenant_id == tenant_id)):
                db.add(Subscription(tenant_id=tenant_id, plan_name="BUSINESS", status="ACTIVE",
                                    period_end=date.today() + timedelta(days=30)))
            user = User(tenant_id=tenant_id, name="Workflow admin", email=marker + "@workflow.test",
                        role=role, status="ACTIVE")
            db.add(user); db.flush(); db.add(AuthAccount(user_id=user.id, verified=True, platform_access=audience == "admin"))
            db.add(AuthSession(token_hash=digest(token), user_id=user.id,
                               expires_at=datetime.now(timezone.utc) + timedelta(hours=1)))
            db.add(SessionContext(token_hash=digest(token), tenant_id=tenant_id, audience=audience)); db.commit(); db.refresh(user)
        client.cookies.set(COOKIE_NAME, token); client.headers["X-Setu-Request"] = "1"
        yield client, user


def payload(user_id, **overrides):
    value = {"name": "Upcoming filing workflow", "description": "Structured test workflow",
             "organization_id": "org-aarohan", "enabled": True, "trigger_type": "DEADLINE_APPROACHING",
             "conditions": [{"field": "priority", "operator": "EQ", "value": "HIGH"}],
             "actions": [{"type": "CREATE_TASK", "parameters": {
                 "title": "Prepare filing evidence", "due_in_days": 2, "priority": "HIGH", "assignee_user_id": user_id,
             }}]}
    value.update(overrides); return value


def test_definition_crud_audit_and_execution_history():
    with workflow_client() as (client, user):
        created = client.post("/api/v1/automations", json=payload(user.id))
        assert created.status_code == 201, created.text
        definition_id = created.json()["id"]
        updated = client.put(f"/api/v1/automations/{definition_id}", json={**payload(user.id), "description": "Updated"})
        assert updated.status_code == 200 and updated.json()["revision"] == 2
        assert client.get("/api/v1/automations").json()[0]["id"] == definition_id
        assert client.get("/api/v1/automations/unknown/executions").status_code == 404
        assert client.delete(f"/api/v1/automations/{definition_id}").status_code == 204
        assert client.get("/api/v1/automations").json()[0]["enabled"] is False


def test_event_execution_is_asynchronous_and_idempotent():
    with workflow_client() as (client, user):
        definition = client.post("/api/v1/automations", json=payload(user.id)).json()
        with SessionLocal() as db:
            compliance = Compliance(tenant_id="tenant-demo", organization_id="org-aarohan", code="WF-14",
                title="Workflow deadline", category="Test", period="2026", statutory_deadline=date.today() + timedelta(days=4),
                status="IN_PROGRESS", priority="HIGH", owner_name="Workflow admin")
            db.add(compliance); db.flush()
            assert queue_workflow_event(db, "tenant-demo", "DEADLINE_APPROACHING", "Compliance", compliance.id,
                                        compliance.organization_id, "phase14-event") == 1
            assert queue_workflow_event(db, "tenant-demo", "DEADLINE_APPROACHING", "Compliance", compliance.id,
                                        compliance.organization_id, "phase14-event") == 0
            db.commit(); compliance_id = compliance.id
        with SessionLocal() as db:
            job = db.scalar(select(ScheduledJob).where(ScheduledJob.job_type == "AUTOMATION_WORKFLOW_EXECUTION"))
            job.attempt_count = 1
            result = execute_job(db, job); finish_job(db, job, result); db.commit()
            assert result == {"status": "SUCCEEDED", "actions": 1}
            execution = db.scalar(select(AutomationExecution).where(AutomationExecution.automation_id == definition["id"]))
            assert execution.status == "SUCCEEDED"
            assert len(db.scalars(select(AutomationActionExecution).where(AutomationActionExecution.execution_id == execution.id)).all()) == 1
            assert len(db.scalars(select(Task).where(Task.compliance_id == compliance_id,
                                                      Task.title == "Prepare filing evidence")).all()) == 1
            assert execute_job(db, job)["actions"] == 1
            db.commit()
            assert len(db.scalars(select(Task).where(Task.compliance_id == compliance_id,
                                                      Task.title == "Prepare filing evidence")).all()) == 1
        history = client.get(f"/api/v1/automations/{definition['id']}/executions")
        assert history.status_code == 200 and history.json()[0]["actions"][0]["type"] == "CREATE_TASK"


def test_disabled_workflow_and_nonmatching_conditions_do_not_act():
    with workflow_client() as (client, user):
        definition = client.post("/api/v1/automations", json=payload(user.id)).json()
        with SessionLocal() as db:
            compliance = Compliance(tenant_id="tenant-demo", organization_id="org-aarohan", code="WF-SKIP",
                title="Skip workflow", category="Test", period="2026", statutory_deadline=date.today(),
                status="IN_PROGRESS", priority="LOW", owner_name="Nobody")
            db.add(compliance); db.flush()
            queue_workflow_event(db, "tenant-demo", "DEADLINE_APPROACHING", "Compliance", compliance.id,
                                 compliance.organization_id, "skip-event")
            automation = db.get(AutomationDefinition, definition["id"]); automation.enabled = False; db.commit()
        with SessionLocal() as db:
            job = db.scalar(select(ScheduledJob).where(ScheduledJob.entity_type == "AutomationExecution")); job.attempt_count = 1
            assert execute_job(db, job)["status"] == "SKIPPED"; db.commit()
            assert not db.scalar(select(Task.id).where(Task.title == "Prepare filing evidence"))


def test_tenant_role_platform_and_manipulated_id_isolation():
    with workflow_client(role="VIEWER") as (client, user):
        assert client.get("/api/v1/automations").status_code == 403
        assert client.post("/api/v1/automations", json=payload(user.id)).status_code == 403
    with workflow_client(audience="admin") as (client, user):
        assert client.get("/api/v1/automations").status_code == 403
    with workflow_client() as (client, user):
        assert client.post("/api/v1/automations", json=payload(user.id, organization_id="other-tenant-org")).status_code == 404
        bad = payload(user.id, actions=[{"type": "UPDATE_FIELDS", "parameters": {"field": "tenant_id", "value": "other"}}])
        assert client.post("/api/v1/automations", json=bad).status_code == 422
        assert client.get("/api/v1/automations/not-owned/executions").status_code == 404


def test_action_authorization_is_rechecked_by_worker_and_failure_is_recorded():
    with workflow_client() as (client, user):
        definition = client.post("/api/v1/automations", json=payload(user.id)).json()
        with SessionLocal() as db:
            compliance = Compliance(tenant_id="tenant-demo", organization_id="org-aarohan", code="WF-AUTH",
                title="Authorization", category="Test", period="2026", statutory_deadline=date.today(),
                status="IN_PROGRESS", priority="HIGH", owner_name="Nobody")
            db.add(compliance); db.flush(); queue_workflow_event(db, "tenant-demo", "DEADLINE_APPROACHING", "Compliance",
                compliance.id, compliance.organization_id, "auth-event"); db.get(User, user.id).status = "DISABLED"; db.commit()
        with SessionLocal() as db:
            job = db.scalar(select(ScheduledJob).where(ScheduledJob.entity_type == "AutomationExecution")); job.attempt_count = 1
            try: execute_job(db, job)
            except Exception as error:
                db.rollback(); job = db.get(ScheduledJob, job.id); fail_job(db, job, error); db.commit()
            execution = db.scalar(select(AutomationExecution).where(AutomationExecution.automation_id == definition["id"]))
            assert execution.status == "FAILED" and execution.last_error_code == "INVALID_JOB_CONTEXT"
            assert not db.scalar(select(Task.id).where(Task.title == "Prepare filing evidence"))


def test_phase14_migration_is_idempotent(tmp_path):
    target = create_engine(f"sqlite:///{tmp_path / 'phase14.db'}")
    Base.metadata.create_all(target)
    assert apply(target) == VERSION and apply(target) == VERSION
    assert inspect(target).has_table("automation_definitions")
    assert inspect(target).has_table("automation_executions")
    assert inspect(target).has_table("automation_action_executions")
