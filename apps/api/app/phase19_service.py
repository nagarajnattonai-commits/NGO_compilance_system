"""Authorized portfolio queries built on existing organization and reporting data."""
from __future__ import annotations

import json
from datetime import date, timedelta

from fastapi import HTTPException
from sqlalchemy import and_, case, func, or_, select

from .compliance_states import CLOSED_STATES
from .document_models import DocumentCurrent
from .models import AuditEvent, Compliance, Document, Organization, Task, User
from .organization_access import accessible_organization_ids
from .organization_models import OrganizationDetails, OrganizationRegistration
from .phase8_models import OrganizationAccess
from .reporting_service import management_analytics


def portfolio_scope(db, tenant_id: str, user) -> tuple[list[Organization], set[str]]:
    if getattr(user, "_admin_audience", False):
        raise HTTPException(403, "Platform administrator sessions cannot access workspace portfolios")
    allowed = accessible_organization_ids(db, tenant_id, user.id)
    statement = select(Organization).where(
        Organization.tenant_id == tenant_id,
        Organization.status != "ARCHIVED",
    )
    if allowed is not None:
        statement = statement.where(Organization.id.in_(allowed))
    organizations = list(db.scalars(statement.order_by(Organization.name)).all())
    return organizations, {row.id for row in organizations}


def portfolio_dashboard(db, tenant_id: str, user, horizon_days: int = 30) -> dict:
    organizations, organization_ids = portfolio_scope(db, tenant_id, user)
    analytics = management_analytics(db, tenant_id, user, horizon_days=horizon_days)
    today = date.today()
    status_rows = db.execute(select(Compliance.status, func.count()).where(
        Compliance.tenant_id == tenant_id,
        Compliance.organization_id.in_(organization_ids),
    ).group_by(Compliance.status)).all() if organization_ids else []
    statuses = dict(status_rows)
    overdue_task_orgs = set(db.scalars(select(Task.organization_id).where(
        Task.tenant_id == tenant_id, Task.organization_id.in_(organization_ids),
        Task.archived_at.is_(None), Task.status != "DONE", Task.due_at < today,
    ).distinct()).all()) if organization_ids else set()
    expiring_registration_orgs = set(db.scalars(select(OrganizationRegistration.organization_id).where(
        OrganizationRegistration.tenant_id == tenant_id,
        OrganizationRegistration.organization_id.in_(organization_ids),
        OrganizationRegistration.expiry_date.between(today, today + timedelta(days=90)),
    ).distinct()).all()) if organization_ids else set()
    attention = {
        row["organization_id"] for row in analytics["organization_summaries"]
        if row["overdue"] or row["documents_expiring"]
    } | overdue_task_orgs | expiring_registration_orgs
    analytics["summary"].update({
        "organizations": len(organizations),
        "active_compliances": analytics["summary"]["open"],
        "under_review": statuses.get("UNDER_REVIEW", 0),
        "ready_to_file": statuses.get("READY_TO_FILE", 0),
        "filed_or_completed": statuses.get("FILED", 0) + statuses.get("COMPLETED", 0),
        "incomplete_tasks": sum(
            value for key, value in ((point["status"], point["count"]) for point in analytics["charts"]["task_status_distribution"])
            if key != "DONE"
        ),
        "organizations_requiring_attention": len(attention),
        "registrations_expiring": len(expiring_registration_orgs),
    })
    return analytics


def organization_directory(db, tenant_id: str, user, *, query: str = "", status: str | None = None,
                           attention: bool = False, sort_by: str = "name", direction: str = "asc",
                           limit: int = 20, offset: int = 0) -> dict:
    _, allowed_ids = portfolio_scope(db, tenant_id, user)
    today, horizon = date.today(), date.today() + timedelta(days=30)
    comp = select(
        Compliance.organization_id.label("organization_id"),
        func.sum(case((and_(Compliance.status.not_in(CLOSED_STATES), Compliance.statutory_deadline < today), 1), else_=0)).label("overdue"),
        func.sum(case((and_(Compliance.status.not_in(CLOSED_STATES), Compliance.statutory_deadline.between(today, horizon)), 1), else_=0)).label("upcoming"),
        func.count(Compliance.id).label("compliances"),
        func.max(Compliance.updated_at).label("compliance_activity"),
    ).where(Compliance.tenant_id == tenant_id, Compliance.organization_id.in_(allowed_ids)).group_by(Compliance.organization_id).subquery()
    task = select(
        Task.organization_id.label("organization_id"),
        func.sum(case((and_(Task.status != "DONE", Task.archived_at.is_(None)), 1), else_=0)).label("open_tasks"),
        func.max(Task.updated_at).label("task_activity"),
    ).where(Task.tenant_id == tenant_id, Task.organization_id.in_(allowed_ids)).group_by(Task.organization_id).subquery()
    docs = select(
        Document.organization_id.label("organization_id"),
        func.sum(case((Document.expiry_at.between(today, today + timedelta(days=90)), 1), else_=0)).label("expiring_documents"),
    ).outerjoin(DocumentCurrent, and_(DocumentCurrent.document_id == Document.id,
        DocumentCurrent.tenant_id == Document.tenant_id)).where(
        Document.tenant_id == tenant_id, Document.organization_id.in_(allowed_ids),
        or_(DocumentCurrent.document_id.is_(None), DocumentCurrent.archived.is_(False)),
    ).group_by(Document.organization_id).subquery()
    registrations = select(
        OrganizationRegistration.organization_id.label("organization_id"),
        func.sum(case((OrganizationRegistration.expiry_date.between(today, today + timedelta(days=90)), 1), else_=0)).label("expiring_registrations"),
    ).where(OrganizationRegistration.tenant_id == tenant_id,
            OrganizationRegistration.organization_id.in_(allowed_ids)).group_by(OrganizationRegistration.organization_id).subquery()
    overdue = func.coalesce(comp.c.overdue, 0)
    upcoming = func.coalesce(comp.c.upcoming, 0)
    open_tasks = func.coalesce(task.c.open_tasks, 0)
    expiring_documents = func.coalesce(docs.c.expiring_documents, 0)
    expiring_registrations = func.coalesce(registrations.c.expiring_registrations, 0)
    statement = select(
        Organization, func.coalesce(comp.c.compliances, 0), overdue, upcoming, open_tasks,
        expiring_documents, expiring_registrations, comp.c.compliance_activity, task.c.task_activity,
    ).outerjoin(comp, comp.c.organization_id == Organization.id).outerjoin(
        task, task.c.organization_id == Organization.id).outerjoin(
        docs, docs.c.organization_id == Organization.id).outerjoin(
        registrations, registrations.c.organization_id == Organization.id).where(
        Organization.tenant_id == tenant_id, Organization.id.in_(allowed_ids), Organization.status != "ARCHIVED",
    )
    if query:
        term = query.strip().lower()
        statement = statement.where(or_(
            func.lower(Organization.name).contains(term, autoescape=True),
            func.lower(Organization.city).contains(term, autoescape=True),
            func.lower(Organization.legal_type).contains(term, autoescape=True),
        ))
    if status:
        statement = statement.where(Organization.status == status)
    if attention:
        statement = statement.where(or_(overdue > 0, open_tasks > 0, expiring_documents > 0, expiring_registrations > 0))
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    sort_columns = {"name": Organization.name, "overdue": overdue, "upcoming": upcoming, "open_tasks": open_tasks,
                    "activity": func.coalesce(task.c.task_activity, comp.c.compliance_activity, Organization.created_at)}
    order = sort_columns[sort_by]
    statement = statement.order_by(order.desc() if direction == "desc" else order.asc(), Organization.name).offset(offset).limit(limit)
    rows = db.execute(statement).all()
    page_ids = [row[0].id for row in rows]
    details = {row.organization_id: json.loads(row.facts) for row in db.scalars(select(OrganizationDetails).where(
        OrganizationDetails.tenant_id == tenant_id, OrganizationDetails.organization_id.in_(page_ids))).all()}
    responsible: dict[str, dict] = {}
    access_rows = db.execute(select(OrganizationAccess, User).join(User, User.id == OrganizationAccess.user_id).where(
        OrganizationAccess.tenant_id == tenant_id, OrganizationAccess.organization_id.in_(page_ids),
        OrganizationAccess.status == "ACTIVE", OrganizationAccess.access_role.in_(("MANAGER", "CONTRIBUTOR")),
        User.status == "ACTIVE",
    ).order_by(OrganizationAccess.organization_id, OrganizationAccess.access_role.desc(), OrganizationAccess.granted_at)).all()
    for access, consultant in access_rows:
        responsible.setdefault(access.organization_id, {"id": consultant.id, "name": consultant.name})
    items = []
    for organization, compliance_count, late, due, open_count, expiring_docs, expiring_regs, compliance_activity, task_activity in rows:
        facts = details.get(organization.id, {})
        activity = max((value for value in (organization.created_at, compliance_activity, task_activity) if value), default=organization.created_at)
        items.append({
            "id": organization.id, "name": organization.name, "legal_type": organization.legal_type,
            "status": organization.status, "city": organization.city,
            "primary_contact": facts.get("contact_name", ""),
            "compliance_count": compliance_count, "overdue": late, "upcoming": due,
            "open_tasks": open_count, "expiring_documents": expiring_docs,
            "expiring_registrations": expiring_regs, "responsible_consultant": responsible.get(organization.id),
            "last_activity_at": activity,
            "health": "ATTENTION" if late or expiring_docs or expiring_regs else "ON_TRACK" if compliance_count else "SETUP",
        })
    return {"items": items, "total": total, "limit": limit, "offset": offset}


def portfolio_ai_context(db, tenant_id: str, user) -> dict:
    from .ai_service import require_workspace_ai
    require_workspace_ai(db, tenant_id, user)
    dashboard = portfolio_dashboard(db, tenant_id, user, 30)
    return {
        "scope": "AUTHORIZED_PORTFOLIO",
        "summary": dashboard["summary"],
        "organizations": dashboard["organization_summaries"],
        "upcoming_deadlines": dashboard["upcoming_deadlines"],
        "advisory_only": True,
    }
