"""Focused production security controls without external infrastructure."""
from uuid import uuid4
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base, engine
from app.database import SessionLocal
from app.bootstrap_schema import apply as bootstrap_schema
from app.auth import digest
from app.main import app
from app.models import AuthSession, Document, User
from app.phase8_models import OrganizationAccess
from app.production_security import (limit_expensive, ready_database,
                                     security_headers, validate_production_configuration,
                                     validate_production_schema)


def production_values():
    return {
        "APP_ENV": "production",
        "APP_ORIGIN": "https://app.example.org",
        "BRAND_PROXY_KEY": "a" * 32,
        "DATABASE_URL": "postgresql+psycopg://user:password@database/compliance",
        "PLATFORM_ADMIN_EMAILS": "operator@example.org",
        "PLATFORM_HOSTS": "app.example.org",
        "WHITE_LABEL_CNAME_TARGET": "edge.example.org",
        "BRAND_S3_BUCKET": "private-brand-assets",
        "INTEGRATION_SECRET_BACKEND": "aws",
        "DOCUMENT_S3_BUCKET": "private-documents",
    }


def test_production_preflight_rejects_unsafe_configuration_without_values_in_errors():
    values = production_values()
    validate_production_configuration(values)
    for key, bad in (
        ("APP_ORIGIN", "http://app.example.org"),
        ("BRAND_PROXY_KEY", "short"),
        ("DATABASE_URL", "sqlite:///data.db"),
        ("PLATFORM_ADMIN_EMAILS", ""),
        ("INTEGRATION_SECRET_BACKEND", "environment"),
        ("DOCUMENT_S3_BUCKET", ""),
        ("DOCUMENT_S3_ENDPOINT", "http://internal.example.org"),
    ):
        candidate = values | {key: bad}
        with pytest.raises(RuntimeError) as error:
            validate_production_configuration(candidate)
        if bad:
            assert bad not in str(error.value)
    validate_production_configuration(values | {"DOCUMENT_S3_BUCKET": "", "DOCUMENT_STORAGE_MANAGED_ONLY": "1"})


def test_production_requires_explicit_complete_schema():
    empty = create_engine("sqlite:///:memory:")
    try:
        with pytest.raises(RuntimeError, match="explicit migrations"):
            validate_production_schema(empty, Base.metadata)
        Base.metadata.create_all(empty)
        validate_production_schema(empty, Base.metadata)
    finally:
        empty.dispose()


def test_fresh_bootstrap_refuses_to_modify_existing_schema():
    empty = create_engine("sqlite:///:memory:")
    try:
        assert bootstrap_schema(empty) == len(Base.metadata.tables)
        with pytest.raises(RuntimeError, match="empty database"):
            bootstrap_schema(empty)
    finally:
        empty.dispose()


def test_health_readiness_headers_cors_and_auth_do_not_disclose_internal_state(monkeypatch):
    with TestClient(app) as client:
        assert client.get("/health").json()["status"] == "ok"
        ready = client.get("/ready")
        assert ready.status_code == 200 and ready.json() == {"status": "ready"}
        assert ready.headers["x-content-type-options"] == "nosniff"
        assert ready.headers["x-frame-options"] == "DENY"
        assert ready.headers["content-security-policy"] == "frame-ancestors 'none'"
        assert "strict-transport-security" not in ready.headers
        assert client.get("/api/v1/ai/conversations/test").status_code == 401
        denied = client.options("/api/v1/search", headers={
            "Origin": "https://evil.example.org", "Access-Control-Request-Method": "GET",
        })
        assert denied.headers.get("access-control-allow-origin") is None
        monkeypatch.setattr("app.main.ready_database", lambda _: False)
        failure = client.get("/ready")
        assert failure.status_code == 503 and failure.json() == {"status": "unavailable"}


def test_sensitive_body_limit_rejects_before_provider_or_webhook_dispatch():
    with TestClient(app) as client:
        for path in ("/api/v1/ai/retrieve", "/api/v1/assistant/query", "/api/v1/inbound-webhooks/missing"):
            response = client.post(path, content=b"x" * 17000)
            assert response.status_code == 413
            assert response.json() == {"detail": "Request body exceeds the limit"}
        streamed = client.post("/api/v1/ai/retrieve", content=iter([b"x" * 9000, b"y" * 9000]))
        assert streamed.status_code == 413, streamed.text
        same_origin = client.post("/api/v1/ai/retrieve", content=b"x" * 17000,
                                  headers={"Origin": "http://localhost:3000"})
        assert same_origin.status_code == 413
        assert same_origin.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_atomic_database_quota_returns_429_with_retry_after():
    with Session(engine) as db:
        actor = uuid4().hex
        limit_expensive(db, "tenant-a", actor, "ai-retrieve", 2)
        limit_expensive(db, "tenant-a", actor, "ai-retrieve", 2)
        with pytest.raises(HTTPException) as error:
            limit_expensive(db, "tenant-a", actor, "ai-retrieve", 2)
        assert error.value.status_code == 429
        assert error.value.headers["Retry-After"] == "60"
        limit_expensive(db, "tenant-b", actor, "ai-retrieve", 2)


def test_production_hsts_is_conditional():
    from starlette.responses import Response

    response = Response()
    security_headers(response, production=True)
    assert response.headers["strict-transport-security"] == "max-age=31536000"
    document_preview = Response(headers={"Content-Security-Policy": "sandbox; default-src 'none'"})
    security_headers(document_preview, production=False)
    assert document_preview.headers["content-security-policy"] == "sandbox; default-src 'none'; frame-ancestors 'none'"
    assert ready_database(engine)


def test_document_mutation_requires_organization_write_role_and_ids_are_scoped():
    with TestClient(app) as client:
        identifier = uuid4().hex
        token = "phase18-" + identifier
        with SessionLocal() as db:
            user = User(tenant_id="tenant-demo", name="Read only organization member",
                        email=identifier + "@example.test", role="MEMBER", status="ACTIVE")
            db.add(user); db.flush()
            db.add(AuthSession(token_hash=digest(token), user_id=user.id,
                               expires_at=datetime.now(timezone.utc) + timedelta(hours=1)))
            db.add(OrganizationAccess(tenant_id="tenant-demo", organization_id="org-udaan",
                                      user_id=user.id, granted_by=user.id, access_role="VIEWER"))
            own = Document(tenant_id="tenant-demo", organization_id="org-udaan",
                           name="Authorized metadata", category="Evidence", uploaded_by="Admin")
            other = Document(tenant_id="tenant-demo", organization_id="org-jal",
                             name="Other organization metadata", category="Evidence", uploaded_by="Admin")
            db.add_all((own, other)); db.commit()
            own_id, other_id = own.id, other.id
        client.cookies.set("setu_session", token)
        client.headers["X-Setu-Request"] = "1"
        assert client.get(f"/api/v1/documents/{own_id}/files").status_code == 200
        assert client.get(f"/api/v1/documents/{other_id}/files").status_code == 403
        assert client.post(f"/api/v1/documents/{own_id}/links", json={
            "target_type": "task", "target_id": "manipulated-id",
        }).status_code == 403
