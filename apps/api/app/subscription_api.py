"""Platform plan assignment API over the existing tenant subscription records."""
from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from .auth import CurrentUser
from .features import PLAN_CATALOG, new_subscription, plan_catalog_payload
from .models import AuditEvent, Subscription, Workspace
from .organization_profile import DB
from .auth_policy import is_platform_admin

router = APIRouter(prefix="/api/v1/platform/subscriptions", tags=["Subscriptions"])


class SubscriptionChange(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    plan_name: str = Field(min_length=1, max_length=40)
    status: Literal["ACTIVE", "TRIAL", "PAST_DUE", "CANCELLED", "SUSPENDED", "DISABLED"] | None = None
    period_start: date | None = None
    period_end: date | None = None
    cancel_at_period_end: bool | None = None

    @field_validator("plan_name")
    @classmethod
    def configured_plan(cls, value: str) -> str:
        key = value.upper()
        if key not in PLAN_CATALOG:
            raise ValueError("Unknown plan")
        return key


def require_platform_admin(user) -> None:
    if not is_platform_admin(user):
        raise HTTPException(403, "Platform administrator access is required")


def _subscription_data(subscription: Subscription | None) -> dict | None:
    if not subscription:
        return None
    return {
        "id": subscription.id,
        "plan_name": subscription.plan_name,
        "status": subscription.status,
        "user_limit": subscription.user_limit,
        "organization_limit": subscription.organization_limit,
        "integration_limit": subscription.integration_limit,
        "storage_limit_gb": subscription.storage_limit_gb,
        "period_start": subscription.period_start,
        "period_end": subscription.period_end,
        "cancel_at_period_end": subscription.cancel_at_period_end,
    }


@router.get("")
def list_platform_subscriptions(db: DB, user: CurrentUser):
    require_platform_admin(user)
    rows = db.execute(select(Workspace, Subscription).outerjoin(
        Subscription, Subscription.tenant_id == Workspace.id,
    ).order_by(Workspace.name).limit(500)).all()
    tenant_ids = [workspace.id for workspace, _ in rows]
    history_by_tenant: dict[str, list[dict]] = {tenant_id: [] for tenant_id in tenant_ids}
    if tenant_ids:
        history = db.scalars(select(AuditEvent).where(
            AuditEvent.tenant_id.in_(tenant_ids),
            AuditEvent.action == "SUBSCRIPTION_CHANGED",
        ).order_by(AuditEvent.created_at.desc()).limit(2500)).all()
        for event in history:
            if len(history_by_tenant[event.tenant_id]) < 5:
                history_by_tenant[event.tenant_id].append({
                    "id": event.id,
                    "actor_name": event.actor_name,
                    "summary": event.summary,
                    "created_at": event.created_at,
                })
    items = [{
        "tenant_id": workspace.id,
        "workspace_name": workspace.name,
        "subscription": _subscription_data(subscription),
        "history": history_by_tenant[workspace.id],
    } for workspace, subscription in rows]
    return {"items": items, "plans": plan_catalog_payload()}


@router.put("/{tenant_id}")
def assign_subscription(tenant_id: str, payload: SubscriptionChange, db: DB, user: CurrentUser):
    require_platform_admin(user)
    workspace = db.get(Workspace, tenant_id)
    if not workspace:
        raise HTTPException(404, "Workspace not found")
    subscription = db.scalar(select(Subscription).where(Subscription.tenant_id == tenant_id))
    previous = _subscription_data(subscription)
    period_start = payload.period_start if payload.period_start is not None else subscription.period_start if subscription else date.today()
    period_end = payload.period_end if payload.period_end is not None else subscription.period_end if subscription else date.today() + timedelta(days=30)
    if period_start and period_start > period_end:
        raise HTTPException(422, "Subscription period start must not follow its end")

    if subscription is None:
        subscription = new_subscription(tenant_id, payload.plan_name, period_end)
        subscription.period_start = period_start
        db.add(subscription)
    else:
        plan = PLAN_CATALOG[payload.plan_name]
        subscription.plan_name = payload.plan_name
        subscription.user_limit = plan.user_limit
        subscription.organization_limit = plan.organization_limit
        subscription.integration_limit = plan.integration_limit
        subscription.storage_limit_gb = plan.storage_limit_gb
        subscription.period_start = period_start
        subscription.period_end = period_end

    if payload.status is not None:
        subscription.status = payload.status
    if payload.cancel_at_period_end is not None:
        subscription.cancel_at_period_end = payload.cancel_at_period_end
    db.flush()
    current = _subscription_data(subscription)
    if previous != current:
        db.add(AuditEvent(
            tenant_id=tenant_id,
            actor_name=user.name,
            action="SUBSCRIPTION_CHANGED",
            entity_type="Subscription",
            entity_id=subscription.id,
            summary=f"Plan/status changed from {previous['plan_name'] if previous else 'none'}/{previous['status'] if previous else 'none'} to {subscription.plan_name}/{subscription.status}",
        ))
    db.commit()
    return {"tenant_id": tenant_id, "workspace_name": workspace.name, "subscription": current}
