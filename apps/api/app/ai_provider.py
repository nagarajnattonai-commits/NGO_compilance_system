"""Provider-neutral AI contracts. Business services never depend on a vendor SDK."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from sqlalchemy import select

from .ai_models import AiProviderConfiguration
from .integration_security import IntegrationError, secret_store


PUBLIC_ERRORS = {
    "AI_DISABLED": "AI services are disabled for this workspace.",
    "AI_NOT_CONFIGURED": "AI services are not configured for this workspace.",
    "INVALID_CONFIGURATION": "The AI provider configuration is invalid.",
    "PROVIDER_UNAVAILABLE": "The AI provider is unavailable. Please try again later.",
    "TIMEOUT": "The AI provider did not respond in time.",
    "RATE_LIMITED": "The AI provider rate limit was reached. Please try again later.",
    "VECTOR_BACKEND_UNAVAILABLE": "The configured vector backend is unavailable.",
    "EXTRACTION_UNSUPPORTED": "Text extraction is not available for this document type.",
    "EXTRACTION_FAILED": "Document text extraction failed.",
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
class ConfiguredProvider:
    configuration: AiProviderConfiguration
    provider: AiProvider


def configured_provider(db, tenant_id: str) -> ConfiguredProvider:
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


def safe_provider_call(operation):
    try:
        return operation()
    except AiProviderError:
        raise
    except TimeoutError:
        raise AiProviderError("TIMEOUT") from None
    except Exception as error:
        code = getattr(error, "code", "")
        if code in {"RATE_LIMITED", "TIMEOUT", "PROVIDER_UNAVAILABLE"}:
            raise AiProviderError(code) from None
        raise AiProviderError("PROVIDER_UNAVAILABLE") from None
