"""Cross-phase release-candidate acceptance contracts.

These tests deliberately compose existing APIs. Detailed domain behavior remains
covered by the focused phase suites.
"""
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from app.auth import COOKIE_NAME, digest
from app.auth_models import AuthAccount, SessionContext
from app.database import SessionLocal
from app.main import app
from app.models import AuthSession, Compliance, User
from app.phase8_models import OrganizationAccess


@contextmanager
def acceptance_actor(kind: str):
    """Create a real session for one deterministic acceptance persona."""
    roles = {
        "ngo_admin": ("ADMIN", "user"),
        "consultant": ("MEMBER", "user"),
        "corporate_admin": ("ADMIN", "user"),
        "platform_admin": ("ADMIN", "admin"),
        "viewer": ("VIEWER", "user"),
    }
    role, audience = roles[kind]
    marker = uuid4().hex
    token = f"phase26-{kind}-{marker}"
    with SessionLocal() as db:
        user = User(tenant_id="tenant-demo", name=f"Phase 26 {kind}",
                    email=f"{kind}-{marker}@acceptance.test", role=role, status="ACTIVE")
        db.add(user); db.flush()
        db.add(AuthAccount(user_id=user.id, verified=True, platform_access=audience == "admin"))
        db.add(AuthSession(token_hash=digest(token), user_id=user.id,
                           expires_at=datetime.now(timezone.utc) + timedelta(hours=1)))
        db.add(SessionContext(token_hash=digest(token), tenant_id="tenant-demo", audience=audience))
        db.commit(); db.refresh(user)
    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, token)
        client.headers["X-Setu-Request"] = "1"
        yield client, user


def add_acceptance_compliance(organization_id: str, marker: str, status: str, title: str):
    with SessionLocal() as db:
        row = Compliance(
            tenant_id="tenant-demo", organization_id=organization_id,
            code=marker, title=title, category="Phase 26 acceptance", period="2026-27",
            statutory_deadline=date.today() - timedelta(days=1), status=status,
            priority="HIGH", owner_name="Acceptance owner", progress=100 if status == "COMPLETED" else 40,
        )
        db.add(row); db.commit(); db.refresh(row)
        return row.id


def grant(user_id: str, organization_id: str, role: str):
    with SessionLocal() as db:
        db.add(OrganizationAccess(
            tenant_id="tenant-demo", organization_id=organization_id, user_id=user_id,
            access_role=role, status="ACTIVE", granted_by=user_id,
        ))
        db.commit()


def test_closed_state_is_consistent_across_search_reports_and_exports():
    marker = "ACCEPTANCE26"
    add_acceptance_compliance("org-aarohan", marker + "-DONE", "COMPLETED", "Completed acceptance filing")
    add_acceptance_compliance("org-aarohan", marker + "-OPEN", "IN_PROGRESS", '=HYPERLINK("https://bad.example")')
    with acceptance_actor("ngo_admin") as (client, _):
        search = client.get("/api/v1/search", params={"q": marker, "types": "compliance"})
        assert search.status_code == 200
        statuses = {row["status"] for row in search.json()["groups"]["compliances"]}
        assert statuses == {"COMPLETED", "IN_PROGRESS"}

        report = client.get("/api/v1/reports/analytics", params={
            "organization_id": "org-aarohan", "category": "Phase 26 acceptance",
        })
        assert report.status_code == 200
        summary = report.json()["summary"]
        assert {key: summary[key] for key in ("total", "completed", "open", "overdue")} == {
            "total": 2, "completed": 1, "open": 1, "overdue": 1,
        }

        exported = client.get("/api/v1/reports/compliance.csv", params={
            "organization_id": "org-aarohan", "category": "Phase 26 acceptance",
        })
        assert exported.status_code == 200
        assert marker + "-DONE" in exported.text and marker + "-OPEN" in exported.text
        assert "'=HYPERLINK" in exported.text


def test_viewer_scope_is_identical_across_search_reports_portfolio_and_direct_ids():
    visible = add_acceptance_compliance("org-aarohan", "VISIBLE26", "IN_PROGRESS", "Visible acceptance work")
    hidden = add_acceptance_compliance("org-udaan", "HIDDEN26", "IN_PROGRESS", "Hidden acceptance work")
    with acceptance_actor("viewer") as (client, user):
        grant(user.id, "org-aarohan", "VIEWER")
        search = client.get("/api/v1/search", params={"q": "26", "types": "compliance"})
        assert search.status_code == 200
        assert "VISIBLE26" in search.text and "HIDDEN26" not in search.text

        report = client.get("/api/v1/reports/analytics", params={"category": "Phase 26 acceptance"})
        assert report.status_code == 200 and report.json()["summary"]["total"] == 1
        portfolio = client.get("/api/v1/portfolio/dashboard")
        assert portfolio.status_code == 200
        assert {row["organization_id"] for row in portfolio.json()["organization_summaries"]} == {"org-aarohan"}

        assert client.get(f"/api/v1/compliances/{visible}/runtime-detail").status_code == 200
        # Direct same-workspace access uses the established explicit-denial convention;
        # aggregate and filter APIs use 404/no rows to avoid scoped enumeration.
        assert client.get(f"/api/v1/compliances/{hidden}/runtime-detail").status_code == 403
        assert client.get("/api/v1/reports/compliance.csv", params={"organization_id": "org-udaan"}).status_code == 404


def test_platform_and_tenant_audiences_remain_separate_across_product_surfaces():
    workspace_paths = (
        "/api/v1/search?q=acceptance",
        "/api/v1/reports/analytics",
        "/api/v1/portfolio/dashboard",
        "/api/v1/ai/conversations",
        "/api/v1/csr/partners",
        "/api/v1/document-intelligence/review",
    )
    with acceptance_actor("platform_admin") as (platform, _):
        assert all(platform.get(path).status_code == 403 for path in workspace_paths)

    with acceptance_actor("viewer") as (viewer, user):
        grant(user.id, "org-aarohan", "VIEWER")
        assert viewer.get("/api/v1/search", params={"q": "Aarohan"}).status_code == 200
        assert viewer.post("/api/v1/csr/partners", json={"organization_id": "org-aarohan"}).status_code == 403
        assert viewer.post("/api/v1/document-intelligence/facts/manipulated/approve", json={}).status_code == 403
        assert viewer.post("/api/v1/portfolio/bulk/compliances/owner", json={
            "target_ids": ["cmp-fcra"], "assignee_user_id": user.id,
        }).status_code == 403
