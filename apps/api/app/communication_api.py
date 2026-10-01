"""Verified provider callbacks for existing external notification deliveries."""
import hashlib
import hmac
import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import select

from .auth import now
from .database import SessionLocal
from .integration_models import ConnectionSettings, IntegrationOperation
from .integration_security import IntegrationError, secret_store
from .models import IntegrationConnection, uid
from .notification_models import NotificationDelivery

router = APIRouter(prefix="/api/v1/integration-callbacks", tags=["Provider callbacks"])
MAX_CALLBACK_BYTES = 256 * 1024
STATUS_MAP = {"sent": "SENT", "delivered": "DELIVERED", "read": "READ", "failed": "FAILED"}
STATUS_RANK = {"QUEUED": 0, "RETRY": 0, "SENT": 1, "DELIVERED": 2, "READ": 3, "FAILED": 4}


def _connection(db, connection_id: str):
    row = db.execute(select(IntegrationConnection, ConnectionSettings).join(
        ConnectionSettings, ConnectionSettings.connection_id == IntegrationConnection.id,
    ).where(
        IntegrationConnection.id == connection_id,
        IntegrationConnection.provider == "meta_whatsapp",
        IntegrationConnection.status == "CONNECTED",
    )).first()
    if not row:
        raise HTTPException(404, "Callback not configured")
    return row


def _callback_credentials(state: ConnectionSettings) -> dict:
    try:
        value = json.loads(secret_store().get_secret_for_server_use(state.credential_reference))
        if not isinstance(value, dict) or not value.get("access_token") or not value.get("app_secret"):
            raise ValueError()
        return value
    except IntegrationError:
        raise
    except (TypeError, ValueError, json.JSONDecodeError):
        raise IntegrationError("INVALID_CONFIGURATION") from None


@router.get("/whatsapp/{connection_id}")
def verify_whatsapp(connection_id: str, hub_mode: str = Query(alias="hub.mode"),
                    hub_verify_token: str = Query(alias="hub.verify_token"),
                    hub_challenge: str = Query(alias="hub.challenge")):
    with SessionLocal() as db:
        _connection_row, state = _connection(db, connection_id)
        try:
            credentials = _callback_credentials(state)
        except IntegrationError:
            raise HTTPException(503, "Callback verification is unavailable") from None
        expected = str(credentials.get("verify_token", ""))
        if hub_mode != "subscribe" or not expected or not hmac.compare_digest(hub_verify_token, expected):
            raise HTTPException(403, "Callback verification failed")
        return int(hub_challenge) if hub_challenge.isdigit() else hub_challenge[:200]


@router.post("/whatsapp/{connection_id}")
async def whatsapp_status(connection_id: str, request: Request):
    if int(request.headers.get("content-length", "0") or 0) > MAX_CALLBACK_BYTES:
        raise HTTPException(413, "Callback payload is too large")
    body = await request.body()
    if len(body) > MAX_CALLBACK_BYTES:
        raise HTTPException(413, "Callback payload is too large")
    signature = request.headers.get("x-hub-signature-256", "")
    with SessionLocal() as db:
        connection, state = _connection(db, connection_id)
        try:
            credentials = _callback_credentials(state)
        except IntegrationError:
            raise HTTPException(503, "Callback verification is unavailable") from None
        expected = "sha256=" + hmac.new(credentials["app_secret"].encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise HTTPException(401, "Invalid callback signature")
        try:
            payload = json.loads(body)
            statuses = [status for entry in payload.get("entry", []) for change in entry.get("changes", [])
                        for status in change.get("value", {}).get("statuses", [])]
        except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
            raise HTTPException(422, "Invalid callback payload") from None
        updated = 0
        for item in statuses[:100]:
            if not isinstance(item, dict):
                continue
            provider_id = str(item.get("id", ""))[:200]
            normalized = STATUS_MAP.get(str(item.get("status", "")).lower())
            if not provider_id or not normalized:
                continue
            delivery = db.scalar(select(NotificationDelivery).where(
                NotificationDelivery.provider_connection_id == connection.id,
                NotificationDelivery.provider_message_id == provider_id,
            ))
            if not delivery or (connection.tenant_id != "__platform__" and delivery.tenant_id != connection.tenant_id):
                continue
            if STATUS_RANK.get(normalized, 0) <= STATUS_RANK.get(delivery.status, 0):
                continue
            occurred = now()
            timestamp = str(item.get("timestamp", ""))
            if timestamp.isdigit():
                try:
                    occurred = datetime.fromtimestamp(int(timestamp), timezone.utc)
                except (OSError, OverflowError, ValueError):
                    occurred = now()
            delivery.status = normalized
            delivery.provider_status_at = occurred
            delivery.updated_at = now()
            if normalized == "DELIVERED": delivery.delivered_at = occurred
            elif normalized == "READ": delivery.read_at = occurred
            elif normalized == "FAILED":
                delivery.failed_at = occurred
                code = str((item.get("errors") or [{}])[0].get("code", "PROVIDER_REJECTED"))
                delivery.last_error_code = "INVALID_RECIPIENT" if code in {"131026", "131047"} else "PROVIDER_REJECTED"
            updated += 1
        db.add(IntegrationOperation(id=uid(),tenant_id=connection.tenant_id,connection_id=connection.id,
            provider_key=connection.provider,operation="whatsapp.callback",status="SUCCESS",
            duration_ms=0,error_code="",completed_at=now()))
        db.commit()
        return {"accepted": True, "updated": updated}
