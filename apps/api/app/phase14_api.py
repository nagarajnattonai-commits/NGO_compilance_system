"""Workspace APIs for structured, tenant-scoped automation workflows."""
from __future__ import annotations

import json
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import CurrentUser, get_db, tenant_context
from .features import can_use_feature
from .models import AuditEvent, Organization, utcnow
from .organization_access import accessible_organization_ids, require_organization_access
from .phase14_models import AutomationActionExecution, AutomationDefinition, AutomationExecution
from .runtime_membership import workspace_members
from .workflow_service import ACTION_TYPES, CONDITION_FIELDS, TRIGGERS

router = APIRouter(prefix="/api/v1/automations", tags=["Automation workflows"])
DB = Annotated[Session, Depends(get_db)]
Tenant = Annotated[str, Depends(tenant_context)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ConditionInput(Strict):
    field: Literal["compliance_status", "priority", "organization_id", "owner", "assignee", "days_until_deadline", "task_state", "document_state"]
    operator: Literal["EQ", "NE", "IN", "LTE", "GTE"] = "EQ"
    value: str | int | list[str]

    @model_validator(mode="after")
    def valid_value(self):
        if self.operator == "IN" and (not isinstance(self.value, list) or not self.value):
            raise ValueError("IN requires a non-empty list")
        if self.operator in {"LTE", "GTE"} and not isinstance(self.value, int):
            raise ValueError("Range operators require an integer")
        return self


class ActionInput(Strict):
    type: Literal["CREATE_TASK", "SEND_NOTIFICATION", "ASSIGN_RESPONSIBLE", "UPDATE_FIELDS"]
    parameters: dict

    @model_validator(mode="after")
    def valid_parameters(self):
        allowed = {
            "CREATE_TASK": {"title", "due_in_days", "priority", "assignee_user_id"},
            "SEND_NOTIFICATION": {"title", "message", "channels", "recipient"},
            "ASSIGN_RESPONSIBLE": {"user_id"},
            "UPDATE_FIELDS": {"field", "value"},
        }[self.type]
        required = {
            "CREATE_TASK": {"title", "assignee_user_id"}, "SEND_NOTIFICATION": {"title", "message"},
            "ASSIGN_RESPONSIBLE": {"user_id"}, "UPDATE_FIELDS": {"field", "value"},
        }[self.type]
        if set(self.parameters) - allowed or not required <= set(self.parameters):
            raise ValueError("Action parameters do not match the selected action")
        if self.type == "CREATE_TASK":
            if not isinstance(self.parameters["title"], str) or not 3 <= len(self.parameters["title"].strip()) <= 220:
                raise ValueError("Task title must be 3-220 characters")
            days = self.parameters.get("due_in_days", 0)
            if not isinstance(days, int) or not 0 <= days <= 365:
                raise ValueError("due_in_days must be between 0 and 365")
            if self.parameters.get("priority", "MEDIUM") not in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}:
                raise ValueError("Invalid task priority")
        if self.type == "SEND_NOTIFICATION":
            channels = self.parameters.get("channels", ["IN_APP"])
            if not isinstance(channels, list) or not channels or not set(channels) <= {"IN_APP", "EMAIL", "WHATSAPP"}:
                raise ValueError("Invalid notification channels")
            if self.parameters.get("recipient", "TENANT_ADMIN") not in {"TENANT_ADMIN", "ASSIGNEE"}:
                raise ValueError("Invalid notification recipient")
        if self.type == "UPDATE_FIELDS":
            field, value = self.parameters["field"], self.parameters["value"]
            if field not in {"priority", "status"}:
                raise ValueError("Only priority and status may be updated")
            allowed_values = ({"LOW", "MEDIUM", "HIGH", "CRITICAL"} if field == "priority" else
                              {"TODO", "IN_PROGRESS", "DONE", "UNDER_REVIEW", "READY_TO_FILE", "ON_HOLD"})
            if value not in allowed_values:
                raise ValueError("Invalid workflow field value")
        return self


class DefinitionInput(Strict):
    name: str = Field(min_length=3, max_length=120)
    description: str = Field(default="", max_length=500)
    organization_id: str | None = Field(default=None, max_length=36)
    enabled: bool = True
    trigger_type: Literal["COMPLIANCE_CREATED", "COMPLIANCE_STATUS_CHANGED", "DEADLINE_APPROACHING", "TASK_CREATED", "TASK_STATUS_CHANGED", "TASK_OVERDUE", "DOCUMENT_UPLOADED", "DOCUMENT_EXPIRING", "FILING_COMPLETED"]
    conditions: list[ConditionInput] = Field(default_factory=list, max_length=10)
    actions: list[ActionInput] = Field(min_length=1, max_length=10)


def _authorize(db: Session, tenant_id: str, actor, *, require_entitlement=True):
    if getattr(actor, "_admin_audience", False) or actor.role != "ADMIN":
        raise HTTPException(403, "Workspace administrator access is required")
    if require_entitlement and not can_use_feature(db, tenant_id, "advanced_automation"):
        raise HTTPException(403, "FEATURE_NOT_ENTITLED:advanced_automation")


def _definition(db: Session, tenant_id: str, definition_id: str) -> AutomationDefinition:
    row = db.scalar(select(AutomationDefinition).where(AutomationDefinition.id == definition_id,
                                                        AutomationDefinition.tenant_id == tenant_id))
    if not row: raise HTTPException(404, "Automation not found")
    return row


def _validate_references(db: Session, tenant_id: str, actor, payload: DefinitionInput):
    if payload.organization_id:
        organization = db.scalar(select(Organization).where(Organization.id == payload.organization_id,
                                                             Organization.tenant_id == tenant_id))
        if not organization: raise HTTPException(404, "Organization not found")
        require_organization_access(db, tenant_id, organization.id, write=True, user_id=actor.id)
    user_ids = {str(action.parameters.get("assignee_user_id") or action.parameters.get("user_id"))
                for action in payload.actions if action.parameters.get("assignee_user_id") or action.parameters.get("user_id")}
    members = {user.id: user for user, role in workspace_members(db, tenant_id) if role != "VIEWER"}
    for user_id in user_ids:
        user = members.get(user_id)
        if not user: raise HTTPException(422, "Automation action user is not an active workspace user")
        if payload.organization_id:
            require_organization_access(db, tenant_id, payload.organization_id, user_id=user.id)
    for condition in payload.conditions:
        if condition.field != "organization_id":
            continue
        values = condition.value if isinstance(condition.value, list) else [condition.value]
        for value in values:
            if not isinstance(value, str):
                raise HTTPException(422, "Condition organization must be an identifier")
            organization = db.scalar(select(Organization.id).where(Organization.id == value,
                                                                    Organization.tenant_id == tenant_id))
            if not organization:
                raise HTTPException(422, "Condition organization is outside this workspace")
            if payload.organization_id and value != payload.organization_id:
                raise HTTPException(422, "Condition organization must match the automation scope")
            require_organization_access(db, tenant_id, value, user_id=actor.id)


def _out(row: AutomationDefinition):
    return {"id": row.id, "name": row.name, "description": row.description,
            "organization_id": row.organization_id, "enabled": row.enabled, "trigger_type": row.trigger_type,
            "conditions": json.loads(row.conditions), "actions": json.loads(row.actions), "revision": row.revision,
            "created_by": row.created_by, "updated_by": row.updated_by,
            "created_at": row.created_at, "updated_at": row.updated_at}


@router.get("/metadata")
def metadata(db: DB, tenant_id: Tenant, actor: CurrentUser):
    _authorize(db, tenant_id, actor)
    allowed = accessible_organization_ids(db, tenant_id, actor.id)
    organizations = db.scalars(select(Organization).where(Organization.tenant_id == tenant_id).order_by(Organization.name)).all()
    if allowed is not None: organizations = [row for row in organizations if row.id in allowed]
    users = [user for user, _ in workspace_members(db, tenant_id) if user.role != "VIEWER"]
    return {"triggers": TRIGGERS, "condition_fields": CONDITION_FIELDS, "action_types": ACTION_TYPES,
            "organizations": [{"id": row.id, "name": row.name} for row in organizations],
            "users": [{"id": row.id, "name": row.name} for row in users]}


@router.get("")
def list_definitions(db: DB, tenant_id: Tenant, actor: CurrentUser):
    _authorize(db, tenant_id, actor)
    rows = db.scalars(select(AutomationDefinition).where(AutomationDefinition.tenant_id == tenant_id)
                      .order_by(AutomationDefinition.updated_at.desc())).all()
    return [_out(row) for row in rows]


@router.post("", status_code=201)
def create_definition(payload: DefinitionInput, db: DB, tenant_id: Tenant, actor: CurrentUser):
    _authorize(db, tenant_id, actor); _validate_references(db, tenant_id, actor, payload)
    row = AutomationDefinition(tenant_id=tenant_id, created_by=actor.id, updated_by=actor.id,
        name=payload.name, description=payload.description, organization_id=payload.organization_id,
        enabled=payload.enabled, trigger_type=payload.trigger_type,
        conditions=json.dumps([item.model_dump() for item in payload.conditions], separators=(",", ":")),
        actions=json.dumps([item.model_dump() for item in payload.actions], separators=(",", ":")))
    db.add(row); db.flush()
    db.add(AuditEvent(tenant_id=tenant_id, actor_name=actor.name, action="AUTOMATION_CREATED",
                      entity_type="AutomationDefinition", entity_id=row.id, summary=f"Created automation {row.name}"))
    db.commit(); db.refresh(row); return _out(row)


@router.put("/{definition_id}")
def update_definition(definition_id: str, payload: DefinitionInput, db: DB, tenant_id: Tenant, actor: CurrentUser):
    _authorize(db, tenant_id, actor); row = _definition(db, tenant_id, definition_id)
    _validate_references(db, tenant_id, actor, payload)
    row.name, row.description, row.organization_id = payload.name, payload.description, payload.organization_id
    row.enabled, row.trigger_type = payload.enabled, payload.trigger_type
    row.conditions = json.dumps([item.model_dump() for item in payload.conditions], separators=(",", ":"))
    row.actions = json.dumps([item.model_dump() for item in payload.actions], separators=(",", ":"))
    row.revision += 1; row.updated_by = actor.id; row.updated_at = utcnow()
    db.add(AuditEvent(tenant_id=tenant_id, actor_name=actor.name, action="AUTOMATION_UPDATED",
                      entity_type="AutomationDefinition", entity_id=row.id, summary=f"Updated automation {row.name} revision {row.revision}"))
    db.commit(); db.refresh(row); return _out(row)


@router.delete("/{definition_id}", status_code=204)
def disable_definition(definition_id: str, db: DB, tenant_id: Tenant, actor: CurrentUser):
    _authorize(db, tenant_id, actor); row = _definition(db, tenant_id, definition_id)
    row.enabled = False; row.revision += 1; row.updated_by = actor.id; row.updated_at = utcnow()
    db.add(AuditEvent(tenant_id=tenant_id, actor_name=actor.name, action="AUTOMATION_DISABLED",
                      entity_type="AutomationDefinition", entity_id=row.id, summary=f"Disabled automation {row.name}"))
    db.commit(); return Response(status_code=204)


@router.get("/{definition_id}/executions")
def execution_history(definition_id: str, db: DB, tenant_id: Tenant, actor: CurrentUser,
                      limit: int = Query(default=50, ge=1, le=100)):
    _authorize(db, tenant_id, actor); _definition(db, tenant_id, definition_id)
    rows = db.scalars(select(AutomationExecution).where(AutomationExecution.tenant_id == tenant_id,
        AutomationExecution.automation_id == definition_id).order_by(AutomationExecution.created_at.desc()).limit(limit)).all()
    return [{"id": row.id, "trigger_type": row.trigger_type, "entity_type": row.entity_type,
             "entity_id": row.entity_id, "status": row.status, "attempt_count": row.attempt_count,
             "last_error_code": row.last_error_code, "result_summary": row.result_summary,
             "created_at": row.created_at, "started_at": row.started_at, "completed_at": row.completed_at,
             "actions": [{"index": item.action_index, "type": item.action_type, "status": item.status,
                          "summary": item.summary} for item in db.scalars(select(AutomationActionExecution).where(
                              AutomationActionExecution.execution_id == row.id).order_by(AutomationActionExecution.action_index)).all()]}
            for row in rows]
