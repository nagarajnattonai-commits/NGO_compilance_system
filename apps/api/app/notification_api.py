"""Authenticated notification preference, history and operations endpoints."""
import json
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from .auth import AdminUser, CurrentUser, DB, check_mutation, tenant_context
from .models import AuditEvent, utcnow
from .notification_models import NotificationDelivery, UserNotificationPreference, WorkspaceNotificationPolicy
from .notification_service import preference_for

Tenant = Annotated[str, Depends(tenant_context)]
router = APIRouter(prefix="/api/v1", dependencies=[Depends(check_mutation)])


class PreferenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    in_app_enabled: bool = True
    email_enabled: bool = True
    whatsapp_enabled: bool = False
    compliance_enabled: bool = True
    task_enabled: bool = True
    document_enabled: bool = True
    system_enabled: bool = True


class PreferenceOut(PreferenceInput):
    user_id: str
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class PolicyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mandatory_channels: list[Literal["IN_APP", "EMAIL", "WHATSAPP"]]


def delivery_output(row: NotificationDelivery, *, admin: bool = False) -> dict:
    address = row.recipient_address
    if admin and address:
        if "@" in address:
            name, domain = address.split("@", 1)
            address = (name[:2] + "***@" + domain) if name else "***@" + domain
        else:
            address = "***" + address[-4:]
    return {
        "id": row.id, "notification_id": row.notification_id, "user_id": row.user_id,
        "channel": row.channel, "recipient": address, "locale": row.locale,
        "template_key": row.template_key, "status": row.status, "attempt_count": row.attempt_count,
        "error_code": row.last_error_code, "queued_at": row.queued_at, "sent_at": row.sent_at,
        "delivered_at": row.delivered_at, "read_at": row.read_at, "failed_at": row.failed_at,
        "created_at": row.created_at,
    }


@router.get("/notification-preferences", response_model=PreferenceOut)
def get_preferences(db: DB, tenant_id: Tenant, user: CurrentUser):
    preference = preference_for(db, tenant_id, user.id)
    db.commit()
    return preference


@router.patch("/notification-preferences", response_model=PreferenceOut)
def update_preferences(payload: PreferenceInput, db: DB, tenant_id: Tenant, user: CurrentUser):
    preference = preference_for(db, tenant_id, user.id)
    for field, value in payload.model_dump().items():
        setattr(preference, field, value)
    preference.updated_at = utcnow()
    db.add(AuditEvent(tenant_id=tenant_id, actor_name=user.name, action="NOTIFICATION_PREFERENCES_UPDATED",
        entity_type="UserNotificationPreference", entity_id=user.id, summary="Updated personal notification channels and categories"))
    db.commit()
    db.refresh(preference)
    return preference


@router.get("/notification-deliveries")
def my_deliveries(db: DB, tenant_id: Tenant, user: CurrentUser, limit: int = Query(50, ge=1, le=200)):
    rows = db.scalars(select(NotificationDelivery).where(
        NotificationDelivery.tenant_id == tenant_id,
        NotificationDelivery.user_id == user.id,
    ).order_by(NotificationDelivery.created_at.desc()).limit(limit)).all()
    return [delivery_output(row) for row in rows]


@router.get("/admin/notification-policy")
def get_policy(db: DB, tenant_id: Tenant, _: AdminUser):
    row = db.get(WorkspaceNotificationPolicy, tenant_id)
    return {"mandatory_channels": json.loads(row.mandatory_channels) if row else ["IN_APP"]}


@router.put("/admin/notification-policy")
def set_policy(payload: PolicyInput, db: DB, tenant_id: Tenant, admin: AdminUser):
    channels = sorted(set(payload.mandatory_channels))
    if "IN_APP" not in channels:
        raise HTTPException(422, "In-app notifications are mandatory for durable workspace history")
    row = db.get(WorkspaceNotificationPolicy, tenant_id)
    if not row:
        row = WorkspaceNotificationPolicy(tenant_id=tenant_id)
        db.add(row)
    row.mandatory_channels = json.dumps(channels)
    row.updated_by = admin.name
    row.updated_at = utcnow()
    db.add(AuditEvent(tenant_id=tenant_id, actor_name=admin.name, action="NOTIFICATION_POLICY_UPDATED",
        entity_type="WorkspaceNotificationPolicy", entity_id=tenant_id, summary="Updated mandatory notification channels"))
    db.commit()
    return {"mandatory_channels": channels}


@router.get("/admin/notification-deliveries")
def operational_deliveries(db: DB, tenant_id: Tenant, _: AdminUser,
                           status: str = "", channel: str = "", limit: int = Query(100, ge=1, le=500)):
    filters = [NotificationDelivery.tenant_id == tenant_id]
    if status:
        filters.append(NotificationDelivery.status == status.upper())
    if channel:
        filters.append(NotificationDelivery.channel == channel.upper())
    rows = db.scalars(select(NotificationDelivery).where(*filters).order_by(
        NotificationDelivery.created_at.desc()).limit(limit)).all()
    return [delivery_output(row, admin=True) for row in rows]
