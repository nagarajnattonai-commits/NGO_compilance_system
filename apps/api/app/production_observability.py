"""Small production-safe request correlation and structured access logging."""
import json
import logging
import time
from uuid import UUID, uuid4

logger = logging.getLogger("setu.access")


def request_id(value: str | None) -> str:
    try:
        return str(UUID(value)) if value else str(uuid4())
    except (ValueError, TypeError, AttributeError):
        return str(uuid4())


def access_record(request, response, started: float) -> str:
    record = {
        "event": "http_request",
        "request_id": request.state.request_id,
        "method": request.method,
        "path": request.url.path,
        "status": response.status_code,
        "duration_ms": max(0, int((time.monotonic() - started) * 1000)),
    }
    tenant_id = getattr(request.state, "tenant_id", "")
    if tenant_id:
        record["tenant_id"] = tenant_id
    return json.dumps(record, separators=(",", ":"), sort_keys=True)
