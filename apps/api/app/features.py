from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth_models import WorkspaceAccess
from .document_models import DocumentBlob
from .integration_models import ConnectionSettings
from .models import IntegrationConnection, Membership, Organization, Subscription, TenantEntitlement, User


@dataclass(frozen=True)
class PlanDefinition:
    label: str
    user_limit: int
    organization_limit: int
    storage_limit_gb: int
    integration_limit: int
    entitlements: frozenset[str]
    features: tuple[str, ...]


CORE_FEATURES = ("core_compliance", "task_management", "document_evidence", "standard_reporting")
PLAN_CATALOG = {
    "STARTER": PlanDefinition("Starter", 5, 3, 1, 1, frozenset(), CORE_FEATURES),
    "PROFESSIONAL": PlanDefinition(
        "Professional", 15, 8, 10, 5, frozenset({"google_calendar_integration"}),
        CORE_FEATURES + ("google_calendar_integration",),
    ),
    "BUSINESS": PlanDefinition(
        "Business", 25, 10, 25, 10,
        frozenset({"advanced_reporting", "advanced_automation", "custom_email", "custom_storage", "whatsapp_integration", "google_calendar_integration", "custom_webhooks", "public_api"}),
        CORE_FEATURES + ("advanced_reporting", "advanced_automation", "integrations", "google_calendar_integration", "custom_webhooks", "public_api"),
    ),
    "ENTERPRISE": PlanDefinition(
        "Enterprise", 250, 50, 250, 50,
        frozenset({"advanced_reporting", "advanced_automation", "custom_email", "custom_storage", "whatsapp_integration", "google_calendar_integration", "custom_webhooks", "public_api", "white_label"}),
        CORE_FEATURES + ("advanced_reporting", "advanced_automation", "integrations", "google_calendar_integration", "custom_webhooks", "public_api", "white_label"),
    ),
}


def plan_definition(plan_name: str) -> PlanDefinition | None:
    return PLAN_CATALOG.get(plan_name.strip().upper())


def plan_catalog_payload() -> list[dict]:
    result = []
    for key, plan in PLAN_CATALOG.items():
        item = asdict(plan)
        item["entitlements"] = sorted(plan.entitlements)
        item["features"] = list(plan.features)
        result.append({"key": key, **item})
    return result


def new_subscription(tenant_id: str, plan_name: str, period_end: date) -> Subscription:
    plan = plan_definition(plan_name)
    if not plan:
        raise ValueError("Unknown subscription plan")
    return Subscription(
        tenant_id=tenant_id,
        plan_name=plan_name.strip().upper(),
        status="ACTIVE",
        user_limit=plan.user_limit,
        organization_limit=plan.organization_limit,
        integration_limit=plan.integration_limit,
        storage_limit_gb=plan.storage_limit_gb,
        period_start=date.today(),
        period_end=period_end,
        cancel_at_period_end=False,
    )


def subscription_usage(db: Session, tenant_id: str) -> dict[str, int | float]:
    user_emails = set(db.scalars(select(func.lower(User.email)).where(
        User.tenant_id == tenant_id, User.status != "DISABLED",
    )).all())
    user_emails.update(db.scalars(select(func.lower(User.email)).join(
        WorkspaceAccess, WorkspaceAccess.user_id == User.id,
    ).where(
        WorkspaceAccess.tenant_id == tenant_id,
        WorkspaceAccess.active.is_(True),
        User.status == "ACTIVE",
    )).all())
    user_emails.update(db.scalars(select(func.lower(Membership.email)).where(
        Membership.tenant_id == tenant_id, Membership.status != "INACTIVE",
    )).all())
    organizations = db.scalar(select(func.count()).select_from(Organization).where(
        Organization.tenant_id == tenant_id, Organization.status != "ARCHIVED",
    )) or 0
    integrations = db.scalar(select(func.count(IntegrationConnection.id)).join(
        ConnectionSettings, ConnectionSettings.connection_id == IntegrationConnection.id,
    ).where(
        IntegrationConnection.tenant_id == tenant_id,
        ConnectionSettings.scope == "TENANT",
    )) or 0
    storage_bytes = db.scalar(select(func.coalesce(func.sum(DocumentBlob.size_bytes), 0)).where(
        DocumentBlob.tenant_id == tenant_id,
    )) or 0
    return {
        "users": len(user_emails),
        "organizations": organizations,
        "integrations": integrations,
        "storage_bytes": storage_bytes,
        "storage_gb": round(storage_bytes / (1024 ** 3), 3),
    }


def require_active_subscription(db: Session, tenant_id: str) -> Subscription | None:
    subscription = db.scalar(select(Subscription).where(
        Subscription.tenant_id == tenant_id,
    ).with_for_update())
    if not subscription:
        return None
    if subscription.status not in {"ACTIVE", "TRIAL"} or subscription.period_end < date.today():
        raise HTTPException(403, "SUBSCRIPTION_INACTIVE")
    return subscription


def require_plan_capacity(db: Session, tenant_id: str, resource: str, used: int | None = None) -> None:
    subscription = require_active_subscription(db, tenant_id)
    if not subscription:
        # Grandfather pre-subscription tenants until a platform operator assigns a plan.
        return
    limits = {
        "users": subscription.user_limit,
        "organizations": subscription.organization_limit,
        "integrations": subscription.integration_limit,
    }
    if resource not in limits:
        raise ValueError("Unknown subscription resource")
    if used is None:
        used = int(subscription_usage(db, tenant_id)[resource])
    if used >= limits[resource]:
        raise HTTPException(403, f"PLAN_LIMIT_REACHED:{resource}")


def can_use_feature(db: Session, tenant_id: str, feature_key: str) -> bool:
    subscription = db.scalar(select(Subscription).where(Subscription.tenant_id == tenant_id))
    if not subscription or subscription.status not in {"ACTIVE", "TRIAL"} or subscription.period_end < date.today():
        return False
    feature = db.scalar(select(TenantEntitlement).where(TenantEntitlement.tenant_id == tenant_id,
                                                      TenantEntitlement.feature_key == feature_key))
    if feature:
        if not feature.enabled:
            return False
        expires = feature.expires_at
        if expires and expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return not expires or expires > datetime.now(timezone.utc)
    plan = plan_definition(subscription.plan_name)
    return bool(plan and feature_key in plan.entitlements)
