"""Focused management-report aggregation and authorization contracts."""
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
def reporting_client(role="ADMIN", audience="user"):
    with TestClient(app) as client:
        identifier = uuid4().hex
        token = "reporting-" + identifier
        with SessionLocal() as db:
            user = User(
                tenant_id="tenant-demo", name="Reporting user", email=identifier + "@reporting.test",
                role=role, status="ACTIVE",
            )
            db.add(user)
            db.flush()
            db.add(AuthAccount(user_id=user.id, verified=True, platform_access=False))
            db.add(AuthSession(
                token_hash=digest(token), user_id=user.id,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            ))
            db.add(SessionContext(token_hash=digest(token), tenant_id="tenant-demo", audience=audience))
            db.commit()
        client.cookies.set(COOKIE_NAME, token)
        client.headers["X-Setu-Request"] = "1"
        yield client, user


def test_analytics_excludes_closed_states_from_active_and_overdue_counts():
    with reporting_client() as (client, _):
        with SessionLocal() as db:
            for compliance_status in ("COMPLETED", "CANCELLED", "NOT_APPLICABLE", "IN_PROGRESS", "UNDER_REVIEW"):
                db.add(Compliance(
                    tenant_id="tenant-demo", organization_id="org-aarohan",
                    code="REPORT-" + compliance_status, title="Reporting " + compliance_status,
                    category="Phase 11 test", period="2026-27",
                    statutory_deadline=date.today() - timedelta(days=1),
                    status=compliance_status, priority="HIGH", owner_name="Reporting owner",
                ))
            db.commit()
        response = client.get("/api/v1/reports/analytics", params={
            "organization_id": "org-aarohan", "category": "Phase 11 test",
        })
        assert response.status_code == 200, response.text
        summary = response.json()["summary"]
        assert summary["total"] == 5
        assert summary["completed"] == 1
        assert summary["cancelled"] == 1
        assert summary["not_applicable"] == 1
        assert summary["overdue"] == 2
        assert summary["open"] == 2
        assert summary["requires_review"] == 1
        assert summary["in_progress"] == 1
        assert summary["completion_rate"] == 33
        organization = next(
            row for row in response.json()["organization_summaries"]
            if row["organization_id"] == "org-aarohan"
        )
        assert organization["total_applicable"] == 3
        assert organization["completed"] == 1
        assert organization["pending"] == 2
        assert organization["completion_percentage"] == 33


def test_deadline_horizons_return_only_matching_upcoming_items():
    with reporting_client() as (client, _):
        with SessionLocal() as db:
            for days in (8, 29, 31, 61, 91):
                db.add(Compliance(
                    tenant_id="tenant-demo", organization_id="org-aarohan",
                    code=f"HORIZON-{days}", title=f"Horizon {days}",
                    category="Phase 11 horizons", period="2026-27",
                    statutory_deadline=date.today() + timedelta(days=days),
                    status="IN_PROGRESS", priority="MEDIUM", owner_name="Horizon owner",
                ))
            db.commit()
        counts = {}
        for horizon in (7, 30, 60, 90):
            response = client.get("/api/v1/reports/analytics", params={
                "organization_id": "org-aarohan", "category": "Phase 11 horizons",
                "horizon_days": horizon,
            })
            assert response.status_code == 200, response.text
            counts[horizon] = response.json()["summary"]["upcoming"]
            assert all(row["days_remaining"] <= horizon for row in response.json()["upcoming_deadlines"])
        assert counts == {7: 0, 30: 2, 60: 3, 90: 4}


def test_analytics_filters_and_viewer_scope_are_server_enforced():
    with reporting_client(role="VIEWER") as (client, user):
        with SessionLocal() as db:
            db.add(OrganizationAccess(
                tenant_id="tenant-demo", organization_id="org-aarohan", user_id=user.id,
                access_role="VIEWER", status="ACTIVE", granted_by="reporting-admin",
            ))
            for organization_id, code, owner in (
                ("org-aarohan", "REPORT-ALLOWED", "Visible owner"),
                ("org-udaan", "REPORT-HIDDEN", "Hidden owner"),
            ):
                db.add(Compliance(
                    tenant_id="tenant-demo", organization_id=organization_id, code=code,
                    title=code, category="Phase 11 access", period="2026-27",
                    statutory_deadline=date.today() + timedelta(days=5), status="IN_PROGRESS",
                    priority="HIGH", owner_name=owner,
                ))
            db.commit()
        portfolio = client.get("/api/v1/reports/analytics", params={"category": "Phase 11 access"})
        assert portfolio.status_code == 200
        assert [row["id"] for row in portfolio.json()["filters"]["organizations"]] == ["org-aarohan"]
        assert portfolio.json()["summary"]["total"] == 1
        assert client.get("/api/v1/reports/analytics", params={
            "organization_id": "org-udaan", "category": "Phase 11 access",
        }).status_code == 404
        assert client.get("/api/v1/reports/analytics", params={
            "category": "Phase 11 access", "date_from": "2030-01-01", "date_to": "2020-01-01",
        }).status_code == 422


def test_platform_admin_audience_cannot_use_workspace_reporting():
    with reporting_client(audience="admin") as (client, _):
        for url in (
            "/api/v1/reports/analytics",
            "/api/v1/reports/compliance",
            "/api/v1/reports/compliance.csv",
            "/api/v1/reports/compliance/print",
        ):
            assert client.get(url).status_code == 403


def test_detail_csv_and_print_exports_share_authorization_and_filters():
    with reporting_client(role="VIEWER") as (client, user):
        with SessionLocal() as db:
            db.add(OrganizationAccess(
                tenant_id="tenant-demo", organization_id="org-aarohan", user_id=user.id,
                access_role="VIEWER", status="ACTIVE", granted_by="reporting-admin",
            ))
            for organization_id, code, title in (
                ("org-aarohan", "VISIBLE-EXPORT", "=HYPERLINK(\"https://bad.example\")"),
                ("org-udaan", "HIDDEN-EXPORT", "Hidden record"),
            ):
                db.add(Compliance(
                    tenant_id="tenant-demo", organization_id=organization_id,
                    code=code, title=title, category="Export test", period="2026-27",
                    statutory_deadline=date.today() + timedelta(days=10), status="IN_PROGRESS",
                    priority="HIGH", owner_name="Allowed owner",
                ))
            db.commit()
        params = {"organization_id": "org-aarohan", "category": "Export test", "owner": "allowed", "priority": "HIGH"}
        detail = client.get("/api/v1/reports/compliance", params=params)
        assert detail.status_code == 200
        assert detail.json()["total"] == 1
        assert len(detail.json()["rows"]) == 1
        row = detail.json()["rows"][0]
        assert row["code"] == "VISIBLE-EXPORT"
        assert row["applicability"] == "APPLICABLE"
        assert row["tasks"] == [] and row["checklist"] == []
        assert "credential" not in detail.text.lower()

        csv_response = client.get("/api/v1/reports/compliance.csv", params=params)
        assert csv_response.status_code == 200
        assert "VISIBLE-EXPORT" in csv_response.text
        assert "HIDDEN-EXPORT" not in csv_response.text
        assert "'=HYPERLINK" in csv_response.text

        print_response = client.get("/api/v1/reports/compliance/print", params=params)
        assert print_response.status_code == 200
        assert "VISIBLE-EXPORT" in print_response.text
        assert "HIDDEN-EXPORT" not in print_response.text
        for url in (
            "/api/v1/reports/compliance",
            "/api/v1/reports/compliance.csv",
            "/api/v1/reports/compliance/print",
        ):
            assert client.get(url, params={"organization_id": "org-udaan"}).status_code == 404
        assert client.get("/api/v1/reports/compliance.csv", params=params,
                          headers={"x-tenant-id": "another-tenant"}).status_code == 403