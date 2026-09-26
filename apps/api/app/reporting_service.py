"""Tenant- and organization-scoped reporting queries over operational records."""
from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, time, timedelta, timezone
import json

from fastapi import HTTPException
from sqlalchemy import and_, case, extract, func, or_, select
from sqlalchemy.orm import Session

from .compliance_states import CLOSED_STATES, EXCLUDED_STATES
from .document_models import DocumentBlob, DocumentCurrent, DocumentEvidenceLink
from .models import AuditEvent, Compliance, ComplianceSnapshot, Document, DocumentVersion, Organization, Submission, Task, User
from .organization_access import accessible_organization_ids
from .phase9_models import ComplianceApproval, ComplianceReview
from .runtime_models import ApplicabilityDecision, ComplianceOwnership

IN_PROGRESS_EXCLUDED = CLOSED_STATES | {"UNDER_REVIEW", "READY_TO_FILE", "FILED"}


def _add_month(value: date, offset: int) -> date:
    month_index = value.year * 12 + value.month - 1 + offset
    year, month_index = divmod(month_index, 12)
    month = month_index + 1
    return date(year, month, min(value.day, monthrange(year, month)[1]))


def _month_range(first: date, count: int) -> list[str]:
    return [(_add_month(first, offset)).strftime("%Y-%m") for offset in range(count)]


def _scope(db: Session, tenant_id: str, user, organization_id: str | None):
    if getattr(user, "_admin_audience", False):
        raise HTTPException(403, "Platform administrator sessions cannot access workspace reports")
    allowed = accessible_organization_ids(db, tenant_id, user.id)
    organizations_query = select(Organization).where(Organization.tenant_id == tenant_id)
    if allowed is not None:
        organizations_query = organizations_query.where(Organization.id.in_(allowed))
    organizations = db.scalars(organizations_query.order_by(Organization.name)).all()
    organization_ids = {organization.id for organization in organizations}
    if organization_id:
        if organization_id not in organization_ids:
            raise HTTPException(404, "Organization not found")
        organizations = [organization for organization in organizations if organization.id == organization_id]
        organization_ids = {organization_id}
    return organizations, organization_ids


def reporting_organizations(db: Session, tenant_id: str, user, organization_id: str | None = None):
    return _scope(db, tenant_id, user, organization_id)[0]


def _compliance_filters(
    tenant_id: str,
    organization_ids: set[str],
    *,
    category: str | None,
    status: str | None,
    owner: str | None,
    priority: str | None,
    date_from: date | None,
    date_to: date | None,
):
    filters = [Compliance.tenant_id == tenant_id, Compliance.organization_id.in_(organization_ids)]
    if category:
        filters.append(Compliance.category == category)
    if status:
        filters.append(Compliance.status == status)
    if owner:
        filters.append(func.lower(Compliance.owner_name).contains(owner.strip().lower()))
    if priority:
        filters.append(Compliance.priority == priority)
    if date_from:
        filters.append(Compliance.statutory_deadline >= date_from)
    if date_to:
        filters.append(Compliance.statutory_deadline <= date_to)
    return filters


def management_analytics(
    db: Session,
    tenant_id: str,
    user,
    *,
    organization_id: str | None = None,
    category: str | None = None,
    status: str | None = None,
    owner: str | None = None,
    priority: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    horizon_days: int = 30,
) -> dict:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "date_from must not be after date_to")
    organizations, organization_ids = _scope(db, tenant_id, user, organization_id)
    filters = _compliance_filters(
        tenant_id, organization_ids, category=category, status=status, owner=owner,
        priority=priority, date_from=date_from, date_to=date_to,
    )
    today = date.today()
    horizon_end = today + timedelta(days=horizon_days)
    expiry_end = today + timedelta(days=90)

    status_rows = db.execute(select(Compliance.status, func.count()).where(*filters).group_by(Compliance.status)).all()
    status_counts = {key: count for key, count in status_rows}
    total = sum(status_counts.values())
    completed = status_counts.get("COMPLETED", 0)
    cancelled = status_counts.get("CANCELLED", 0)
    not_applicable = status_counts.get("NOT_APPLICABLE", 0)
    applicable = total - sum(status_counts.get(state, 0) for state in EXCLUDED_STATES)
    active_filters = [*filters, Compliance.status.not_in(CLOSED_STATES)]
    overdue = db.scalar(select(func.count()).select_from(Compliance).where(
        *active_filters, Compliance.statutory_deadline < today,
    )) or 0
    upcoming = db.scalar(select(func.count()).select_from(Compliance).where(
        *active_filters, Compliance.statutory_deadline >= today,
        Compliance.statutory_deadline <= horizon_end,
    )) or 0
    risk_rows = db.execute(select(Compliance.priority, func.count()).where(
        *active_filters, Compliance.priority.in_(("HIGH", "CRITICAL")),
    ).group_by(Compliance.priority)).all()
    high_risk = sum(count for _, count in risk_rows)
    needs_review = status_counts.get("UNDER_REVIEW", 0)
    in_progress = sum(
        count for state, count in status_counts.items() if state not in IN_PROGRESS_EXCLUDED
    )

    compliance_ids = select(Compliance.id).where(*filters)
    filing_count = db.scalar(select(func.count(func.distinct(Submission.compliance_id))).where(
        Submission.tenant_id == tenant_id,
        Submission.compliance_id.in_(compliance_ids),
        Submission.filed_at.is_not(None),
    )) or 0

    task_filters = [Task.tenant_id == tenant_id, Task.organization_id.in_(organization_ids), Task.archived_at.is_(None)]
    if date_from:
        task_filters.append(Task.due_at >= date_from)
    if date_to:
        task_filters.append(Task.due_at <= date_to)
    if owner:
        task_filters.append(func.lower(Task.assignee_name).contains(owner.strip().lower()))
    if category or status or priority:
        task_filters.append(Task.compliance_id.in_(compliance_ids))
    task_rows = db.execute(select(
        Task.organization_id,
        Task.status,
        func.count(),
        func.sum(case((and_(Task.status != "DONE", Task.due_at >= today, Task.due_at <= horizon_end), 1), else_=0)),
        func.sum(case((and_(Task.status != "DONE", Task.due_at < today), 1), else_=0)),
    ).where(*task_filters).group_by(Task.organization_id, Task.status)).all()
    task_by_org: dict[str, dict[str, int]] = {}
    task_status_counts: dict[str, int] = {}
    tasks_due = overdue_tasks = 0
    for org_id, task_status, count, due_count, late_count in task_rows:
        task_by_org.setdefault(org_id, {"total": 0, "completed": 0})
        task_by_org[org_id]["total"] += count
        if task_status == "DONE":
            task_by_org[org_id]["completed"] += count
        task_status_counts[task_status] = task_status_counts.get(task_status, 0) + count
        tasks_due += int(due_count or 0)
        overdue_tasks += int(late_count or 0)

    document_rows = db.execute(select(Document.organization_id, func.count()).outerjoin(
        DocumentCurrent, and_(DocumentCurrent.document_id == Document.id, DocumentCurrent.tenant_id == Document.tenant_id),
    ).where(
        Document.tenant_id == tenant_id,
        Document.organization_id.in_(organization_ids),
        Document.expiry_at >= today,
        Document.expiry_at <= expiry_end,
        or_(DocumentCurrent.document_id.is_(None), DocumentCurrent.archived.is_(False)),
    ).group_by(Document.organization_id)).all()
    expiring_by_org = dict(document_rows)

    org_status_rows = db.execute(select(Compliance.organization_id, Compliance.status, func.count()).where(
        *filters,
    ).group_by(Compliance.organization_id, Compliance.status)).all()
    org_status_counts: dict[str, dict[str, int]] = {}
    for org_id, compliance_status, count in org_status_rows:
        org_status_counts.setdefault(org_id, {})[compliance_status] = count
    org_overdue_rows = db.execute(select(Compliance.organization_id, func.count()).where(
        *active_filters, Compliance.statutory_deadline < today,
    ).group_by(Compliance.organization_id)).all()
    overdue_by_org = dict(org_overdue_rows)
    org_upcoming_rows = db.execute(select(Compliance.organization_id, func.count()).where(
        *active_filters, Compliance.statutory_deadline >= today,
        Compliance.statutory_deadline <= horizon_end,
    ).group_by(Compliance.organization_id)).all()
    upcoming_by_org = dict(org_upcoming_rows)

    organization_summaries = []
    for organization in organizations:
        counts = org_status_counts.get(organization.id, {})
        org_total = sum(counts.values())
        org_completed = counts.get("COMPLETED", 0)
        org_applicable = org_total - sum(counts.get(state, 0) for state in EXCLUDED_STATES)
        task_summary = task_by_org.get(organization.id, {"total": 0, "completed": 0})
        task_total = task_summary["total"]
        organization_summaries.append({
            "organization_id": organization.id,
            "organization_name": organization.name,
            "total_applicable": org_applicable,
            "completed": org_completed,
            "pending": max(0, org_applicable - org_completed),
            "overdue": overdue_by_org.get(organization.id, 0),
            "upcoming": upcoming_by_org.get(organization.id, 0),
            "completion_percentage": round(org_completed / org_applicable * 100) if org_applicable else 0,
            "task_total": task_total,
            "task_completed": task_summary["completed"],
            "task_completion_percentage": round(task_summary["completed"] / task_total * 100) if task_total else 0,
            "documents_expiring": expiring_by_org.get(organization.id, 0),
        })

    status_distribution = [{"status": key, "count": status_counts[key]} for key in sorted(status_counts)]
    first_month = today.replace(day=1)
    future_months = _month_range(first_month, 6)
    future_end = _add_month(first_month, 6)
    deadline_rows = db.execute(select(
        extract("year", Compliance.statutory_deadline),
        extract("month", Compliance.statutory_deadline),
        func.count(),
    ).where(
        *active_filters,
        Compliance.statutory_deadline >= first_month,
        Compliance.statutory_deadline < future_end,
    ).group_by(extract("year", Compliance.statutory_deadline), extract("month", Compliance.statutory_deadline))).all()
    deadline_counts = {f"{int(year):04d}-{int(month):02d}": count for year, month, count in deadline_rows}
    monthly_deadline_trend = [{"month": month, "count": deadline_counts.get(month, 0)} for month in future_months]

    history_start = _add_month(first_month, -5)
    history_months = _month_range(history_start, 6)
    history_start_at = datetime.combine(history_start, time.min, timezone.utc)
    history_end_at = datetime.combine(_add_month(first_month, 1), time.min, timezone.utc)
    def audit_counts(action: str, summary_pattern: str | None = None) -> dict[str, int]:
        query = select(
            extract("year", AuditEvent.created_at),
            extract("month", AuditEvent.created_at),
            func.count(AuditEvent.id),
        ).join(Compliance, and_(Compliance.id == AuditEvent.entity_id, Compliance.tenant_id == AuditEvent.tenant_id)).where(
            AuditEvent.tenant_id == tenant_id,
            AuditEvent.entity_type == "Compliance",
            AuditEvent.action == action,
            AuditEvent.created_at >= history_start_at,
            AuditEvent.created_at < history_end_at,
            *filters,
        )
        if summary_pattern:
            query = query.where(AuditEvent.summary.like(summary_pattern))
        rows = db.execute(query.group_by(
            extract("year", AuditEvent.created_at), extract("month", AuditEvent.created_at),
        )).all()
        return {f"{int(year):04d}-{int(month):02d}": count for year, month, count in rows}

    completion_counts = audit_counts("STATUS_CHANGED", "% -> COMPLETED%")
    overdue_counts = audit_counts("COMPLIANCE_OVERDUE")
    upcoming_rows = db.execute(select(Compliance, Organization.name).join(
        Organization, and_(Organization.id == Compliance.organization_id, Organization.tenant_id == Compliance.tenant_id),
    ).where(
        *active_filters,
        Compliance.statutory_deadline >= today,
        Compliance.statutory_deadline <= horizon_end,
    ).order_by(Compliance.statutory_deadline, Compliance.priority.desc()).limit(12)).all()
    upcoming_deadlines = [{
        "compliance_id": item.id,
        "organization_id": item.organization_id,
        "organization_name": organization_name,
        "code": item.code,
        "compliance": item.title,
        "owner": item.owner_name,
        "due_date": item.statutory_deadline.isoformat(),
        "days_remaining": (item.statutory_deadline - today).days,
        "status": item.status,
        "priority": item.priority,
    } for item, organization_name in upcoming_rows]

    option_filters = [Compliance.tenant_id == tenant_id, Compliance.organization_id.in_(organization_ids)]
    category_options = db.scalars(select(Compliance.category).where(*option_filters).distinct().order_by(Compliance.category)).all()
    owner_options = db.scalars(select(Compliance.owner_name).where(*option_filters).distinct().order_by(Compliance.owner_name)).all()
    status_options = db.scalars(select(Compliance.status).where(*option_filters).distinct().order_by(Compliance.status)).all()
    return {
        "summary": {
            "total": total,
            "completed": completed,
            "in_progress": in_progress,
            "overdue": overdue,
            "upcoming": upcoming,
            "requires_review": needs_review,
            "not_applicable": not_applicable,
            "cancelled": cancelled,
            "tasks_due": tasks_due,
            "overdue_tasks": overdue_tasks,
            "documents_expiring": sum(expiring_by_org.values()),
            "filing_completion_percentage": round(filing_count / applicable * 100) if applicable else 0,
            "high_risk": high_risk,
            "open": total - sum(status_counts.get(state, 0) for state in CLOSED_STATES),
            "completion_rate": round(completed / applicable * 100) if applicable else 0,
        },
        "upcoming_deadlines": upcoming_deadlines,
        "organization_summaries": organization_summaries,
        "charts": {
            "status_distribution": status_distribution,
            "monthly_deadline_trend": monthly_deadline_trend,
            "completion_trend": [{"month": month, "count": completion_counts.get(month, 0)} for month in history_months],
            "overdue_trend": [{"month": month, "count": overdue_counts.get(month, 0)} for month in history_months],
            "task_status_distribution": [{"status": key, "count": task_status_counts[key]} for key in sorted(task_status_counts)],
            "organization_comparison": organization_summaries,
        },
        "filters": {
            "organizations": [{"id": item.id, "name": item.name} for item in organizations],
            "categories": category_options,
            "owners": owner_options,
            "statuses": status_options,
            "priorities": ["LOW", "MEDIUM", "HIGH", "CRITICAL"],
            "horizons": [7, 30, 60, 90],
        },
    }


def compliance_report_rows(
    db: Session,
    tenant_id: str,
    user,
    *,
    organization_id: str | None = None,
    category: str | None = None,
    status: str | None = None,
    owner: str | None = None,
    priority: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[dict]:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "date_from must not be after date_to")
    _, organization_ids = _scope(db, tenant_id, user, organization_id)
    filters = _compliance_filters(
        tenant_id, organization_ids, category=category, status=status, owner=owner,
        priority=priority, date_from=date_from, date_to=date_to,
    )
    selected = db.execute(select(Compliance, Organization.name).join(
        Organization, and_(Organization.id == Compliance.organization_id, Organization.tenant_id == Compliance.tenant_id),
    ).where(*filters).order_by(Compliance.statutory_deadline, Compliance.code).offset(offset).limit(limit)).all()
    if not selected:
        return []
    items = [item for item, _ in selected]
    item_ids = [item.id for item in items]
    snapshots = {row.compliance_id: row for row in db.scalars(select(ComplianceSnapshot).where(
        ComplianceSnapshot.tenant_id == tenant_id, ComplianceSnapshot.compliance_id.in_(item_ids),
    )).all()}
    tasks = db.scalars(select(Task).where(
        Task.tenant_id == tenant_id, Task.organization_id.in_(organization_ids), Task.compliance_id.in_(item_ids),
    ).order_by(Task.due_at, Task.title)).all()
    tasks_by_compliance: dict[str, list[Task]] = {}
    tasks_by_id: dict[str, Task] = {}
    for task in tasks:
        tasks_by_compliance.setdefault(task.compliance_id, []).append(task)
        tasks_by_id[task.id] = task
    submissions = db.scalars(select(Submission).where(
        Submission.tenant_id == tenant_id, Submission.compliance_id.in_(item_ids),
    ).order_by(Submission.submitted_at.desc())).all()
    submissions_by_compliance: dict[str, list[Submission]] = {}
    submissions_by_id: dict[str, Submission] = {}
    for submission in submissions:
        submissions_by_compliance.setdefault(submission.compliance_id, []).append(submission)
        submissions_by_id[submission.id] = submission
    task_ids = list(tasks_by_id)
    submission_ids = list(submissions_by_id)
    link_scopes = [DocumentEvidenceLink.compliance_id.in_(item_ids)]
    if task_ids:
        link_scopes.append(DocumentEvidenceLink.task_id.in_(task_ids))
    if submission_ids:
        link_scopes.append(DocumentEvidenceLink.submission_id.in_(submission_ids))
    evidence_rows = db.execute(select(DocumentEvidenceLink, Document, DocumentBlob).join(
        Document, and_(Document.id == DocumentEvidenceLink.document_id, Document.tenant_id == DocumentEvidenceLink.tenant_id),
    ).join(
        DocumentBlob, and_(DocumentBlob.version_id == DocumentEvidenceLink.version_id,
                           DocumentBlob.document_id == DocumentEvidenceLink.document_id,
                           DocumentBlob.tenant_id == DocumentEvidenceLink.tenant_id),
    ).where(
        DocumentEvidenceLink.tenant_id == tenant_id,
        DocumentEvidenceLink.organization_id.in_(organization_ids),
        DocumentEvidenceLink.active.is_(True),
        DocumentBlob.status == "AVAILABLE",
        or_(*link_scopes),
    )).all()
    evidence_by_compliance: dict[str, list[dict]] = {}
    for link, document, blob in evidence_rows:
        compliance_id = link.compliance_id
        if not compliance_id and link.task_id:
            task = tasks_by_id.get(link.task_id)
            compliance_id = task.compliance_id if task else None
        if not compliance_id and link.submission_id:
            submission = submissions_by_id.get(link.submission_id)
            compliance_id = submission.compliance_id if submission else None
        if compliance_id not in item_ids:
            continue
        source = "compliance" if link.compliance_id else "task" if link.task_id else "filing"
        evidence_by_compliance.setdefault(compliance_id, []).append({
            "name": document.name,
            "category": document.category,
            "version": blob.version_number,
            "uploaded_at": blob.uploaded_at.isoformat(),
            "expiry_at": blob.expiry_at.isoformat() if blob.expiry_at else None,
            "effective_at": blob.effective_at.isoformat() if blob.effective_at else None,
            "source": source,
        })

    direct_documents = db.scalars(select(Document).where(
        Document.tenant_id == tenant_id,
        Document.organization_id.in_(organization_ids),
        Document.compliance_id.in_(item_ids),
    )).all()
    for document in direct_documents:
        evidence_by_compliance.setdefault(document.compliance_id, []).append({
            "name": document.name,
            "category": document.category,
            "version": document.version,
            "uploaded_at": document.created_at.isoformat(),
            "expiry_at": document.expiry_at.isoformat() if document.expiry_at else None,
            "effective_at": None,
            "source": "record",
        })

    reviews = db.scalars(select(ComplianceReview).where(
        ComplianceReview.tenant_id == tenant_id, ComplianceReview.compliance_id.in_(item_ids),
    ).order_by(ComplianceReview.revision.desc())).all()
    reviews_by_compliance: dict[str, list[ComplianceReview]] = {}
    for review in reviews:
        reviews_by_compliance.setdefault(review.compliance_id, []).append(review)
    approvals = db.scalars(select(ComplianceApproval).where(
        ComplianceApproval.tenant_id == tenant_id, ComplianceApproval.compliance_id.in_(item_ids),
    ).order_by(ComplianceApproval.requested_at.desc())).all()
    approvals_by_compliance: dict[str, list[ComplianceApproval]] = {}
    for approval in approvals:
        approvals_by_compliance.setdefault(approval.compliance_id, []).append(approval)
    audits = db.scalars(select(AuditEvent).where(
        AuditEvent.tenant_id == tenant_id,
        AuditEvent.entity_type == "Compliance",
        AuditEvent.entity_id.in_(item_ids),
    ).order_by(AuditEvent.created_at, AuditEvent.id)).all()
    audits_by_compliance: dict[str, list[AuditEvent]] = {}
    for audit in audits:
        audits_by_compliance.setdefault(audit.entity_id, []).append(audit)

    owners = {row.compliance_id: row.owner_id for row in db.scalars(select(ComplianceOwnership).where(
        ComplianceOwnership.tenant_id == tenant_id, ComplianceOwnership.compliance_id.in_(item_ids),
    )).all()}
    snapshot_definition_ids = {row.definition_id for row in snapshots.values()}
    decisions = db.scalars(select(ApplicabilityDecision).where(
        ApplicabilityDecision.tenant_id == tenant_id,
        ApplicabilityDecision.organization_id.in_(organization_ids),
        ApplicabilityDecision.template_id.in_(snapshot_definition_ids),
    ).order_by(ApplicabilityDecision.evaluated_at.desc())).all() if snapshot_definition_ids else []
    decisions_by_template_org: dict[tuple[str, str], ApplicabilityDecision] = {}
    for decision in decisions:
        decisions_by_template_org.setdefault((decision.organization_id, decision.template_id), decision)
    related_user_ids = set(owners.values())
    related_user_ids.update(row.submitted_by for row in reviews)
    related_user_ids.update(row.reviewer_id for row in reviews if row.reviewer_id)
    related_user_ids.update(row.requested_by for row in approvals)
    related_user_ids.update(row.approver_id for row in approvals if row.approver_id)
    related_user_ids.update(row.filed_by for row in submissions if row.filed_by)
    user_names = dict(db.execute(select(User.id, User.name).where(
        User.tenant_id == tenant_id, User.id.in_(related_user_ids),
    )).all()) if related_user_ids else {}
    proof_document_ids = {row.proof_document_id for row in submissions if row.proof_document_id}
    proof_documents = {row.id: row for row in db.scalars(select(Document).where(
        Document.tenant_id == tenant_id, Document.id.in_(proof_document_ids),
        Document.organization_id.in_(organization_ids),
    )).all()} if proof_document_ids else {}
    proof_version_ids = {row.proof_version_id for row in submissions if row.proof_version_id}
    proof_versions = {row.id: row for row in db.scalars(select(DocumentVersion).where(
        DocumentVersion.tenant_id == tenant_id, DocumentVersion.id.in_(proof_version_ids),
    )).all()} if proof_version_ids else {}

    output = []
    for item, organization_name in selected:
        snapshot = snapshots.get(item.id)
        frozen_tasks = []
        document_requirements = []
        decision = None
        if snapshot:
            try:
                frozen_tasks = json.loads(snapshot.checklist_tasks)
                configuration = json.loads(snapshot.configuration)
            except (TypeError, ValueError):
                frozen_tasks, configuration = [], {}
            document_requirements = configuration.get("documents", []) if isinstance(configuration, dict) else []
            decision = decisions_by_template_org.get((item.organization_id, snapshot.definition_id))
        checklist = []
        for entry in frozen_tasks if isinstance(frozen_tasks, list) else []:
            task_id = entry.get("task_id") if isinstance(entry, dict) else entry
            actual_task = tasks_by_id.get(task_id)
            checklist.append({
                "task_id": task_id,
                "title": entry.get("title", actual_task.title if actual_task else "") if isinstance(entry, dict) else actual_task.title if actual_task else "",
                "required": bool(entry.get("required", True)) if isinstance(entry, dict) else True,
                "status": actual_task.status if actual_task else "MISSING",
                "due_date": actual_task.due_at.isoformat() if actual_task else None,
            })
        evidence = evidence_by_compliance.get(item.id, [])
        evidence_requirements = []
        for requirement in document_requirements if isinstance(document_requirements, list) else []:
            if not isinstance(requirement, dict):
                continue
            matching = [row for row in evidence if row["source"] != "record" and row["category"] == requirement.get("document_type")]
            if requirement.get("must_be_valid", True):
                matching = [row for row in matching if (not row["effective_at"] or row["effective_at"] <= item.statutory_deadline.isoformat()) and (not row["expiry_at"] or row["expiry_at"] >= item.statutory_deadline.isoformat())]
            minimum_count = int(requirement.get("minimum_count", 1))
            evidence_requirements.append({
                "document_type": requirement.get("document_type", ""),
                "required": bool(requirement.get("required", True)),
                "minimum_count": minimum_count,
                "covered_count": len(matching),
                "satisfied": len(matching) >= minimum_count or not requirement.get("required", True),
            })
        latest_submission = submissions_by_compliance.get(item.id, [])
        filing = None
        if latest_submission:
            submission = latest_submission[0]
            proof_document = proof_documents.get(submission.proof_document_id)
            proof_version = proof_versions.get(submission.proof_version_id)
            filing = {
                "reference": submission.acknowledgement_ref,
                "proof_type": submission.proof_type,
                "channel": submission.filing_channel,
                "filed_at": submission.filed_at.isoformat() if submission.filed_at else None,
                "filed_by": user_names.get(submission.filed_by, "") if submission.filed_by else "",
                "proof_name": proof_document.name if proof_document else None,
                "proof_version": proof_version.version if proof_version else None,
            }
        output.append({
            "organization_id": item.organization_id,
            "organization_name": organization_name,
            "compliance_id": item.id,
            "code": item.code,
            "title": item.title,
            "category": item.category,
            "period": item.period,
            "priority": item.priority,
            "owner": user_names.get(owners.get(item.id), item.owner_name),
            "deadline": item.statutory_deadline.isoformat(),
            "internal_target": item.internal_target.isoformat() if item.internal_target else None,
            "status": item.status,
            "applicability": "NOT_APPLICABLE" if item.status == "NOT_APPLICABLE" else decision.effective_result if decision else "APPLICABLE",
            "tasks": [{
                "id": task.id, "title": task.title, "due_date": task.due_at.isoformat(),
                "status": task.status, "priority": task.priority, "owner": task.assignee_name,
            } for task in tasks_by_compliance.get(item.id, [])],
            "checklist": checklist,
            "evidence": evidence,
            "evidence_coverage": {
                "available_count": sum(row["source"] in {"compliance", "task", "filing"} for row in evidence),
                "requirements": evidence_requirements,
            },
            "reviews": [{
                "revision": row.revision, "decision": row.decision,
                "submitted_by": user_names.get(row.submitted_by, ""),
                "submitted_at": row.submitted_at.isoformat(),
                "reviewed_by": user_names.get(row.reviewer_id, "") if row.reviewer_id else None,
                "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
            } for row in reviews_by_compliance.get(item.id, [])],
            "approvals": [{
                "revision": row.revision, "decision": row.decision, "target_status": row.target_status,
                "requested_by": user_names.get(row.requested_by, ""),
                "requested_at": row.requested_at.isoformat(),
                "approved_by": user_names.get(row.approver_id, "") if row.approver_id else None,
                "decided_at": row.decided_at.isoformat() if row.decided_at else None,
            } for row in approvals_by_compliance.get(item.id, [])],
            "filing": filing,
            "completion": {"status": item.status, "progress": item.progress, "completed": item.status == "COMPLETED"},
            "audit_timeline": [{
                "action": row.action, "actor": row.actor_name, "summary": row.summary,
                "occurred_at": row.created_at.isoformat(),
            } for row in audits_by_compliance.get(item.id, [])],
        })
    return output


def compliance_report_count(
    db: Session,
    tenant_id: str,
    user,
    *,
    organization_id: str | None = None,
    category: str | None = None,
    status: str | None = None,
    owner: str | None = None,
    priority: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> int:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "date_from must not be after date_to")
    _, organization_ids = _scope(db, tenant_id, user, organization_id)
    filters = _compliance_filters(
        tenant_id, organization_ids, category=category, status=status, owner=owner,
        priority=priority, date_from=date_from, date_to=date_to,
    )
    return db.scalar(select(func.count(Compliance.id)).where(*filters)) or 0