"""Tenant-scoped APIs for secure document indexing and retrieval."""
from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from .ai_provider import AiProviderError
from .ai_service import RetrievalFilters, index_document, index_status, public_error, retrieve, status
from .auth import CurrentUser, get_db, tenant_context

router = APIRouter(prefix="/api/v1/ai", tags=["Secure AI foundation"])
DB = Annotated[Session, Depends(get_db)]
Tenant = Annotated[str, Depends(tenant_context)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RetrievalFilterInput(Strict):
    organization_id: str | None = Field(default=None, max_length=36)
    compliance_id: str | None = Field(default=None, max_length=36)
    document_id: str | None = Field(default=None, max_length=36)
    version_id: str | None = Field(default=None, max_length=36)
    source_type: Literal["DOCUMENT", "EVIDENCE"] | None = None


class RetrievalInput(Strict):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)
    filters: RetrievalFilterInput = Field(default_factory=RetrievalFilterInput)


@router.get("/status")
def ai_status(db: DB, tenant_id: Tenant, user: CurrentUser):
    return status(db, tenant_id, user)


@router.post("/index/document/{version_id}")
def create_document_index(version_id: str, db: DB, tenant_id: Tenant, user: CurrentUser):
    try:
        return index_document(db, tenant_id, user, version_id)
    except AiProviderError as error:
        raise public_error(error) from None


@router.get("/index/document/{version_id}")
def document_index_status(version_id: str, db: DB, tenant_id: Tenant, user: CurrentUser):
    return index_status(db, tenant_id, user, version_id)


@router.post("/retrieve")
def retrieve_context(payload: RetrievalInput, db: DB, tenant_id: Tenant, user: CurrentUser):
    try:
        return retrieve(db, tenant_id, user, payload.query, payload.top_k, RetrievalFilters(**payload.filters.model_dump()))
    except AiProviderError as error:
        raise public_error(error) from None
