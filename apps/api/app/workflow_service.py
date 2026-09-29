"""Structured workflow dispatch and execution on the existing durable job queue."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .automation_service import queue_job
from .features import can_use_feature
from .models import AuditEvent, Compliance, Document, Notification, Organization, Task, User, utcnow
from .phase14_models import AutomationActionExecution, AutomationDefinition, AutomationExecution

TRIGGERS = (
    "COMPLIANCE_CREATED", "COMPLIANCE_STATUS_CHANGED", "DEADLINE_APPROACHING",
    "TASK_CREATED", "TASK_STATUS_CHANGED", "TASK_OVERDUE",
    "DOCUMENT_UPLOADED", "DOCUMENT_EXPIRING", "FILING_COMPLETED",
)
CONDITION_FIELDS = (
    "compliance_status", "priority", "organization_id", "owner", "assignee",
    "days_until_deadline", "task_state", "document_state",
)
ACTION_TYPES = ("CREATE_TASK", "SEND_NOTIFICATION", "ASSIGN_RESPONSIBLE", "UPDATE_FIELDS")


def queue_workflow_event(db, tenant_id: str, trigger_type: str, entity_type: str, entity_id: str,
                         organization_id: str | None, event_key: str, *, depth: int | None = None) -> int:
    if trigger_type not in TRIGGERS or (depth if depth is not None else db.info.get("workflow_depth", 0)) >= 5:
        return 0
    definitions = db.scalars(select(AutomationDefinition).where(
        AutomationDefinition.tenant_id == tenant_id,
        AutomationDefinition.trigger_type == trigger_type,
        AutomationDefinition.enabled.is_(True),
    )).all()
    created = 0
    for definition in definitions:
        if definition.organization_id and definition.organization_id != organization_id:
            continue
        existing = db.scalar(select(AutomationExecution).where(
            AutomationExecution.automation_id == definition.id,
            AutomationExecution.event_key == event_key,
        ))
        if existing:
            continue
        execution = AutomationExecution(
            tenant_id=tenant_id, automation_id=definition.id, organization_id=organization_id,
            trigger_type=trigger_type, event_key=event_key, entity_type=entity_type, entity_id=entity_id,
        )
        try:
            with db.begin_nested():
                db.add(execution); db.flush()
                job, _ = queue_job(
                    db, tenant_id, "AUTOMATION_WORKFLOW_EXECUTION", f"workflow:{definition.id}:{event_key}",
                    entity_type="AutomationExecution", entity_id=execution.id,
                    payload={"execution_id": execution.id, "depth": (depth if depth is not None else db.info.get("workflow_depth", 0)) + 1},
                )
                execution.job_id = job.id
            created += 1
        except IntegrityError:
            continue
    return created


def _context(db, execution: AutomationExecution) -> tuple[object, Organization, dict]:
    tenant_id = execution.tenant_id
    if execution.entity_type == "Compliance":
        entity = db.scalar(select(Compliance).where(Compliance.id == execution.entity_id, Compliance.tenant_id == tenant_id))
        organization_id = entity.organization_id if entity else None
        values = {
            "compliance_status": entity.status if entity else None, "priority": entity.priority if entity else None,
            "owner": entity.owner_name if entity else None,
            "days_until_deadline": (entity.statutory_deadline - date.today()).days if entity else None,
        }
    elif execution.entity_type == "Task":
        entity = db.scalar(select(Task).where(Task.id == execution.entity_id, Task.tenant_id == tenant_id))
        organization_id = entity.organization_id if entity else None
        values = {
            "task_state": entity.status if entity else None, "priority": entity.priority if entity else None,
            "assignee": (entity.assignee_user_id or entity.assignee_name) if entity else None,
            "days_until_deadline": (entity.due_at - date.today()).days if entity else None,
        }
    elif execution.entity_type == "Document":
        entity = db.scalar(select(Document).where(Document.id == execution.entity_id, Document.tenant_id == tenant_id))
        organization_id = entity.organization_id if entity else None
        state = "NO_EXPIRY" if entity and not entity.expiry_at else "EXPIRED" if entity and entity.expiry_at < date.today() else "CURRENT"
        values = {"document_state": state, "days_until_deadline": (entity.expiry_at - date.today()).days if entity and entity.expiry_at else None}
    else:
        raise ValueError("Unsupported workflow entity")
    if not entity:
        raise HTTPException(404, "Workflow entity no longer exists")
    organization = db.scalar(select(Organization).where(Organization.id == organization_id, Organization.tenant_id == tenant_id))
    if not organization:
        raise HTTPException(404, "Workflow organization no longer exists")
    values["organization_id"] = organization.id
    return entity, organization, values


def _matches(conditions: list[dict], values: dict) -> bool:
    for condition in conditions:
        actual, expected, operator = values.get(condition["field"]), condition["value"], condition["operator"]
        if operator == "EQ" and actual != expected: return False
        if operator == "NE" and actual == expected: return False
        if operator == "IN" and actual not in expected: return False
        if operator == "LTE" and (actual is None or actual > expected): return False
        if operator == "GTE" and (actual is None or actual < expected): return False
    return True


def _authorized_actor(db, definition: AutomationDefinition, organization_id: str) -> User:
    from .organization_access import organization_access_role
    actor = db.scalar(select(User).where(User.id == definition.updated_by, User.tenant_id == definition.tenant_id,
                                         User.status == "ACTIVE"))
    if not actor or actor.role != "ADMIN" or not organization_access_role(db, definition.tenant_id, organization_id, actor.id):
        raise HTTPException(403, "AUTOMATION_ACTOR_NOT_AUTHORIZED")
    return actor


def _eligible(db, tenant_id: str, organization_id: str, user_id: str) -> User:
    from .phase8_api import eligible_users
    user = next((candidate for candidate, _ in eligible_users(db, tenant_id, organization_id) if candidate.id == user_id), None)
    if not user:
        raise HTTPException(422, "AUTOMATION_ASSIGNEE_NOT_AUTHORIZED")
    return user


def _perform_action(db, definition, execution, entity, organization, actor, action: dict) -> tuple[str, str, str]:
    parameters, action_type = action["parameters"], action["type"]
    tenant_id = execution.tenant_id
    if action_type == "CREATE_TASK":
        assignee = _eligible(db, tenant_id, organization.id, parameters["assignee_user_id"])
        due_at = date.today() + timedelta(days=parameters.get("due_in_days", 0))
        task = Task(tenant_id=tenant_id, organization_id=organization.id,
                    compliance_id=entity.id if isinstance(entity, Compliance) else getattr(entity, "compliance_id", None),
                    title=parameters["title"], due_at=due_at, status="TODO", priority=parameters.get("priority", "MEDIUM"),
                    assignee_user_id=assignee.id, assignee_name=assignee.name,
                    assignee_initials="".join(part[0] for part in assignee.name.split())[:3].upper(),
                    assigned_by=actor.id, assigned_at=utcnow())
        db.add(task); db.flush()
        from .phase8_api import notify_task
        notify_task(db, task, event_type="TASK_ASSIGNED", title="Task assigned",
                    message=f"{task.title} is due on {task.due_at.isoformat()}.", user_ids=[assignee.id])
        from .main import audit
        audit(db, tenant_id, "TASK_CREATED", "Task", task.id, f"Created by automation {definition.name}")
        return "Task", task.id, f"Created task {task.title}"
    if action_type == "SEND_NOTIFICATION":
        channels = tuple(parameters.get("channels", ["IN_APP"]))
        if "EMAIL" in channels and not can_use_feature(db, tenant_id, "custom_email"):
            raise HTTPException(403, "FEATURE_NOT_ENTITLED:custom_email")
        if "WHATSAPP" in channels and not can_use_feature(db, tenant_id, "whatsapp_integration"):
            raise HTTPException(403, "FEATURE_NOT_ENTITLED:whatsapp_integration")
        recipient = parameters.get("recipient", "TENANT_ADMIN")
        user_ids = []
        if recipient == "ASSIGNEE" and isinstance(entity, Task) and entity.assignee_user_id:
            user_ids = [entity.assignee_user_id]
        notification = Notification(tenant_id=tenant_id, title=parameters["title"], message=parameters["message"], kind="AUTOMATION")
        db.add(notification); db.flush()
        from .notification_service import distribute_notification
        distribute_notification(db, notification, event_type=execution.trigger_type, category="COMPLIANCE",
                                organization_id=organization.id, entity_type=execution.entity_type,
                                entity_id=execution.entity_id, recipient_role=None if user_ids else "TENANT_ADMIN",
                                user_ids=user_ids, channels=channels)
        return "Notification", notification.id, f"Queued {','.join(channels)} notification"
    if action_type == "ASSIGN_RESPONSIBLE":
        user = _eligible(db, tenant_id, organization.id, parameters["user_id"])
        if isinstance(entity, Task):
            entity.assignee_user_id, entity.assignee_name = user.id, user.name
            entity.assignee_initials = "".join(part[0] for part in user.name.split())[:3].upper()
            entity.assigned_by, entity.assigned_at, entity.updated_at = actor.id, utcnow(), utcnow()
        elif isinstance(entity, Compliance):
            from .runtime_models import ComplianceOwnership
            ownership = db.get(ComplianceOwnership, entity.id)
            if not ownership:
                ownership = ComplianceOwnership(compliance_id=entity.id, tenant_id=tenant_id, owner_id=user.id)
                db.add(ownership)
            ownership.owner_id, ownership.assigned_by, ownership.assigned_at, ownership.manual = user.id, actor.id, utcnow(), False
            entity.owner_name = user.name; entity.owner_initials = "".join(part[0] for part in user.name.split())[:3].upper()
        else:
            raise ValueError("Responsible user can only be assigned to a task or compliance")
        return execution.entity_type, execution.entity_id, f"Assigned {user.name}"
    if action_type == "UPDATE_FIELDS":
        field, value = parameters["field"], parameters["value"]
        triggered = False
        if field == "priority" and isinstance(entity, (Task, Compliance)):
            entity.priority = value; entity.updated_at = utcnow()
        elif field == "status" and isinstance(entity, Task):
            entity.status = value; entity.completed_at = utcnow() if value == "DONE" else None; entity.updated_at = utcnow()
            from .main import audit
            audit(db, tenant_id, "TASK_UPDATED", "Task", entity.id, f"Automation {definition.name} updated status to {value}")
            triggered = True
        elif field == "status" and isinstance(entity, Compliance):
            from .main import apply_compliance_transition
            db.info.update(actor_id=actor.id, actor_name="Automation worker")
            apply_compliance_transition(db, tenant_id, entity, value, reason="Configured automation workflow")
        else:
            raise ValueError("Field is not allowed for this entity")
        if not triggered:
            db.add(AuditEvent(tenant_id=tenant_id, actor_name="Automation worker", action="AUTOMATION_FIELD_UPDATED",
                              entity_type=execution.entity_type, entity_id=execution.entity_id,
                              summary=f"Automation {definition.name} updated {field} to {value}"))
        return execution.entity_type, execution.entity_id, f"Updated {field} to {value}"
    raise ValueError("Unsupported workflow action")


def execute_workflow(db, job, _today) -> dict:
    payload = json.loads(job.payload); execution_id = payload.get("execution_id")
    execution = db.scalar(select(AutomationExecution).where(AutomationExecution.id == execution_id,
                                                             AutomationExecution.tenant_id == job.tenant_id))
    if not execution: raise HTTPException(404, "Automation execution not found")
    definition = db.scalar(select(AutomationDefinition).where(AutomationDefinition.id == execution.automation_id,
                                                               AutomationDefinition.tenant_id == job.tenant_id))
    if not definition: raise HTTPException(404, "Automation definition not found")
    execution.attempt_count = job.attempt_count; execution.started_at = utcnow(); execution.status = "RUNNING"
    if not definition.enabled:
        execution.status = "SKIPPED"; execution.completed_at = utcnow(); execution.result_summary = "Automation disabled before execution"
        return {"status": "SKIPPED", "actions": 0}
    entity, organization, values = _context(db, execution)
    if definition.organization_id and definition.organization_id != organization.id:
        raise HTTPException(403, "AUTOMATION_ORGANIZATION_SCOPE_CHANGED")
    actor = _authorized_actor(db, definition, organization.id)
    if not _matches(json.loads(definition.conditions), values):
        execution.status = "SKIPPED"; execution.completed_at = utcnow(); execution.result_summary = "Conditions did not match"
        return {"status": "SKIPPED", "actions": 0}
    db.info["workflow_depth"] = int(payload.get("depth", 1))
    completed = 0
    for index, action in enumerate(json.loads(definition.actions)):
        receipt = db.scalar(select(AutomationActionExecution).where(
            AutomationActionExecution.execution_id == execution.id,
            AutomationActionExecution.action_index == index,
        ))
        if receipt: completed += 1; continue
        entity_type, entity_id, summary = _perform_action(db, definition, execution, entity, organization, actor, action)
        db.add(AutomationActionExecution(tenant_id=job.tenant_id, execution_id=execution.id, action_index=index,
                                         action_type=action["type"], entity_type=entity_type, entity_id=entity_id,
                                         summary=summary[:280]))
        db.flush(); completed += 1
    execution.status = "SUCCEEDED"; execution.completed_at = utcnow(); execution.last_error_code = ""
    execution.result_summary = f"Completed {completed} actions"
    db.add(AuditEvent(tenant_id=job.tenant_id, actor_name="Automation worker", action="AUTOMATION_EXECUTED",
                      entity_type="AutomationDefinition", entity_id=definition.id, summary=execution.result_summary))
    return {"status": "SUCCEEDED", "actions": completed}


def mark_workflow_failure(db, job, code: str) -> None:
    try:
        execution_id = json.loads(job.payload).get("execution_id")
    except (TypeError, ValueError):
        return
    execution = db.scalar(select(AutomationExecution).where(AutomationExecution.id == execution_id,
                                                             AutomationExecution.tenant_id == job.tenant_id))
    if execution:
        execution.status = "RETRY" if job.status == "RETRY" else "FAILED"
        execution.attempt_count = job.attempt_count; execution.last_error_code = code
        execution.completed_at = job.completed_at
