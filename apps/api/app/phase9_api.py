"""Organization-scoped Phase 9 review and approval APIs."""
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import Field
from sqlalchemy import select

from .auth import CurrentUser
from .models import Compliance
from .organization_access import require_organization_access
from .organization_profile import DB, Strict, Tenant
from .phase9_models import ComplianceApproval, ComplianceReview
from .phase9_service import decide_approval, decide_review, records, request_approval

router = APIRouter(prefix="/api/v1", tags=["Compliance workflow"])


class DecisionInput(Strict):
    decision: Literal["APPROVED", "CHANGES_REQUESTED"]
    comments: str = Field(min_length=3, max_length=2000)


class ApprovalRequestInput(Strict):
    target_status: Literal["READY_TO_FILE", "FILED", "COMPLETED"]


def owned(db, tenant_id: str, compliance_id: str, actor_id: str, *, write: bool = False) -> Compliance:
    item = db.scalar(select(Compliance).where(
        Compliance.id == compliance_id,
        Compliance.tenant_id == tenant_id,
    ))
    if not item:
        raise HTTPException(404, "Compliance not found")
    require_organization_access(db, tenant_id, item.organization_id, write=write, user_id=actor_id)
    return item


@router.get("/compliances/{compliance_id}/workflow-records")
def workflow_records(compliance_id: str, db: DB, tenant: Tenant, actor: CurrentUser):
    return records(db, owned(db, tenant, compliance_id, actor.id))


@router.post("/compliances/{compliance_id}/reviews/{review_id}/decision")
def review_decision(compliance_id: str, review_id: str, payload: DecisionInput,
                    db: DB, tenant: Tenant, actor: CurrentUser):
    item = owned(db, tenant, compliance_id, actor.id, write=True)
    review = db.get(ComplianceReview, review_id)
    if not review or review.tenant_id != tenant or review.compliance_id != item.id:
        raise HTTPException(404, "Review not found")
    decide_review(db, item, review, payload.decision, payload.comments)
    db.commit()
    return records(db, item)


@router.post("/compliances/{compliance_id}/approvals/{approval_id}/decision")
def approval_decision(compliance_id: str, approval_id: str, payload: DecisionInput,
                      db: DB, tenant: Tenant, actor: CurrentUser):
    item = owned(db, tenant, compliance_id, actor.id, write=True)
    approval = db.get(ComplianceApproval, approval_id)
    if not approval or approval.tenant_id != tenant or approval.compliance_id != item.id:
        raise HTTPException(404, "Approval not found")
    decide_approval(db, item, approval, payload.decision, payload.comments)
    db.commit()
    return records(db, item)


@router.post("/compliances/{compliance_id}/approvals/request", status_code=201)
def approval_request(compliance_id: str, payload: ApprovalRequestInput,
                     db: DB, tenant: Tenant, actor: CurrentUser):
    item = owned(db, tenant, compliance_id, actor.id, write=True)
    request_approval(db, item, payload.target_status)
    db.commit()
    return records(db, item)
