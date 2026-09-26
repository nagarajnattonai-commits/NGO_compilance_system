"""One-way, queued Google Calendar synchronization with persistent mappings."""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import timedelta

from authlib.integrations.requests_client import OAuth2Session
from fastapi import HTTPException
from sqlalchemy import func, select

from .auth import aware, now
from .automation_service import queue_job
from .features import can_use_feature
from .integration_models import ConnectionSettings
from .integration_providers import CalendarConfiguration, GoogleCalendarAdapter
from .integration_security import IntegrationError, secret_store
from .integration_service import log_operation
from .models import Compliance, IntegrationConnection, Task, utcnow
from .phase10_models import CalendarEventMapping, CalendarSyncPolicy

GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events"


def callback_url() -> str:
    from .auth import APP_ORIGIN
    return os.getenv("GOOGLE_CALENDAR_REDIRECT_URI", APP_ORIGIN + "/api/v1/calendar/google/callback")


def oauth_client(*, token: dict | None = None) -> OAuth2Session:
    client_id = os.getenv("GOOGLE_CALENDAR_CLIENT_ID", "")
    secret_ref = os.getenv("GOOGLE_CALENDAR_CLIENT_SECRET_REF", "")
    if not client_id or not secret_ref:
        raise IntegrationError("INTEGRATION_NOT_CONFIGURED")
    client_secret = secret_store().get_secret_for_server_use(secret_ref)
    session = OAuth2Session(
        client_id,
        client_secret,
        token=token,
        scope=CALENDAR_SCOPE,
        redirect_uri=callback_url(),
        code_challenge_method="S256",
        token_endpoint_auth_method="client_secret_post",
    )
    session.trust_env = False
    return session


def safe_token(token: dict, previous: dict | None = None) -> dict:
    allowed = {key: token[key] for key in ("access_token", "refresh_token", "expires_at", "expires_in", "token_type", "scope") if key in token}
    if not allowed.get("refresh_token") and previous and previous.get("refresh_token"):
        allowed["refresh_token"] = previous["refresh_token"]
    if not allowed.get("access_token") or not allowed.get("refresh_token"):
        raise IntegrationError("AUTHENTICATION_FAILED")
    return allowed


def token_for(db, connection: IntegrationConnection, state: ConnectionSettings) -> dict:
    try:
        token = json.loads(secret_store().get_secret_for_server_use(state.credential_reference))
    except (TypeError, ValueError, json.JSONDecodeError):
        raise IntegrationError("AUTHENTICATION_FAILED") from None
    if not isinstance(token, dict) or not token.get("access_token"):
        raise IntegrationError("AUTHENTICATION_FAILED")
    expires_at = float(token.get("expires_at") or 0)
    if expires_at and expires_at <= time.time() + 60:
        refresh_token = token.get("refresh_token")
        if not refresh_token:
            raise IntegrationError("AUTHENTICATION_FAILED")
        try:
            with oauth_client(token=token) as session:
                refreshed = session.refresh_token(GOOGLE_TOKEN, refresh_token=refresh_token, timeout=8)
            token = safe_token(refreshed, token)
            secret_store().update_secret(state.credential_reference, json.dumps(token, separators=(",", ":")))
        except IntegrationError:
            raise
        except Exception:
            raise IntegrationError("AUTHENTICATION_FAILED") from None
    return token


def calendar_adapter(db, connection: IntegrationConnection, state: ConnectionSettings) -> GoogleCalendarAdapter:
    configuration = CalendarConfiguration.model_validate_json(state.configuration).model_dump()
    token = token_for(db, connection, state)
    return GoogleCalendarAdapter(configuration, json.dumps(token, separators=(",", ":")))


def policy_for(db, tenant_id: str, connection_id: str, actor_id: str | None = None) -> CalendarSyncPolicy:
    policy = db.get(CalendarSyncPolicy, connection_id)
    if policy and policy.tenant_id != tenant_id:
        raise HTTPException(404, "Calendar policy not found")
    if not policy:
        if not actor_id:
            raise HTTPException(404, "Calendar policy not found")
        policy = CalendarSyncPolicy(connection_id=connection_id, tenant_id=tenant_id, updated_by=actor_id)
        db.add(policy)
        db.flush()
    return policy


def _desired_hash(entity, kind: str) -> str:
    if isinstance(entity, Compliance):
        due = entity.statutory_deadline if kind == "STATUTORY" else entity.internal_target
        parts = (entity.id, kind, str(due), entity.status, entity.code, aware(entity.updated_at).isoformat())
    else:
        archived = aware(entity.archived_at).isoformat() if entity.archived_at else ""
        parts = (entity.id, kind, str(entity.due_at), entity.status, archived, aware(entity.updated_at).isoformat())
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def _provider_event_id(tenant_id: str, connection_id: str, entity_type: str, entity_id: str, kind: str) -> str:
    return hashlib.sha256(f"{tenant_id}:{connection_id}:{entity_type}:{entity_id}:{kind}".encode()).hexdigest()[:48]


def _connected_policies(db, tenant_id: str):
    if not can_use_feature(db, tenant_id, "google_calendar_integration"):
        return []
    return db.execute(select(IntegrationConnection, ConnectionSettings, CalendarSyncPolicy).join(
        ConnectionSettings, ConnectionSettings.connection_id == IntegrationConnection.id
    ).join(CalendarSyncPolicy, CalendarSyncPolicy.connection_id == IntegrationConnection.id).where(
        IntegrationConnection.tenant_id == tenant_id,
        IntegrationConnection.provider == "google_calendar",
        IntegrationConnection.status == "CONNECTED",
        ConnectionSettings.scope == "TENANT",
    )).all()


def queue_entity_sync(db, entity, connection_id: str | None = None) -> int:
    """Queue provider work in the caller's transaction; no provider call occurs here."""
    entity_type = "Compliance" if isinstance(entity, Compliance) else "Task"
    created = 0
    for connection, state, policy in _connected_policies(db, entity.tenant_id):
        if connection_id and connection.id != connection_id:
            continue
        kinds = []
        if isinstance(entity, Compliance):
            if policy.sync_statutory_deadlines:
                kinds.append("STATUTORY")
            if policy.sync_internal_targets and entity.internal_target:
                kinds.append("INTERNAL")
        elif policy.sync_tasks:
            kinds.append("TASK")
        configuration = CalendarConfiguration.model_validate_json(state.configuration)
        for kind in kinds:
            policy_revision = aware(policy.updated_at).isoformat()
            fingerprint = hashlib.sha256((
                _desired_hash(entity, kind) + "|" + policy_revision + "|" +
                policy.closed_behavior + "|" + configuration.calendar_id
            ).encode()).hexdigest()
            mapping = db.scalar(select(CalendarEventMapping).where(
                CalendarEventMapping.tenant_id == entity.tenant_id,
                CalendarEventMapping.connection_id == connection.id,
                CalendarEventMapping.entity_type == entity_type,
                CalendarEventMapping.entity_id == entity.id,
                CalendarEventMapping.event_kind == kind,
            ))
            if not mapping:
                mapping = CalendarEventMapping(
                    tenant_id=entity.tenant_id,
                    organization_id=entity.organization_id,
                    connection_id=connection.id,
                    entity_type=entity_type,
                    entity_id=entity.id,
                    event_kind=kind,
                    calendar_id=configuration.calendar_id,
                    provider_event_id=_provider_event_id(entity.tenant_id, connection.id, entity_type, entity.id, kind),
                )
                db.add(mapping)
                db.flush()
            elif not mapping.last_synced_at:
                mapping.calendar_id = configuration.calendar_id
            job, duplicate = queue_job(
                db, entity.tenant_id, "CALENDAR_SYNC",
                f"calendar:{connection.id}:{entity_type}:{entity.id}:{kind}:{fingerprint}",
                entity_type=entity_type, entity_id=entity.id,
                payload={"connection_id": connection.id, "entity_type": entity_type,
                         "entity_id": entity.id, "event_kind": kind, "sync_hash": fingerprint},
            )
            if not duplicate or job.status not in {"SUCCEEDED"}:
                mapping.sync_status = "QUEUED"
                mapping.error_code = ""
                mapping.updated_at = utcnow()
            created += int(not duplicate)
    return created


def queue_all(db, tenant_id: str, connection_id: str | None = None) -> int:
    count = 0
    for entity in db.scalars(select(Compliance).where(Compliance.tenant_id == tenant_id)).all():
        count += queue_entity_sync(db, entity, connection_id)
    for entity in db.scalars(select(Task).where(Task.tenant_id == tenant_id)).all():
        count += queue_entity_sync(db, entity, connection_id)
    return count


def _event(db, entity, kind: str) -> tuple[dict, bool]:
    from .auth import APP_ORIGIN
    from .models import Organization
    organization = db.scalar(select(Organization).where(
        Organization.id == entity.organization_id,
        Organization.tenant_id == entity.tenant_id,
    ))
    organization_name = organization.name if organization else "Organization"
    if isinstance(entity, Compliance):
        due = entity.statutory_deadline if kind == "STATUTORY" else entity.internal_target
        if not due:
            raise ValueError("Calendar date is unavailable")
        closed = entity.status in {"COMPLETED", "CANCELLED", "NOT_APPLICABLE"}
        summary = (f"{entity.title} · {organization_name}" if kind == "STATUTORY" else
                   f"Internal target: {entity.title} · {organization_name}")
        link = f"{APP_ORIGIN}/compliances/{entity.id}"
        status = entity.status
    else:
        due = entity.due_at
        closed = entity.status == "DONE" or entity.archived_at is not None
        summary = f"Compliance task due · {organization_name}"
        link = f"{APP_ORIGIN}/organizations/{entity.organization_id}"
        status = entity.status
    payload = {
        "summary": summary,
        "description": f"Status: {status}. Open the authoritative record in Setu: {link}",
        "start": {"date": due.isoformat()},
        "end": {"date": (due + timedelta(days=1)).isoformat()},
        "transparency": "transparent" if closed else "opaque",
        "extendedProperties": {"private": {"setuEntityType": type(entity).__name__, "setuEntityId": entity.id, "setuEventKind": kind}},
    }
    return payload, closed


def process_sync_job(db, job) -> dict:
    payload = json.loads(job.payload)
    from .integration_service import resolve_connection
    connection, state = resolve_connection(db, job.tenant_id, payload.get("connection_id"), "CALENDAR", "calendar.events")
    policy = db.get(CalendarSyncPolicy, connection.id)
    mapping = db.scalar(select(CalendarEventMapping).where(
        CalendarEventMapping.tenant_id == job.tenant_id,
        CalendarEventMapping.connection_id == connection.id,
        CalendarEventMapping.entity_type == payload.get("entity_type"),
        CalendarEventMapping.entity_id == payload.get("entity_id"),
        CalendarEventMapping.event_kind == payload.get("event_kind"),
    ))
    if not state or not policy or not mapping:
        raise ValueError("Calendar sync context is missing")
    model = Compliance if mapping.entity_type == "Compliance" else Task if mapping.entity_type == "Task" else None
    if not model:
        raise ValueError("Unsupported calendar entity")
    entity = db.scalar(select(model).where(model.id == mapping.entity_id, model.tenant_id == job.tenant_id,
                                           model.organization_id == mapping.organization_id))
    if not entity:
        raise ValueError("Calendar entity is unavailable")
    event, closed = _event(db, entity, mapping.event_kind)
    started = time.perf_counter()
    try:
        adapter = calendar_adapter(db, connection, state)
        if payload.get("action") == "CANCEL" or closed and policy.closed_behavior == "CANCEL":
            if mapping.last_synced_at:
                adapter.cancel_event(mapping.provider_event_id)
            outcome = "CANCELLED"
        elif mapping.last_synced_at:
            adapter.update_event(mapping.provider_event_id, event)
            outcome = "SYNCED"
        else:
            adapter.create_event(mapping.provider_event_id, event)
            outcome = "SYNCED"
        duration = int((time.perf_counter() - started) * 1000)
        log_operation(db, connection, "calendar_sync", "SUCCESS", duration)
        mapping.sync_status = outcome
        mapping.sync_hash = payload.get("sync_hash", "")
        mapping.error_code = ""
        mapping.last_synced_at = None if outcome == "CANCELLED" else now()
        mapping.updated_at = now()
        connection.last_synced_at = now()
        return {"mapping_id": mapping.id, "status": outcome, "provider_event_id": mapping.provider_event_id}
    except IntegrationError as error:
        log_operation(db, connection, "calendar_sync", "FAILED", int((time.perf_counter() - started) * 1000), error.code)
        raise


def mark_sync_failure(db, job, code: str) -> None:
    if job.job_type != "CALENDAR_SYNC":
        return
    try:
        payload = json.loads(job.payload)
    except (TypeError, ValueError):
        return
    mapping = db.scalar(select(CalendarEventMapping).where(
        CalendarEventMapping.tenant_id == job.tenant_id,
        CalendarEventMapping.connection_id == payload.get("connection_id"),
        CalendarEventMapping.entity_type == payload.get("entity_type"),
        CalendarEventMapping.entity_id == payload.get("entity_id"),
        CalendarEventMapping.event_kind == payload.get("event_kind"),
    ))
    if mapping:
        mapping.sync_status = "FAILED" if job.status in {"FAILED", "DEAD_LETTER"} else "RETRY"
        mapping.error_code = code
        mapping.updated_at = now()
