from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from app.auth_models import AuthAccount, SessionContext
from app.auth import digest
from app.brand_domains import active_domain, invalidate_domains, valid_https, validate_hostname, verify_domain_records
from app.brand_outputs import render_email
from app.branding_schema import BrandConfiguration
from app.database import SessionLocal
from app.main import app
from app.models import AuthSession, BrandAsset, Subscription, TenantBranding, TenantDomain, TenantEntitlement, User, Workspace


@contextmanager
def client_for(role="ADMIN", tenant="tenant-demo", entitled=True):
    with TestClient(app) as client:
        invalidate_domains()
        with SessionLocal() as db:
            if not db.get(Workspace, tenant):
                db.add(Workspace(id=tenant, name="White Label Test"))
            if not db.scalar(select(Subscription).where(Subscription.tenant_id == tenant)):
                db.add(Subscription(tenant_id=tenant, period_end=date.today() + timedelta(days=30)))
            entitlement = db.scalar(select(TenantEntitlement).where(TenantEntitlement.tenant_id == tenant, TenantEntitlement.feature_key == "white_label"))
            if not entitlement:
                entitlement = TenantEntitlement(tenant_id=tenant, feature_key="white_label")
                db.add(entitlement)
            entitlement.enabled = entitled
            user = User(tenant_id=tenant, name="Brand Administrator", email=f"{role.lower()}@white-label.test", role=role)
            db.add(user)
            db.flush()
            db.add(AuthAccount(user_id=user.id, verified=True, platform_access=role == "ADMIN"))
            db.add(SessionContext(token_hash=digest("white-label-session"), tenant_id=tenant, audience="user"))
            db.add(AuthSession(token_hash=digest("white-label-session"), user_id=user.id, expires_at=datetime.now(timezone.utc) + timedelta(hours=1)))
            db.commit()
        client.cookies.set("setu_session", "white-label-session")
        client.headers["X-Setu-Request"] = "1"
        yield client


def draft(client, name="ABC Compliance"):
    settings = client.get("/api/v1/white-label").json()
    configuration = settings["configuration"]
    configuration["brand_name"] = name
    configuration["product_name"] = name + " Portal"
    response = client.patch("/api/v1/white-label/draft", json={"expected_revision": settings["revision"], "configuration": configuration})
    assert response.status_code == 200, response.text
    return response.json()


def publish(client, settings):
    response = client.post("/api/v1/white-label/publish", json={"expected_revision": settings["revision"]})
    assert response.status_code == 200, response.text
    return response.json()


def png(width=64, height=64):
    output = BytesIO()
    Image.new("RGBA", (width, height), "#218838").save(output, "PNG")
    return output.getvalue()


def test_draft_publish_reset_history_and_stale_revision():
    with client_for() as client:
        settings = draft(client)
        assert client.get("/api/v1/white-label/published").json()["enabled"] is False
        assert client.post("/api/v1/white-label/publish", json={"expected_revision": 0}).status_code == 409
        published = publish(client, settings)
        brand = client.get("/api/v1/white-label/published").json()
        assert brand["product_name"] == "ABC Compliance Portal"
        assert brand["enabled"] is True
        reset = client.post("/api/v1/white-label/reset", json={"expected_revision": published["revision"]}).json()
        assert reset["configuration"]["product_name"] == "Setu NGO"
        assert client.get("/api/v1/white-label/published").json()["product_name"] == "ABC Compliance Portal"
        assert len(reset["history"]) == 2
        assert client.get("/api/v1/white-label/versions/1").json()["brand_name"] == "ABC Compliance"
        actions = [event["action"] for event in client.get("/api/v1/audit-events").json()]
        assert "WHITE_LABEL_BRANDING_PUBLISHED" in actions and "WHITE_LABEL_BRANDING_RESET" in actions


@pytest.mark.parametrize("role", ["MEMBER", "VIEWER"])
def test_white_label_permission_is_enforced_on_backend(role):
    with client_for(role=role) as client:
        assert client.get("/api/v1/white-label").status_code == 403
        assert client.patch("/api/v1/white-label/draft", json={"expected_revision": 0, "configuration": BrandConfiguration().model_dump()}).status_code == 403
        assert client.post("/api/v1/white-label/domains", json={"hostname": "portal.customer.org"}).status_code == 403
        assert client.get("/api/v1/white-label/published").status_code == 200


def test_entitlement_expiry_falls_back_without_deleting_configuration():
    with client_for() as client:
        publish(client, draft(client))
        with SessionLocal() as db:
            entitlement = db.scalar(select(TenantEntitlement).where(TenantEntitlement.tenant_id == "tenant-demo"))
            entitlement.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            db.commit()
        assert client.get("/api/v1/white-label").json()["configuration"]["brand_name"] == "ABC Compliance"
        assert client.get("/api/v1/white-label/published").json()["brand_name"] == "Setu NGO"
        assert client.post("/api/v1/white-label/publish", json={"expected_revision": 2}).status_code == 403


def test_cross_tenant_configuration_domain_and_assets_are_blocked(monkeypatch, tmp_path):
    monkeypatch.setenv("BRAND_ASSET_DIR", str(tmp_path))
    with client_for() as client:
        publish(client, draft(client, "Tenant A"))
        asset = client.post("/api/v1/white-label/assets?asset_type=PRIMARY_LOGO", files={"file": ("logo.png", png(), "image/png")}).json()
        domain = client.post("/api/v1/white-label/domains", json={"hostname": "portal.customer.org"}).json()
        with SessionLocal() as db:
            db.add(Workspace(id="tenant-b", name="Tenant B"))
            db.add(Subscription(tenant_id="tenant-b", period_end=date.today() + timedelta(days=30)))
            db.add(TenantEntitlement(tenant_id="tenant-b", feature_key="white_label", enabled=True))
            user = db.scalar(select(User).where(User.email == "admin@white-label.test"))
            user.tenant_id = "tenant-b"
            db.get(SessionContext, digest("white-label-session")).tenant_id = "tenant-b"
            db.commit()
        assert client.get("/api/v1/white-label").json()["configuration"]["brand_name"] == "Setu NGO"
        assert client.get("/api/v1/white-label/versions/1").status_code == 404
        assert client.get(f'/api/v1/white-label/assets/{asset["id"]}/content').status_code == 404
        assert client.post(f'/api/v1/white-label/domains/{domain["id"]}/verify').status_code == 404
        assert client.patch("/api/v1/white-label/draft", headers={"X-Tenant-ID": "tenant-demo"}, json={"expected_revision": 0, "configuration": BrandConfiguration().model_dump()}).status_code == 403
        config = BrandConfiguration().model_dump()
        config["assets"] = {"PRIMARY_LOGO": asset["id"]}
        assert client.patch("/api/v1/white-label/draft", json={"expected_revision": 0, "configuration": config}).status_code == 422


def test_asset_validation_private_draft_published_and_removal(monkeypatch, tmp_path):
    monkeypatch.setenv("BRAND_ASSET_DIR", str(tmp_path))
    with client_for() as client:
        assert client.post("/api/v1/white-label/assets?asset_type=PRIMARY_LOGO", files={"file": ("logo.svg", b"<svg><script/></svg>", "image/svg+xml")}).status_code == 422
        assert client.post("/api/v1/white-label/assets?asset_type=PRIMARY_LOGO", files={"file": ("logo.png", b"not an image", "image/png")}).status_code == 422
        assert client.post("/api/v1/white-label/assets?asset_type=FAVICON", files={"file": ("logo.png", png(64, 32), "image/png")}).status_code == 422
        assert client.post("/api/v1/white-label/assets?asset_type=PRIMARY_LOGO", files={"file": ("large.png", b"x" * (2 * 1024 * 1024 + 1), "image/png")}).status_code == 422
        response = client.post("/api/v1/white-label/assets?asset_type=PRIMARY_LOGO", files={"file": ("logo.png", png(), "image/png")})
        assert response.status_code == 201
        asset = response.json()
        assert "storage_key" not in asset
        private_token = client.cookies.get("setu_session")
        client.cookies.clear()
        assert client.get(asset["url"]).status_code == 401
        client.cookies.set("setu_session", private_token)
        settings = client.get("/api/v1/white-label").json()
        config = settings["configuration"]
        config["assets"] = {"PRIMARY_LOGO": asset["id"]}
        settings = client.patch("/api/v1/white-label/draft", json={"expected_revision": settings["revision"], "configuration": config}).json()
        publish(client, settings)
        assert client.delete(f'/api/v1/white-label/assets/{asset["id"]}').status_code == 409
        client.cookies.clear()
        image = client.get(asset["url"])
        assert image.status_code == 200 and image.headers["content-type"] == "image/png"
        with Image.open(BytesIO(image.content)) as decoded:
            assert decoded.size == (64, 64)


@pytest.mark.parametrize("change", [{"support_url": "javascript:alert(1)"}, {"privacy_url": "http://unsafe.org"}, {"brand_name": "<script>alert(1)</script>"}, {"light": {"primary": "red;display:none"}}, {"sender_name": "Evil\nBcc: secret@unsafe.org"}])
def test_unsafe_configuration_rejected(change):
    with client_for() as client:
        client.get("/api/v1/white-label")
        config = BrandConfiguration().model_dump()
        config.update(change)
        assert client.patch("/api/v1/white-label/draft", json={"expected_revision": 0, "configuration": config}).status_code == 422


def test_poor_contrast_can_be_saved_but_not_published():
    with client_for() as client:
        settings = client.get("/api/v1/white-label").json()
        config = settings["configuration"]
        config["light"]["text"] = "#ffffff"
        settings = client.patch("/api/v1/white-label/draft", json={"expected_revision": 0, "configuration": config}).json()
        assert settings["warnings"]
        assert client.post("/api/v1/white-label/publish", json={"expected_revision": settings["revision"]}).status_code == 422


@pytest.mark.parametrize("hostname", ["localhost", "127.0.0.1", "https://portal.customer.org", "portal.customer.org/path", "portal.customer.org:443", "portal.local", "portal.localhost.org.", "-bad.customer.org"])
def test_invalid_domains_are_rejected(hostname):
    if hostname == "portal.localhost.org.":
        # A public domain ending in .org is valid; localhost is only a label.
        assert validate_hostname(hostname) == "portal.localhost.org"
    else:
        with pytest.raises(ValueError):
            validate_hostname(hostname)


def test_domain_workflow_requires_dns_and_https_and_binds_session(monkeypatch):
    with client_for() as client:
        publish(client, draft(client))
        domain = client.post("/api/v1/white-label/domains", json={"hostname": "portal.customer.org"}).json()
        assert client.get("/api/v1/white-label/public?hostname=portal.customer.org").status_code == 404
        assert client.post(f'/api/v1/white-label/domains/{domain["id"]}/primary').status_code == 409
        monkeypatch.setattr("app.branding.verify_domain_records", lambda domain: (True, False))
        verified = client.post(f'/api/v1/white-label/domains/{domain["id"]}/verify').json()
        assert verified["status"] == "VERIFIED" and verified["ssl_status"] == "PENDING"
        assert client.get("/api/v1/white-label/public?hostname=portal.customer.org").status_code == 404
        with SessionLocal() as db:
            row = db.get(TenantDomain, domain["id"])
            row.last_checked_at = None
            db.commit()
        monkeypatch.setattr("app.branding.verify_domain_records", lambda domain: (True, True))
        assert client.post(f'/api/v1/white-label/domains/{domain["id"]}/verify').json()["status"] == "ACTIVE"
        assert client.post(f'/api/v1/white-label/domains/{domain["id"]}/primary').status_code == 200
        public = client.get("/api/v1/white-label/public?hostname=portal.customer.org").json()
        assert public["brand_name"] == "ABC Compliance" and "tenant_id" not in public and "configuration" not in public
        assert client.get("/api/v1/auth/me", headers={"X-Setu-Host": "portal.customer.org", "X-Setu-Proxy-Key": "setu-development-proxy"}).status_code == 200
        assert client.get("/api/v1/auth/me", headers={"X-Setu-Host": "unknown.customer.org", "X-Setu-Proxy-Key": "setu-development-proxy"}).status_code == 403
        assert client.delete(f'/api/v1/white-label/domains/{domain["id"]}').status_code == 204
        assert client.get("/api/v1/white-label/public?hostname=portal.customer.org").status_code == 404


def test_real_dns_comparison_and_https_ssrf_guard(monkeypatch):
    domain = TenantDomain(hostname="portal.customer.org", verification_token="setu-verify=secret")
    monkeypatch.setenv("WHITE_LABEL_CNAME_TARGET", "platform.host.org")
    monkeypatch.setattr("app.brand_domains.dns_records", lambda name, kind: ["setu-verify=wrong"] if kind == "TXT" else ["platform.host.org"])
    assert verify_domain_records(domain) == (False, False)
    monkeypatch.setattr("app.brand_domains.dns_records", lambda name, kind: ["setu-verify=secret"] if kind == "TXT" else ["platform.host.org"])
    monkeypatch.setattr("app.brand_domains.valid_https", lambda name: True)
    assert verify_domain_records(domain) == (True, True)
    # The original function rejects private addresses before opening a socket.
    monkeypatch.setattr("app.brand_domains.dns_records", lambda name, kind: ["127.0.0.1"])
    assert valid_https("portal.customer.org") is False


def test_certificate_ask_gate_requires_recorded_ownership_and_routing(monkeypatch):
    with client_for() as client:
        publish(client, draft(client))
        path = "/api/v1/white-label/domain-authorization?domain=portal.customer.org"
        assert client.get(path).status_code == 403
        row = client.post("/api/v1/white-label/domains", json={"hostname": "portal.customer.org"}).json()
        assert client.get(path).status_code == 403
        monkeypatch.setenv("WHITE_LABEL_CNAME_TARGET", "edge.platform.org")
        monkeypatch.setattr("app.brand_domains.dns_records", lambda name, kind: [row["txt_value"]] if kind == "TXT" else ["wrong.platform.org"])
        assert client.post(f'/api/v1/white-label/domains/{row["id"]}/verify').json()["status"] == "VERIFIED"
        assert client.get(path).status_code == 403  # TXT alone cannot authorize issuance.
        with SessionLocal() as db:
            db.get(TenantDomain, row["id"]).last_checked_at = None
            db.commit()
        monkeypatch.setattr("app.brand_domains.dns_records", lambda name, kind: [row["txt_value"]] if kind == "TXT" else ["edge.platform.org"])
        monkeypatch.setattr("app.brand_domains.valid_https", lambda hostname: False)
        assert client.post(f'/api/v1/white-label/domains/{row["id"]}/verify').json()["status"] == "VERIFIED"
        def no_network(*args):
            raise AssertionError("Certificate ask gate must never block on DNS/TLS")
        monkeypatch.setattr("app.brand_domains.dns_records", no_network)
        response = client.get(path)
        assert response.status_code == 204 and not response.content
        assert response.headers["cache-control"] == "no-store"
        monkeypatch.setenv("PLATFORM_ADMIN_EMAILS", "admin@white-label.test")
        with SessionLocal() as db:
            db.get(SessionContext, digest("white-label-session")).audience = "admin"
            db.commit()
        assert client.post(f'/api/v1/platform/white-label/tenant-demo/domains/{row["id"]}/suspend').status_code == 200
        assert client.get(path).status_code == 403
        assert client.post(f'/api/v1/white-label/domains/{row["id"]}/verify').status_code == 403
        assert client.post(f'/api/v1/platform/white-label/tenant-demo/domains/{row["id"]}/resume').status_code == 200
        assert client.get(path).status_code == 403  # Explicit re-verification required.


def test_subscription_downgrade_disables_brand_and_domain_without_deleting_history():
    with client_for() as client:
        settings = publish(client, draft(client))
        with SessionLocal() as db:
            domain = TenantDomain(tenant_id="tenant-demo", hostname="portal.customer.org", verification_token="token", status="ACTIVE", ssl_status="ACTIVE", routing_verified=True, verified_at=datetime.now(timezone.utc))
            db.add(domain)
            db.commit()
            assert active_domain(db, domain.hostname) is not None
            subscription = db.scalar(select(Subscription).where(Subscription.tenant_id == "tenant-demo"))
            subscription.status = "CANCELLED"
            db.commit()
            assert active_domain(db, domain.hostname) is None
        assert client.get("/api/v1/white-label/published").json()["enabled"] is False
        assert client.get("/api/v1/white-label/public?hostname=portal.customer.org").status_code == 404
        assert client.get("/api/v1/white-label/domain-authorization?domain=portal.customer.org").status_code == 403
        assert client.get("/api/v1/auth/me", headers={"X-Setu-Host": "portal.customer.org", "X-Setu-Proxy-Key": "setu-development-proxy"}).status_code == 403
        preserved = client.get("/api/v1/white-label").json()
        assert preserved["published_version"] == settings["published_version"] and preserved["history"]
        assert preserved["configuration"]["brand_name"] == "ABC Compliance"


def test_platform_admin_permission_entitlement_and_suspension(monkeypatch):
    with client_for() as client:
        settings = publish(client, draft(client))
        assert client.get("/api/v1/platform/white-label").status_code == 403
        monkeypatch.setenv("PLATFORM_ADMIN_EMAILS", "admin@white-label.test")
        with SessionLocal() as db:
            db.get(SessionContext, digest("white-label-session")).audience = "admin"
            db.commit()
        assert client.get("/api/v1/platform/white-label/access").json()["allowed"] is True
        assert client.get("/api/v1/platform/white-label").status_code == 200
        response = client.post("/api/v1/platform/white-label/tenant-demo/action", json={"action": "SUSPEND"})
        assert response.json()["status"] == "SUSPENDED"
        assert client.get("/api/v1/white-label/published").json()["enabled"] is False
        assert client.patch("/api/v1/white-label/draft", json={"expected_revision": response.json()["revision"], "configuration": settings["configuration"]}).status_code == 409
        assert client.post("/api/v1/platform/white-label/tenant-demo/action", json={"action": "RESUME"}).status_code == 200
        assert client.put("/api/v1/platform/white-label/tenant-demo/entitlement", json={"enabled": False}).status_code == 200
        assert client.get("/api/v1/white-label/published").json()["enabled"] is False
        assert client.get("/api/v1/white-label").json()["configuration"]["brand_name"] == "ABC Compliance"


def test_localized_brand_email_and_report_keep_client_identity():
    with client_for() as client:
        settings = client.get("/api/v1/white-label").json()
        config = settings["configuration"]
        config.update({"brand_name": "ABC Provider", "localized_taglines": {"kn-IN": "ಸರಳ ಅನುಸರಣೆ"}, "report_footer": "ABC Provider support"})
        settings = client.patch("/api/v1/white-label/draft", json={"expected_revision": 0, "configuration": config}).json()
        publish(client, settings)
        assert client.get("/api/v1/white-label/published?locale=kn-IN").json()["tagline"] == "ಸರಳ ಅನುಸರಣೆ"
        with SessionLocal() as db:
            email = render_email(db, "tenant-demo", "compliance.deadlineReminder", {"complianceName": "FCRA", "dueDate": "2026-09-11", "userName": "<script>"}, "kn-IN")
            assert email["locale"] == "kn-IN" and "ABC Provider" in email["html"]
            assert "&lt;script&gt;" in email["html"] and "<script>" not in email["html"]
        report = client.get("/api/v1/reports/compliance/print?organization_id=org-aarohan&locale=kn-IN")
        assert report.status_code == 200
        assert "ABC Provider" in report.text and "Aarohan Foundation" in report.text and 'lang="kn-IN"' in report.text
        assert client.get("/api/v1/reports/compliance/print?organization_id=unknown").status_code == 404
