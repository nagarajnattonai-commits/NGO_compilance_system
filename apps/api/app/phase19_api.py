"""Consultant portfolio APIs over existing organizations, tasks and compliances."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .auth import CurrentUser, get_db, tenant_context
from .models import AuditEvent, Compliance, Organization, Task, User
from .organization_access import require_organization_access
from .phase8_api import eligible_users, notify_task
from .phase19_service import (organization_directory, portfolio_ai_context,
                              portfolio_dashboard, portfolio_scope)
from .production_security import limit_expensive
from .runtime_models import ComplianceOwnership

router = APIRouter(prefix="/api/v1/portfolio", tags=["Consultant portfolio"])
DB = Annotated[Session, Depends(get_db)]
Tenant = Annotated[str, Depends(tenant_context)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class BulkAssignment(Strict):
    target_ids: list[str] = Field(min_length=1, max_length=100)
    assignee_user_id: str = Field(min_length=1, max_length=36)

    @model_validator(mode="after")
    def unique_targets(self):
        if len(set(self.target_ids)) != len(self.target_ids) or any(len(value) > 36 for value in self.target_ids):
            raise ValueError("Targets must be unique valid identifiers")
        return self


def _workspace_user(db, tenant_id: str, user_id: str) -> User:
    from .organization_access import workspace_role
    user = db.get(User, user_id)
    if not user or user.status != "ACTIVE" or not workspace_role(db, tenant_id, user_id):
        raise HTTPException(422, "ASSIGNEE_NOT_AVAILABLE")
    return user


def _audit(db, tenant_id: str, actor, action: str, entity_type: str, entity_id: str, summary: str):
    db.add(AuditEvent(tenant_id=tenant_id, actor_name=actor.name, action=action,
                      entity_type=entity_type, entity_id=entity_id, summary=summary[:280]))


@router.get("/dashboard")
def dashboard(db: DB, tenant_id: Tenant, user: CurrentUser,
              horizon_days: Literal[7, 30, 60, 90] = 30):
    limit_expensive(db, tenant_id, user.id, "portfolio-dashboard", 60)
    return portfolio_dashboard(db, tenant_id, user, horizon_days)


@router.get("/organizations")
def organizations(db: DB, tenant_id: Tenant, user: CurrentUser,
                  q: str = Query(default="", max_length=120),
                  status: Literal["DRAFT", "ACTIVE", "SUSPENDED"] | None = None,
                  attention: bool = False,
                  sort_by: Literal["name", "overdue", "upcoming", "open_tasks", "activity"] = "name",
                  direction: Literal["asc", "desc"] = "asc",
                  limit: int = Query(default=20, ge=1, le=100), offset: int = Query(default=0, ge=0)):
    limit_expensive(db, tenant_id, user.id, "portfolio-directory", 90)
    return organization_directory(db, tenant_id, user, query=q, status=status, attention=attention,
                                  sort_by=sort_by, direction=direction, limit=limit, offset=offset)


def _task_filters(tenant_id: str, organization_ids: set[str], organization_id: str | None,
                  compliance_id: str | None, status: str | None, priority: str | None,
                  assignee_user_id: str | None, owner: str | None, timing: str):
    filters = [Task.tenant_id == tenant_id, Task.organization_id.in_(organization_ids), Task.archived_at.is_(None)]
    if organization_id: filters.append(Task.organization_id == organization_id)
    if compliance_id: filters.append(Task.compliance_id == compliance_id)
    if status: filters.append(Task.status == status)
    if priority: filters.append(Task.priority == priority)
    if assignee_user_id: filters.append(Task.assignee_user_id == assignee_user_id)
    if owner:
        filters.append(Task.compliance_id.in_(select(Compliance.id).where(
            Compliance.tenant_id == tenant_id,
            func.lower(Compliance.owner_name).contains(owner.lower(), autoescape=True))))
    today = date.today()
    windows = {
        "OVERDUE": (Task.due_at < today, Task.status != "DONE"),
        "TODAY": (Task.due_at == today,),
        "WEEK": (Task.due_at.between(today, today + timedelta(days=7)),),
        "MONTH": (Task.due_at.between(today, today + timedelta(days=30)),),
    }
    filters.extend(windows.get(timing, ()))
    return filters


@router.get("/work-queue")
def work_queue(db: DB, tenant_id: Tenant, user: CurrentUser,
               organization_id: str | None = Query(default=None, max_length=36),
               compliance_id: str | None = Query(default=None, max_length=36),
               status: Literal["TODO", "IN_PROGRESS", "DONE"] | None = None,
               priority: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] | None = None,
               assignee_user_id: str | None = Query(default=None, max_length=36),
               owner: str | None = Query(default=None, max_length=120),
               timing: Literal["ALL", "OVERDUE", "TODAY", "WEEK", "MONTH"] = "ALL",
               limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0)):
    organizations, allowed_ids = portfolio_scope(db, tenant_id, user)
    if organization_id and organization_id not in allowed_ids:
        raise HTTPException(404, "Organization not found")
    filters = _task_filters(tenant_id, allowed_ids, organization_id, compliance_id, status,
                            priority, assignee_user_id, owner, timing)
    base = select(Task, Organization.name, Compliance.title, Compliance.owner_name).join(
        Organization, Organization.id == Task.organization_id).outerjoin(
        Compliance, Compliance.id == Task.compliance_id).where(*filters)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.execute(base.order_by(Task.due_at, Task.priority.desc(), Task.id).offset(offset).limit(limit)).all()
    return {"items": [{
        "id": task.id, "organization_id": task.organization_id, "organization_name": organization_name,
        "compliance_id": task.compliance_id, "compliance": compliance_title or "",
        "owner": owner_name or "", "title": task.title, "status": task.status,
        "priority": task.priority, "assignee_user_id": task.assignee_user_id,
        "assignee": task.assignee_name, "due_at": task.due_at,
        "overdue": task.status != "DONE" and task.due_at < date.today(),
        "url": f"/compliances/{task.compliance_id}" if task.compliance_id else "/dashboard",
    } for task, organization_name, compliance_title, owner_name in rows],
        "total": total, "limit": limit, "offset": offset,
        "organizations": [{"id": row.id, "name": row.name} for row in organizations]}


@router.get("/deadlines")
def deadlines(db: DB, tenant_id: Tenant, user: CurrentUser,
              organization_id: str | None = Query(default=None, max_length=36),
              compliance_id: str | None = Query(default=None, max_length=36),
              owner: str | None = Query(default=None, max_length=120),
              assignee_user_id: str | None = Query(default=None, max_length=36),
              status: str | None = Query(default=None, max_length=30),
              date_from: date | None = None, date_to: date | None = None,
              limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0)):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "date_from must not be after date_to")
    organizations, allowed_ids = portfolio_scope(db, tenant_id, user)
    if organization_id and organization_id not in allowed_ids:
        raise HTTPException(404, "Organization not found")
    filters = [Compliance.tenant_id == tenant_id, Compliance.organization_id.in_(allowed_ids)]
    if organization_id: filters.append(Compliance.organization_id == organization_id)
    if compliance_id: filters.append(Compliance.id == compliance_id)
    if owner: filters.append(func.lower(Compliance.owner_name).contains(owner.lower(), autoescape=True))
    if status: filters.append(Compliance.status == status)
    if date_from: filters.append(Compliance.statutory_deadline >= date_from)
    if date_to: filters.append(Compliance.statutory_deadline <= date_to)
    if assignee_user_id:
        filters.append(Compliance.id.in_(select(Task.compliance_id).where(
            Task.tenant_id == tenant_id, Task.assignee_user_id == assignee_user_id)))
    base = select(Compliance, Organization.name).join(Organization, Organization.id == Compliance.organization_id).where(*filters)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.execute(base.order_by(Compliance.statutory_deadline, Compliance.priority.desc()).offset(offset).limit(limit)).all()
    return {"items": [{
        "id": item.id, "organization_id": item.organization_id, "organization_name": organization_name,
        "code": item.code, "title": item.title, "owner": item.owner_name, "status": item.status,
        "priority": item.priority, "deadline": item.statutory_deadline,
        "days_remaining": (item.statutory_deadline - date.today()).days,
        "url": f"/compliances/{item.id}",
    } for item, organization_name in rows], "total": total, "limit": limit, "offset": offset,
        "organizations": [{"id": row.id, "name": row.name} for row in organizations]}


@router.post("/bulk/tasks/assignee")
def bulk_task_assignee(payload: BulkAssignment, db: DB, tenant_id: Tenant, user: CurrentUser):
    if user.role == "VIEWER": raise HTTPException(403, "Read-only accounts cannot reassign tasks")
    assignee = _workspace_user(db, tenant_id, payload.assignee_user_id)
    tasks = list(db.scalars(select(Task).where(Task.tenant_id == tenant_id, Task.id.in_(payload.target_ids),
                                               Task.archived_at.is_(None))).all())
    if len(tasks) != len(payload.target_ids): raise HTTPException(404, "One or more tasks were not found")
    for task in tasks:
        require_organization_access(db, tenant_id, task.organization_id, write=True, user_id=user.id)
        if not any(candidate.id == assignee.id for candidate, _ in eligible_users(db, tenant_id, task.organization_id)):
            raise HTTPException(422, "TASK_ASSIGNEE_NOT_AUTHORIZED")
    assigned_at = datetime.now(timezone.utc)
    initials = "".join(part[0] for part in assignee.name.split())[:2].upper()
    for task in tasks:
        task.assignee_user_id, task.assignee_name, task.assignee_initials = assignee.id, assignee.name, initials
        task.assigned_by, task.assigned_at, task.updated_at = user.id, assigned_at, assigned_at
        _audit(db, tenant_id, user, "TASK_REASSIGNED", "Task", task.id, f"Reassigned {task.title} to {assignee.name}")
        notify_task(db, task, event_type="TASK_REASSIGNED", title="Task reassigned",
                    message=f"{task.title} is now assigned to you.", user_ids=[assignee.id])
    db.commit()
    return {"updated": len(tasks), "assignee_user_id": assignee.id}


@router.post("/bulk/compliances/owner")
def bulk_compliance_owner(payload: BulkAssignment, db: DB, tenant_id: Tenant, user: CurrentUser):
    if user.role == "VIEWER": raise HTTPException(403, "Read-only accounts cannot assign compliance owners")
    owner = _workspace_user(db, tenant_id, payload.assignee_user_id)
    items = list(db.scalars(select(Compliance).where(Compliance.tenant_id == tenant_id,
                                                      Compliance.id.in_(payload.target_ids))).all())
    if len(items) != len(payload.target_ids): raise HTTPException(404, "One or more compliances were not found")
    for item in items:
        require_organization_access(db, tenant_id, item.organization_id, write=True, user_id=user.id)
        if not any(candidate.id == owner.id for candidate, _ in eligible_users(db, tenant_id, item.organization_id)):
            raise HTTPException(422, "COMPLIANCE_OWNER_NOT_AUTHORIZED")
    assigned_at = datetime.now(timezone.utc)
    for item in items:
        item.owner_name = owner.name
        item.owner_initials = "".join(part[0] for part in owner.name.split())[:2].upper()
        item.updated_at = assigned_at
        assignment = db.get(ComplianceOwnership, item.id)
        if not assignment:
            assignment = ComplianceOwnership(compliance_id=item.id, tenant_id=tenant_id, owner_id=owner.id)
            db.add(assignment)
        assignment.owner_id, assignment.assigned_by, assignment.assigned_at, assignment.manual = owner.id, user.id, assigned_at, True
        _audit(db, tenant_id, user, "COMPLIANCE_OWNER_ASSIGNED", "Compliance", item.id,
               f"Assigned {item.title} to {owner.name}")
    db.commit()
    return {"updated": len(items), "owner_user_id": owner.id}


@router.get("/ai-context")
def ai_context(db: DB, tenant_id: Tenant, user: CurrentUser):
    limit_expensive(db, tenant_id, user.id, "portfolio-ai-context", 30)
    return portfolio_ai_context(db, tenant_id, user)
