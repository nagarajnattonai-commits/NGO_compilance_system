"""Phase 8 organization authorization, task assignment and collaboration contracts."""
import json
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from uuid import uuid4

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from app.auth import COOKIE_NAME, digest
from app.automation_service import _task_overdue_scan
from app.database import SessionLocal, engine
from app.main import app
from app.migrate_phase8 import VERSION, apply
from app.models import AuthSession, Task, User
from app.notification_models import NotificationRecipient
from app.phase8_models import OrganizationAccess, TaskComment

HEADERS = {"X-Setu-Request": "1"}


def image_bytes():
    output = BytesIO()
    Image.new("RGB", (24, 24), "blue").save(output, "PNG")
    return output.getvalue()


def account(db, identifier, *, role="MEMBER"):
    user = User(id=identifier, tenant_id="tenant-demo", name=identifier.replace("-", " ").title(),
                email=identifier + "@example.test", phone="919999999999", role=role, status="ACTIVE")
    token = "token-" + identifier
    db.add(user)
    db.add(AuthSession(token_hash=digest(token), user_id=user.id,
                       expires_at=datetime.now(timezone.utc) + timedelta(hours=1)))
    return user, token


def use(client, token):
    client.cookies.set(COOKIE_NAME, token)
    client.headers.update(HEADERS)


def setup_accounts():
    with SessionLocal() as db:
        admin, admin_token = account(db, "phase8-admin", role="ADMIN")
        first, first_token = account(db, "phase8-first")
        second, second_token = account(db, "phase8-second")
        db.commit()
    return admin, admin_token, first, first_token, second, second_token


def test_organization_access_is_explicit_and_responsibility_does_not_grant_it():
    with TestClient(app) as client:
        _, admin_token, first, first_token, second, second_token = setup_accounts()
        use(client, admin_token)
        granted = client.put("/api/v1/organizations/org-udaan/access",
                             json={"user_id": first.id, "access_role": "CONTRIBUTOR"})
        assert granted.status_code == 200, granted.text

        use(client, first_token)
        assert [row["id"] for row in client.get("/api/v1/organizations").json()] == ["org-udaan"]
        assert client.get("/api/v1/organizations/org-udaan/profile").status_code == 200
        assert client.get("/api/v1/organizations/org-jal/profile").status_code == 403

        use(client, second_token)
        assert client.get("/api/v1/organizations").json() == []
        assert client.get("/api/v1/compliances").json() == []
        assert client.get("/api/v1/tasks").json() == []


def test_task_assignment_reassignment_comments_filters_and_notifications():
    with TestClient(app) as client:
        _, admin_token, first, first_token, second, _ = setup_accounts()
        use(client, admin_token)
        assert client.put("/api/v1/organizations/org-udaan/access",
                          json={"user_id": first.id, "access_role": "CONTRIBUTOR"}).status_code == 200
        created = client.post("/api/v1/tasks", json={
            "organization_id": "org-udaan", "compliance_id": "cmp-audit",
            "title": "Prepare audited statements", "due_at": "2030-09-30",
            "priority": "HIGH", "assignee_user_id": first.id,
        })
        assert created.status_code == 201, created.text
        task = created.json()
        assert task["assignee_user_id"] == first.id and task["assigned_by"] == "phase8-admin"

        denied = client.patch(f"/api/v1/tasks/{task['id']}", json={"assignee_user_id": second.id})
        assert denied.status_code == 422 and denied.json()["detail"] == "TASK_ASSIGNEE_NOT_AUTHORIZED"
        assert client.put("/api/v1/organizations/org-udaan/access",
                          json={"user_id": second.id, "access_role": "VIEWER"}).status_code == 200
        reassigned = client.patch(f"/api/v1/tasks/{task['id']}", json={"assignee_user_id": second.id})
        assert reassigned.status_code == 200 and reassigned.json()["assignee_user_id"] == second.id

        use(client, first_token)
        comment = client.post(f"/api/v1/tasks/{task['id']}/comments", json={"body": "Evidence is ready."})
        assert comment.status_code == 200 or comment.status_code == 201
        assert client.get(f"/api/v1/tasks/{task['id']}/comments").json()[0]["body"] == "Evidence is ready."
        rows = client.get("/api/v1/tasks", params={"priority": "HIGH", "search": "audited"}).json()
        assert [row["id"] for row in rows] == [task["id"]]

        with SessionLocal() as db:
            assert db.scalar(select(TaskComment).where(TaskComment.task_id == task["id"]))
            recipients = db.scalars(select(NotificationRecipient).where(
                NotificationRecipient.user_id.in_([first.id, second.id]))).all()
            assert recipients


def test_task_attachment_reuses_real_document_evidence():
    with TestClient(app) as client:
        _, admin_token, first, _, _, _ = setup_accounts()
        use(client, admin_token)
        client.put("/api/v1/organizations/org-udaan/access",
                   json={"user_id": first.id, "access_role": "CONTRIBUTOR"})
        task = client.post("/api/v1/tasks", json={
            "organization_id": "org-udaan", "title": "Attach signed evidence",
            "due_at": "2030-09-30", "assignee_user_id": first.id,
        }).json()
        metadata = {"request_id": str(uuid4()), "organization_id": "org-udaan",
                    "name": "Task evidence.png", "category": "Task evidence"}
        uploaded = client.post("/api/v1/documents/upload", data={"metadata": json.dumps(metadata)},
                               files={"file": ("evidence.png", image_bytes(), "image/png")})
        assert uploaded.status_code == 201, uploaded.text
        document_id = uploaded.json()["document"]["id"]
        linked = client.post(f"/api/v1/tasks/{task['id']}/attachments", json={"document_id": document_id})
        assert linked.status_code == 201, linked.text
        assert client.get(f"/api/v1/tasks/{task['id']}/attachments").json()[0]["document_id"] == document_id
        assert client.delete(f"/api/v1/tasks/{task['id']}/attachments/{linked.json()['id']}").status_code == 204
        assert client.get(f"/api/v1/tasks/{task['id']}/attachments").json() == []


def test_phase8_migration_is_idempotent():
    assert apply(engine) == VERSION
    assert apply(engine) == VERSION


def test_task_overdue_notification_targets_real_assignee():
    with TestClient(app):
        _, _, first, _, _, _ = setup_accounts()
        with SessionLocal() as db:
            db.add(OrganizationAccess(tenant_id="tenant-demo", organization_id="org-udaan",
                                      user_id=first.id, access_role="CONTRIBUTOR",
                                      status="ACTIVE", granted_by="phase8-admin"))
            task = Task(tenant_id="tenant-demo", organization_id="org-udaan", title="Late filing task",
                        due_at=date.today() - timedelta(days=1), status="TODO", priority="HIGH",
                        assignee_user_id=first.id, assignee_name=first.name)
            db.add(task)
            db.flush()
            result = _task_overdue_scan(db, type("Job", (), {"tenant_id": "tenant-demo"})(), date.today())
            db.commit()
            assert result["events"] >= 1
            assert db.scalar(select(NotificationRecipient).where(NotificationRecipient.user_id == first.id))
