"""Focused Phase 22 CSR workflow, entitlement and isolation tests."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import COOKIE_NAME, digest
from app.auth_models import AuthAccount, SessionContext
from app.database import SessionLocal
from app.main import app
from app.migrate_phase22 import VERSION, apply
from app.models import AuthSession, Organization, TenantEntitlement, User
from app.phase8_models import OrganizationAccess


@contextmanager
def client_for(role="ADMIN", audience="user"):
    marker = uuid4().hex
    token = "phase22-" + marker
    with SessionLocal() as db:
        user = User(tenant_id="tenant-demo", name="CSR tester", email=marker + "@phase22.test",
                    role=role, status="ACTIVE")
        db.add(user); db.flush()
        db.add(AuthAccount(user_id=user.id, verified=True, platform_access=audience == "admin"))
        db.add(SessionContext(token_hash=digest(token), tenant_id="tenant-demo", audience=audience))
        db.add(AuthSession(token_hash=digest(token), user_id=user.id,
                           expires_at=datetime.now(timezone.utc) + timedelta(hours=1)))
        entitlement = db.scalar(select(TenantEntitlement).where(
            TenantEntitlement.tenant_id == "tenant-demo",
            TenantEntitlement.feature_key == "csr_partner_management"))
        if entitlement: entitlement.enabled = True
        else: db.add(TenantEntitlement(tenant_id="tenant-demo", feature_key="csr_partner_management",
                                       enabled=True, updated_by="Phase 22 test"))
        db.commit(); db.refresh(user)
    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, token); client.headers["X-Setu-Request"] = "1"
        yield client, user


def new_org():
    marker = uuid4().hex[:10]
    with SessionLocal() as db:
        row = Organization(tenant_id="tenant-demo", name="CSR NGO " + marker,
                           legal_type="TRUST", registration_number="CSR-" + marker)
        db.add(row); db.commit(); db.refresh(row); return row.id


def setup_review(client, organization_id, shared=True):
    partner = client.post("/api/v1/csr/partners", json={
        "organization_id": organization_id, "status": "PROSPECTIVE", "internal_notes": "corporate-only"
    })
    assert partner.status_code == 201, partner.text
    relationship_id = partner.json()["id"]
    project = client.post("/api/v1/csr/projects", json={
        "relationship_id": relationship_id, "name": "Nutrition programme", "code": "P-" + uuid4().hex[:8],
        "status": "ACTIVE", "shared_with_ngo": shared
    })
    assert project.status_code == 201, project.text
    template = client.post("/api/v1/csr/checklist-templates", json={
        "name": "CSR checklist " + uuid4().hex[:8], "version": 1,
        "items": [{"category": "Registration", "title": "Review registration evidence",
                   "requirement_type": "DOCUMENT", "required": True,
                   "expiry_monitoring": True, "share_with_ngo": True}]
    })
    assert template.status_code == 201, template.text
    review = client.post("/api/v1/csr/reviews", json={
        "relationship_id": relationship_id, "template_id": template.json()["id"],
        "project_id": project.json()["id"], "title": "Partner due diligence", "shared_with_ngo": shared
    })
    assert review.status_code == 201, review.text
    return relationship_id, project.json(), review.json()


def test_admin_partner_project_template_review_and_operational_report():
    with client_for() as (client, _):
        relationship_id, project, review = setup_review(client, new_org())
        assert project["relationship_id"] == relationship_id
        assert review["status"] == "NOT_STARTED" and review["items"][0]["status"] == "NOT_STARTED"
        item_id = review["items"][0]["id"]
        assert client.patch(f"/api/v1/csr/items/{item_id}", json={"status": "IN_PROGRESS"}).status_code == 200
        invalid = client.patch(f"/api/v1/csr/items/{item_id}", json={"status": "APPROVED"})
        assert invalid.status_code == 409
        report = client.get("/api/v1/csr/reports/portfolio")
        assert report.status_code == 200 and report.json()["legal_certification"] is False
        csv = client.get("/api/v1/csr/reports/portfolio.csv")
        assert csv.status_code == 200 and csv.headers["x-operational-status-only"] == "true"
        search = client.get("/api/v1/search", params={
            "q":"Nutrition", "types":"csr_partner,csr_project,due_diligence"
        })
        assert search.status_code == 200, search.text
        assert [row["id"] for row in search.json()["groups"]["csr_projects"]] == [project["id"]]


def test_entitlement_platform_admin_role_and_manipulated_ids():
    with client_for() as (client, _):
        with SessionLocal() as db:
            row = db.scalar(select(TenantEntitlement).where(
                TenantEntitlement.tenant_id == "tenant-demo",
                TenantEntitlement.feature_key == "csr_partner_management"))
            row.enabled = False; db.commit()
        assert client.get("/api/v1/csr/partners").status_code == 403
        assert client.get("/api/v1/csr/reviews/manipulated").status_code == 404
    with client_for(audience="admin") as (platform, _):
        assert platform.get("/api/v1/csr/partners").status_code == 403
    with client_for(role="VIEWER") as (viewer, _):
        assert viewer.post("/api/v1/csr/partners", json={"organization_id": new_org()}).status_code == 403
        assert viewer.patch("/api/v1/csr/items/manipulated", json={"status":"IN_PROGRESS"}).status_code == 403


def test_explicit_ngo_collaboration_shares_only_authorized_records():
    with client_for() as (admin, _):
        org = new_org(); relationship_id, project, review = setup_review(admin, org, shared=True)
        hidden_org = new_org(); hidden_relationship, _, _ = setup_review(admin, hidden_org, shared=False)
        with client_for(role="MEMBER") as (ngo, user):
            with SessionLocal() as db:
                db.add(OrganizationAccess(tenant_id="tenant-demo", organization_id=org, user_id=user.id,
                                          access_role="CONTRIBUTOR", status="ACTIVE", granted_by=user.id)); db.commit()
            grant = admin.post(f"/api/v1/csr/partners/{relationship_id}/collaborators", json={"user_id":user.id})
            assert grant.status_code == 201, grant.text
            partners = ngo.get("/api/v1/csr/partners").json()
            assert [row["id"] for row in partners] == [relationship_id]
            assert "internal_notes" not in partners[0]
            assert ngo.get("/api/v1/csr/dashboard").status_code == 403
            assert ngo.get("/api/v1/csr/checklist-templates").status_code == 403
            assert [row["id"] for row in ngo.get("/api/v1/csr/projects").json()] == [project["id"]]
            item = review["items"][0]
            updated = ngo.patch(f"/api/v1/csr/items/{item['id']}", json={
                "status":"IN_PROGRESS", "response":"Evidence will be uploaded"
            })
            assert updated.status_code == 200
            assert ngo.patch(f"/api/v1/csr/items/{item['id']}", json={
                "status":"SUBMITTED", "internal_notes":"bypass"
            }).status_code == 403
            assert ngo.get(f"/api/v1/csr/partners?q={hidden_relationship}").json() == []


def test_cross_org_and_cross_tenant_identifiers_are_not_exposed():
    with client_for() as (admin, _):
        org = new_org(); relationship_id, project, review = setup_review(admin, org)
        other_org = new_org(); other_relationship, other_project, other_review = setup_review(admin, other_org)
        with client_for(role="MEMBER") as (member, user):
            with SessionLocal() as db:
                db.add(OrganizationAccess(tenant_id="tenant-demo", organization_id=org, user_id=user.id,
                                          access_role="CONTRIBUTOR", status="ACTIVE", granted_by=user.id)); db.commit()
            assert member.get(f"/api/v1/csr/projects?relationship_id={other_relationship}").status_code == 404
            assert member.get(f"/api/v1/csr/reviews/{other_review['id']}").status_code == 404
            assert member.patch(f"/api/v1/csr/projects/{other_project['id']}", json={"status":"ACTIVE"}).status_code == 404
            own = member.get(f"/api/v1/csr/reviews/{review['id']}")
            assert own.status_code == 200 and own.json()["organization_id"] == org
            assert member.get("/api/v1/csr/reviews/not-a-real-id").status_code == 404


def test_phase22_migration_is_additive_and_idempotent():
    assert apply() == VERSION
    assert apply() == VERSION


def test_ui_capabilities_match_corporate_and_organization_read_only_permissions():
    with client_for() as (admin, _):
        org = new_org(); partner, project, review = setup_review(admin, org)
        row = next(row for row in admin.get("/api/v1/csr/partners").json() if row["id"] == partner)
        assert row["can_manage"] and row["can_grant_collaborators"]
        assert review["can_write"]
        assert set(review["items"][0]["allowed_statuses"]) == {"NOT_STARTED", "IN_PROGRESS", "NOT_APPLICABLE"}
        assert admin.patch(f"/api/v1/csr/partners/{partner}", json={"shared_notes":"Shared update"}).status_code == 200
        assert admin.patch(f"/api/v1/csr/projects/{project['id']}", json={"name":"Updated programme"}).status_code == 200
        with client_for(role="MEMBER") as (reader, user):
            with SessionLocal() as db:
                db.add(OrganizationAccess(tenant_id="tenant-demo", organization_id=org, user_id=user.id,
                    access_role="VIEWER", status="ACTIVE", granted_by=user.id)); db.commit()
            row = reader.get(f"/api/v1/csr/reviews/{review['id']}").json()
            assert not row["can_write"] and row["items"][0]["allowed_statuses"] == []
            assert not reader.get("/api/v1/csr/partners").json()[0]["can_manage"]
            assert reader.patch(f"/api/v1/csr/items/{review['items'][0]['id']}", json={"status":"IN_PROGRESS"}).status_code == 403


def test_ui_linking_decisions_history_and_wrong_organization_ids():
    from test_documents import upload_original
    with client_for() as (admin, user):
        org = new_org(); partner, _, review = setup_review(admin, org)
        item = review["items"][0]["id"]
        uploaded = upload_original(admin, organization_id=org)
        assert uploaded.status_code == 201, uploaded.text
        version = uploaded.json()["document"]["current_version_id"]
        assert admin.post(f"/api/v1/csr/items/{item}/evidence", json={"version_id":version}).status_code == 201
        task = admin.post("/api/v1/tasks", json={"organization_id":org,"title":"Resolve checklist evidence","due_at":"2030-01-01","assignee_user_id":user.id})
        assert task.status_code == 201, task.text
        assert admin.post("/api/v1/csr/task-links", json={"relationship_id":partner,"item_id":item,"task_id":task.json()["id"]}).status_code == 201
        wrong_task = admin.post("/api/v1/tasks", json={"organization_id":new_org(),"title":"Unrelated task","due_at":"2030-01-01","assignee_user_id":user.id}).json()
        assert admin.post("/api/v1/csr/task-links", json={"relationship_id":partner,"item_id":item,"task_id":wrong_task["id"]}).status_code == 404
        for status in ("SUBMITTED", "UNDER_REVIEW", "APPROVED"):
            result = admin.patch(f"/api/v1/csr/items/{item}", json={"status":status,"response":"Evidence reviewed","internal_notes":"Private corporate assessment"})
            assert result.status_code == 200, result.text
        result = result.json()
        assert result["status"] == "APPROVED" and result["history"]
        assert result["items"][0]["tasks"][0]["id"] == task.json()["id"]
        assert result["items"][0]["evidence"][0]["version_id"] == version
        with client_for(role="MEMBER") as (ngo, user):
            assert admin.post(f"/api/v1/csr/partners/{partner}/collaborators", json={"user_id":user.id}).status_code == 201
            shared = ngo.get(f"/api/v1/csr/reviews/{review['id']}").json()
            assert shared["can_write"] and shared["collaborator_view"]
            assert "internal_notes" not in shared["items"][0]
            assert "Private corporate assessment" not in str(shared)
            assert shared["items"][0]["allowed_statuses"] == ["APPROVED"]
            assert ngo.post("/api/v1/csr/task-links", json={"relationship_id":partner,"item_id":item,"task_id":wrong_task["id"]}).status_code == 403


def test_csr_workflow_ids_cannot_be_used_from_another_entitled_tenant():
    from app.models import Subscription
    with client_for() as (admin, _):
        partner, project, review = setup_review(admin, new_org())
        with TestClient(app) as foreign:
            foreign.headers["X-Setu-Request"] = "1"
            credentials = {"email": uuid4().hex + "@csr-isolation.test", "password":"CSR-isolation-QA-2026!"}
            assert foreign.post("/api/v1/auth/signup", json={"name":"Other admin", "workspace_name":"Other CSR", **credentials}).status_code == 201
            assert foreign.post("/api/v1/auth/login", json=credentials).status_code == 200
            tenant = foreign.get("/api/v1/auth/me").json()["user"]["tenant_id"]
            with SessionLocal() as db:
                db.scalar(select(Subscription).where(Subscription.tenant_id == tenant)).plan_name = "ENTERPRISE"
                db.commit()
            assert foreign.get("/api/v1/csr/partners").json() == []
            assert foreign.get(f"/api/v1/csr/reviews/{review['id']}").status_code == 404
            assert foreign.patch(f"/api/v1/csr/partners/{partner}", json={"status":"ACTIVE"}).status_code == 404
            assert foreign.patch(f"/api/v1/csr/projects/{project['id']}", json={"status":"ACTIVE"}).status_code == 404
            assert foreign.patch(f"/api/v1/csr/items/{review['items'][0]['id']}", json={"status":"IN_PROGRESS"}).status_code == 404
