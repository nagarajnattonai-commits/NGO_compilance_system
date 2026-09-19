"""Phase 7 recipient, preference, localization, delivery and isolation contracts."""
import json
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.auth import now
from app.automation_models import ScheduledJob
from app.automation_service import claim_job, execute_job, fail_job, finish_job
from app.database import SessionLocal, engine
from app.integration_security import IntegrationError
from app.migrate_notifications import VERSION, apply
from app.models import ComplianceNotificationTemplate, Membership, Notification, Organization, TenantLocale, User, UserPreference, Workspace
from app.notification_models import NotificationDelivery, NotificationRecipient, UserNotificationPreference
from app.notification_service import distribute_notification, mark_read, notification_inbox, resolve_recipients


def setup_tenant(db, tenant_id="tenant-a"):
    db.add(Workspace(id=tenant_id, name=tenant_id))
    db.add(Organization(id="org-" + tenant_id[-1], tenant_id=tenant_id, name="NGO " + tenant_id,
                        legal_type="TRUST", registration_number="REG-" + tenant_id))
    db.add(TenantLocale(tenant_id=tenant_id, locale_code="en-IN", display_name="English", enabled=True, is_default=True))
    db.flush()


def add_user(db, identifier, tenant_id="tenant-a", *, role="MEMBER", phone="919999999999", locale=None):
    user = User(id=identifier, tenant_id=tenant_id, name=identifier, email=identifier + "@example.test",
                phone=phone, role=role, status="ACTIVE")
    db.add(user)
    if locale:
        db.add(UserPreference(user_id=identifier, tenant_id=tenant_id, locale=locale,
                              timezone="Asia/Kolkata", time_format="12h"))
    db.flush()
    return user


def notice(db, tenant_id="tenant-a", identifier="notice", *, localized=False):
    row = Notification(id=identifier, tenant_id=tenant_id, title="Annual filing", message="Filing due", kind="REMINDER")
    db.add(row)
    db.flush()
    if localized:
        db.add(ComplianceNotificationTemplate(notification_id=row.id, tenant_id=tenant_id,
            template_key="compliance.deadlineReminder", variables=json.dumps({
                "complianceName": "Annual filing", "names": {"hi-IN": "वार्षिक दाखिला"},
                "dueDate": "2026-09-30", "reminderText": "Filing due",
                "reminderTexts": {"hi-IN": "दाखिला शीघ्र देय है"},
            }, ensure_ascii=False)))
        db.flush()
    return row


def test_recipient_resolution_uses_active_real_accounts_and_organization_scope():
    with SessionLocal() as db:
        setup_tenant(db)
        assigned = add_user(db, "assigned")
        add_user(db, "unassigned")
        db.add(Membership(tenant_id="tenant-a", organization_id="org-a", name="Assigned",
                          email=assigned.email, role="COMPLIANCE_OFFICER", status="ACTIVE"))
        db.add(Membership(tenant_id="tenant-a", organization_id=None, name="Inactive",
                          email="unassigned@example.test", role="COMPLIANCE_OFFICER", status="DISABLED"))
        db.commit()
        result = resolve_recipients(db, "tenant-a", organization_id="org-a", recipient_role="COMPLIANCE_OFFICER")
        assert [user.id for user in result] == ["assigned"]


def test_preferences_control_channels_but_in_app_is_durable():
    with SessionLocal() as db:
        setup_tenant(db)
        user = add_user(db, "recipient")
        db.add(Membership(tenant_id="tenant-a", organization_id="org-a", name=user.name,
                          email=user.email, role="ACCOUNTANT", status="ACTIVE"))
        preference = UserNotificationPreference(user_id=user.id, tenant_id="tenant-a", email_enabled=False,
                                                whatsapp_enabled=True)
        db.add(preference)
        row = notice(db)
        assert distribute_notification(db, row, event_type="DEADLINE", organization_id="org-a",
            recipient_role="ACCOUNTANT", channels=("EMAIL", "WHATSAPP")) == 3
        db.commit()
        statuses = {item.channel: (item.status, item.last_error_code) for item in db.scalars(select(NotificationDelivery)).all()}
        assert statuses["IN_APP"] == ("DELIVERED", "")
        assert statuses["EMAIL"] == ("CANCELLED", "CHANNEL_DISABLED")
        assert statuses["WHATSAPP"][0] == "QUEUED"
        assert db.scalar(select(ScheduledJob).where(ScheduledJob.job_type == "NOTIFICATION_DELIVERY"))


def test_localized_content_is_frozen_when_queued(monkeypatch):
    with SessionLocal() as db:
        setup_tenant(db)
        user = add_user(db, "hindi", locale="hi-IN")
        db.add(Membership(tenant_id="tenant-a", organization_id="org-a", name=user.name,
                          email=user.email, role="AUDITOR", status="ACTIVE"))
        row = notice(db, localized=True)
        distribute_notification(db, row, event_type="DEADLINE", organization_id="org-a",
                                recipient_role="AUDITOR", channels=("EMAIL",))
        db.commit()
        delivery = db.scalar(select(NotificationDelivery).where(NotificationDelivery.channel == "EMAIL"))
        assert delivery.locale == "hi-IN"
        assert delivery.frozen_text == "दाखिला शीघ्र देय है"
        assert "वार्षिक दाखिला" in delivery.frozen_html
        template = db.get(ComplianceNotificationTemplate, row.id)
        template.variables = json.dumps({"reminderText": "Changed later"})
        db.commit()
        assert db.get(NotificationDelivery, delivery.id).frozen_text == "दाखिला शीघ्र देय है"


def test_email_and_whatsapp_jobs_record_success(monkeypatch):
    sent = []
    monkeypatch.setattr("app.notification_service.deliver_email", lambda *args, **kwargs: sent.append("EMAIL"))
    monkeypatch.setattr("app.notification_service.deliver_whatsapp", lambda *args, **kwargs: sent.append("WHATSAPP"))
    with SessionLocal() as db:
        setup_tenant(db)
        user = add_user(db, "recipient")
        db.add(Membership(tenant_id="tenant-a", organization_id="org-a", name=user.name,
                          email=user.email, role="AUDITOR", status="ACTIVE"))
        db.add(UserNotificationPreference(user_id=user.id, tenant_id="tenant-a", whatsapp_enabled=True))
        distribute_notification(db, notice(db), event_type="DEADLINE", organization_id="org-a",
                                recipient_role="AUDITOR", channels=("EMAIL", "WHATSAPP"), provider_template="deadline_notice")
        db.commit()
        for index in range(2):
            claimed = claim_job(db, "worker", at=now() + timedelta(seconds=index))
            result = execute_job(db, claimed)
            finish_job(db, claimed, result)
            db.commit()
        assert set(sent) == {"EMAIL", "WHATSAPP"}
        assert {row.status for row in db.scalars(select(NotificationDelivery).where(NotificationDelivery.channel != "IN_APP"))} == {"SENT"}


@pytest.mark.parametrize("code,expected_job,expected_delivery", [
    ("PROVIDER_UNAVAILABLE", "RETRY", "RETRY"),
    ("INVALID_CONFIGURATION", "FAILED", "FAILED"),
])
def test_provider_failure_is_classified_and_persisted(monkeypatch, code, expected_job, expected_delivery):
    monkeypatch.setattr("app.notification_service.deliver_email", lambda *args, **kwargs: (_ for _ in ()).throw(IntegrationError(code)))
    with SessionLocal() as db:
        setup_tenant(db)
        user = add_user(db, "recipient")
        db.add(Membership(tenant_id="tenant-a", organization_id="org-a", name=user.name,
                          email=user.email, role="AUDITOR", status="ACTIVE"))
        distribute_notification(db, notice(db), event_type="DEADLINE", organization_id="org-a",
                                recipient_role="AUDITOR", channels=("EMAIL",))
        db.commit()
        claimed = claim_job(db, "worker", at=now())
        with pytest.raises(IntegrationError) as caught:
            execute_job(db, claimed)
        db.rollback()
        claimed = db.get(ScheduledJob, claimed.id)
        fail_job(db, claimed, caught.value)
        db.commit()
        delivery = db.scalar(select(NotificationDelivery).where(NotificationDelivery.channel == "EMAIL"))
        assert claimed.status == expected_job and delivery.status == expected_delivery
        assert delivery.last_error_code == code


def test_per_user_read_state_and_tenant_isolation():
    with SessionLocal() as db:
        setup_tenant(db, "tenant-a")
        setup_tenant(db, "tenant-b")
        first = add_user(db, "first", "tenant-a")
        second = add_user(db, "second", "tenant-a")
        outsider = add_user(db, "outsider", "tenant-b")
        row = notice(db)
        distribute_notification(db, row, event_type="SYSTEM", category="SYSTEM", user_ids=(first.id, second.id))
        db.commit()
        assert len(notification_inbox(db, "tenant-a", first.id)) == 1
        assert mark_read(db, "tenant-a", first.id, row.id)
        db.commit()
        states = {item.user_id: item.read_at is not None for item in db.scalars(select(NotificationRecipient)).all()}
        assert states == {"first": True, "second": False}
        assert notification_inbox(db, "tenant-b", outsider.id) == []
        assert not mark_read(db, "tenant-b", outsider.id, row.id)


def test_phase7_migration_is_repeatable():
    assert apply(engine) == VERSION
    assert apply(engine) == VERSION
