"""Tenant-scoped APIs for document intelligence and per-fact human review."""
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from .auth import CurrentUser, get_db, tenant_context
from .document_intelligence_service import approve_fact, reject_fact, request_run, review_queue, version_runs
from .production_security import limit_expensive

router = APIRouter(prefix="/api/v1", tags=["Document intelligence"])
DB = Annotated[Session, Depends(get_db)]
Tenant = Annotated[str, Depends(tenant_context)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RequestInput(Strict):
    reprocess: bool = False


class ApproveInput(Strict):
    edited_value: str | None = Field(default=None, max_length=2000)


@router.post("/documents/versions/{version_id}/intelligence", status_code=202)
def request_document_intelligence(version_id: str, payload: RequestInput, db: DB, tenant: Tenant, user: CurrentUser):
    limit_expensive(db, tenant, user.id, "document-intelligence", 12)
    return request_run(db, tenant, user, version_id, reprocess=payload.reprocess)


@router.get("/documents/versions/{version_id}/intelligence")
def get_document_intelligence(version_id: str, db: DB, tenant: Tenant, user: CurrentUser):
    return version_runs(db, tenant, user, version_id)


@router.get("/document-intelligence/review")
def get_review_queue(db: DB, tenant: Tenant, user: CurrentUser,
                     organization_id: str | None = Query(default=None, max_length=36)):
    return review_queue(db, tenant, user, organization_id)


@router.post("/document-intelligence/facts/{fact_id}/approve")
def approve_document_fact(fact_id: str, payload: ApproveInput, db: DB, tenant: Tenant, user: CurrentUser):
    return approve_fact(db, tenant, user, fact_id, payload.edited_value)


@router.post("/document-intelligence/facts/{fact_id}/reject")
def reject_document_fact(fact_id: str, db: DB, tenant: Tenant, user: CurrentUser):
    return reject_fact(db, tenant, user, fact_id)
