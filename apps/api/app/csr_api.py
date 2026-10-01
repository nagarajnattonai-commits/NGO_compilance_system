"""CSR NGO partner, project and configurable due-diligence APIs."""
from datetime import date
from decimal import Decimal
import csv
import io
import json
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from .auth import CurrentUser, get_db, tenant_context
from .csr_service import (PARTNER_STATES, PROJECT_STATES, REVIEW_STATES, add_collaborator, create_project,
                          create_relationship, create_review, create_template, dashboard, link_evidence,
                          link_task, partner_directory, projects, review_data, reviews, templates,
                          update_item, update_project, update_relationship)
from .production_security import limit_expensive

router = APIRouter(prefix="/api/v1/csr", tags=["CSR partner management"])
DB = Annotated[Session, Depends(get_db)]
Tenant = Annotated[str, Depends(tenant_context)]
PartnerStatus = Literal["PROSPECTIVE", "UNDER_REVIEW", "APPROVED", "ACTIVE", "ON_HOLD", "INACTIVE"]
ProjectStatus = Literal["DRAFT", "PLANNED", "ACTIVE", "ON_HOLD", "COMPLETED", "CANCELLED"]
ItemStatus = Literal["NOT_STARTED", "IN_PROGRESS", "SUBMITTED", "UNDER_REVIEW", "CHANGES_REQUESTED",
                     "APPROVED", "REJECTED", "NOT_APPLICABLE", "REVIEW_REQUIRED"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PartnerCreate(Strict):
    organization_id: str = Field(min_length=1, max_length=36)
    status: PartnerStatus = "PROSPECTIVE"
    review_status: ItemStatus = "NOT_STARTED"
    owner_user_id: str | None = Field(default=None, max_length=36)
    onboarding_date: date | None = None
    internal_notes: str = Field(default="", max_length=4000)
    shared_notes: str = Field(default="", max_length=4000)
    collaboration_enabled: bool = False


class PartnerUpdate(Strict):
    status: PartnerStatus | None = None
    review_status: ItemStatus | None = None
    owner_user_id: str | None = Field(default=None, max_length=36)
    onboarding_date: date | None = None
    internal_notes: str | None = Field(default=None, max_length=4000)
    shared_notes: str | None = Field(default=None, max_length=4000)
    collaboration_enabled: bool | None = None


class CollaboratorInput(Strict):
    user_id: str = Field(min_length=1, max_length=36)


class ProjectInput(Strict):
    relationship_id: str = Field(min_length=1, max_length=36)
    name: str = Field(min_length=3, max_length=200)
    code: str = Field(min_length=2, max_length=60, pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
    description: str = Field(default="", max_length=5000)
    status: ProjectStatus = "DRAFT"
    start_date: date | None = None
    end_date: date | None = None
    owner_user_id: str | None = Field(default=None, max_length=36)
    ngo_contact: str = Field(default="", max_length=160)
    approved_budget: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    category: str = Field(default="", max_length=100)
    location: str = Field(default="", max_length=160)
    internal_notes: str = Field(default="", max_length=4000)
    shared_with_ngo: bool = False

    @model_validator(mode="after")
    def date_order(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("Project end date cannot precede start date")
        return self


class ProjectUpdate(Strict):
    name: str | None = Field(default=None, min_length=3, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    status: ProjectStatus | None = None
    start_date: date | None = None
    end_date: date | None = None
    owner_user_id: str | None = Field(default=None, max_length=36)
    ngo_contact: str | None = Field(default=None, max_length=160)
    approved_budget: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    category: str | None = Field(default=None, max_length=100)
    location: str | None = Field(default=None, max_length=160)
    internal_notes: str | None = Field(default=None, max_length=4000)
    shared_with_ngo: bool | None = None

    @model_validator(mode="after")
    def date_order(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("Project end date cannot precede start date")
        return self


class TemplateItemInput(Strict):
    category: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(default="", max_length=2000)
    requirement_type: Literal["CONFIRMATION", "DOCUMENT", "REGISTRATION", "PROFILE_FACT", "REVIEW", "COMMENT"] = "CONFIRMATION"
    required: bool = True
    registration_kind: Literal["", "12A", "12AB", "80G", "FCRA", "GST", "CSR"] = ""
    expiry_monitoring: bool = False
    share_with_ngo: bool = True

    @model_validator(mode="after")
    def registration_requirement(self):
        if self.requirement_type == "REGISTRATION" and not self.registration_kind:
            raise ValueError("Registration requirements must select a typed registration kind")
        return self


class TemplateInput(Strict):
    name: str = Field(min_length=3, max_length=160)
    description: str = Field(default="", max_length=4000)
    version: int = Field(default=1, ge=1, le=1000)
    enabled: bool = True
    items: list[TemplateItemInput] = Field(min_length=1, max_length=100)


class ReviewInput(Strict):
    relationship_id: str = Field(min_length=1, max_length=36)
    template_id: str = Field(min_length=1, max_length=36)
    project_id: str | None = Field(default=None, max_length=36)
    title: str = Field(min_length=3, max_length=200)
    due_date: date | None = None
    shared_with_ngo: bool = False


class ItemUpdate(Strict):
    status: ItemStatus
    response: str | None = Field(default=None, max_length=5000)
    reviewer_comment: str | None = Field(default=None, max_length=4000)
    internal_notes: str | None = Field(default=None, max_length=4000)
    expiry_at: date | None = None


class EvidenceInput(Strict):
    version_id: str = Field(min_length=1, max_length=36)


class TaskLinkInput(Strict):
    relationship_id: str = Field(min_length=1, max_length=36)
    task_id: str = Field(min_length=1, max_length=36)
    project_id: str | None = Field(default=None, max_length=36)
    item_id: str | None = Field(default=None, max_length=36)


@router.get("/dashboard")
def csr_dashboard(db: DB, tenant: Tenant, user: CurrentUser):
    limit_expensive(db, tenant, user.id, "csr-dashboard", 60)
    return dashboard(db, tenant, user)


@router.get("/partners")
def list_partners(db: DB, tenant: Tenant, user: CurrentUser, q: str = Query(default="", max_length=120)):
    return partner_directory(db, tenant, user, q)


@router.post("/partners", status_code=201)
def add_partner(payload: PartnerCreate, db: DB, tenant: Tenant, user: CurrentUser):
    values = payload.model_dump(exclude={"organization_id"})
    return create_relationship(db, tenant, user, payload.organization_id, values)


@router.patch("/partners/{relationship_id}")
def patch_partner(relationship_id: str, payload: PartnerUpdate, db: DB, tenant: Tenant, user: CurrentUser):
    return update_relationship(db, tenant, user, relationship_id, payload.model_dump(exclude_unset=True))


@router.post("/partners/{relationship_id}/collaborators", status_code=201)
def grant_collaborator(relationship_id: str, payload: CollaboratorInput, db: DB, tenant: Tenant, user: CurrentUser):
    return add_collaborator(db, tenant, user, relationship_id, payload.user_id)


@router.get("/projects")
def list_projects(db: DB, tenant: Tenant, user: CurrentUser,
                  relationship_id: str | None = Query(default=None, max_length=36)):
    return projects(db, tenant, user, relationship_id)


@router.post("/projects", status_code=201)
def add_project(payload: ProjectInput, db: DB, tenant: Tenant, user: CurrentUser):
    values = payload.model_dump(exclude={"relationship_id"})
    return create_project(db, tenant, user, payload.relationship_id, values)


@router.patch("/projects/{project_id}")
def patch_project(project_id: str, payload: ProjectUpdate, db: DB, tenant: Tenant, user: CurrentUser):
    return update_project(db, tenant, user, project_id, payload.model_dump(exclude_unset=True))


@router.get("/checklist-templates")
def list_templates(db: DB, tenant: Tenant, user: CurrentUser):
    return templates(db, tenant, user)


@router.post("/checklist-templates", status_code=201)
def add_template(payload: TemplateInput, db: DB, tenant: Tenant, user: CurrentUser):
    return create_template(db, tenant, user, payload.model_dump(exclude={"items"}),
                           [item.model_dump() for item in payload.items])


@router.get("/reviews")
def list_reviews(db: DB, tenant: Tenant, user: CurrentUser,
                 relationship_id: str | None = Query(default=None, max_length=36)):
    return reviews(db, tenant, user, relationship_id)


@router.post("/reviews", status_code=201)
def add_review(payload: ReviewInput, db: DB, tenant: Tenant, user: CurrentUser):
    return create_review(db, tenant, user, payload.relationship_id, payload.template_id,
                         payload.project_id, payload.title, payload.due_date, payload.shared_with_ngo)


@router.get("/reviews/{review_id}")
def get_review(review_id: str, db: DB, tenant: Tenant, user: CurrentUser):
    return review_data(db, tenant, user, review_id)


@router.patch("/items/{item_id}")
def patch_item(item_id: str, payload: ItemUpdate, db: DB, tenant: Tenant, user: CurrentUser):
    return update_item(db, tenant, user, item_id, payload.status, payload.response,
                       payload.reviewer_comment, payload.internal_notes, payload.expiry_at)


@router.post("/items/{item_id}/evidence", status_code=201)
def add_evidence(item_id: str, payload: EvidenceInput, db: DB, tenant: Tenant, user: CurrentUser):
    return link_evidence(db, tenant, user, item_id, payload.version_id)


@router.post("/task-links", status_code=201)
def add_task_link(payload: TaskLinkInput, db: DB, tenant: Tenant, user: CurrentUser):
    return link_task(db, tenant, user, payload.relationship_id, payload.task_id,
                     payload.project_id, payload.item_id)


def _csv_value(value) -> str:
    if isinstance(value, (dict, list)): value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text


@router.get("/reports/portfolio")
def portfolio_report(db: DB, tenant: Tenant, user: CurrentUser):
    overview = dashboard(db, tenant, user)
    return {"title": "CSR partner operational due diligence summary", "legal_certification": False, **overview}


@router.get("/reports/portfolio.csv")
def portfolio_report_csv(db: DB, tenant: Tenant, user: CurrentUser):
    limit_expensive(db, tenant, user.id, "csr-report-export", 5, 60)
    rows = dashboard(db, tenant, user)["partners"]
    fields = ("organization_name", "organization_type", "status", "review_status", "profile_completeness",
              "expiring_registrations", "open_reviews", "active_projects", "owner_name", "last_activity_at")
    output = io.StringIO(newline=""); writer = csv.writer(output); writer.writerow(fields)
    for row in rows: writer.writerow([_csv_value(row.get(field)) for field in fields])
    return Response(output.getvalue(), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="setu-csr-partner-summary.csv"',
                 "X-Content-Type-Options": "nosniff",
                 "X-Operational-Status-Only": "true"})
