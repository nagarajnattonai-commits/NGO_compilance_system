"""Focused Phase 23 production provider, routing, safety and retry contracts."""
import json
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.ai_provider import AiProviderError, configured_ocr_provider, configured_provider
from app.ai_service import status as ai_status
from app.automation_service import error_code
from app.integration_models import ConnectionSettings, IntegrationOperation
from app.integration_providers import OpenAIConfiguration, OpenAIOcrConfiguration
from app.integration_security import IntegrationError
from app.main import app as _app  # Import all model modules before test schema creation.
from app.models import IntegrationConnection, Subscription, TenantEntitlement
from app.production_ai_adapters import OpenAICompatibleAdapter, OpenAIResponsesOcrAdapter
from app.database import SessionLocal


AI_CONFIG = {
    "endpoint": "https://api.openai.com/v1",
    "generation_model": "gpt-test",
    "embedding_model": "embed-test",
    "embedding_dimensions": 64,
    "timeout_seconds": 12,
    "max_output_tokens": 128,
    "max_batch_size": 4,
}
OCR_CONFIG = {
    "endpoint": "https://api.openai.com/v1",
    "model": "ocr-test",
    "timeout_seconds": 12,
    "max_pages": 4,
    "max_output_tokens": 512,
    "max_output_characters": 4000,
}


def _connection(db, *, tenant="tenant-demo", category="AI", provider="openai_compatible", config=None,
                status="CONNECTED", scope="TENANT", fallback=False, identifier="1" * 32):
    connection = IntegrationConnection(
        id=identifier, tenant_id=tenant, provider=provider, category=category, status=status,
    )
    state = ConnectionSettings(
        connection_id=connection.id, scope=scope, display_name="Production provider",
        environment="PRODUCTION", configuration=json.dumps(config or AI_CONFIG),
        credential_reference="env://SETU_SECRET_" + identifier.upper(), credential_suffix="cret",
        fallback_allowed=fallback, created_by="test", updated_by="test",
    )
    db.add_all((connection, state))
    db.flush()
    return connection


def _entitle(db, feature_key):
    if not db.scalar(select(Subscription).where(Subscription.tenant_id == "tenant-demo")):
        db.add(Subscription(tenant_id="tenant-demo", plan_name="ENTERPRISE", status="ACTIVE",
                            period_end=date.today() + timedelta(days=30)))
    db.add(TenantEntitlement(tenant_id="tenant-demo", feature_key=feature_key, enabled=True))


def test_generation_embedding_and_ocr_adapters_are_bounded(monkeypatch):
    requests = []

    def fake_http(url, *, body, headers, timeout_seconds, max_response_bytes=1_000_000):
        requests.append((url, body, headers, timeout_seconds, max_response_bytes))
        if url.endswith("/embeddings"):
            return 200, 60, {"data": [{"index": 1, "embedding": [3] * 64}, {"index": 0, "embedding": [1] * 64}]}
        if url.endswith("/responses"):
            return 200, 60, {"output_text": " Registration: 1234 "}
        return 200, 60, {"choices": [{"message": {"content": "Grounded answer"}}]}

    monkeypatch.setattr("app.production_ai_adapters.validate_url", lambda *_: None)
    monkeypatch.setattr("app.production_ai_adapters.safe_json_http", fake_http)
    ai = OpenAICompatibleAdapter(AI_CONFIG, "never-log-this-secret")
    assert ai.generate(system="safe", user="question", model="gpt-test", timeout_seconds=12) == "Grounded answer"
    assert ai.embed(texts=["one", "two"], model="embed-test", timeout_seconds=12) == [[1.0] * 64, [3.0] * 64]
    ocr = OpenAIResponsesOcrAdapter(OCR_CONFIG, "never-log-this-secret")
    assert ocr.extract(b"image", "image/png") == "Registration: 1234"
    assert all(request[2]["Authorization"] == "Bearer never-log-this-secret" for request in requests)
    with pytest.raises(IntegrationError) as unsupported:
        ai.generate(system="", user="x", model="wrong", timeout_seconds=12)
    assert unsupported.value.code == "UNSUPPORTED_MODEL"
    with pytest.raises(IntegrationError) as bounded:
        ai.embed(texts=["x"] * 5, model="embed-test", timeout_seconds=12)
    assert bounded.value.code == "MALFORMED_REQUEST"


def test_tenant_provider_precedes_platform_fallback_and_records_safe_telemetry(monkeypatch):
    monkeypatch.setenv("SETU_SECRET_11111111111111111111111111111111", "tenant-secret")
    monkeypatch.setattr("app.production_ai_adapters.validate_url", lambda *_: None)
    monkeypatch.setattr(
        "app.production_ai_adapters.safe_json_http",
        lambda *_, **__: (200, 60, {"data": [{"index": 0, "embedding": [0.1] * 64}]}),
    )
    with SessionLocal() as db:
        _entitle(db, "ai_rag")
        tenant = _connection(db)
        _connection(db, tenant="__platform__", scope="PLATFORM", fallback=True, identifier="2" * 32)
        provider = configured_provider(db, "tenant-demo")
        assert provider.configuration.source == "TENANT"
        safe_status = ai_status(db, "tenant-demo", SimpleNamespace(_admin_audience=False))
        assert safe_status["provider"] == "openai_compatible" and safe_status["credentials_exposed"] is False
        assert "secret" not in json.dumps(safe_status).lower()
        assert provider.provider.embed(texts=["bounded"], model="embed-test", timeout_seconds=12) == [[0.1] * 64]
        db.commit()
        operation = db.scalar(select(IntegrationOperation).where(IntegrationOperation.connection_id == tenant.id))
        assert operation and operation.status == "SUCCEEDED" and operation.operation == "ai.embedding"
        assert "secret" not in json.dumps(operation.__dict__, default=str).lower()


def test_explicit_disabled_provider_never_silently_falls_back_to_legacy(monkeypatch):
    with SessionLocal() as db:
        _entitle(db, "ai_rag")
        _connection(db, status="DISABLED")
        db.commit()
        with pytest.raises(AiProviderError) as error:
            configured_provider(db, "tenant-demo")
        assert error.value.code == "PROVIDER_DISABLED"


def test_ocr_routing_uses_tenant_secret_and_provider_errors_are_retryable(monkeypatch):
    monkeypatch.setenv("SETU_SECRET_33333333333333333333333333333333", "rotated-ocr-secret")
    monkeypatch.setattr("app.production_ai_adapters.validate_url", lambda *_: None)

    def fake_http(_url, *, headers, **_kwargs):
        assert headers["Authorization"] == "Bearer rotated-ocr-secret"
        return 200, 60, {"output_text": "Visible filing acknowledgement"}

    monkeypatch.setattr("app.production_ai_adapters.safe_json_http", fake_http)
    with SessionLocal() as db:
        _entitle(db, "document_intelligence")
        _connection(db, category="OCR", provider="openai_responses_ocr", config=OCR_CONFIG, identifier="3" * 32)
        provider = configured_ocr_provider(db, "tenant-demo")
        assert provider.extract(b"image", "image/png") == "Visible filing acknowledgement"
    assert error_code(AiProviderError("TIMEOUT")) == ("TIMEOUT", True)
    assert error_code(AiProviderError("INVALID_CREDENTIAL")) == ("INVALID_CREDENTIAL", False)


def test_provider_schemas_reject_unknown_and_unbounded_configuration():
    with pytest.raises(Exception):
        OpenAIConfiguration.model_validate({**AI_CONFIG, "timeout_seconds": 121})
    with pytest.raises(Exception):
        OpenAIOcrConfiguration.model_validate({**OCR_CONFIG, "max_pages": 101})
    with pytest.raises(Exception):
        OpenAIConfiguration.model_validate({**AI_CONFIG, "api_key": "must-not-be-stored"})
