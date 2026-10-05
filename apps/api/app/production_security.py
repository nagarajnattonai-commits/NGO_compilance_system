"""Production preflight and small, non-disclosing HTTP security controls."""
from __future__ import annotations

import os
import re
from urllib.parse import urlsplit

from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import JSONResponse


def validate_production_configuration(environment=None) -> None:
    values = os.environ if environment is None else environment
    if values.get("APP_ENV") != "production":
        return
    origin = urlsplit(values.get("APP_ORIGIN", ""))
    if (origin.scheme != "https" or not origin.hostname or origin.username or origin.password
            or origin.path not in ("", "/") or origin.query or origin.fragment):
        raise RuntimeError("Production APP_ORIGIN must be an HTTPS origin")
    if len(values.get("BRAND_PROXY_KEY", "")) < 32:
        raise RuntimeError("Production requires a shared BRAND_PROXY_KEY of at least 32 characters")
    database_url = values.get("DATABASE_URL", "")
    if not database_url.startswith("postgresql+psycopg://"):
        raise RuntimeError("Production requires an explicit PostgreSQL DATABASE_URL")
    if not values.get("PLATFORM_ADMIN_EMAILS", "").strip():
        raise RuntimeError("Production requires a platform administrator allowlist")
    if values.get("INTEGRATION_SECRET_BACKEND") != "aws":
        raise RuntimeError("Production requires the AWS integration secret store")
    if not values.get("PLATFORM_HOSTS", "").strip():
        raise RuntimeError("Production requires an explicit PLATFORM_HOSTS allowlist")
    if not values.get("WHITE_LABEL_CNAME_TARGET", "").strip():
        raise RuntimeError("Production requires the white-label TLS edge hostname")
    if not values.get("BRAND_S3_BUCKET", "").strip():
        raise RuntimeError("Production requires private object storage for brand assets")
    if not values.get("DOCUMENT_S3_BUCKET", "").strip() and values.get("DOCUMENT_STORAGE_MANAGED_ONLY") != "1":
        raise RuntimeError("Production requires private S3 document storage or explicit managed-only storage")
    endpoint = values.get("DOCUMENT_S3_ENDPOINT", "")
    if endpoint and not endpoint.startswith("https://"):
        raise RuntimeError("Production document storage endpoint must use HTTPS")
    for key, default, minimum, maximum in (
        ("DATABASE_POOL_SIZE", 10, 1, 50),
        ("DATABASE_MAX_OVERFLOW", 20, 0, 100),
        ("DATABASE_POOL_TIMEOUT", 10, 1, 60),
        ("DATABASE_CONNECT_TIMEOUT", 10, 1, 60),
    ):
        try:
            value = int(values.get(key, str(default)))
        except (TypeError, ValueError):
            raise RuntimeError(f"Production {key} must be an integer") from None
        if not minimum <= value <= maximum:
            raise RuntimeError(f"Production {key} is outside the supported range")
    if values.get("DOCUMENT_SCAN_REQUIRED", "false").lower() == "true":
        raise RuntimeError("Production document scanning is required but no scanner adapter is configured")


def build_metadata(environment=None) -> dict[str, str]:
    values = os.environ if environment is None else environment
    version = values.get("RELEASE_VERSION", "0.25.0")
    build = values.get("BUILD_SHA", "development")
    safe = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
    return {
        "version": version if safe.fullmatch(version) else "invalid",
        "build": build if safe.fullmatch(build) else "invalid",
        "environment": values.get("APP_ENV", "development") if values.get("APP_ENV", "development") in {"development", "test", "production"} else "unknown",
    }


def validate_production_schema(engine, metadata) -> None:
    existing = set(inspect(engine).get_table_names())
    missing = set(metadata.tables) - existing
    if missing:
        raise RuntimeError("Production database schema is incomplete; apply the explicit migrations before startup")


def ready_database(engine) -> bool:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError:
        return False


def security_headers(response, *, production: bool) -> None:
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Frame-Options"] = "DENY"
    existing_csp = response.headers.get("Content-Security-Policy", "")
    response.headers["Content-Security-Policy"] = (
        existing_csp + "; frame-ancestors 'none'" if existing_csp and "frame-ancestors" not in existing_csp
        else existing_csp or "frame-ancestors 'none'"
    )
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if production:
        response.headers["Strict-Transport-Security"] = "max-age=31536000"


def limit_expensive(db, tenant_id: str, user_id: str, operation: str,
                    maximum: int, seconds: int = 60) -> None:
    from .integration_service import quota
    quota(db, f"security:{operation}:{tenant_id}:{user_id}", maximum, seconds)


class BoundedSensitiveBody:
    """Reject large AI and inbound webhook bodies before request parsing."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") not in {"POST", "PUT", "PATCH"}:
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        if not (path.startswith("/api/v1/ai/") or path == "/api/v1/assistant/query"
                or path.startswith("/api/v1/inbound-webhooks/")):
            return await self.app(scope, receive, send)
        limit = 16 * 1024
        headers = dict(scope.get("headers", []))

        async def reject():
            await JSONResponse({"detail": "Request body exceeds the limit"}, status_code=413)(scope, receive, send)

        try:
            declared = int(headers.get(b"content-length", b"0"))
        except ValueError:
            return await reject()
        if declared > limit or declared < 0:
            return await reject()
        consumed = 0
        buffered = []
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            consumed += len(message.get("body", b""))
            if consumed > limit:
                return await reject()
            buffered.append(message)
            if not message.get("more_body", False):
                break
        index = 0

        async def replay_receive():
            nonlocal index
            if index < len(buffered):
                message = buffered[index]
                index += 1
                return message
            return await receive()

        await self.app(scope, replay_receive, send)
