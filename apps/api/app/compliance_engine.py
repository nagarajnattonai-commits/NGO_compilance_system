"""Structured rule/runtime engine shared by preview, onboarding and automation."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from .compliance_template_schema import FIELDS, TemplateConfiguration
from .models import (AuditEvent, AutomationReceipt, Compliance, ComplianceCategory, ComplianceMaster, ComplianceNotificationTemplate,
                     ComplianceReminder, ComplianceSnapshot, ComplianceTemplateVersion, Document,
                     Membership, Notification, Organization, OrganizationComplianceProfile, Task, User, utcnow)


def validate_publish(config: TemplateConfiguration) -> list[str]:
    errors = []
    for field in ("name", "category_id", "jurisdiction"):
        if not getattr(config, field):
            errors.append(f"{field}: required")
    rule = config.applicability
    if not rule.match_all and (not rule.groups or any(not group.conditions for group in rule.groups)):
        errors.append("applicability: explicitly select all organizations or configure nonempty rule groups")
    if rule.match_all and rule.groups:
        errors.append("applicability: match-all cannot also contain conditions")
    if config.deadline.strategy == "FIXED_DATE" and not config.deadline.fixed_date:
        errors.append("deadline: fixed date required")
    if config.deadline.strategy == "CERTIFICATE_EXPIRY_MINUS_DAYS" and not config.deadline.document_type:
        errors.append("deadline: certificate document type required")
    if config.deadline.strategy == "PERIOD_END_PLUS_DAYS" and not config.recurrence.anchor_date:
        errors.append("recurrence: period start anchor required")
    if config.deadline.strategy == "PERIOD_END_PLUS_DAYS" and config.recurrence.anchor_date and config.recurrence.anchor_date.day != 1:
        errors.append("recurrence: period start anchor must be the first day of a month")
    if config.recurrence.frequency == "EVENT_BASED" and config.deadline.strategy != "EVENT_DATE_PLUS_DAYS":
        errors.append("deadline: event-based recurrence requires an event deadline")
    if config.deadline.strategy == "EVENT_DATE_PLUS_DAYS" and config.recurrence.frequency != "EVENT_BASED":
        errors.append("recurrence: event deadlines require event-based recurrence")
    if config.deadline.strategy in {"PERIOD_END_PLUS_DAYS", "FINANCIAL_YEAR_END_PLUS_DAYS"} and config.recurrence.frequency in {"ONE_TIME", "EVENT_BASED"}:
        errors.append("deadline: period deadlines require periodic recurrence")
    if config.deadline.strategy == "FINANCIAL_YEAR_END_PLUS_DAYS" and not (config.recurrence.frequency == "ANNUAL" or config.recurrence.frequency == "CUSTOM" and config.recurrence.interval_months == 12):
        errors.append("recurrence: fiscal-year-end deadlines require a twelve-month recurrence")
    stages = config.workflow.stages
    states = [stage.state for stage in stages]
    if not states or states[0] != "NOT_STARTED" or states[-1] != "COMPLETED" or len(states) != len(set(states)):
        errors.append("workflow: unique stages must start at NOT_STARTED and end at COMPLETED")
    edges = config.workflow.transitions
    pairs = [(edge.from_state, edge.to_state) for edge in edges]
    if len(pairs) != len(set(pairs)):
        errors.append("workflow: duplicate transition")
    if any(a not in states or b not in states or a == b for a, b in pairs):
        errors.append("workflow: transitions must connect two distinct configured states")
    reachable = {"NOT_STARTED"}
    for _ in states:
        reachable.update(b for a, b in pairs if a in reachable)
    if any(state not in reachable for state in states):
        errors.append("workflow: every stage must be reachable from NOT_STARTED")
    can_complete = {"COMPLETED"}
    for _ in states:
        can_complete.update(a for a, b in pairs if b in can_complete)
    if any(state not in can_complete for state in states):
        errors.append("workflow: every stage must have a path to COMPLETED")
    if any(not item.title for item in config.checklist):
        errors.append("checklist: all items require a title")
    if any(not item.document_type for item in config.documents):
        errors.append("documents: all requirements need a document type")
    known = {"checklist": {x.id for x in config.checklist}, "document_instructions": {x.id for x in config.documents}, "reminder_text": {x.id for x in config.reminders}}
    for translation in config.translations.values():
        if any(set(getattr(translation, field)) - ids for field, ids in known.items()):
            errors.append("translations: translation references a missing configuration item")
    return errors


def organization_facts(db, organization):
    profile = db.get(OrganizationComplianceProfile, organization.id)
    return {"annual_revenue": profile.annual_revenue if profile and profile.tenant_id == organization.tenant_id else None,
        "revenue_period": profile.revenue_period if profile else ""}


def combine(matches, operator):
    if not matches:
        return False
    if operator == "AND":
        return False if False in matches else None if None in matches else True
    return True if True in matches else None if None in matches else False


def evaluate_rules(config: TemplateConfiguration, organization: Organization, facts: dict | None = None) -> dict:
    if config.applicability.match_all:
        return {"applicable": True, "groups": [], "match_all": True}
    groups = []
    for group in config.applicability.groups:
        conditions = []
        for rule in group.conditions:
            actual = (facts or {}).get(rule.field) if rule.field in {"annual_revenue", "revenue_period"} else getattr(organization, rule.field, None)
            expected = rule.value
            op = rule.operator
            if isinstance(actual, datetime):
                actual = actual.date()
            if FIELDS[rule.field] == "date" and isinstance(expected, str):
                expected = date.fromisoformat(expected)
            if FIELDS[rule.field] == "number" and isinstance(expected, (int, float)):
                expected = Decimal(str(expected))
            if actual is None and op not in {"IS_EMPTY", "IS_NOT_EMPTY"}:
                result = None
            elif op == "EQUALS":
                result = actual == expected
            elif op == "NOT_EQUALS":
                result = actual != expected
            elif op == "CONTAINS":
                result = str(expected).casefold() in str(actual or "").casefold()
            elif op == "NOT_CONTAINS":
                result = str(expected).casefold() not in str(actual or "").casefold()
            elif op == "IS_EMPTY":
                result = actual is None or actual == ""
            elif op == "IS_NOT_EMPTY":
                result = actual is not None and actual != ""
            elif op == "IS_TRUE":
                result = actual is True
            elif op == "IS_FALSE":
                result = actual is False
            elif op == "IN":
                result = actual in expected
            elif op == "NOT_IN":
                result = actual not in expected
            elif op == "GREATER_THAN":
                result = actual > expected
            elif op == "GREATER_THAN_OR_EQUAL":
                result = actual >= expected
            elif op == "LESS_THAN":
                result = actual < expected
            else:
                result = actual <= expected
            conditions.append({"id": rule.id, "field": rule.field, "operator": op, "actual": actual, "expected": expected, "satisfied": result})
        matches = [condition["satisfied"] for condition in conditions]
        groups.append({"id": group.id, "operator": group.operator, "satisfied": combine(matches, group.operator), "conditions": conditions})
    matches = [group["satisfied"] for group in groups]
    matched = combine(matches, config.applicability.operator)
    return {"applicable": matched is True, "groups": groups, "match_all": False,
        **({"requires_review": "Organization data required for rule evaluation"} if matched is None else {})}


def interval_months(config: TemplateConfiguration) -> int:
    return {"MONTHLY": 1, "QUARTERLY": 3, "HALF_YEARLY": 6, "ANNUAL": 12}.get(config.recurrence.frequency, config.recurrence.interval_months)


def shift_months(value: date, months: int) -> date:
    year, month = divmod(value.year * 12 + value.month - 1 + months, 12)
    # Never silently invent how a statutory date should move in a short month.
    return date(year, month + 1, value.day)


def calculate_deadline(config: TemplateConfiguration, as_of: date, event_date: date | None = None, expiry: date | None = None) -> dict:
    rule = config.deadline
    frequency = config.recurrence.frequency
    if rule.strategy == "FIXED_DATE":
        if not rule.fixed_date:
            raise ValueError("Configure a fixed date before generation")
        deadline = rule.fixed_date
        if frequency not in {"ONE_TIME", "EVENT_BASED"} and deadline < as_of:
            months = interval_months(config)
            distance = (as_of.year - deadline.year) * 12 + as_of.month - deadline.month
            deadline = shift_months(rule.fixed_date, max(0, distance // months) * months)
            if deadline < as_of:
                deadline = shift_months(deadline, months)
        cycle = "ONE_TIME" if frequency == "ONE_TIME" else deadline.isoformat()
    elif rule.strategy == "EVENT_DATE_PLUS_DAYS":
        if not event_date:
            raise ValueError("An event date is required; the system will not guess it")
        deadline = event_date + timedelta(days=rule.offset_days)
        cycle = "EVENT:" + event_date.isoformat()
    elif rule.strategy == "CERTIFICATE_EXPIRY_MINUS_DAYS":
        if not expiry:
            raise ValueError("A valid organization certificate expiry is required")
        deadline = expiry - timedelta(days=rule.offset_days)
        cycle = "EXPIRY:" + expiry.isoformat()
    elif rule.strategy == "FINANCIAL_YEAR_END_PLUS_DAYS":
        start_month = config.recurrence.fiscal_start_month
        start_year = as_of.year if as_of.month >= start_month else as_of.year - 1
        start = date(start_year, start_month, 1)
        end = shift_months(start, 12) - timedelta(days=1)
        deadline = end + timedelta(days=rule.offset_days)
        cycle = f"{start.isoformat()}:{end.isoformat()}"
    else:
        anchor = config.recurrence.anchor_date
        if not anchor or as_of < anchor:
            raise ValueError("A period-start anchor on or before the evaluation date is required")
        months = interval_months(config)
        distance = (as_of.year - anchor.year) * 12 + as_of.month - anchor.month
        start = shift_months(anchor, distance // months * months)
        end = shift_months(start, months) - timedelta(days=1)
        deadline = end + timedelta(days=rule.offset_days)
        cycle = f"{start.isoformat()}:{end.isoformat()}"
    return {"statutory_deadline": deadline, "internal_target": deadline - timedelta(days=rule.internal_lead_days), "cycle": cycle}


def organization_expiry(db, tenant_id: str, organization_id: str, config: TemplateConfiguration):
    if config.deadline.strategy != "CERTIFICATE_EXPIRY_MINUS_DAYS":
        return None
    return db.scalar(select(Document.expiry_at).where(Document.tenant_id == tenant_id, Document.organization_id == organization_id,
        Document.category == config.deadline.document_type, Document.expiry_at.is_not(None)).order_by(Document.expiry_at.desc()).limit(1))


def resolve_role(db, organization: Organization, role: str):
    # Memberships are assignments, not auth accounts: only an active matched account resolves an owner.
    members = db.scalars(select(Membership).where(Membership.tenant_id == organization.tenant_id, Membership.role == role,
        Membership.status == "ACTIVE", or_(Membership.organization_id == organization.id, Membership.organization_id.is_(None))).order_by(Membership.organization_id.desc(), Membership.id)).all()
    for member in members:
        user = db.scalar(select(User).where(User.tenant_id == organization.tenant_id, User.email == member.email, User.status == "ACTIVE", User.role != "VIEWER"))
        if user:
            return user
    if role == "TENANT_ADMIN":
        return db.scalar(select(User).where(User.tenant_id == organization.tenant_id, User.role == "ADMIN", User.status == "ACTIVE").order_by(User.id).limit(1))
    return None


def published_templates(db):
    return db.execute(select(ComplianceMaster, ComplianceTemplateVersion).join(ComplianceTemplateVersion,
        (ComplianceTemplateVersion.definition_id == ComplianceMaster.id) & (ComplianceTemplateVersion.version == ComplianceMaster.current_version)
    ).where(ComplianceTemplateVersion.status == "PUBLISHED")).all()


def generate_master_plan(db, tenant_id: str, organization: Organization, as_of: date | None = None, event_date: date | None = None):
    if organization.tenant_id != tenant_id:
        raise HTTPException(403, "Organization is not owned by this tenant")
    as_of = as_of or date.today()
    generated, review = [], []
    # Serializes callers generating a plan for this organization on PostgreSQL.
    db.execute(select(Organization.id).where(Organization.id == organization.id, Organization.tenant_id == tenant_id).with_for_update()).first()
    for master, version in published_templates(db):
        config = TemplateConfiguration.model_validate_json(version.configuration)
        applicability = evaluate_rules(config, organization, organization_facts(db, organization))
        if applicability.get("requires_review"):
            review.append({"code": master.code, "reason": applicability["requires_review"]})
        if not applicability["applicable"]:
            continue
        try:
            dates = calculate_deadline(config, as_of, event_date, organization_expiry(db, tenant_id, organization.id, config))
        except (ValueError, OverflowError) as error:
            review.append({"code": master.code, "reason": str(error)})
            continue
        if db.scalar(select(ComplianceSnapshot.compliance_id).where(ComplianceSnapshot.tenant_id == tenant_id, ComplianceSnapshot.organization_id == organization.id,
                ComplianceSnapshot.definition_id == master.id, ComplianceSnapshot.cycle == dates["cycle"])):
            continue
        # An existing legacy obligation with this code/deadline is not duplicated or migrated silently.
        if db.scalar(select(Compliance.id).where(Compliance.tenant_id == tenant_id, Compliance.organization_id == organization.id, Compliance.code == master.code,
                Compliance.statutory_deadline == dates["statutory_deadline"])):
            review.append({"code": master.code, "reason": "Existing legacy instance requires explicit migration"})
            continue
        owner = resolve_role(db, organization, config.responsibility.owner_role) or resolve_role(db, organization, config.responsibility.fallback_role)
        category = db.get(ComplianceCategory, config.category_id)
        try:
            with db.begin_nested():
                item = Compliance(tenant_id=tenant_id, organization_id=organization.id, code=master.code, title=config.name, category=category.name,
                    period=dates["cycle"][:30], statutory_deadline=dates["statutory_deadline"], internal_target=dates["internal_target"], status="NOT_STARTED",
                    priority=config.priority, owner_name=owner.name if owner else "Owner Required", owner_initials="".join(x[0] for x in owner.name.split())[:3] if owner else "",
                    progress=0, legal_reference=config.legal_reference, risk_note=f"Template v{version.version}; risk {config.risk_level}" + ("; Owner Required" if not owner else ""))
                db.add(item)
                db.flush()
                task_ids = []
                for checklist in config.checklist:
                    assignee = resolve_role(db, organization, checklist.responsible_role) or owner
                    task = Task(tenant_id=tenant_id, organization_id=organization.id, compliance_id=item.id, title=checklist.title,
                        due_at=dates["statutory_deadline"] + timedelta(days=checklist.relative_due_days), status="TODO", priority=config.priority,
                        assignee_name=assignee.name if assignee else "Owner Required", assignee_initials="")
                    db.add(task)
                    db.flush()
                    task_ids.append({"item_id": checklist.id, "task_id": task.id, "required": checklist.required})
                db.add(ComplianceSnapshot(compliance_id=item.id, tenant_id=tenant_id, organization_id=organization.id, definition_id=master.id,
                    version_id=version.id, cycle=dates["cycle"], configuration=version.configuration, checklist_tasks=json.dumps(task_ids), owner_required=owner is None))
                for reminder in config.reminders:
                    if reminder.enabled:
                        db.add(ComplianceReminder(tenant_id=tenant_id, compliance_id=item.id, event_key=f"{tenant_id}:master:{item.id}:{reminder.id}",
                            scheduled_for=dates["statutory_deadline"] + timedelta(days=reminder.offset_days), configuration=reminder.model_dump_json()))
                db.add(AuditEvent(tenant_id=tenant_id, actor_name=db.info.get("actor_name", "System"), action="COMPLIANCE_GENERATED",
                    entity_type="Compliance", entity_id=item.id, summary=f"Generated {master.code} v{version.version}, cycle {dates['cycle']}"[:280]))
                db.flush()
            generated.append(item)
        except IntegrityError:
            # The unique snapshot cycle is the final concurrency/idempotency guard.
            if not db.scalar(select(ComplianceSnapshot.compliance_id).where(ComplianceSnapshot.tenant_id == tenant_id, ComplianceSnapshot.organization_id == organization.id,
                    ComplianceSnapshot.definition_id == master.id, ComplianceSnapshot.cycle == dates["cycle"])):
                raise
    return generated, review


def document_coverage(db, snapshot: ComplianceSnapshot, deadline: date):
    config = TemplateConfiguration.model_validate_json(snapshot.configuration)
    documents = db.scalars(select(Document).where(Document.tenant_id == snapshot.tenant_id, Document.organization_id == snapshot.organization_id)).all()
    return [{"id": requirement.id, "document_type": requirement.document_type, "required": requirement.required, "minimum_count": requirement.minimum_count,
        "document_ids": [doc.id for doc in documents if doc.category == requirement.document_type and (not requirement.must_be_valid or not doc.expiry_at or doc.expiry_at >= deadline)]}
        for requirement in config.documents]


def actor_roles(db, tenant_id, organization_id):
    user = db.get(User, db.info.get("actor_id"))
    roles = {"TENANT_ADMIN"} if user and user.role == "ADMIN" else set()
    if user and user.role != "VIEWER":
        roles.update(db.scalars(select(Membership.role).where(Membership.tenant_id == tenant_id, Membership.email == user.email,
            Membership.status == "ACTIVE", or_(Membership.organization_id == organization_id, Membership.organization_id.is_(None)))).all())
    return roles


def enforce_snapshot_transition(db, tenant_id, item, target_status, proof_document_id):
    snapshot = db.get(ComplianceSnapshot, item.id)
    if not snapshot or snapshot.tenant_id != tenant_id:
        return None
    config = TemplateConfiguration.model_validate_json(snapshot.configuration)
    source = "IN_PROGRESS" if item.status == "OVERDUE" else item.status
    edge = next((edge for edge in config.workflow.transitions if edge.from_state == source and edge.to_state == target_status), None)
    if not edge:
        raise HTTPException(409, "Transition is not allowed by this instance's template version")
    roles = actor_roles(db, tenant_id, item.organization_id)
    if not roles.intersection(edge.allowed_roles):
        raise HTTPException(403, "Your organization role cannot perform this transition")
    if edge.required_approval and not roles.intersection({config.responsibility.reviewer_role, config.responsibility.approver_role}):
        raise HTTPException(403, "The configured reviewer or approver must approve this transition")
    if edge.required_evidence and not proof_document_id:
        raise HTTPException(422, "This workflow transition requires organization evidence")
    if target_status == "COMPLETED":
        required_ids = [entry["task_id"] for entry in json.loads(snapshot.checklist_tasks) if entry["required"]]
        if required_ids and db.scalar(select(Task.id).where(Task.tenant_id == tenant_id, Task.id.in_(required_ids), Task.status != "DONE")):
            raise HTTPException(422, "Required checklist tasks must be complete")
        if any(entry["required"] and len(entry["document_ids"]) < entry["minimum_count"] for entry in document_coverage(db, snapshot, item.statutory_deadline)):
            raise HTTPException(422, "Required valid organization documents are missing")
    return edge


def dispatch_master_reminders(db, tenant_id: str, today: date) -> int:
    count = 0
    reminders = db.scalars(select(ComplianceReminder).where(ComplianceReminder.tenant_id == tenant_id,
        ComplianceReminder.scheduled_for <= today, ComplianceReminder.sent_at.is_(None)).with_for_update()).all()
    for reminder in reminders:
        item = db.get(Compliance, reminder.compliance_id)
        if not item or item.status in {"COMPLETED", "CANCELLED", "NOT_APPLICABLE"}:
            reminder.sent_at = utcnow()
            continue
        if db.scalar(select(AutomationReceipt.id).where(AutomationReceipt.event_key == reminder.event_key)):
            reminder.sent_at = utcnow()
            continue
        rule = json.loads(reminder.configuration)
        try:
            with db.begin_nested():
                db.add(AutomationReceipt(tenant_id=tenant_id, event_key=reminder.event_key, event_type="TEMPLATE_REMINDER"))
                # Existing notifications are tenant-wide. Recipient role remains visible, not claimed as private routing.
                notification = Notification(tenant_id=tenant_id, title=item.title,
                    message=f"[{rule['recipient_role']}] " + (rule["text"] or f"{item.code} — {item.statutory_deadline.isoformat()}"),
                    kind="WARNING" if rule["escalation_level"] else "REMINDER")
                db.add(notification)
                db.flush()
                snapshot = db.get(ComplianceSnapshot, item.id)
                config = TemplateConfiguration.model_validate_json(snapshot.configuration)
                db.add(ComplianceNotificationTemplate(notification_id=notification.id, tenant_id=tenant_id, variables=json.dumps({
                    "complianceName": item.title, "names": {locale: translation.name for locale, translation in config.translations.items() if translation.name},
                    "dueDate": item.statutory_deadline.isoformat(), "recipientRole": rule["recipient_role"], "reminderText": rule["text"],
                    "reminderTexts": {locale: translation.reminder_text.get(rule["id"], "") for locale, translation in config.translations.items()},
                    "escalationLevel": rule["escalation_level"], "templateVersionId": snapshot.version_id,
                }, ensure_ascii=False)))
                reminder.sent_at = utcnow()
                db.flush()
            count += 1
        except IntegrityError:
            if not db.scalar(select(AutomationReceipt.id).where(AutomationReceipt.event_key == reminder.event_key)):
                raise
    return count
