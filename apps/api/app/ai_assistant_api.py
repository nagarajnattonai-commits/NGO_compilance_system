"""Minimal APIs for organization-scoped grounded assistant conversations."""
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from .ai_assistant_service import ask, create_conversation, get_conversation, list_conversations
from .ai_provider import AiProviderError
from .ai_service import public_error
from .auth import CurrentUser, get_db, tenant_context

router = APIRouter(prefix="/api/v1/ai/conversations", tags=["Compliance AI assistant"])
DB = Annotated[Session, Depends(get_db)]
Tenant = Annotated[str, Depends(tenant_context)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ConversationInput(Strict):
    organization_id: str = Field(min_length=1, max_length=36)
    title: str = Field(default="", max_length=160)


class MessageInput(Strict):
    question: str = Field(min_length=3, max_length=2000)
    compliance_id: str | None = Field(default=None, max_length=36)
    document_id: str | None = Field(default=None, max_length=36)


@router.post("")
def start_conversation(payload: ConversationInput, db: DB, tenant_id: Tenant, user: CurrentUser):
    return create_conversation(db, tenant_id, user, payload.organization_id, payload.title)


@router.get("")
def conversations(organization_id: str = Query(min_length=1, max_length=36), *, db: DB,
                  tenant_id: Tenant, user: CurrentUser):
    return list_conversations(db, tenant_id, user, organization_id)


@router.get("/{conversation_id}")
def conversation(conversation_id: str, db: DB, tenant_id: Tenant, user: CurrentUser):
    return get_conversation(db, tenant_id, user, conversation_id)


@router.post("/{conversation_id}/messages")
def send_message(conversation_id: str, payload: MessageInput, db: DB, tenant_id: Tenant, user: CurrentUser):
    try:
        return ask(db, tenant_id, user, conversation_id, payload.question, payload.compliance_id, payload.document_id)
    except AiProviderError as error:
        raise public_error(error) from None
