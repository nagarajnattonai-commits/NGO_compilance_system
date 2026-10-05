"""Focused contracts for the repaired workspace/frontend workflows."""
from urllib.parse import parse_qs, urlsplit

from sqlalchemy import delete, select

from app.database import SessionLocal
from app.features import can_use_feature, require_plan_capacity
from app.models import Subscription, TenantEntitlement
from test_subscriptions import subscription_client
from test_phase13_search import add_search_records
from test_phase22_csr import client_for, new_org, setup_review


def test_unassigned_subscription_preserves_core_access_without_paid_features():
    with subscription_client() as (client, user):
        with SessionLocal() as db:
            db.execute(delete(Subscription).where(Subscription.tenant_id == user.tenant_id))
            db.add(TenantEntitlement(tenant_id=user.tenant_id, feature_key="advanced_reporting",
                                     enabled=True, updated_by="test"))
            db.commit()
        response = client.get("/api/v1/subscription")
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["configured"] is False and data["id"] is None
        assert data["plan_name"] == "LEGACY" and data["status"] == "UNASSIGNED"
        assert data["period_end"] is None and data["features"] == []
        assert all(data[key] is None for key in ("user_limit", "organization_limit", "integration_limit", "storage_limit_gb"))
        assert data["feature_access"] and not any(data["feature_access"].values())
        assert client.get("/api/v1/organizations").status_code == 200
        assert client.get("/api/v1/subscription", headers={"x-tenant-id": "foreign"}).status_code == 403
        assert client.get("/api/v1/reports/compliance.csv").status_code == 403
        assert client.get("/api/v1/automations").status_code == 403
        with SessionLocal() as db:
            assert not db.scalar(select(Subscription).where(Subscription.tenant_id == user.tenant_id))
            require_plan_capacity(db, user.tenant_id, "organizations", used=999)
            assert not can_use_feature(db, user.tenant_id, "advanced_reporting")


def test_unassigned_subscription_does_not_allow_platform_session(monkeypatch):
    email = "workflow-operator@example.test"
    monkeypatch.setenv("PLATFORM_ADMIN_EMAILS", email)
    with subscription_client(platform_admin=True, email=email) as (client, user):
        with SessionLocal() as db:
            db.execute(delete(Subscription).where(Subscription.tenant_id == user.tenant_id))
            db.commit()
        assert client.get("/api/v1/subscription").status_code == 403


def test_partial_reminder_update_preserves_account_channels_and_categories():
    with subscription_client() as (client, _):
        original = {"in_app_enabled": True, "email_enabled": False, "whatsapp_enabled": True,
                    "compliance_enabled": True, "task_enabled": False,
                    "document_enabled": False, "system_enabled": False}
        assert client.patch("/api/v1/notification-preferences", json=original).status_code == 200
        changed = client.patch("/api/v1/notification-preferences", json={"compliance_enabled": False})
        assert changed.status_code == 200
        for key, value in original.items():
            assert changed.json()[key] == (False if key == "compliance_enabled" else value)
        assert client.get("/api/v1/notification-preferences").json()["compliance_enabled"] is False
        assert client.patch("/api/v1/notification-preferences", json={"weekly_digest": True}).status_code == 422


def test_search_task_and_document_urls_select_existing_workspace_records():
    with subscription_client() as (client, _):
        with SessionLocal() as db:
            add_search_records(db, "tenant-demo", "org-aarohan", "NAVFIX")
            db.commit()
        data = client.get("/api/v1/search?q=NAVFIX").json()
        for group, view in (("tasks", "tasks"), ("documents", "documents")):
            result = data["groups"][group][0]
            parsed = urlsplit(result["url"])
            assert parsed.path == "/dashboard"
            assert parse_qs(parsed.query) == {"view": [view], "record": [result["id"]], "type": [result["type"]]}


def test_search_csr_urls_select_authorized_existing_tabs():
    # Reuse existing CSR fixtures and domain APIs rather than inventing records.
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app):
        with client_for() as (client, _):
            organization_id = new_org()
            setup_review(client, organization_id)
            data = client.get("/api/v1/search", params={"types": "csr_partner,csr_project,due_diligence"}).json()
            for group in ("csr_partners", "csr_projects", "due_diligence"):
                assert data["groups"][group]
                for result in data["groups"][group]:
                    query = parse_qs(urlsplit(result["url"]).query)
                    assert query == {"view": ["csr"], "record": [result["id"]], "type": [result["type"]]}
