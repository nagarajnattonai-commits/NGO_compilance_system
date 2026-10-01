"""Provider-neutral AI contracts. Business services never depend on a vendor SDK."""
from __future__ import annotations

from dataclasses import dataclass
import json
import time
from typing import Callable, Protocol

from sqlalchemy import select

from .ai_models import AiProviderConfiguration
from .integration_models import ConnectionSettings, IntegrationOperation
from .integration_security import IntegrationError, secret_store
from .models import IntegrationConnection, uid, utcnow


PUBLIC_ERRORS = {
    "AI_DISABLED": "AI services are disabled for this workspace.",
    "AI_NOT_CONFIGURED": "AI services are not configured for this workspace.",
    "PROVIDER_NOT_CONFIGURED": "The requested provider capability is not configured.",
    "PROVIDER_DISABLED": "The configured provider is disabled.",
    "INVALID_CREDENTIAL": "The provider credential is invalid. Replace it and test the connection.",
    "UNSUPPORTED_MODEL": "The configured provider model is not supported.",
    "MALFORMED_REQUEST": "The provider rejected the bounded request configuration.",
    "INVALID_CONFIGURATION": "The AI provider configuration is invalid.",
    "PROVIDER_UNAVAILABLE": "The AI provider is unavailable. Please try again later.",
    "TIMEOUT": "The AI provider did not respond in time.",
    "RATE_LIMITED": "The AI provider rate limit was reached. Please try again later.",
    "VECTOR_BACKEND_UNAVAILABLE": "The configured vector backend is unavailable.",
    "EXTRACTION_UNSUPPORTED": "Text extraction is not available for this document type.",
    "EXTRACTION_FAILED": "Document text extraction failed.",
    "OCR_UNAVAILABLE": "OCR is not configured for this workspace.",
    "OCR_FAILED": "OCR could not process this document.",
    "OCR_PAYLOAD_TOO_LARGE": "The document is too large for OCR processing.",
}


class AiProviderError(Exception):
    def __init__(self, code: str):
        self.code = code if code in PUBLIC_ERRORS else "PROVIDER_UNAVAILABLE"
        super().__init__(PUBLIC_ERRORS[self.code])


class AiProvider(Protocol):
    def generate(self, *, system: str, user: str, model: str, timeout_seconds: int) -> str: ...
    def embed(self, *, texts: list[str], model: str, timeout_seconds: int) -> list[list[float]]: ...


ProviderFactory = Callable[[str], AiProvider]
_providers: dict[str, ProviderFactory] = {}


def register_provider(name: str, factory: ProviderFactory) -> None:
    _providers[name.strip().lower()] = factory


def clear_providers() -> None:
    _providers.clear()


@dataclass(frozen=True)
class RuntimeProviderConfiguration:
    provider: str
    generation_model: str
    embedding_model: str
    timeout_seconds: int
    source: str = "TENANT"


@dataclass(frozen=True)
class ConfiguredProvider:
    configuration: AiProviderConfiguration | RuntimeProviderConfiguration
    provider: AiProvider


def provider_error_from_integration(error: IntegrationError) -> AiProviderError:
    mapping={
        "INTEGRATION_NOT_CONFIGURED":"PROVIDER_NOT_CONFIGURED",
        "AUTHENTICATION_FAILED":"INVALID_CREDENTIAL",
        "INVALID_CONFIGURATION":"INVALID_CONFIGURATION",
        "UNSUPPORTED_MODEL":"UNSUPPORTED_MODEL",
        "MALFORMED_REQUEST":"MALFORMED_REQUEST",
        "PROVIDER_DISABLED":"PROVIDER_DISABLED",
        "RATE_LIMITED":"RATE_LIMITED",
        "PROVIDER_UNAVAILABLE":"PROVIDER_UNAVAILABLE",
        "TIMEOUT":"TIMEOUT",
        "PERMISSION_DENIED":"PROVIDER_NOT_CONFIGURED",
        "SECRET_STORE_UNAVAILABLE":"PROVIDER_UNAVAILABLE",
    }
    return AiProviderError(mapping.get(error.code,"PROVIDER_UNAVAILABLE"))


def _configured_integrations(db, tenant_id: str, category: str):
    """Find explicit tenant or eligible platform configuration, regardless of health."""
    from .integration_providers import REGISTRY
    from .integration_service import PLATFORM_OWNER

    keys = [definition.key for definition in REGISTRY.values() if definition.category == category]
    if not keys:
        return []
    rows = db.execute(
        select(IntegrationConnection, ConnectionSettings)
        .join(ConnectionSettings, ConnectionSettings.connection_id == IntegrationConnection.id)
        .where(
            IntegrationConnection.provider.in_(keys),
            IntegrationConnection.tenant_id.in_((tenant_id, PLATFORM_OWNER)),
            ConnectionSettings.environment == "PRODUCTION",
        )
    ).all()
    return [
        (connection, state)
        for connection, state in rows
        if (connection.tenant_id == tenant_id and state.scope == "TENANT")
        or (connection.tenant_id == PLATFORM_OWNER and state.scope == "PLATFORM" and state.fallback_allowed)
    ]


def _resolution_error(db, tenant_id: str, category: str, error: IntegrationError):
    rows = _configured_integrations(db, tenant_id, category)
    if not rows:
        return None
    if all(connection.status == "DISABLED" for connection, _state in rows):
        return AiProviderError("PROVIDER_DISABLED")
    return provider_error_from_integration(error)


class _ObservedProvider:
    def __init__(self, db, tenant_id, connection, adapter):
        self.db,self.tenant_id,self.connection,self.adapter=db,tenant_id,connection,adapter

    def _call(self, capability, operation):
        started=time.perf_counter();error_code="";status="SUCCEEDED"
        try:return operation()
        except IntegrationError as error:
            status="FAILED";error_code=provider_error_from_integration(error).code
            raise provider_error_from_integration(error) from None
        except AiProviderError as error:
            status="FAILED";error_code=error.code;raise
        except TimeoutError:
            status="FAILED";error_code="TIMEOUT";raise AiProviderError("TIMEOUT") from None
        except Exception:
            status="FAILED";error_code="PROVIDER_UNAVAILABLE";raise AiProviderError("PROVIDER_UNAVAILABLE") from None
        finally:
            self.db.add(IntegrationOperation(id=uid(),tenant_id=self.tenant_id,connection_id=self.connection.id,
                provider_key=self.connection.provider,operation=capability,status=status,
                duration_ms=max(0,int((time.perf_counter()-started)*1000)),error_code=error_code,
                completed_at=utcnow()))

    def generate(self, **kwargs):return self._call("ai.generation",lambda:self.adapter.generate(**kwargs))
    def embed(self, **kwargs):return self._call("ai.embedding",lambda:self.adapter.embed(**kwargs))


class ObservedOcrProvider:
    def __init__(self, db, tenant_id, connection, adapter):
        self.observed=_ObservedProvider(db,tenant_id,connection,adapter)
    def extract(self, content, mime_type):
        return self.observed._call("ocr.extraction",lambda:self.observed.adapter.extract(content,mime_type))


def configured_provider(db, tenant_id: str) -> ConfiguredProvider:
    from .integration_service import resolve_integration
    from .integration_providers import get_provider
    try:
        connection,state,adapter=resolve_integration(db,tenant_id,"AI","ai.generate",environment="PRODUCTION")
        config=json.loads(state.configuration)
        if "ai.embed" not in get_provider(connection.provider).capabilities:
            raise AiProviderError("INVALID_CONFIGURATION")
        return ConfiguredProvider(RuntimeProviderConfiguration(
            provider=connection.provider,generation_model=config["generation_model"],
            embedding_model=config["embedding_model"],timeout_seconds=config["timeout_seconds"],source=state.scope,
        ),_ObservedProvider(db,tenant_id,connection,adapter))
    except AiProviderError:
        raise
    except IntegrationError as error:
        resolution_error = _resolution_error(db, tenant_id, "AI", error)
        if resolution_error:
            raise resolution_error from None
        # Preserve the explicitly configured Phase 16 provider only when no
        # production integration has been configured at either scope.
    row = db.scalar(select(AiProviderConfiguration).where(AiProviderConfiguration.tenant_id == tenant_id))
    if not row:
        raise AiProviderError("AI_NOT_CONFIGURED")
    if not row.enabled:
        raise AiProviderError("AI_DISABLED")
    if not row.provider.strip() or not row.generation_model.strip() or not row.embedding_model.strip() or not 1 <= row.timeout_seconds <= 120:
        raise AiProviderError("INVALID_CONFIGURATION")
    factory = _providers.get(row.provider.lower())
    if not factory:
        raise AiProviderError("PROVIDER_UNAVAILABLE")
    try:
        credential = secret_store().get_secret_for_server_use(row.credential_reference)
    except IntegrationError as error:
        code = "AI_NOT_CONFIGURED" if error.code == "INTEGRATION_NOT_CONFIGURED" else "INVALID_CONFIGURATION"
        raise AiProviderError(code) from None
    try:
        return ConfiguredProvider(row, factory(credential))
    except AiProviderError:
        raise
    except Exception:
        raise AiProviderError("PROVIDER_UNAVAILABLE") from None


def configured_ocr_provider(db, tenant_id: str):
    from .integration_service import resolve_integration
    try:
        connection,_state,adapter=resolve_integration(db,tenant_id,"OCR","ocr.extract",environment="PRODUCTION")
        return ObservedOcrProvider(db,tenant_id,connection,adapter)
    except IntegrationError as error:
        resolution_error = _resolution_error(db, tenant_id, "OCR", error)
        if resolution_error:
            raise resolution_error from None
        return None


def safe_provider_call(operation):
    try:
        return operation()
    except AiProviderError:
        raise
    except TimeoutError:
        raise AiProviderError("TIMEOUT") from None
    except IntegrationError as error:
        raise provider_error_from_integration(error) from None
    except Exception as error:
        code = getattr(error, "code", "")
        if code in {"RATE_LIMITED", "TIMEOUT", "PROVIDER_UNAVAILABLE"}:
            raise AiProviderError(code) from None
        raise AiProviderError("PROVIDER_UNAVAILABLE") from None
