"""Organization access administration and task collaboration APIs."""
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from .auth import CurrentUser, get_db, tenant_context
from .document_models import DocumentEvidenceLink
from .document_service import attach_link, genuine_file, owned_document
from .models import AuditEvent, Document, Organization, Task, User, utcnow
from .organization_access import (
    ACCESS_ROLES,
    organization_access_role,
    require_organization_access,
    workspace_role,
)
from .phase8_models import OrganizationAccess, TaskComment
from .runtime_membership import workspace_members

router = APIRouter(prefix="/api/v1", tags=["Organization access and tasks"])
DB = Annotated[object, Depends(get_db)]
Tenant = Annotated[str, Depends(tenant_context)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AccessInput(Strict):
    user_id: str = Field(min_length=1, max_length=36)
    access_role: Literal["VIEWER", "CONTRIBUTOR", "MANAGER"] = "CONTRIBUTOR"


class CommentInput(Strict):
    body: str = Field(min_length=1, max_length=4000)


class AttachmentInput(Strict):
    document_id: str = Field(min_length=1, max_length=36)


def _admin(actor):
    if actor.role != "ADMIN":
        raise HTTPException(403, "Workspace administrator access is required")


def _organization(db, tenant_id: str, organization_id: str) -> Organization:
    row = db.scalar(select(Organization).where(
        Organization.id == organization_id,
        Organization.tenant_id == tenant_id,
    ))
    if not row:
        raise HTTPException(404, "Organization not found in this workspace")
    return row


def _task(db, tenant_id: str, task_id: str, *, write: bool = False, actor=None) -> Task:
    row = db.scalar(select(Task).where(Task.id == task_id, Task.tenant_id == tenant_id))
    if not row:
        raise HTTPException(404, "Task not found")
    if write and actor and row.assignee_user_id == actor.id and actor.role != "VIEWER":
        require_organization_access(db, tenant_id, row.organization_id, user_id=actor.id)
    else:
        require_organization_access(db, tenant_id, row.organization_id, write=write, user_id=actor.id if actor else None)
    return row


def _audit(db, tenant_id: str, actor, action: str, entity_type: str, entity_id: str, summary: str):
    db.add(AuditEvent(tenant_id=tenant_id, actor_name=actor.name, action=action,
                      entity_type=entity_type, entity_id=entity_id, summary=summary[:280]))


def eligible_users(db, tenant_id: str, organization_id: str) -> list[tuple[User, str]]:
    result = []
    for user, role in workspace_members(db, tenant_id):
        if role == "VIEWER":
            continue
        access = organization_access_role(db, tenant_id, organization_id, user.id)
        if access:
            result.append((user, access))
    return sorted(result, key=lambda pair: (pair[0].name.casefold(), pair[0].id))


def notify_task(db, task: Task, *, event_type: str, title: str, message: str, user_ids: list[str]):
    if not user_ids:
        return
    from .models import Notification
    from .notification_service import distribute_notification
    notification = Notification(tenant_id=task.tenant_id, title=title, message=message, kind="TASK")
    db.add(notification)
    db.flush()
    distribute_notification(
        db, notification, event_type=event_type, category="TASK",
        organization_id=task.organization_id, entity_type="Task", entity_id=task.id,
        user_ids=user_ids, channels=("IN_APP", "EMAIL", "WHATSAPP"),
    )


@router.get("/organizations/{organization_id}/access")
def list_access(organization_id: str, db: DB, tenant_id: Tenant, actor: CurrentUser):
    _admin(actor)
    _organization(db, tenant_id, organization_id)
    rows = db.scalars(select(OrganizationAccess).where(
        OrganizationAccess.tenant_id == tenant_id,
        OrganizationAccess.organization_id == organization_id,
    ).order_by(OrganizationAccess.status, OrganizationAccess.user_id)).all()
    users = {row.id: row for row in db.scalars(select(User).where(User.id.in_([item.user_id for item in rows]))).all()}
    return [{
        "id": row.id, "user_id": row.user_id,
        "user_name": users[row.user_id].name if row.user_id in users else "Unavailable user",
        "user_email": users[row.user_id].email if row.user_id in users else "",
        "access_role": row.access_role, "status": row.status,
        "granted_by": row.granted_by, "granted_at": row.granted_at, "updated_at": row.updated_at,
    } for row in rows]


@router.put("/organizations/{organization_id}/access")
def grant_access(organization_id: str, payload: AccessInput, db: DB, tenant_id: Tenant, actor: CurrentUser):
    _admin(actor)
    _organization(db, tenant_id, organization_id)
    if payload.access_role not in ACCESS_ROLES:
        raise HTTPException(422, "Invalid organization access role")
    if not workspace_role(db, tenant_id, payload.user_id):
        raise HTTPException(422, "User must have active workspace login access")
    row = db.scalar(select(OrganizationAccess).where(
        OrganizationAccess.tenant_id == tenant_id,
        OrganizationAccess.organization_id == organization_id,
        OrganizationAccess.user_id == payload.user_id,
    ))
    action = "ORGANIZATION_ACCESS_UPDATED" if row else "ORGANIZATION_ACCESS_GRANTED"
    if not row:
        row = OrganizationAccess(tenant_id=tenant_id, organization_id=organization_id,
                                 user_id=payload.user_id, granted_by=actor.id)
        db.add(row)
    row.access_role = payload.access_role
    row.status = "ACTIVE"
    row.updated_at = utcnow()
    db.flush()
    _audit(db, tenant_id, actor, action, "OrganizationAccess", row.id,
           f"{payload.user_id} -> {organization_id}: {payload.access_role}")
    db.commit()
    return {"id": row.id, "user_id": row.user_id, "access_role": row.access_role, "status": row.status}


@router.delete("/organizations/{organization_id}/access/{user_id}", status_code=204)
def revoke_access(organization_id: str, user_id: str, db: DB, tenant_id: Tenant, actor: CurrentUser):
    _admin(actor)
    _organization(db, tenant_id, organization_id)
    row = db.scalar(select(OrganizationAccess).where(
        OrganizationAccess.tenant_id == tenant_id,
        OrganizationAccess.organization_id == organization_id,
        OrganizationAccess.user_id == user_id,
        OrganizationAccess.status == "ACTIVE",
    ))
    if not row:
        raise HTTPException(404, "Organization access record not found")
    row.status = "REVOKED"
    row.updated_at = utcnow()
    _audit(db, tenant_id, actor, "ORGANIZATION_ACCESS_REVOKED", "OrganizationAccess", row.id,
           f"Revoked {user_id} from {organization_id}")
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@router.get("/organizations/{organization_id}/eligible-assignees")
def assignees(organization_id: str, db: DB, tenant_id: Tenant, actor: CurrentUser):
    _organization(db, tenant_id, organization_id)
    require_organization_access(db, tenant_id, organization_id, user_id=actor.id)
    return [{"id": user.id, "name": user.name, "email": user.email, "access_role": access}
            for user, access in eligible_users(db, tenant_id, organization_id)]


@router.get("/tasks/{task_id}/comments")
def task_comments(task_id: str, db: DB, tenant_id: Tenant, actor: CurrentUser):
    task = _task(db, tenant_id, task_id, actor=actor)
    return [{"id": row.id, "task_id": row.task_id, "author_id": row.author_id,
             "author_name": row.author_name, "body": row.body, "created_at": row.created_at}
            for row in db.scalars(select(TaskComment).where(
                TaskComment.tenant_id == tenant_id,
                TaskComment.organization_id == task.organization_id,
                TaskComment.task_id == task.id,
            ).order_by(TaskComment.created_at)).all()]


@router.post("/tasks/{task_id}/comments", status_code=201)
def add_task_comment(task_id: str, payload: CommentInput, db: DB, tenant_id: Tenant, actor: CurrentUser):
    task = _task(db, tenant_id, task_id, write=True, actor=actor)
    row = TaskComment(tenant_id=tenant_id, organization_id=task.organization_id, task_id=task.id,
                      author_id=actor.id, author_name=actor.name, body=payload.body)
    db.add(row)
    db.flush()
    _audit(db, tenant_id, actor, "TASK_COMMENTED", "Task", task.id, f"Comment added to {task.title}")
    if task.assignee_user_id and task.assignee_user_id != actor.id:
        notify_task(db, task, event_type="TASK_COMMENTED", title="New task comment",
                    message=f"{actor.name} commented on {task.title}.", user_ids=[task.assignee_user_id])
    db.commit()
    return {"id": row.id, "task_id": row.task_id, "author_id": row.author_id,
            "author_name": row.author_name, "body": row.body, "created_at": row.created_at}


@router.get("/tasks/{task_id}/attachments")
def task_attachments(task_id: str, db: DB, tenant_id: Tenant, actor: CurrentUser):
    task = _task(db, tenant_id, task_id, actor=actor)
    rows = db.execute(select(DocumentEvidenceLink, Document).join(
        Document, Document.id == DocumentEvidenceLink.document_id).where(
            DocumentEvidenceLink.tenant_id == tenant_id,
            DocumentEvidenceLink.organization_id == task.organization_id,
            DocumentEvidenceLink.task_id == task.id,
            DocumentEvidenceLink.active.is_(True),
        ).order_by(DocumentEvidenceLink.linked_at.desc())).all()
    return [{"id": link.id, "document_id": document.id, "version_id": link.version_id,
             "name": document.name, "linked_by": link.linked_by, "linked_at": link.linked_at}
            for link, document in rows]


@router.post("/tasks/{task_id}/attachments", status_code=201)
def add_task_attachment(task_id: str, payload: AttachmentInput, db: DB, tenant_id: Tenant, actor: CurrentUser):
    task = _task(db, tenant_id, task_id, write=True, actor=actor)
    document = owned_document(db, tenant_id, payload.document_id)
    if document.organization_id != task.organization_id:
        raise HTTPException(422, "Document and task must belong to the same organization")
    blob = genuine_file(db, document)
    if not blob:
        raise HTTPException(422, "Task attachment requires an available stored file version")
    link = attach_link(db, tenant_id, task.organization_id, document, blob, actor, "task", task.id)
    _audit(db, tenant_id, actor, "TASK_ATTACHMENT_LINKED", "Task", task.id,
           f"Linked evidence document {document.id}")
    db.commit()
    return {"id": link.id, "document_id": document.id, "version_id": link.version_id,
            "name": document.name, "linked_by": link.linked_by, "linked_at": link.linked_at}


@router.delete("/tasks/{task_id}/attachments/{link_id}", status_code=204)
def archive_task_attachment(task_id: str, link_id: str, db: DB, tenant_id: Tenant, actor: CurrentUser):
    task = _task(db, tenant_id, task_id, write=True, actor=actor)
    link = db.scalar(select(DocumentEvidenceLink).where(
        DocumentEvidenceLink.id == link_id,
        DocumentEvidenceLink.tenant_id == tenant_id,
        DocumentEvidenceLink.organization_id == task.organization_id,
        DocumentEvidenceLink.task_id == task.id,
        DocumentEvidenceLink.active.is_(True),
    ))
    if not link:
        raise HTTPException(404, "Task attachment not found")
    link.active = False
    _audit(db, tenant_id, actor, "TASK_ATTACHMENT_ARCHIVED", "Task", task.id,
           f"Archived task evidence link {link.id}")
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
