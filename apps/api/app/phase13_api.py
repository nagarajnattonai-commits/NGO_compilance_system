"""Tenant- and organization-scoped global search and personal saved views."""
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import CurrentUser, get_db, tenant_context
from .document_models import DocumentCurrent
from .models import Compliance, ComplianceSnapshot, Document, Organization, Submission, Task, utcnow
from .organization_access import accessible_organization_ids
from .organization_models import OrganizationRegistration
from .phase13_models import SavedView
from .runtime_models import ApplicabilityDecision

router = APIRouter(prefix="/api/v1", tags=["search"])
DB = Annotated[Session, Depends(get_db)]
Tenant = Annotated[str, Depends(tenant_context)]
SearchType = Literal["organization", "compliance", "task", "document", "registration", "filing"]
ViewScope = Literal["GLOBAL_SEARCH", "COMPLIANCES", "TASKS", "DOCUMENTS", "REPORTS"]
ALL_TYPES = ("organization", "compliance", "task", "document", "registration", "filing")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FilterState(StrictModel):
    query: str = Field(default="", max_length=120)
    types: list[SearchType] = Field(default_factory=list, max_length=6)
    organization_id: str | None = Field(default=None, max_length=36)
    compliance_id: str | None = Field(default=None, max_length=36)
    status: str | None = Field(default=None, max_length=30)
    priority: str | None = Field(default=None, max_length=20)
    owner: str | None = Field(default=None, max_length=120)
    assignee: str | None = Field(default=None, max_length=120)
    date_from: date | None = None
    date_to: date | None = None
    timing: Literal["ALL", "OVERDUE", "UPCOMING"] = "ALL"
    document_expiry: Literal["ALL", "EXPIRED", "EXPIRING", "NO_EXPIRY"] = "ALL"
    applicability: Literal["ALL", "APPLICABLE", "NOT_APPLICABLE", "REQUIRES_REVIEW"] = "ALL"
    upcoming_days: int = Field(default=30, ge=1, le=365)

    @model_validator(mode="after")
    def valid_range(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must not be after date_to")
        return self


class Sorting(StrictModel):
    by: Literal["relevance", "title", "date", "status"] = "relevance"
    direction: Literal["asc", "desc"] = "asc"


class SavedViewInput(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    scope: ViewScope = "GLOBAL_SEARCH"
    filters: FilterState = Field(default_factory=FilterState)
    sorting: Sorting = Field(default_factory=Sorting)
    visible_columns: list[str] = Field(default_factory=list, max_length=30)
    is_default: bool = False

    @model_validator(mode="after")
    def valid_columns(self):
        allowed = {"type", "title", "organization", "status", "date", "priority", "owner", "assignee"}
        if len(set(self.visible_columns)) != len(self.visible_columns) or not set(self.visible_columns) <= allowed:
            raise ValueError("visible_columns contains an unsupported or duplicate column")
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("name must not be blank")
        return self


def _workspace_scope(db: Session, tenant_id: str, user) -> tuple[list[Organization], set[str]]:
    if getattr(user, "_admin_audience", False):
        raise HTTPException(403, "Workspace search is not available to platform administrators")
    statement = select(Organization).where(Organization.tenant_id == tenant_id)
    permitted = accessible_organization_ids(db, tenant_id, user.id)
    if permitted is not None:
        statement = statement.where(Organization.id.in_(permitted))
    organizations = list(db.scalars(statement.order_by(Organization.name)).all())
    return organizations, {row.id for row in organizations}


def _text(*columns, term: str):
    return or_(*(func.lower(column).contains(term.lower(), autoescape=True) for column in columns))


def _result(kind: str, row_id: str, title: str, organization: Organization, status: str,
            subtitle: str = "", relevant_date=None, url: str = "/dashboard"):
    return {
        "id": row_id, "type": kind, "title": title,
        "organization_id": organization.id, "organization": organization.name,
        "status": status, "subtitle": subtitle,
        "date": relevant_date.isoformat() if relevant_date else None, "url": url,
    }


def _sort(items: list[dict], by: str, direction: str) -> list[dict]:
    field = {"title": "title", "date": "date", "status": "status"}.get(by)
    if not field:
        return items
    return sorted(items, key=lambda item: (item[field] is None, str(item[field] or "").lower()),
                  reverse=direction == "desc")


def _ordered(statement, by: str, direction: str, columns: dict, fallback):
    column = columns.get(by, fallback)
    primary = column.desc() if direction == "desc" else column.asc()
    return statement.order_by(primary, fallback.asc())


@router.get("/search")
def global_search(
    request: Request, db: DB, tenant_id: Tenant, user: CurrentUser,
    q: str = Query(default="", max_length=120), types: str = Query(default=""),
    organization_id: str | None = Query(default=None, max_length=36),
    compliance_id: str | None = Query(default=None, max_length=36),
    status: str | None = Query(default=None, max_length=30),
    priority: str | None = Query(default=None, max_length=20),
    owner: str | None = Query(default=None, max_length=120),
    assignee: str | None = Query(default=None, max_length=120),
    date_from: date | None = None, date_to: date | None = None,
    timing: Literal["ALL", "OVERDUE", "UPCOMING"] = "ALL",
    document_expiry: Literal["ALL", "EXPIRED", "EXPIRING", "NO_EXPIRY"] = "ALL",
    applicability: Literal["ALL", "APPLICABLE", "NOT_APPLICABLE", "REQUIRES_REVIEW"] = "ALL",
    upcoming_days: int = Query(default=30, ge=1, le=365),
    sort_by: Literal["relevance", "title", "date", "status"] = "relevance",
    sort_direction: Literal["asc", "desc"] = "asc",
    limit_per_group: int = Query(default=8, ge=1, le=25),
):
    allowed_parameters = {
        "q", "types", "organization_id", "compliance_id", "status", "priority", "owner", "assignee",
        "date_from", "date_to", "timing", "document_expiry", "applicability", "upcoming_days",
        "sort_by", "sort_direction", "limit_per_group",
    }
    if unknown := set(request.query_params) - allowed_parameters:
        raise HTTPException(422, f"Unsupported search filter: {sorted(unknown)[0]}")
    try:
        state = FilterState(
            query=q.strip(), types=[item for item in types.split(",") if item], organization_id=organization_id,
            compliance_id=compliance_id, status=status, priority=priority, owner=owner, assignee=assignee,
            date_from=date_from, date_to=date_to, timing=timing, document_expiry=document_expiry,
            applicability=applicability, upcoming_days=upcoming_days,
        )
    except ValidationError as error:
        raise HTTPException(422, str(error))
    selected_types = tuple(state.types) or ALL_TYPES
    organizations, allowed_ids = _workspace_scope(db, tenant_id, user)
    if state.organization_id and state.organization_id not in allowed_ids:
        raise HTTPException(404, "Organization not found")
    scoped_ids = {state.organization_id} if state.organization_id else allowed_ids
    if state.compliance_id:
        compliance = db.scalar(select(Compliance).where(
            Compliance.id == state.compliance_id, Compliance.tenant_id == tenant_id,
            Compliance.organization_id.in_(scoped_ids),
        ))
        if not compliance:
            raise HTTPException(404, "Compliance not found")
    term = state.query
    today = date.today()
    groups: dict[str, list[dict]] = {name + "s": [] for name in ALL_TYPES}

    if "organization" in selected_types and not state.compliance_id:
        rows = [row for row in organizations if row.id in scoped_ids]
        if term:
            lowered = term.lower()
            rows = [row for row in rows if lowered in " ".join((row.name, row.legal_type, row.registration_number, row.city)).lower()]
        if state.status:
            rows = [row for row in rows if row.status == state.status]
        items = [_result("organization", row.id, row.name, row, row.status,
            " · ".join(value for value in (row.legal_type, row.city) if value), url=f"/organizations/{row.id}") for row in rows]
        groups["organizations"] = _sort(items, sort_by, sort_direction)[:limit_per_group]

    if "compliance" in selected_types:
        statement = select(Compliance, Organization).join(Organization, Organization.id == Compliance.organization_id).where(
            Compliance.tenant_id == tenant_id, Organization.tenant_id == tenant_id,
            Compliance.organization_id.in_(scoped_ids),
        )
        if state.compliance_id: statement = statement.where(Compliance.id == state.compliance_id)
        if term: statement = statement.where(_text(Compliance.title, Compliance.code, Compliance.category, term=term))
        if state.status: statement = statement.where(Compliance.status == state.status)
        if state.priority: statement = statement.where(Compliance.priority == state.priority)
        if state.owner: statement = statement.where(func.lower(Compliance.owner_name).contains(state.owner.lower(), autoescape=True))
        if state.date_from: statement = statement.where(Compliance.statutory_deadline >= state.date_from)
        if state.date_to: statement = statement.where(Compliance.statutory_deadline <= state.date_to)
        if state.timing == "OVERDUE": statement = statement.where(Compliance.statutory_deadline < today)
        if state.timing == "UPCOMING": statement = statement.where(Compliance.statutory_deadline.between(today, today + timedelta(days=state.upcoming_days)))
        if state.applicability != "ALL":
            matching = select(ApplicabilityDecision.id).join(
                ComplianceSnapshot, and_(ComplianceSnapshot.version_id == ApplicabilityDecision.version_id,
                                         ComplianceSnapshot.organization_id == ApplicabilityDecision.organization_id)
            ).where(ComplianceSnapshot.compliance_id == Compliance.id,
                    ApplicabilityDecision.tenant_id == tenant_id,
                    ApplicabilityDecision.effective_result == state.applicability).exists()
            statement = statement.where(matching)
        statement = _ordered(statement, sort_by, sort_direction, {
            "title": Compliance.title, "date": Compliance.statutory_deadline, "status": Compliance.status,
        }, Compliance.title)
        rows = db.execute(statement.limit(limit_per_group)).all()
        groups["compliances"] = [_result("compliance", row.id, row.title, org, row.status,
            f"{row.code} · {row.priority}", row.statutory_deadline, f"/compliances/{row.id}") for row, org in rows]

    if "task" in selected_types:
        statement = select(Task, Organization).join(Organization, Organization.id == Task.organization_id).where(
            Task.tenant_id == tenant_id, Task.organization_id.in_(scoped_ids), Task.archived_at.is_(None))
        if state.compliance_id: statement = statement.where(Task.compliance_id == state.compliance_id)
        if term: statement = statement.where(_text(Task.title, Task.assignee_name, term=term))
        if state.status: statement = statement.where(Task.status == state.status)
        if state.priority: statement = statement.where(Task.priority == state.priority)
        if state.assignee: statement = statement.where(func.lower(Task.assignee_name).contains(state.assignee.lower(), autoescape=True))
        if state.date_from: statement = statement.where(Task.due_at >= state.date_from)
        if state.date_to: statement = statement.where(Task.due_at <= state.date_to)
        if state.timing == "OVERDUE": statement = statement.where(Task.due_at < today)
        if state.timing == "UPCOMING": statement = statement.where(Task.due_at.between(today, today + timedelta(days=state.upcoming_days)))
        statement = _ordered(statement, sort_by, sort_direction, {
            "title": Task.title, "date": Task.due_at, "status": Task.status,
        }, Task.title)
        rows = db.execute(statement.limit(limit_per_group)).all()
        groups["tasks"] = [_result("task", row.id, row.title, org, row.status,
            f"{row.assignee_name} · {row.priority}", row.due_at) for row, org in rows]

    if "document" in selected_types:
        statement = select(Document, Organization).join(Organization, Organization.id == Document.organization_id).outerjoin(
            DocumentCurrent, DocumentCurrent.document_id == Document.id).where(
            Document.tenant_id == tenant_id, Document.organization_id.in_(scoped_ids),
            or_(DocumentCurrent.document_id.is_(None), DocumentCurrent.archived.is_(False)))
        if state.compliance_id: statement = statement.where(Document.compliance_id == state.compliance_id)
        if term: statement = statement.where(_text(Document.name, Document.category, Document.uploaded_by, term=term))
        if state.date_from: statement = statement.where(Document.expiry_at >= state.date_from)
        if state.date_to: statement = statement.where(Document.expiry_at <= state.date_to)
        if state.document_expiry == "EXPIRED": statement = statement.where(Document.expiry_at < today)
        if state.document_expiry == "EXPIRING": statement = statement.where(Document.expiry_at.between(today, today + timedelta(days=state.upcoming_days)))
        if state.document_expiry == "NO_EXPIRY": statement = statement.where(Document.expiry_at.is_(None))
        statement = _ordered(statement, sort_by, sort_direction, {
            "title": Document.name, "date": Document.expiry_at,
        }, Document.name)
        rows = db.execute(statement.limit(limit_per_group)).all()
        groups["documents"] = [_result("document", row.id, row.name, org,
            "EXPIRED" if row.expiry_at and row.expiry_at < today else "CURRENT", row.category, row.expiry_at) for row, org in rows]

    if "registration" in selected_types and not state.compliance_id:
        statement = select(OrganizationRegistration, Organization).join(
            Organization, Organization.id == OrganizationRegistration.organization_id).where(
            OrganizationRegistration.tenant_id == tenant_id,
            OrganizationRegistration.organization_id.in_(scoped_ids))
        if term: statement = statement.where(_text(OrganizationRegistration.kind, OrganizationRegistration.number, term=term))
        if state.status: statement = statement.where(OrganizationRegistration.status == state.status)
        if state.date_from: statement = statement.where(OrganizationRegistration.expiry_date >= state.date_from)
        if state.date_to: statement = statement.where(OrganizationRegistration.expiry_date <= state.date_to)
        statement = _ordered(statement, sort_by, sort_direction, {
            "title": OrganizationRegistration.kind, "date": OrganizationRegistration.expiry_date,
            "status": OrganizationRegistration.status,
        }, OrganizationRegistration.kind)
        rows = db.execute(statement.limit(limit_per_group)).all()
        groups["registrations"] = [_result("registration", row.id, row.kind, org, row.status,
            row.number, row.expiry_date, f"/organizations/{org.id}") for row, org in rows]

    if "filing" in selected_types:
        statement = select(Submission, Compliance, Organization).join(
            Compliance, Compliance.id == Submission.compliance_id).join(
            Organization, Organization.id == Compliance.organization_id).where(
            Submission.tenant_id == tenant_id, Compliance.tenant_id == tenant_id,
            Compliance.organization_id.in_(scoped_ids))
        if state.compliance_id: statement = statement.where(Submission.compliance_id == state.compliance_id)
        if term: statement = statement.where(_text(Submission.acknowledgement_ref, Submission.filing_channel, Submission.notes, Compliance.title, term=term))
        if state.status and state.status != "FILED": statement = statement.where(False)
        if state.date_from: statement = statement.where(func.date(Submission.submitted_at) >= state.date_from)
        if state.date_to: statement = statement.where(func.date(Submission.submitted_at) <= state.date_to)
        statement = _ordered(statement, sort_by, sort_direction, {
            "title": Compliance.title, "date": Submission.submitted_at,
        }, Compliance.title)
        rows = db.execute(statement.limit(limit_per_group)).all()
        groups["filings"] = [_result("filing", row.id, compliance.title, org, "FILED",
            row.acknowledgement_ref, row.filed_at or row.submitted_at, f"/compliances/{compliance.id}") for row, compliance, org in rows]

    groups = {key: _sort(value, sort_by, sort_direction) for key, value in groups.items()}
    return {"query": term, "groups": groups, "total": sum(map(len, groups.values())),
            "organizations": [{"id": row.id, "name": row.name} for row in organizations]}


def _saved_out(row: SavedView) -> dict:
    return {"id": row.id, "name": row.name, "scope": row.scope,
            "filters": json.loads(row.filters), "sorting": json.loads(row.sorting),
            "visible_columns": json.loads(row.visible_columns), "is_default": row.is_default,
            "created_at": row.created_at, "updated_at": row.updated_at}


def _personal_view(db: Session, tenant_id: str, user_id: str, view_id: str) -> SavedView:
    row = db.scalar(select(SavedView).where(SavedView.id == view_id, SavedView.tenant_id == tenant_id,
                                            SavedView.user_id == user_id))
    if not row:
        raise HTTPException(404, "Saved view not found")
    return row


def _unset_default(db: Session, tenant_id: str, user_id: str, scope: str, except_id: str | None = None):
    statement = update(SavedView).where(SavedView.tenant_id == tenant_id, SavedView.user_id == user_id,
                                        SavedView.scope == scope, SavedView.is_default.is_(True))
    if except_id: statement = statement.where(SavedView.id != except_id)
    db.execute(statement.values(is_default=False, updated_at=utcnow()))


@router.get("/saved-views")
def list_saved_views(db: DB, tenant_id: Tenant, user: CurrentUser,
                     scope: ViewScope = "GLOBAL_SEARCH"):
    _workspace_scope(db, tenant_id, user)
    rows = db.scalars(select(SavedView).where(SavedView.tenant_id == tenant_id, SavedView.user_id == user.id,
                                               SavedView.scope == scope).order_by(SavedView.is_default.desc(), SavedView.name)).all()
    return [_saved_out(row) for row in rows]


@router.post("/saved-views", status_code=201)
def create_saved_view(payload: SavedViewInput, db: DB, tenant_id: Tenant, user: CurrentUser):
    _workspace_scope(db, tenant_id, user)
    if payload.is_default: _unset_default(db, tenant_id, user.id, payload.scope)
    row = SavedView(tenant_id=tenant_id, user_id=user.id, name=payload.name, scope=payload.scope,
                    filters=payload.filters.model_dump_json(), sorting=payload.sorting.model_dump_json(),
                    visible_columns=json.dumps(payload.visible_columns), is_default=payload.is_default)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A saved view with this name already exists")
    db.refresh(row)
    return _saved_out(row)


@router.put("/saved-views/{view_id}")
def update_saved_view(view_id: str, payload: SavedViewInput, db: DB, tenant_id: Tenant, user: CurrentUser):
    _workspace_scope(db, tenant_id, user)
    row = _personal_view(db, tenant_id, user.id, view_id)
    if payload.is_default: _unset_default(db, tenant_id, user.id, payload.scope, row.id)
    row.name, row.scope = payload.name, payload.scope
    row.filters, row.sorting = payload.filters.model_dump_json(), payload.sorting.model_dump_json()
    row.visible_columns, row.is_default, row.updated_at = json.dumps(payload.visible_columns), payload.is_default, utcnow()
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A saved view with this name already exists")
    db.refresh(row)
    return _saved_out(row)


@router.delete("/saved-views/{view_id}", status_code=204)
def delete_saved_view(view_id: str, db: DB, tenant_id: Tenant, user: CurrentUser):
    _workspace_scope(db, tenant_id, user)
    db.delete(_personal_view(db, tenant_id, user.id, view_id))
    db.commit()
    return Response(status_code=204)
