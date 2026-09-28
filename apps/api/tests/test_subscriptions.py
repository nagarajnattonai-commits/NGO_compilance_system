"""Phase 12 plan catalogue and tenant entitlement contracts."""
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, inspect, select, text

from app.auth import COOKIE_NAME, digest
from app.auth_models import AuthAccount, SessionContext
from app.database import SessionLocal
from app.features import (
    PLAN_CATALOG, can_use_feature, new_subscription, plan_catalog_payload,
    require_plan_capacity, subscription_usage,
)
from app.migrate_phase12 import VERSION, apply
from app.main import app
from app.models import AuditEvent, AuthSession, Organization, Subscription, TenantEntitlement, User, Workspace


@contextmanager
def subscription_client(tenant_id="tenant-demo", *, role="ADMIN", platform_admin=False, email=None):
    with TestClient(app) as client:
        email = email or f"subscription-{uuid4().hex}@example.test"
        token = "subscription-" + uuid4().hex
        with SessionLocal() as db:
            if not db.get(Workspace, tenant_id):
                db.add(Workspace(id=tenant_id, name=tenant_id))
                db.flush()
            if not db.scalar(select(Subscription).where(Subscription.tenant_id == tenant_id)):
                db.add(new_subscription(tenant_id, "STARTER", date.today() + timedelta(days=30)))
            user = User(tenant_id=tenant_id, name="Subscription test user", email=email, role=role, status="ACTIVE")
            db.add(user)
            db.flush()
            db.add(AuthAccount(user_id=user.id, verified=True, platform_access=platform_admin))
            db.add(AuthSession(token_hash=digest(token), user_id=user.id,
                               expires_at=datetime.now(timezone.utc) + timedelta(hours=1)))
            db.add(SessionContext(token_hash=digest(token), tenant_id=tenant_id,
                                  audience="admin" if platform_admin else "user"))
            db.commit()
        client.cookies.set(COOKIE_NAME, token)
        client.headers["X-Setu-Request"] = "1"
        yield client, user


def test_plan_defaults_preserve_explicit_entitlement_overrides():
    with TestClient(app):
        with SessionLocal() as db:
            subscription = db.scalar(select(Subscription).where(Subscription.tenant_id == "tenant-demo"))
            assert subscription
            db.execute(delete(TenantEntitlement).where(
                TenantEntitlement.tenant_id == "tenant-demo",
                TenantEntitlement.feature_key == "google_calendar_integration",
            ))
            subscription.plan_name = "STARTER"
            db.flush()
            assert not can_use_feature(db, "tenant-demo", "google_calendar_integration")

            subscription.plan_name = "BUSINESS"
            db.flush()
            assert can_use_feature(db, "tenant-demo", "google_calendar_integration")

            override = TenantEntitlement(
                tenant_id="tenant-demo", feature_key="google_calendar_integration", enabled=False,
            )
            db.add(override)
            db.flush()
            assert not can_use_feature(db, "tenant-demo", "google_calendar_integration")

            override.enabled = True
            subscription.plan_name = "STARTER"
            db.flush()
            assert can_use_feature(db, "tenant-demo", "google_calendar_integration")

            override.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            db.flush()
            assert not can_use_feature(db, "tenant-demo", "google_calendar_integration")

            override.expires_at = None
            subscription.status = "SUSPENDED"
            db.flush()
            assert not can_use_feature(db, "tenant-demo", "google_calendar_integration")

        assert set(PLAN_CATALOG) == {"STARTER", "PROFESSIONAL", "BUSINESS", "ENTERPRISE"}
        assert [row["key"] for row in plan_catalog_payload()] == list(PLAN_CATALOG)
        assert PLAN_CATALOG["STARTER"].user_limit == 5


def test_phase12_migration_adds_subscription_fields_idempotently(tmp_path):
    target = create_engine(f"sqlite:///{tmp_path / 'pre_phase12.db'}")
    with target.begin() as connection:
        connection.exec_driver_sql("""
            CREATE TABLE subscriptions (
                id VARCHAR(36) PRIMARY KEY,
                tenant_id VARCHAR(36) NOT NULL,
                plan_name VARCHAR(40) NOT NULL,
                status VARCHAR(20) NOT NULL,
                user_limit INTEGER NOT NULL,
                organization_limit INTEGER NOT NULL,
                storage_limit_gb INTEGER NOT NULL,
                period_end DATE NOT NULL
            )
        """)
        connection.execute(text("""
            INSERT INTO subscriptions
                (id, tenant_id, plan_name, status, user_limit, organization_limit, storage_limit_gb, period_end)
            VALUES ('sub-starter', 'tenant-starter', 'STARTER', 'ACTIVE', 5, 3, 1, '2027-01-01')
        """))
    assert apply(target) == VERSION
    assert apply(target) == VERSION
    names = {column["name"] for column in inspect(target).get_columns("subscriptions")}
    assert {"period_start", "integration_limit", "cancel_at_period_end"} <= names
    with target.connect() as connection:
        row = connection.execute(text("""
            SELECT period_start, integration_limit, cancel_at_period_end
            FROM subscriptions WHERE id = 'sub-starter'
        """)).one()
    assert row.period_start is None
    assert row.integration_limit == 1
    assert row.cancel_at_period_end in (False, 0)


def test_tenant_subscription_view_is_scoped_and_viewer_read_only():
    with subscription_client(role="VIEWER") as (client, _):
        response = client.get("/api/v1/subscription")
        assert response.status_code == 200
        payload = response.json()
        assert payload["plan_name"] == "BUSINESS"
        with SessionLocal() as db:
            assert payload["usage"] == subscription_usage(db, "tenant-demo")
        assert len(payload["plans"]) == 4
        assert isinstance(payload["history"], list)
        assert client.get("/api/v1/subscription", headers={"x-tenant-id": "another-tenant"}).status_code == 403
        assert client.post("/api/v1/organizations", json={
            "name": "Viewer cannot create", "legal_type": "TRUST",
            "registration_number": "VIEWER-SUB-1", "city": "Pune",
            "generate_compliance_plan": False,
        }).status_code == 403


def test_platform_plan_assignment_is_separate_audited_and_limit_driving(monkeypatch):
    email = "platform-subscriptions@example.test"
    monkeypatch.setenv("PLATFORM_ADMIN_EMAILS", email)
    monkeypatch.setenv("PLATFORM_HOSTS", "testserver")
    with subscription_client(platform_admin=True, email=email) as (client, _):
        assert client.get("/api/v1/subscription").status_code == 403
        with SessionLocal() as db:
            db.add(Workspace(id="tenant-plan-target", name="Plan target workspace"))
            db.add(new_subscription("tenant-plan-target", "STARTER", date(2027, 1, 1)))
            db.commit()
        updated = client.put("/api/v1/platform/subscriptions/tenant-plan-target", json={
            "plan_name": "PROFESSIONAL", "status": "TRIAL",
            "period_start": "2026-09-26", "period_end": "2027-09-26",
            "cancel_at_period_end": False,
        })
        assert updated.status_code == 200, updated.text
        subscription = updated.json()["subscription"]
        assert subscription["plan_name"] == "PROFESSIONAL"
        assert subscription["status"] == "TRIAL"
        assert subscription["user_limit"] == 15
        assert subscription["organization_limit"] == 8
        assert subscription["integration_limit"] == 5
        with SessionLocal() as db:
            saved = db.scalar(select(Subscription).where(Subscription.tenant_id == "tenant-plan-target"))
            assert saved.period_start == date(2026, 9, 26)
            assert db.scalar(select(AuditEvent.id).where(
                AuditEvent.tenant_id == "tenant-plan-target",
                AuditEvent.action == "SUBSCRIPTION_CHANGED",
            ))
        listing = client.get("/api/v1/platform/subscriptions")
        assert listing.status_code == 200
        target = next(row for row in listing.json()["items"] if row["tenant_id"] == "tenant-plan-target")
        assert target["history"] and "PROFESSIONAL" in target["history"][0]["summary"]
        assert client.put("/api/v1/platform/subscriptions/tenant-plan-target", json={
            "plan_name": "NOT_CONFIGURED",
        }).status_code == 422

    with subscription_client(tenant_id="tenant-plan-target", role="ADMIN") as (client, _):
        assert client.get("/api/v1/platform/subscriptions").status_code == 403
        assert client.put("/api/v1/platform/subscriptions/tenant-plan-target", json={
            "plan_name": "ENTERPRISE",
        }).status_code == 403


def test_starter_limits_block_direct_organization_user_and_integration_apis(monkeypatch):
    email = "subscription-limits@example.test"

    class MemorySecrets:
        def reference(self, tenant, resource):
            return f"test://{tenant}/{resource}"

    monkeypatch.setattr("app.integration_api.secret_store", lambda: MemorySecrets())
    with subscription_client(tenant_id="tenant-limit-target", email=email) as (client, user):
        with SessionLocal() as db:
            plan = db.scalar(select(Subscription).where(Subscription.tenant_id == "tenant-limit-target"))
            plan.user_limit = 1
            plan.organization_limit = 0
            plan.integration_limit = 0
            plan.plan_name = "BUSINESS"
            db.add(TenantEntitlement(tenant_id="tenant-limit-target", feature_key="custom_email", enabled=True))
            db.commit()

        organization = client.post("/api/v1/organizations", json={
            "name": "Over-limit organization", "legal_type": "TRUST",
            "registration_number": "OVER-LIMIT-ORG", "city": "Pune",
            "generate_compliance_plan": False,
        })
        assert organization.status_code == 403
        assert organization.json()["detail"] == "PLAN_LIMIT_REACHED:organizations"

        invited = client.post("/api/v1/admin/users/invite", json={
            "name": "Second user", "email": "second-user@example.test", "role": "MEMBER",
        })
        assert invited.status_code == 403
        assert invited.json()["detail"] == "PLAN_LIMIT_REACHED:users"

        connection = client.post("/api/v1/integrations-management/tenant/connections", json={
            "provider_key": "smtp", "display_name": "Over-limit integration",
            "environment": "PRODUCTION",
            "configuration": {"host": "mail.example.org", "username": "mailer",
                              "from_address": "notify@example.org", "port": 465},
        })
        assert connection.status_code == 403
        assert connection.json()["detail"] == "PLAN_LIMIT_REACHED:integrations"


def test_inactive_subscription_and_reporting_exports_cannot_be_bypassed_directly():
    tenant = "tenant-entitlement-bypass"
    with subscription_client(tenant_id=tenant) as (client, _):
        with SessionLocal() as db:
            subscription = db.scalar(select(Subscription).where(Subscription.tenant_id == tenant))
            subscription.plan_name = "STARTER"
            subscription.organization_limit = PLAN_CATALOG["STARTER"].organization_limit
            db.commit()

        assert client.get("/api/v1/reports/compliance").status_code == 200
        csv = client.get("/api/v1/reports/compliance.csv")
        assert csv.status_code == 403
        assert csv.json()["detail"] == "UPGRADE_REQUIRED:advanced_reporting"
        printable = client.get("/api/v1/reports/compliance/print")
        assert printable.status_code == 403

        with SessionLocal() as db:
            subscription = db.scalar(select(Subscription).where(Subscription.tenant_id == tenant))
            subscription.plan_name = "BUSINESS"
            subscription.user_limit = PLAN_CATALOG["BUSINESS"].user_limit
            subscription.organization_limit = PLAN_CATALOG["BUSINESS"].organization_limit
            subscription.integration_limit = PLAN_CATALOG["BUSINESS"].integration_limit
            subscription.storage_limit_gb = PLAN_CATALOG["BUSINESS"].storage_limit_gb
            db.commit()
        assert client.get("/api/v1/reports/compliance.csv").status_code == 200

        with SessionLocal() as db:
            subscription = db.scalar(select(Subscription).where(Subscription.tenant_id == tenant))
            subscription.status = "PAST_DUE"
            db.commit()
        blocked = client.post("/api/v1/organizations", json={
            "name": "Suspended workspace organization", "legal_type": "TRUST",
            "registration_number": "SUSPENDED-SUB-1", "city": "Pune",
            "generate_compliance_plan": False,
        })
        assert blocked.status_code == 403
        assert blocked.json()["detail"] == "SUBSCRIPTION_INACTIVE"


def test_usage_is_tenant_scoped_and_legacy_missing_subscription_keeps_existing_behavior():
    suffix = uuid4().hex
    tenant = "tenant-usage-scope-" + suffix
    other = "tenant-usage-other-" + suffix
    with TestClient(app):
        with SessionLocal() as db:
            db.add_all([Workspace(id=tenant, name="Usage scope"), Workspace(id=other, name="Other usage")])
            db.add(Organization(
                tenant_id=other, name="Other tenant NGO", legal_type="TRUST",
                registration_number="OTHER-USAGE-1", city="Pune",
            ))
            db.commit()
            assert subscription_usage(db, tenant)["organizations"] == 0
            assert subscription_usage(db, other)["organizations"] == 1
            assert db.scalar(select(Subscription).where(Subscription.tenant_id == tenant)) is None
            require_plan_capacity(db, tenant, "organizations")
