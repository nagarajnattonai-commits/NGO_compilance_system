"""Focused Phase 13 search, saved-view and isolation contracts."""
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select

from app.auth import COOKIE_NAME, digest
from app.auth_models import AuthAccount, SessionContext
from app.database import Base, SessionLocal
from app.main import app
from app.migrate_phase13 import VERSION, apply
from app.models import AuthSession, Compliance, Document, Organization, Submission, Task, User, Workspace
from app.organization_models import OrganizationRegistration
from app.phase13_models import SavedView
from app.phase8_models import OrganizationAccess


@contextmanager
def search_client(role="ADMIN", audience="user", tenant_id="tenant-demo"):
    with TestClient(app) as client:
        identifier = uuid4().hex
        token = "search-" + identifier
        with SessionLocal() as db:
            user = User(tenant_id=tenant_id, name="Search user", email=identifier + "@search.test",
                        role=role, status="ACTIVE")
            db.add(user); db.flush()
            db.add(AuthAccount(user_id=user.id, verified=True, platform_access=audience == "admin"))
            db.add(AuthSession(token_hash=digest(token), user_id=user.id,
                               expires_at=datetime.now(timezone.utc) + timedelta(hours=1)))
            db.add(SessionContext(token_hash=digest(token), tenant_id=tenant_id, audience=audience))
            db.commit(); db.refresh(user)
        client.cookies.set(COOKIE_NAME, token)
        client.headers["X-Setu-Request"] = "1"
        yield client, user


def add_search_records(db, tenant_id, organization_id, marker):
    compliance = Compliance(
        tenant_id=tenant_id, organization_id=organization_id, code=f"{marker}-CODE",
        title=f"{marker} compliance", category="Annual", period="2026-27",
        statutory_deadline=date.today() + timedelta(days=10), status="IN_PROGRESS",
        priority="HIGH", owner_name=f"{marker} owner",
    )
    db.add(compliance); db.flush()
    db.add(Task(tenant_id=tenant_id, organization_id=organization_id, compliance_id=compliance.id,
                title=f"{marker} task", due_at=date.today() + timedelta(days=5), status="TODO",
                priority="HIGH", assignee_name=f"{marker} assignee"))
    document = Document(tenant_id=tenant_id, organization_id=organization_id, compliance_id=compliance.id,
                        name=f"{marker} evidence", category="Proof", expiry_at=date.today() + timedelta(days=20),
                        uploaded_by="Tester")
    db.add(document)
    db.add(OrganizationRegistration(tenant_id=tenant_id, organization_id=organization_id,
                                    kind=f"{marker[:6]}REG", status="ACTIVE", number=f"{marker}-NUMBER"))
    db.add(Submission(tenant_id=tenant_id, compliance_id=compliance.id,
                      acknowledgement_ref=f"{marker}-ACK", notes=f"{marker} filing"))
    return compliance


def test_global_search_groups_all_supported_authorized_entities():
    with search_client() as (client, _):
        with SessionLocal() as db:
            add_search_records(db, "tenant-demo", "org-aarohan", "PHASE13")
            db.commit()
        response = client.get("/api/v1/search", params={"q": "PHASE13", "limit_per_group": 10})
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["total"] == 5
        assert all(payload["groups"][group] for group in (
            "compliances", "tasks", "documents", "registrations", "filings"
        ))
        assert {item["type"] for group in payload["groups"].values() for item in group} >= {
            "compliance", "task", "document", "registration", "filing"
        }
        organizations = client.get("/api/v1/search", params={"q": "Aarohan", "types": "organization"})
        assert organizations.status_code == 200 and len(organizations.json()["groups"]["organizations"]) == 1


def test_search_enforces_tenant_org_and_direct_id_scope():
    with search_client(role="VIEWER") as (client, user):
        with SessionLocal() as db:
            db.add(OrganizationAccess(tenant_id="tenant-demo", organization_id="org-aarohan", user_id=user.id,
                                      access_role="VIEWER", status="ACTIVE", granted_by=user.id))
            allowed = add_search_records(db, "tenant-demo", "org-aarohan", "VISIBLE13")
            hidden = add_search_records(db, "tenant-demo", "org-udaan", "HIDDEN13")
            other_org = Organization(id="phase13-other-org", tenant_id="phase13-other-tenant", name="OTHER13 org",
                                     legal_type="Trust", registration_number="OTHER13", status="ACTIVE")
            db.add(Workspace(id="phase13-other-tenant", name="Other tenant")); db.add(other_org); db.flush()
            add_search_records(db, "phase13-other-tenant", other_org.id, "OTHER13")
            db.commit()
        response = client.get("/api/v1/search", params={"q": "13"})
        assert response.status_code == 200
        text = response.text
        assert "VISIBLE13" in text and "HIDDEN13" not in text and "OTHER13" not in text
        assert client.get("/api/v1/search", params={"organization_id": "org-udaan"}).status_code == 404
        assert client.get("/api/v1/search", params={"compliance_id": hidden.id}).status_code == 404
        assert client.get("/api/v1/search", params={"compliance_id": allowed.id}).status_code == 200


def test_platform_admin_and_manipulated_filters_are_rejected():
    with search_client(audience="admin") as (client, _):
        assert client.get("/api/v1/search", params={"q": "anything"}).status_code == 403
        assert client.get("/api/v1/saved-views").status_code == 403
    with search_client() as (client, _):
        assert client.get("/api/v1/search", params={"types": "organization,secret"}).status_code == 422
        assert client.get("/api/v1/search", params={"tenant_id": "other-tenant"}).status_code == 422
        assert client.get("/api/v1/search", params={"date_from": "2030-01-01", "date_to": "2020-01-01"}).status_code == 422
        response = client.get("/api/v1/search", params={"q": "%_"})
        assert response.status_code == 200 and response.json()["total"] == 0


def test_saved_views_are_personal_tenant_scoped_and_viewer_writable():
    with search_client(role="VIEWER") as (client, user):
        payload = {
            "name": "My deadlines", "scope": "GLOBAL_SEARCH", "is_default": True,
            "filters": {"timing": "UPCOMING", "priority": "HIGH"},
            "sorting": {"by": "date", "direction": "asc"}, "visible_columns": ["title", "date"],
        }
        created = client.post("/api/v1/saved-views", json=payload)
        assert created.status_code == 201, created.text
        view_id = created.json()["id"]
        assert created.json()["is_default"] is True
        second = client.post("/api/v1/saved-views", json={**payload, "name": "Second", "is_default": True})
        assert second.status_code == 201
        listed = client.get("/api/v1/saved-views").json()
        assert len(listed) == 2 and sum(row["is_default"] for row in listed) == 1
        with SessionLocal() as db:
            stranger = SavedView(tenant_id="tenant-demo", user_id="not-this-user", name="Private",
                                  scope="GLOBAL_SEARCH", filters="{}", sorting="{}", visible_columns="[]")
            other_tenant = SavedView(tenant_id="other-tenant", user_id=user.id, name="Other tenant",
                                     scope="GLOBAL_SEARCH", filters="{}", sorting="{}", visible_columns="[]")
            db.add_all((stranger, other_tenant)); db.commit()
            stranger_id, other_id = stranger.id, other_tenant.id
        assert client.delete(f"/api/v1/saved-views/{stranger_id}").status_code == 404
        assert client.delete(f"/api/v1/saved-views/{other_id}").status_code == 404
        assert client.delete(f"/api/v1/saved-views/{view_id}").status_code == 204
        bad = client.post("/api/v1/saved-views", json={**payload, "name": "Bad", "visible_columns": ["secret"]})
        assert bad.status_code == 422


def test_phase13_migration_is_idempotent(tmp_path):
    target = create_engine(f"sqlite:///{tmp_path / 'phase13.db'}")
    Base.metadata.create_all(target)
    assert apply(target) == VERSION
    assert apply(target) == VERSION
    with target.connect() as connection:
        versions = connection.execute(select(1).select_from(SavedView.__table__)).all()
        assert versions == []
