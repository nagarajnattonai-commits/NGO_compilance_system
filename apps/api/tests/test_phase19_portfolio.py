"""Focused consultant portfolio authorization and aggregation contracts."""
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import COOKIE_NAME, digest
from app.auth_models import AuthAccount, SessionContext
from app.database import SessionLocal
from app.main import app
from app.models import AuthSession, Compliance, Task, TenantEntitlement, User
from app.phase8_models import OrganizationAccess


@contextmanager
def portfolio_client(role="MEMBER", audience="user"):
    with TestClient(app) as client:
        marker = uuid4().hex
        token = "portfolio-" + marker
        with SessionLocal() as db:
            user = User(tenant_id="tenant-demo", name="Portfolio consultant",
                        email=marker + "@portfolio.test", role=role, status="ACTIVE")
            db.add(user); db.flush()
            db.add(AuthAccount(user_id=user.id, verified=True, platform_access=audience == "admin"))
            db.add(AuthSession(token_hash=digest(token), user_id=user.id,
                               expires_at=datetime.now(timezone.utc) + timedelta(hours=1)))
            db.add(SessionContext(token_hash=digest(token), tenant_id="tenant-demo", audience=audience))
            db.commit(); db.refresh(user)
        client.cookies.set(COOKIE_NAME, token)
        client.headers["X-Setu-Request"] = "1"
        yield client, user


def add_work(db, organization_id, marker, days, *, assignee=None):
    compliance = Compliance(
        tenant_id="tenant-demo", organization_id=organization_id, code=marker,
        title=marker + " compliance", category="Portfolio", period="2026-27",
        statutory_deadline=date.today() + timedelta(days=days), status="IN_PROGRESS",
        priority="HIGH", owner_name=marker + " owner",
    )
    db.add(compliance); db.flush()
    task = Task(
        tenant_id="tenant-demo", organization_id=organization_id, compliance_id=compliance.id,
        title=marker + " task", due_at=date.today() + timedelta(days=days), status="TODO",
        priority="HIGH", assignee_name=assignee.name if assignee else marker + " assignee",
        assignee_user_id=assignee.id if assignee else None,
    )
    db.add(task); db.flush()
    return compliance, task


def grant(db, user, organization_id, role="CONTRIBUTOR"):
    db.add(OrganizationAccess(tenant_id="tenant-demo", organization_id=organization_id,
                              user_id=user.id, access_role=role, granted_by=user.id))


def test_portfolio_dashboard_directory_queue_and_deadlines_exclude_other_clients():
    with portfolio_client() as (client, user):
        with SessionLocal() as db:
            grant(db, user, "org-aarohan")
            allowed, _ = add_work(db, "org-aarohan", "VISIBLE19", -2)
            hidden, _ = add_work(db, "org-udaan", "HIDDEN19", -3)
            db.commit()
        dashboard = client.get("/api/v1/portfolio/dashboard")
        assert dashboard.status_code == 200, dashboard.text
        assert dashboard.json()["summary"]["organizations"] == 1
        assert dashboard.json()["summary"]["overdue"] >= 1
        assert {row["organization_id"] for row in dashboard.json()["organization_summaries"]} == {"org-aarohan"}
        directory = client.get("/api/v1/portfolio/organizations", params={"q": "Aarohan"})
        assert directory.status_code == 200 and directory.json()["total"] == 1
        assert directory.json()["items"][0]["overdue"] >= 1
        queue = client.get("/api/v1/portfolio/work-queue", params={"timing": "OVERDUE"})
        assert "VISIBLE19" in queue.text and "HIDDEN19" not in queue.text
        deadlines = client.get("/api/v1/portfolio/deadlines")
        assert "VISIBLE19" in deadlines.text and "HIDDEN19" not in deadlines.text
        assert client.get("/api/v1/portfolio/work-queue", params={"organization_id": "org-udaan"}).status_code == 404
        assert client.get("/api/v1/portfolio/deadlines", params={"compliance_id": hidden.id}).json()["total"] == 0
        assert client.get("/api/v1/portfolio/deadlines", params={"compliance_id": allowed.id}).json()["total"] == 1


def test_bulk_assignment_validates_every_target_before_mutation():
    with portfolio_client() as (client, actor):
        with SessionLocal() as db:
            assignee = User(tenant_id="tenant-demo", name="Authorized consultant",
                            email=uuid4().hex + "@portfolio.test", role="MEMBER", status="ACTIVE")
            db.add(assignee); db.flush()
            grant(db, actor, "org-aarohan")
            grant(db, assignee, "org-aarohan")
            allowed_compliance, allowed_task = add_work(db, "org-aarohan", "BULK19A", 5)
            _, hidden_task = add_work(db, "org-udaan", "BULK19B", 5)
            db.commit(); assignee_id = assignee.id
        rejected = client.post("/api/v1/portfolio/bulk/tasks/assignee", json={
            "target_ids": [allowed_task.id, hidden_task.id], "assignee_user_id": assignee_id,
        })
        assert rejected.status_code == 403
        with SessionLocal() as db:
            assert db.get(Task, allowed_task.id).assignee_user_id is None
        accepted = client.post("/api/v1/portfolio/bulk/tasks/assignee", json={
            "target_ids": [allowed_task.id], "assignee_user_id": assignee_id,
        })
        assert accepted.status_code == 200 and accepted.json()["updated"] == 1
        owner = client.post("/api/v1/portfolio/bulk/compliances/owner", json={
            "target_ids": [allowed_compliance.id], "assignee_user_id": assignee_id,
        })
        assert owner.status_code == 200
        with SessionLocal() as db:
            assert db.get(Task, allowed_task.id).assignee_user_id == assignee_id
            assert db.get(Compliance, allowed_compliance.id).owner_name == "Authorized consultant"


def test_client_invitation_is_organization_scoped_and_cannot_escalate():
    with portfolio_client(role="ADMIN") as (client, _):
        email = uuid4().hex + "@client.test"
        created = client.post("/api/v1/admin/users/invite", json={
            "name": "Client reviewer", "email": email, "role": "VIEWER",
            "organization_ids": ["org-aarohan"],
        })
        assert created.status_code == 201, created.text
        user_id = created.json()["user"]["id"]
        with SessionLocal() as db:
            rows = list(db.scalars(select(OrganizationAccess).where(OrganizationAccess.user_id == user_id)).all())
            assert [(row.organization_id, row.access_role) for row in rows] == [("org-aarohan", "VIEWER")]
        escalation = client.post("/api/v1/admin/users/invite", json={
            "name": "Bad admin", "email": uuid4().hex + "@client.test", "role": "ADMIN",
            "organization_ids": ["org-aarohan"],
        })
        assert escalation.status_code == 422
        manipulated = client.post("/api/v1/admin/users/invite", json={
            "name": "Unknown org", "email": uuid4().hex + "@client.test", "role": "VIEWER",
            "organization_ids": ["other-tenant-org"],
        })
        assert manipulated.status_code == 404


def test_viewer_platform_admin_and_portfolio_ai_boundaries():
    with portfolio_client(role="VIEWER") as (client, viewer):
        with SessionLocal() as db:
            grant(db, viewer, "org-aarohan", "VIEWER")
            _, task = add_work(db, "org-aarohan", "VIEWER19", 2)
            db.add(TenantEntitlement(tenant_id="tenant-demo", feature_key="ai_rag", enabled=True))
            db.commit()
        assert client.post("/api/v1/portfolio/bulk/tasks/assignee", json={
            "target_ids": [task.id], "assignee_user_id": viewer.id,
        }).status_code == 403
        context = client.get("/api/v1/portfolio/ai-context")
        assert context.status_code == 200
        assert {row["organization_id"] for row in context.json()["organizations"]} == {"org-aarohan"}
    with portfolio_client(role="ADMIN", audience="admin") as (client, _):
        assert client.get("/api/v1/portfolio/dashboard").status_code == 403
        assert client.get("/api/v1/portfolio/ai-context").status_code == 403
