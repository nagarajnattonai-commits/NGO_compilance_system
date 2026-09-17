from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Subscription, TenantEntitlement


def can_use_feature(db: Session, tenant_id: str, feature_key: str) -> bool:
    subscription = db.scalar(select(Subscription).where(Subscription.tenant_id == tenant_id))
    if not subscription or subscription.status != "ACTIVE" or subscription.period_end < date.today():
        return False
    feature = db.scalar(select(TenantEntitlement).where(TenantEntitlement.tenant_id == tenant_id,
                                                      TenantEntitlement.feature_key == feature_key))
    if not feature or not feature.enabled:
        return False
    expires = feature.expires_at
    if expires and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return not expires or expires > datetime.now(timezone.utc)
