"""Recipient resolution, immutable rendering, channel fan-out and delivery execution."""
from __future__ import annotations

import html
import json
from collections.abc import Iterable

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from .auth import now
from .auth_models import WorkspaceAccess
from .automation_service import queue_job
from .brand_outputs import render_email
from .integration_notifications import deliver_email, deliver_whatsapp
from .models import (
    ComplianceNotificationTemplate,
    Membership,
    Notification,
    TenantLocale,
    User,
    UserPreference,
)
from .notification_models import (
    NotificationContext,
    NotificationDelivery,
    NotificationRecipient,
    UserNotificationPreference,
    WorkspaceNotificationPolicy,
)
from .runtime_membership import workspace_members
from .runtime_models import ComplianceOwnership

CHANNELS = {"IN_APP", "EMAIL", "WHATSAPP"}
CATEGORIES = {"COMPLIANCE", "TASK", "DOCUMENT", "SYSTEM"}


def preference_for(db, tenant_id: str, user_id: str) -> UserNotificationPreference:
    preference = db.get(UserNotificationPreference, user_id)
    if preference and preference.tenant_id != tenant_id:
        raise ValueError("Notification preference workspace mismatch")
    if not preference:
        preference = UserNotificationPreference(user_id=user_id, tenant_id=tenant_id)
        db.add(preference)
        db.flush()
    return preference


def user_locale(db, tenant_id: str, user_id: str) -> str:
    locale = db.scalar(select(UserPreference.locale).where(
        UserPreference.user_id == user_id,
        UserPreference.tenant_id == tenant_id,
    ))
    if locale:
        return locale
    return db.scalar(select(TenantLocale.locale_code).where(
        TenantLocale.tenant_id == tenant_id,
        TenantLocale.enabled.is_(True),
        TenantLocale.is_default.is_(True),
    )) or "en-IN"


def resolve_recipients(db, tenant_id: str, *, organization_id: str | None = None,
                       recipient_role: str | None = None, user_ids: Iterable[str] = ()) -> list[User]:
    """Resolve real, active accounts with effective access to this workspace."""
    members = {user.id: (user, access) for user, access in workspace_members(db, tenant_id)}
    resolved: dict[str, User] = {}
    for user_id in user_ids:
        if user_id in members:
            resolved[user_id] = members[user_id][0]
    if recipient_role == "OWNER" and organization_id:
        owner_ids = db.scalars(select(ComplianceOwnership.owner_id).where(
            ComplianceOwnership.tenant_id == tenant_id,
            ComplianceOwnership.organization_id == organization_id,
        )).all()
        for user_id in owner_ids:
            if user_id in members:
                resolved[user_id] = members[user_id][0]
    elif recipient_role == "TENANT_ADMIN":
        for user, access in members.values():
            if access == "ADMIN":
                resolved[user.id] = user
    elif recipient_role:
        allowed_email = {user.email.casefold(): user for user, access in members.values() if access != "VIEWER"}
        assignments = db.scalars(select(Membership).where(
            Membership.tenant_id == tenant_id,
            Membership.role == recipient_role,
            Membership.status == "ACTIVE",
            or_(Membership.organization_id == organization_id, Membership.organization_id.is_(None)),
        )).all()
        for assignment in assignments:
            user = allowed_email.get(assignment.email.casefold())
            if user:
                resolved[user.id] = user
    return sorted(resolved.values(), key=lambda item: item.id)


def _mandatory_channels(db, tenant_id: str) -> set[str]:
    policy = db.get(WorkspaceNotificationPolicy, tenant_id)
    try:
        values = set(json.loads(policy.mandatory_channels)) if policy else {"IN_APP"}
    except (TypeError, ValueError):
        values = {"IN_APP"}
    return values & CHANNELS


def _enabled(preference: UserNotificationPreference, category: str, channel: str) -> bool:
    category_flag = {
        "COMPLIANCE": preference.compliance_enabled,
        "TASK": preference.task_enabled,
        "DOCUMENT": preference.document_enabled,
        "SYSTEM": preference.system_enabled,
    }.get(category, True)
    channel_flag = {
        "IN_APP": preference.in_app_enabled,
        "EMAIL": preference.email_enabled,
        "WHATSAPP": preference.whatsapp_enabled,
    }[channel]
    return category_flag and channel_flag


def _variables(db, notification_id: str) -> tuple[str, dict]:
    row = db.get(ComplianceNotificationTemplate, notification_id)
    if not row:
        return "", {}
    try:
        return row.template_key, json.loads(row.variables)
    except (TypeError, ValueError):
        return row.template_key, {}


def _frozen_content(db, notification: Notification, user: User, locale: str) -> dict[str, str]:
    template_key, variables = _variables(db, notification.id)
    names = variables.get("names", {})
    messages = variables.get("reminderTexts", {})
    subject = names.get(locale) or variables.get("complianceName") or notification.title
    text = messages.get(locale) or variables.get("reminderText") or notification.message
    result = {"subject": subject, "text": text, "html": "", "template_key": template_key}
    if template_key == "compliance.deadlineReminder":
        rendered = render_email(db, notification.tenant_id, template_key, {
            "userName": user.name,
            "complianceName": subject,
            "dueDate": variables.get("dueDate", ""),
        }, locale)
        custom = f'<p style="white-space:pre-wrap">{html.escape(text)}</p>'
        result.update(subject=rendered["subject"], html=rendered["html"].replace("</main>", custom + "</main>"))
    return result


def distribute_notification(db, notification: Notification, *, event_type: str, category: str = "COMPLIANCE",
                            organization_id: str | None = None, entity_type: str = "", entity_id: str = "",
                            recipient_role: str | None = None, user_ids: Iterable[str] = (),
                            channels: Iterable[str] = ("IN_APP",), provider_template: str = "") -> int:
    """Fan one logical event out once per user/channel and freeze localized output."""
    requested = set(channels) & CHANNELS
    requested.update(_mandatory_channels(db, notification.tenant_id))
    category = category if category in CATEGORIES else "SYSTEM"
    context = db.get(NotificationContext, notification.id)
    if not context:
        context = NotificationContext(notification_id=notification.id, tenant_id=notification.tenant_id,
            event_type=event_type, category=category, organization_id=organization_id,
            entity_type=entity_type, entity_id=entity_id)
        db.add(context)
        db.flush()
    recipients = resolve_recipients(db, notification.tenant_id, organization_id=organization_id,
                                   recipient_role=recipient_role, user_ids=user_ids)
    created = 0
    for user in recipients:
        recipient = db.scalar(select(NotificationRecipient).where(
            NotificationRecipient.notification_id == notification.id,
            NotificationRecipient.user_id == user.id,
        ))
        if not recipient:
            db.add(NotificationRecipient(tenant_id=notification.tenant_id, notification_id=notification.id, user_id=user.id))
        preference = preference_for(db, notification.tenant_id, user.id)
        locale = user_locale(db, notification.tenant_id, user.id)
        content = _frozen_content(db, notification, user, locale)
        for channel in sorted(requested):
            existing = db.scalar(select(NotificationDelivery.id).where(
                NotificationDelivery.notification_id == notification.id,
                NotificationDelivery.user_id == user.id,
                NotificationDelivery.channel == channel,
            ))
            if existing:
                continue
            address = user.email if channel == "EMAIL" else user.phone if channel == "WHATSAPP" else ""
            enabled = _enabled(preference, category, channel) or channel in _mandatory_channels(db, notification.tenant_id)
            status = "DELIVERED" if channel == "IN_APP" and enabled else "PENDING" if enabled and address else "CANCELLED"
            error = "" if status != "CANCELLED" else "RECIPIENT_UNAVAILABLE" if enabled else "CHANNEL_DISABLED"
            delivery = NotificationDelivery(tenant_id=notification.tenant_id, notification_id=notification.id,
                user_id=user.id, channel=channel, recipient_address=address, locale=locale,
                template_key=content["template_key"], provider_template=provider_template,
                frozen_subject=content["subject"], frozen_text=content["text"], frozen_html=content["html"],
                status=status, delivered_at=now() if status == "DELIVERED" else None, last_error_code=error)
            db.add(delivery)
            db.flush()
            if status == "PENDING":
                queue_job(db, notification.tenant_id, "NOTIFICATION_DELIVERY", f"notification-delivery:{delivery.id}",
                          entity_type="NotificationDelivery", entity_id=delivery.id,
                          payload={"delivery_id": delivery.id})
                delivery.status = "QUEUED"
                delivery.queued_at = now()
            created += 1
    return created


def notification_inbox(db, tenant_id: str, user_id: str) -> list[dict]:
    """Return only this account's inbox. Old pre-Phase-7 rows are adopted per account."""
    legacy = db.scalars(select(Notification).outerjoin(NotificationContext,
        NotificationContext.notification_id == Notification.id).where(
            Notification.tenant_id == tenant_id,
            NotificationContext.notification_id.is_(None),
        )).all()
    for item in legacy:
        if not db.scalar(select(NotificationRecipient.id).where(
            NotificationRecipient.notification_id == item.id,
            NotificationRecipient.user_id == user_id,
        )):
            db.add(NotificationRecipient(tenant_id=tenant_id, notification_id=item.id, user_id=user_id,
                                         read_at=item.created_at if item.is_read else None))
    db.flush()
    rows = db.execute(select(Notification, NotificationRecipient).join(
        NotificationRecipient, NotificationRecipient.notification_id == Notification.id).where(
            Notification.tenant_id == tenant_id,
            NotificationRecipient.tenant_id == tenant_id,
            NotificationRecipient.user_id == user_id,
            NotificationRecipient.dismissed_at.is_(None),
        ).order_by(Notification.created_at.desc())).all()
    return [{
        "id": item.id, "title": item.title, "message": item.message, "kind": item.kind,
        "is_read": recipient.read_at is not None, "created_at": item.created_at,
        "template_key": item.template_key, "template_variables": item.template_variables,
    } for item, recipient in rows]


def mark_read(db, tenant_id: str, user_id: str, notification_id: str) -> bool:
    recipient = db.scalar(select(NotificationRecipient).where(
        NotificationRecipient.notification_id == notification_id,
        NotificationRecipient.tenant_id == tenant_id,
        NotificationRecipient.user_id == user_id,
    ))
    if not recipient:
        notification_inbox(db, tenant_id, user_id)
        recipient = db.scalar(select(NotificationRecipient).where(
            NotificationRecipient.notification_id == notification_id,
            NotificationRecipient.tenant_id == tenant_id,
            NotificationRecipient.user_id == user_id,
        ))
    if not recipient:
        return False
    recipient.read_at = now()
    for delivery in db.scalars(select(NotificationDelivery).where(
        NotificationDelivery.notification_id == notification_id,
        NotificationDelivery.user_id == user_id,
        NotificationDelivery.channel == "IN_APP",
    )):
        delivery.status = "READ"
        delivery.read_at = recipient.read_at
        delivery.updated_at = recipient.read_at
    if not db.get(NotificationContext, notification_id):
        db.get(Notification, notification_id).is_read = True
    return True


def execute_delivery(db, job) -> dict:
    delivery_id = json.loads(job.payload).get("delivery_id")
    delivery = db.scalar(select(NotificationDelivery).where(
        NotificationDelivery.id == delivery_id,
        NotificationDelivery.tenant_id == job.tenant_id,
    ))
    if not delivery:
        raise ValueError("Notification delivery not found")
    if delivery.status in {"SENT", "DELIVERED", "READ"}:
        return {"delivery_id": delivery.id, "status": delivery.status, "duplicate": True}
    if delivery.channel == "EMAIL":
        deliver_email(db, delivery.tenant_id, delivery.recipient_address, delivery.frozen_subject,
                      delivery.frozen_text, delivery.frozen_html or None)
    elif delivery.channel == "WHATSAPP":
        deliver_whatsapp(db, delivery.tenant_id, delivery.recipient_address, delivery.frozen_text,
                         delivery.provider_template, delivery.locale)
    else:
        raise ValueError("Unsupported external notification channel")
    return {"delivery_id": delivery.id, "status": "SENT"}


def update_delivery_success(db, job, completed_at):
    if job.job_type != "NOTIFICATION_DELIVERY":
        return
    delivery = db.get(NotificationDelivery, job.entity_id)
    if delivery:
        delivery.status = "SENT"
        delivery.attempt_count = job.attempt_count
        delivery.sent_at = completed_at
        delivery.updated_at = completed_at
        delivery.last_error_code = ""


def update_delivery_failure(db, job, failed_at, code: str):
    if job.job_type != "NOTIFICATION_DELIVERY":
        return
    delivery = db.get(NotificationDelivery, job.entity_id)
    if delivery:
        delivery.status = "RETRY" if job.status == "RETRY" else "FAILED"
        delivery.attempt_count = job.attempt_count
        delivery.failed_at = failed_at
        delivery.updated_at = failed_at
        delivery.last_error_code = code
