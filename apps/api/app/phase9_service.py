"""Frozen workflow review, approval, filing and completion controls."""
from __future__ import annotations

import json

from fastapi import HTTPException
from sqlalchemy import func, select

from .compliance_engine import document_coverage
from .compliance_template_schema import TemplateConfiguration
from .models import (
    AuditEvent,
    Compliance,
    ComplianceNotificationTemplate,
    ComplianceSnapshot,
    Notification,
    Submission,
    Task,
    utcnow,
)
from .phase9_models import ComplianceApproval, ComplianceReview
from .runtime_membership import actor_roles
from .runtime_models import ComplianceOwnership


def frozen_configuration(db, item: Compliance) -> tuple[ComplianceSnapshot | None, TemplateConfiguration | None]:
    snapshot = db.get(ComplianceSnapshot, item.id)
    if not snapshot or snapshot.tenant_id != item.tenant_id:
        return None, None
    return snapshot, TemplateConfiguration.model_validate_json(snapshot.configuration)


def latest_review(db, item: Compliance) -> ComplianceReview | None:
    return db.scalar(select(ComplianceReview).where(
        ComplianceReview.tenant_id == item.tenant_id,
        ComplianceReview.compliance_id == item.id,
    ).order_by(ComplianceReview.revision.desc()))


def latest_approval(db, item: Compliance, review_id: str | None = None) -> ComplianceApproval | None:
    filters = [
        ComplianceApproval.tenant_id == item.tenant_id,
        ComplianceApproval.compliance_id == item.id,
    ]
    if review_id:
        filters.append(ComplianceApproval.review_id == review_id)
    return db.scalar(select(ComplianceApproval).where(*filters).order_by(ComplianceApproval.revision.desc()))


def _actor_id(db) -> str:
    actor_id = db.info.get("actor_id")
    if not actor_id:
        raise HTTPException(401, "Authenticated workflow actor is required")
    return actor_id


def _require_role(db, item: Compliance, role: str, message: str) -> None:
    if role not in actor_roles(db, item.tenant_id, item.organization_id):
        raise HTTPException(403, message)


def _required_controls(db, item: Compliance, snapshot: ComplianceSnapshot) -> None:
    required_ids = [entry["task_id"] for entry in json.loads(snapshot.checklist_tasks) if entry["required"]]
    if required_ids and db.scalar(select(Task.id).where(
        Task.tenant_id == item.tenant_id,
        Task.id.in_(required_ids),
        Task.status != "DONE",
    )):
        raise HTTPException(422, "REQUIRED_CHECKLIST_INCOMPLETE: complete every required checklist task")
    missing = [entry for entry in document_coverage(db, snapshot, item.statutory_deadline)
               if entry["required"] and len(entry["document_ids"]) < entry["minimum_count"]]
    if missing:
        detail = "; ".join(
            f"{entry['document_type']} ({len(entry['document_ids'])}/{entry['minimum_count']})"
            for entry in missing
        )
        raise HTTPException(422, "REQUIRED_EVIDENCE_MISSING: " + detail)


def _approval_required(config: TemplateConfiguration) -> bool:
    return any(edge.required_approval for edge in config.workflow.transitions)


def _notify(db, item: Compliance, event: str, title: str, message: str, *,
            recipient_role: str | None = None, user_ids: tuple[str, ...] = ()) -> None:
    from .notification_service import distribute_notification

    notification = Notification(tenant_id=item.tenant_id, title=title, message=message, kind="REVIEW")
    db.add(notification)
    db.flush()
    db.add(ComplianceNotificationTemplate(
        notification_id=notification.id,
        tenant_id=item.tenant_id,
        template_key=f"compliance.workflow.{event.lower()}",
        variables=json.dumps({"complianceName": item.title, "code": item.code, "event": event}),
    ))
    db.flush()
    distribute_notification(
        db,
        notification,
        event_type=event,
        category="COMPLIANCE",
        organization_id=item.organization_id,
        entity_type="Compliance",
        entity_id=item.id,
        recipient_role=recipient_role,
        user_ids=user_ids,
        channels=("IN_APP",),
    )


def _owner_ids(db, item: Compliance) -> tuple[str, ...]:
    owner = db.get(ComplianceOwnership, item.id)
    return (owner.owner_id,) if owner and owner.tenant_id == item.tenant_id else ()


def _audit(db, item: Compliance, action: str, summary: str) -> None:
    db.add(AuditEvent(
        tenant_id=item.tenant_id,
        actor_name=db.info.get("actor_name", "System"),
        action=action,
        entity_type="Compliance",
        entity_id=item.id,
        summary=summary[:280],
    ))


def before_transition(db, item: Compliance, target_status: str, edge, *, reason: str | None,
                      submission_reference: str | None, proof_document_id: str | None,
                      proof_type: str | None) -> None:
    snapshot, config = frozen_configuration(db, item)
    if not snapshot or not config:
        return
    actor_id = _actor_id(db)

    if target_status == "UNDER_REVIEW":
        revision = (db.scalar(select(func.max(ComplianceReview.revision)).where(
            ComplianceReview.compliance_id == item.id,
            ComplianceReview.tenant_id == item.tenant_id,
        )) or 0) + 1
        review = ComplianceReview(
            tenant_id=item.tenant_id,
            organization_id=item.organization_id,
            compliance_id=item.id,
            revision=revision,
            submitted_by=actor_id,
        )
        db.add(review)
        db.flush()
        _audit(db, item, "REVIEW_SUBMITTED", f"Review revision {revision} submitted")
        _notify(db, item, "REVIEW_REQUESTED", f"{item.code} review requested",
                f"{item.title} was submitted for review.", recipient_role=config.responsibility.reviewer_role)

    if target_status == "CHANGES_REQUESTED":
        review = latest_review(db, item)
        approval = latest_approval(db, item, review.id if review else None)
        if approval and approval.decision == "PENDING":
            _require_role(db, item, config.responsibility.approver_role,
                          "The configured approver must request these changes")
            if config.responsibility.separate_reviewer_approver and approval.requested_by == actor_id:
                raise HTTPException(403, "SEPARATION_OF_DUTIES: reviewer and approver must differ")
            approval.decision = "CHANGES_REQUESTED"
            approval.approver_id = actor_id
            approval.decided_at = utcnow()
            approval.comments = reason or ""
        elif review and review.decision == "PENDING":
            _require_role(db, item, config.responsibility.reviewer_role,
                          "The configured reviewer must request these changes")
            if config.responsibility.separate_preparer_reviewer and review.submitted_by == actor_id:
                raise HTTPException(403, "SEPARATION_OF_DUTIES: preparer and reviewer must differ")
            review.decision = "CHANGES_REQUESTED"
            review.reviewer_id = actor_id
            review.reviewed_at = utcnow()
            review.comments = reason or ""
        else:
            raise HTTPException(409, "PENDING_REVIEW_OR_APPROVAL_REQUIRED")
        _audit(db, item, "CHANGES_REQUESTED", reason or "Changes requested")

    has_review = any(stage.state == "UNDER_REVIEW" for stage in config.workflow.stages)
    if target_status == "READY_TO_FILE" or target_status == "COMPLETED" and has_review:
        review = latest_review(db, item)
        if not review or review.decision != "APPROVED":
            raise HTTPException(409, "REVIEW_APPROVAL_REQUIRED: approve the latest review first")
        if edge and edge.required_approval or target_status == "COMPLETED" and _approval_required(config):
            approval = latest_approval(db, item, review.id)
            if not approval or approval.decision != "APPROVED":
                raise HTTPException(409, "EXPLICIT_APPROVAL_REQUIRED: an approval record is required")
        _required_controls(db, item, snapshot)
    elif target_status == "COMPLETED":
        if edge and edge.required_approval:
            approval = latest_approval(db, item)
            if not approval or approval.decision != "APPROVED":
                raise HTTPException(409, "EXPLICIT_APPROVAL_REQUIRED: an approval record is required")
        _required_controls(db, item, snapshot)

    if target_status == "FILED":
        if not submission_reference or not proof_document_id:
            raise HTTPException(422, "FILING_REFERENCE_AND_PROOF_REQUIRED")
        normalized = (proof_type or "").upper()
        if normalized not in config.workflow.filing_proof_types:
            raise HTTPException(422, "FILING_PROOF_TYPE_INVALID: choose a type from the frozen workflow")

    requires_filing = any(stage.state == "FILED" for stage in config.workflow.stages)
    if target_status == "COMPLETED" and requires_filing:
        filing = db.scalar(select(Submission).where(
            Submission.tenant_id == item.tenant_id,
            Submission.compliance_id == item.id,
            Submission.acknowledgement_ref != "",
            Submission.proof_version_id.is_not(None),
        ).order_by(Submission.submitted_at.desc()))
        if not filing:
            raise HTTPException(422, "IMMUTABLE_FILING_PROOF_REQUIRED")


def after_transition(db, item: Compliance, previous: str, target_status: str) -> None:
    snapshot, config = frozen_configuration(db, item)
    if not snapshot or not config or target_status == "UNDER_REVIEW":
        return
    recipients = _owner_ids(db, item)
    events = {
        "CHANGES_REQUESTED": ("CHANGES_REQUESTED", f"{item.code} changes requested", "Changes were requested before this compliance can proceed."),
        "READY_TO_FILE": ("READY_TO_FILE", f"{item.code} ready to file", "Review and approval controls are complete; this compliance is ready to file."),
        "FILED": ("COMPLIANCE_FILED", f"{item.code} filed", "The filing reference and immutable proof were recorded."),
        "COMPLETED": ("COMPLIANCE_COMPLETED", f"{item.code} completed", "All frozen workflow controls were satisfied."),
    }
    if previous == "COMPLETED":
        events[target_status] = ("COMPLIANCE_REOPENED", f"{item.code} reopened", "The completed compliance was reopened with a recorded reason.")
    event = events.get(target_status)
    if event:
        _notify(db, item, event[0], event[1], event[2], user_ids=recipients,
                recipient_role=config.responsibility.owner_role if not recipients else None)


def decide_review(db, item: Compliance, review: ComplianceReview, decision: str, comments: str) -> None:
    _, config = frozen_configuration(db, item)
    if not config:
        raise HTTPException(409, "A frozen template is required for workflow review")
    if review.tenant_id != item.tenant_id or review.compliance_id != item.id:
        raise HTTPException(404, "Review not found")
    if review.decision != "PENDING" or item.status != "UNDER_REVIEW":
        raise HTTPException(409, "Only the pending review can be decided")
    actor_id = _actor_id(db)
    _require_role(db, item, config.responsibility.reviewer_role, "The configured reviewer must decide this review")
    if config.responsibility.separate_preparer_reviewer and review.submitted_by == actor_id:
        raise HTTPException(403, "SEPARATION_OF_DUTIES: preparer and reviewer must differ")
    review.decision = decision
    review.reviewer_id = actor_id
    review.reviewed_at = utcnow()
    review.comments = comments
    _audit(db, item, "REVIEW_DECIDED", f"Review revision {review.revision}: {decision}; {comments}")
    if decision == "CHANGES_REQUESTED":
        previous = item.status
        item.status = "CHANGES_REQUESTED"
        item.progress = max(item.progress, 60)
        item.updated_at = utcnow()
        _audit(db, item, "STATUS_CHANGED", f"Moved {item.title}: {previous} -> CHANGES_REQUESTED; reason: {comments}")
        _notify(db, item, "CHANGES_REQUESTED", f"{item.code} changes requested", comments, user_ids=_owner_ids(db, item))
        return
    next_edge = next((edge for edge in config.workflow.transitions
                      if edge.from_state == "UNDER_REVIEW" and edge.to_state == "READY_TO_FILE"), None)
    if next_edge and next_edge.required_approval:
        approval = ComplianceApproval(
            tenant_id=item.tenant_id,
            organization_id=item.organization_id,
            compliance_id=item.id,
            review_id=review.id,
            revision=(db.scalar(select(func.max(ComplianceApproval.revision)).where(
                ComplianceApproval.compliance_id == item.id,
                ComplianceApproval.tenant_id == item.tenant_id,
            )) or 0) + 1,
            target_status="READY_TO_FILE",
            requested_by=actor_id,
        )
        db.add(approval)
        db.flush()
        _audit(db, item, "APPROVAL_REQUESTED", f"Approval requested for review revision {review.revision}")
        _notify(db, item, "APPROVAL_REQUESTED", f"{item.code} approval requested",
                "The approved review now requires explicit approval.", recipient_role=config.responsibility.approver_role)
    else:
        _notify(db, item, "REVIEW_APPROVED", f"{item.code} review approved",
                comments or "The latest review was approved.", user_ids=_owner_ids(db, item))


def decide_approval(db, item: Compliance, approval: ComplianceApproval, decision: str, comments: str) -> None:
    _, config = frozen_configuration(db, item)
    if not config:
        raise HTTPException(409, "A frozen template is required for workflow approval")
    if approval.tenant_id != item.tenant_id or approval.compliance_id != item.id:
        raise HTTPException(404, "Approval not found")
    if approval.decision != "PENDING":
        raise HTTPException(409, "Only the pending approval can be decided")
    if item.status != "UNDER_REVIEW":
        edge = next((candidate for candidate in config.workflow.transitions
                     if candidate.from_state == item.status and candidate.to_state == approval.target_status), None)
        if not edge or not edge.required_approval:
            raise HTTPException(409, "The approved transition is no longer available")
    actor_id = _actor_id(db)
    _require_role(db, item, config.responsibility.approver_role, "The configured approver must decide this approval")
    review = db.get(ComplianceReview, approval.review_id) if approval.review_id else None
    if config.responsibility.separate_reviewer_approver and review and review.reviewer_id == actor_id:
        raise HTTPException(403, "SEPARATION_OF_DUTIES: reviewer and approver must differ")
    approval.decision = decision
    approval.approver_id = actor_id
    approval.decided_at = utcnow()
    approval.comments = comments
    _audit(db, item, "APPROVAL_DECIDED", f"Approval for review revision {review.revision if review else 'standalone'}: {decision}; {comments}")
    if decision == "CHANGES_REQUESTED":
        previous = item.status
        item.status = "CHANGES_REQUESTED"
        item.progress = max(item.progress, 60)
        item.updated_at = utcnow()
        _audit(db, item, "STATUS_CHANGED", f"Moved {item.title}: {previous} -> CHANGES_REQUESTED; reason: {comments}")
        _notify(db, item, "CHANGES_REQUESTED", f"{item.code} changes requested", comments, user_ids=_owner_ids(db, item))
    else:
        _notify(db, item, "COMPLIANCE_APPROVED", f"{item.code} approved",
                comments or "The latest review received explicit approval.", user_ids=_owner_ids(db, item))


def records(db, item: Compliance) -> dict:
    reviews = db.scalars(select(ComplianceReview).where(
        ComplianceReview.tenant_id == item.tenant_id,
        ComplianceReview.compliance_id == item.id,
    ).order_by(ComplianceReview.revision.desc())).all()
    approvals = db.scalars(select(ComplianceApproval).where(
        ComplianceApproval.tenant_id == item.tenant_id,
        ComplianceApproval.compliance_id == item.id,
    ).order_by(ComplianceApproval.requested_at.desc())).all()
    return {
        "reviews": [{
            "id": row.id, "revision": row.revision, "submitted_by": row.submitted_by,
            "submitted_at": row.submitted_at, "reviewer_id": row.reviewer_id,
            "reviewed_at": row.reviewed_at, "decision": row.decision, "comments": row.comments,
        } for row in reviews],
        "approvals": [{
            "id": row.id, "review_id": row.review_id, "revision": row.revision, "target_status": row.target_status,
            "requested_by": row.requested_by, "requested_at": row.requested_at,
            "approver_id": row.approver_id, "decided_at": row.decided_at,
            "decision": row.decision, "comments": row.comments,
        } for row in approvals],
    }


def request_approval(db, item: Compliance, target_status: str) -> ComplianceApproval:
    """Request an explicit approval for a frozen required-approval edge."""
    _, config = frozen_configuration(db, item)
    if not config:
        raise HTTPException(409, "A frozen template is required for workflow approval")
    source = "IN_PROGRESS" if item.status == "OVERDUE" else item.status
    edge = next((candidate for candidate in config.workflow.transitions
                 if candidate.from_state == source and candidate.to_state == target_status), None)
    if not edge or not edge.required_approval:
        raise HTTPException(409, "The requested transition does not require approval")
    roles = actor_roles(db, item.tenant_id, item.organization_id)
    if not roles.intersection(edge.allowed_roles):
        raise HTTPException(403, "Your organization role cannot request this approval")
    current_review = latest_review(db, item)
    if current_review and current_review.decision != "APPROVED":
        raise HTTPException(409, "Approve the latest review before requesting approval")
    current = latest_approval(db, item, current_review.id if current_review else None)
    if current and current.decision == "PENDING":
        return current
    revision = (db.scalar(select(func.max(ComplianceApproval.revision)).where(
        ComplianceApproval.compliance_id == item.id,
        ComplianceApproval.tenant_id == item.tenant_id,
    )) or 0) + 1
    approval = ComplianceApproval(
        tenant_id=item.tenant_id,
        organization_id=item.organization_id,
        compliance_id=item.id,
        review_id=current_review.id if current_review else None,
        revision=revision,
        target_status=target_status,
        requested_by=_actor_id(db),
    )
    db.add(approval)
    db.flush()
    _audit(db, item, "APPROVAL_REQUESTED", f"Approval requested for {source} -> {target_status}")
    _notify(db, item, "APPROVAL_REQUESTED", f"{item.code} approval requested",
            f"Explicit approval is required before {target_status}.", recipient_role=config.responsibility.approver_role)
    return approval
