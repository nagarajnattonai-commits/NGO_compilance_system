"""Safe Google Calendar OAuth, policy, status and retry APIs."""
from __future__ import annotations

import hashlib
import json
import secrets
from datetime import timedelta
from typing import Literal
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import Field
from sqlalchemy import delete, func, select

from .auth import CurrentUser, aware, digest, now
from .automation_service import queue_job
from .calendar_service import (
    CALENDAR_SCOPE,
    GOOGLE_AUTH,
    GOOGLE_TOKEN,
    calendar_adapter,
    callback_url,
    oauth_client,
    policy_for,
    queue_all,
    safe_token,
)
from .features import can_use_feature
from .integration_models import ConnectionSettings
from .integration_providers import CalendarConfiguration
from .integration_security import IntegrationError, public_error, require_success, safe_http, secret_store
from .integration_service import audit, log_operation
from .models import IntegrationConnection
from .organization_access import accessible_organization_ids, require_organization_access
from .organization_profile import DB, Strict, Tenant
from .permissions import has_permission
from .phase10_models import CalendarEventMapping, CalendarOAuthState, CalendarSyncPolicy

router = APIRouter(prefix="/api/v1/calendar", tags=["Calendar integration"])


class CalendarPolicyInput(Strict):
    calendar_id: str = Field(min_length=1, max_length=200)
    sync_statutory_deadlines: bool = True
    sync_internal_targets: bool = True
    sync_tasks: bool = True
    closed_behavior: Literal["UPDATE", "CANCEL"] = "UPDATE"


def manage(user) -> None:
    if not has_permission(user, "integrations.tenant.manage"):
        raise HTTPException(403, "Required integration permission is missing")


def view(user) -> None:
    if not has_permission(user, "integrations.tenant.view"):
        raise HTTPException(403, "Required integration permission is missing")


def entitled(db, tenant_id: str) -> None:
    if not can_use_feature(db, tenant_id, "google_calendar_integration"):
        raise HTTPException(403, "Google Calendar is not enabled for this workspace subscription")


def google_connection(db, tenant_id: str, connection_id: str):
    row = db.execute(select(IntegrationConnection, ConnectionSettings).join(
        ConnectionSettings, ConnectionSettings.connection_id == IntegrationConnection.id
    ).where(
        IntegrationConnection.id == connection_id,
        IntegrationConnection.tenant_id == tenant_id,
        IntegrationConnection.provider == "google_calendar",
        ConnectionSettings.scope == "TENANT",
    )).first()
    if not row:
        raise HTTPException(404, "Google Calendar connection not found")
    return row


def policy_output(policy: CalendarSyncPolicy | None) -> dict:
    return {
        "sync_statutory_deadlines": policy.sync_statutory_deadlines if policy else True,
        "sync_internal_targets": policy.sync_internal_targets if policy else True,
        "sync_tasks": policy.sync_tasks if policy else True,
        "closed_behavior": policy.closed_behavior if policy else "UPDATE",
    }


@router.get("/status")
def calendar_status(db: DB, tenant: Tenant, user: CurrentUser):
    view(user)
    enabled = can_use_feature(db, tenant, "google_calendar_integration")
    allowed = accessible_organization_ids(db, tenant, user.id)
    results = []
    rows = db.execute(select(IntegrationConnection, ConnectionSettings).join(
        ConnectionSettings, ConnectionSettings.connection_id == IntegrationConnection.id
    ).where(
        IntegrationConnection.tenant_id == tenant,
        IntegrationConnection.provider == "google_calendar",
        ConnectionSettings.scope == "TENANT",
    ).order_by(ConnectionSettings.updated_at.desc())).all()
    for connection, state in rows:
        mapping_filter = [CalendarEventMapping.tenant_id == tenant, CalendarEventMapping.connection_id == connection.id]
        if allowed is not None:
            mapping_filter.append(CalendarEventMapping.organization_id.in_(allowed))
        counts = dict(db.execute(select(CalendarEventMapping.sync_status, func.count()).where(
            *mapping_filter
        ).group_by(CalendarEventMapping.sync_status)).all())
        mappings = db.scalars(select(CalendarEventMapping).where(*mapping_filter).order_by(
            CalendarEventMapping.updated_at.desc()
        ).limit(50)).all()
        policy = db.get(CalendarSyncPolicy, connection.id)
        configuration = CalendarConfiguration.model_validate_json(state.configuration)
        results.append({
            "connection_id": connection.id,
            "status": connection.status,
            "calendar_id": configuration.calendar_id,
            "oauth_connected": bool(state.credential_suffix),
            "last_synced_at": connection.last_synced_at,
            "error_code": state.error_code,
            "policy": policy_output(policy),
            "sync_counts": {key: counts.get(key, 0) for key in ("QUEUED", "SYNCED", "RETRY", "FAILED", "CANCELLED", "DISCONNECTED")},
            "mappings": [{"id": row.id, "organization_id": row.organization_id, "entity_type": row.entity_type,
                          "entity_id": row.entity_id, "event_kind": row.event_kind, "sync_status": row.sync_status,
                          "last_synced_at": row.last_synced_at, "error_code": row.error_code} for row in mappings],
        })
    return {"entitled": enabled, "connections": results}


@router.patch("/connections/{connection_id}/policy")
def update_policy(connection_id: str, payload: CalendarPolicyInput, db: DB, tenant: Tenant, user: CurrentUser):
    manage(user)
    entitled(db, tenant)
    connection, state = google_connection(db, tenant, connection_id)
    configuration = CalendarConfiguration(calendar_id=payload.calendar_id)
    previous_configuration = CalendarConfiguration.model_validate_json(state.configuration)
    if connection.status == "CONNECTED" and previous_configuration.calendar_id != configuration.calendar_id and db.scalar(select(
        CalendarEventMapping.id
    ).where(
        CalendarEventMapping.tenant_id == tenant,
        CalendarEventMapping.connection_id == connection.id,
        CalendarEventMapping.last_synced_at.is_not(None),
    ).limit(1)):
        raise HTTPException(409, "Disconnect the synchronized calendar before selecting a different calendar")
    state.configuration = configuration.model_dump_json()
    policy = policy_for(db, tenant, connection.id, user.id)
    previous = {"STATUTORY": policy.sync_statutory_deadlines, "INTERNAL": policy.sync_internal_targets,
                "TASK": policy.sync_tasks}
    policy.sync_statutory_deadlines = payload.sync_statutory_deadlines
    policy.sync_internal_targets = payload.sync_internal_targets
    policy.sync_tasks = payload.sync_tasks
    policy.closed_behavior = payload.closed_behavior
    policy.updated_by = user.id
    policy.updated_at = now()
    state.updated_by = user.name
    state.updated_at = now()
    if previous_configuration.calendar_id != configuration.calendar_id:
        for mapping in db.scalars(select(CalendarEventMapping).where(
            CalendarEventMapping.tenant_id == tenant,
            CalendarEventMapping.connection_id == connection.id,
        )):
            mapping.calendar_id = configuration.calendar_id
            mapping.last_synced_at = None
            mapping.sync_status = "PENDING"
    queued = queue_all(db, tenant, connection.id) if connection.status == "CONNECTED" else 0
    selected = {"STATUTORY": payload.sync_statutory_deadlines, "INTERNAL": payload.sync_internal_targets,
                "TASK": payload.sync_tasks}
    if connection.status == "CONNECTED":
        for mapping in db.scalars(select(CalendarEventMapping).where(
            CalendarEventMapping.tenant_id == tenant,
            CalendarEventMapping.connection_id == connection.id,
            CalendarEventMapping.event_kind.in_([kind for kind in previous if previous[kind] and not selected[kind]]),
        )).all():
            job, duplicate = queue_job(
                db, tenant, "CALENDAR_SYNC", f"calendar-policy-cancel:{mapping.id}:{policy.updated_at.isoformat()}",
                entity_type=mapping.entity_type, entity_id=mapping.entity_id,
                payload={"connection_id": connection.id, "entity_type": mapping.entity_type,
                         "entity_id": mapping.entity_id, "event_kind": mapping.event_kind,
                         "sync_hash": mapping.sync_hash, "action": "CANCEL"},
            )
            queued += int(not duplicate)
            mapping.sync_status = "QUEUED"
    audit(db, user, "CALENDAR_POLICY_CHANGED", connection.id)
    db.commit()
    return {"connection_id": connection.id, "calendar_id": configuration.calendar_id,
            "policy": policy_output(policy), "queued": queued}


@router.post("/connections/{connection_id}/oauth/start")
def oauth_start(connection_id: str, db: DB, tenant: Tenant, user: CurrentUser):
    manage(user)
    entitled(db, tenant)
    connection, _ = google_connection(db, tenant, connection_id)
    state_token = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(48)
    try:
        with oauth_client() as session:
            authorization_url, _ = session.create_authorization_url(
                GOOGLE_AUTH,
                state=state_token,
                code_verifier=verifier,
                access_type="offline",
                prompt="consent",
                include_granted_scopes="true",
            )
    except IntegrationError as error:
        public_error(error)
    db.execute(delete(CalendarOAuthState).where(CalendarOAuthState.expires_at < now()))
    db.add(CalendarOAuthState(
        state_hash=digest(state_token), tenant_id=tenant, user_id=user.id,
        connection_id=connection.id, verifier=verifier, expires_at=now() + timedelta(minutes=10),
    ))
    audit(db, user, "CALENDAR_OAUTH_STARTED", connection.id)
    db.commit()
    return {"authorization_url": authorization_url, "expires_in": 600}


@router.get("/google/callback")
def oauth_callback(request: Request, db: DB, tenant: Tenant, user: CurrentUser,
                   state: str = "", code: str = "", error: str = ""):
    flow = db.get(CalendarOAuthState, digest(state))
    valid = flow and flow.tenant_id == tenant and flow.user_id == user.id and not flow.used_at and aware(flow.expires_at) > now()
    if not valid:
        raise HTTPException(400, "Invalid or expired calendar authorization request")
    flow.used_at = now()
    db.commit()  # consume state before the provider exchange
    connection, settings = google_connection(db, tenant, flow.connection_id)
    try:
        if error or not code:
            raise IntegrationError("AUTHENTICATION_FAILED")
        with oauth_client() as session:
            token = session.fetch_token(GOOGLE_TOKEN, code=code, code_verifier=flow.verifier, timeout=8)
        token = safe_token(token)
        store = secret_store()
        store.update_secret(settings.credential_reference, json.dumps(token, separators=(",", ":")))
        settings.credential_suffix = hashlib.sha256(token["access_token"].encode()).hexdigest()[-4:]
        settings.failure_count = 0
        settings.error_code = ""
        settings.blocked_until = None
        settings.updated_at = now()
        settings.updated_by = user.name
        connection.status = "CONFIGURED"
        policy_for(db, tenant, connection.id, user.id)
        audit(db, user, "CALENDAR_OAUTH_CONNECTED", connection.id)
        db.commit()
        response = RedirectResponse("/settings/integrations/connections?calendar=connected", 303)
    except Exception:
        db.rollback()
        response = RedirectResponse("/settings/integrations/connections?calendar=failed", 303)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@router.post("/connections/{connection_id}/test")
def test_calendar(connection_id: str, db: DB, tenant: Tenant, user: CurrentUser):
    manage(user)
    entitled(db, tenant)
    connection, state = google_connection(db, tenant, connection_id)
    started = now()
    try:
        calendar_adapter(db, connection, state).test_connection()
        state.last_tested_at = now()
        state.last_success_at = now()
        state.failure_count = 0
        state.error_code = ""
        connection.status = "CONFIGURED"
        log = log_operation(db, connection, "calendar_test", "SUCCESS", int((now() - started).total_seconds() * 1000))
        audit(db, user, "CALENDAR_CONNECTION_TESTED", connection.id)
        db.commit()
        return {"success": True, "error_code": "", "request_id": log.id}
    except IntegrationError as problem:
        state.last_tested_at = now()
        state.last_error_at = now()
        state.failure_count += 1
        state.error_code = problem.code
        connection.status = "ERROR"
        log = log_operation(db, connection, "calendar_test", "FAILED", int((now() - started).total_seconds() * 1000), problem.code)
        db.commit()
        return {"success": False, "error_code": problem.code, "request_id": log.id}


@router.post("/connections/{connection_id}/sync")
def sync_now(connection_id: str, db: DB, tenant: Tenant, user: CurrentUser):
    manage(user)
    entitled(db, tenant)
    connection, _ = google_connection(db, tenant, connection_id)
    if connection.status != "CONNECTED":
        raise HTTPException(409, "Activate the tested calendar connection before synchronization")
    queued = queue_all(db, tenant, connection.id)
    audit(db, user, "CALENDAR_SYNC_QUEUED", connection.id)
    db.commit()
    return {"queued": queued}


@router.post("/mappings/{mapping_id}/retry")
def retry_mapping(mapping_id: str, db: DB, tenant: Tenant, user: CurrentUser):
    manage(user)
    mapping = db.scalar(select(CalendarEventMapping).where(
        CalendarEventMapping.id == mapping_id,
        CalendarEventMapping.tenant_id == tenant,
    ))
    if not mapping:
        raise HTTPException(404, "Calendar mapping not found")
    require_organization_access(db, tenant, mapping.organization_id, write=True, user_id=user.id)
    job, _ = queue_job(
        db, tenant, "CALENDAR_SYNC", f"calendar-manual:{mapping.id}:{secrets.token_hex(8)}",
        entity_type=mapping.entity_type, entity_id=mapping.entity_id,
        payload={"connection_id": mapping.connection_id, "entity_type": mapping.entity_type,
                 "entity_id": mapping.entity_id, "event_kind": mapping.event_kind, "sync_hash": mapping.sync_hash},
    )
    mapping.sync_status = "QUEUED"
    mapping.error_code = ""
    db.commit()
    return {"job_id": job.id, "status": mapping.sync_status}


@router.post("/connections/{connection_id}/disconnect")
def disconnect_calendar(connection_id: str, db: DB, tenant: Tenant, user: CurrentUser):
    manage(user)
    connection, state = google_connection(db, tenant, connection_id)
    store = secret_store()
    try:
        token = json.loads(store.get_secret_for_server_use(state.credential_reference))
        revoke_token = token.get("refresh_token") or token.get("access_token")
        if revoke_token:
            status, retry_after = safe_http(
                "https://oauth2.googleapis.com/revoke", "POST",
                {"Content-Type": "application/x-www-form-urlencoded"},
                urlencode({"token": revoke_token}).encode(),
            )
            require_success(status, retry_after)
    except IntegrationError:
        # Local revocation remains authoritative if Google is unavailable.
        pass
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    try:
        store.delete_secret(state.credential_reference)
    except IntegrationError as problem:
        public_error(problem)
    connection.status = "DISABLED"
    state.credential_suffix = ""
    state.last_success_at = None
    state.error_code = ""
    for mapping in db.scalars(select(CalendarEventMapping).where(
        CalendarEventMapping.tenant_id == tenant,
        CalendarEventMapping.connection_id == connection.id,
    )):
        mapping.sync_status = "DISCONNECTED"
        mapping.updated_at = now()
    audit(db, user, "CALENDAR_OAUTH_DISCONNECTED", connection.id)
    db.commit()
    return {"connection_id": connection.id, "status": connection.status, "oauth_connected": False}
