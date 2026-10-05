"""Focused release-readiness contracts without live production dependencies."""
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.automation_service import schedule_scans
from app.database import Base
from app.document_storage import DocumentStorage
from app.brand_domains import request_hostname
from app.main import app
from app.models import Workspace
from app.production_ops import healthy, report
from app.production_security import build_metadata, validate_production_configuration


def production_values():
    return {
        "APP_ENV": "production", "APP_ORIGIN": "https://app.example.org",
        "BRAND_PROXY_KEY": "b" * 32, "DATABASE_URL": "postgresql+psycopg://user:password@db/app",
        "PLATFORM_ADMIN_EMAILS": "operator@example.org", "PLATFORM_HOSTS": "app.example.org",
        "WHITE_LABEL_CNAME_TARGET": "edge.example.org", "BRAND_S3_BUCKET": "private-brand-assets",
        "DOCUMENT_S3_BUCKET": "private-documents", "INTEGRATION_SECRET_BACKEND": "aws",
    }


def test_production_contract_rejects_unsafe_core_configuration_without_disclosing_values():
    values = production_values()
    validate_production_configuration(values)
    for key, bad in (
        ("DATABASE_URL", "sqlite:///secret-local.db"), ("PLATFORM_HOSTS", ""),
        ("WHITE_LABEL_CNAME_TARGET", ""), ("BRAND_S3_BUCKET", ""),
        ("DATABASE_POOL_SIZE", "5000"), ("DATABASE_CONNECT_TIMEOUT", "secret-timeout"),
        ("DOCUMENT_SCAN_REQUIRED", "true"),
    ):
        with pytest.raises(RuntimeError) as error:
            validate_production_configuration(values | {key: bad})
        if bad:
            assert bad not in str(error.value)


def test_build_metadata_is_bounded_and_never_reflects_secret_shaped_values():
    assert build_metadata({"APP_ENV": "production", "RELEASE_VERSION": "2026.10.1", "BUILD_SHA": "abc123"}) == {
        "version": "2026.10.1", "build": "abc123", "environment": "production",
    }
    unsafe = build_metadata({"APP_ENV": "production", "RELEASE_VERSION": "token value", "BUILD_SHA": "secret/value"})
    assert unsafe == {"version": "invalid", "build": "invalid", "environment": "production"}


def test_health_is_lightweight_correlated_and_optional_providers_do_not_gate_readiness():
    with TestClient(app) as client:
        health = client.get("/health", headers={"X-Request-ID": "attacker-controlled"})
        assert health.status_code == 200 and health.json()["status"] == "ok"
        UUID(health.headers["X-Request-ID"])
        assert health.json()["build"] and "secret" not in health.text.lower()
        assert client.get("/ready").status_code == 200


def test_arbitrary_forwarded_host_is_not_trusted(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("BRAND_PROXY_KEY", "c" * 32)
    scope = {"type": "http", "method": "GET", "scheme": "https", "server": ("app.example.org", 443),
             "path": "/", "query_string": b"", "headers": [(b"x-forwarded-host", b"foreign.example.org")]}
    assert request_hostname(Request(scope)) == "app.example.org"
    scope["headers"] = [(b"x-setu-host", b"portal.customer.org"), (b"x-setu-proxy-key", ("c" * 32).encode())]
    assert request_hostname(Request(scope)) == "portal.customer.org"


def test_schema_integrity_check_is_read_only_and_scheduler_is_duplicate_safe():
    target = create_engine("sqlite:///:memory:")
    try:
        Base.metadata.create_all(target)
        with Session(target) as db:
            db.add(Workspace(id="release-tenant", name="Release rehearsal")); db.commit()
            first = schedule_scans(db)
            second = schedule_scans(db)
            assert first["created"] > 0 and second["created"] == 0 and second["replayed"] == first["created"]
        result = report(target)
        assert healthy(result) and result["missing_table_count"] == 0
    finally:
        target.dispose()


def test_production_document_storage_never_falls_back_to_local(monkeypatch):
    target = create_engine("sqlite:///:memory:")
    try:
        Base.metadata.create_all(target)
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.delenv("DOCUMENT_S3_BUCKET", raising=False)
        with Session(target) as db, pytest.raises(RuntimeError, match="private S3"):
            DocumentStorage(db, "missing-tenant")
    finally:
        target.dispose()
