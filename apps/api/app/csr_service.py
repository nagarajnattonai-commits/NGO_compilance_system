"""Authorization and domain services for CSR partner operations."""
from __future__ import annotations

import json
from datetime import date, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import and_, case, func, or_, select

from .csr_models import (CsrChecklistTemplate, CsrChecklistTemplateItem, CsrDueDiligenceItem,
                         CsrDueDiligenceReview, CsrEvidenceLink, CsrPartnerCollaborator,
                         CsrPartnerRelationship, CsrProject, CsrTaskLink)
from .document_intelligence_models import DocumentIntelligenceRun, ExtractedDocumentFact
from .document_models import DocumentBlob
from .features import can_use_feature
from .models import AuditEvent, Compliance, Document, Notification, Organization, Task, User, utcnow
from .organization_access import accessible_organization_ids, organization_access_role, require_organization_access, workspace_role
from .organization_models import OrganizationDetails, OrganizationRegistration

FEATURE = "csr_partner_management"
PARTNER_STATES = {"PROSPECTIVE", "UNDER_REVIEW", "APPROVED", "ACTIVE", "ON_HOLD", "INACTIVE"}
PROJECT_STATES = {"DRAFT", "PLANNED", "ACTIVE", "ON_HOLD", "COMPLETED", "CANCELLED"}
REVIEW_STATES = {"NOT_STARTED", "IN_PROGRESS", "SUBMITTED", "UNDER_REVIEW", "CHANGES_REQUESTED",
                 "APPROVED", "REJECTED", "NOT_APPLICABLE", "REVIEW_REQUIRED"}
NGO_ITEM_TRANSITIONS = {
    "NOT_STARTED": {"IN_PROGRESS", "SUBMITTED", "NOT_APPLICABLE"},
    "IN_PROGRESS": {"SUBMITTED", "NOT_APPLICABLE"},
    "CHANGES_REQUESTED": {"IN_PROGRESS", "SUBMITTED"},
    "REVIEW_REQUIRED": {"IN_PROGRESS", "SUBMITTED"},
}
CORPORATE_ITEM_TRANSITIONS = {
    "NOT_STARTED": {"IN_PROGRESS", "NOT_APPLICABLE"},
    "IN_PROGRESS": {"SUBMITTED", "NOT_APPLICABLE"},
    "SUBMITTED": {"UNDER_REVIEW", "CHANGES_REQUESTED"},
    "UNDER_REVIEW": {"APPROVED", "REJECTED", "CHANGES_REQUESTED"},
    "CHANGES_REQUESTED": {"UNDER_REVIEW", "REJECTED"},
    "REVIEW_REQUIRED": {"UNDER_REVIEW", "CHANGES_REQUESTED"},
    "APPROVED": {"REVIEW_REQUIRED"},
    "REJECTED": {"UNDER_REVIEW"},
}


def require_csr(db, tenant_id: str, user) -> None:
    if getattr(user, "_admin_audience", False):
        raise HTTPException(403, "CSR workspaces are unavailable to platform administrator sessions")
    if not can_use_feature(db, tenant_id, FEATURE):
        raise HTTPException(403, "CSR_PARTNER_MANAGEMENT_ENTITLEMENT_REQUIRED")


def _audit(db, tenant_id: str, user, action: str, entity_type: str, entity_id: str, summary: str) -> None:
    db.add(AuditEvent(tenant_id=tenant_id, actor_name=user.name, action=action,
                      entity_type=entity_type, entity_id=entity_id, summary=summary[:280]))


def collaborator_relationship_ids(db, tenant_id: str, user_id: str) -> set[str]:
    return set(db.scalars(select(CsrPartnerCollaborator.relationship_id).where(
        CsrPartnerCollaborator.tenant_id == tenant_id,
        CsrPartnerCollaborator.user_id == user_id,
        CsrPartnerCollaborator.active.is_(True),
    )).all())


def csr_scope(db, tenant_id: str, user) -> tuple[set[str] | None, bool]:
    require_csr(db, tenant_id, user)
    collaborations = collaborator_relationship_ids(db, tenant_id, user.id)
    if collaborations and user.role != "ADMIN":
        return collaborations, True
    permitted_orgs = accessible_organization_ids(db, tenant_id, user.id)
    query = select(CsrPartnerRelationship.id).where(CsrPartnerRelationship.tenant_id == tenant_id)
    if permitted_orgs is not None:
        query = query.where(CsrPartnerRelationship.organization_id.in_(permitted_orgs))
    return set(db.scalars(query).all()), False


def relationship(db, tenant_id: str, user, relationship_id: str, *, write: bool = False,
                 corporate_only: bool = False) -> tuple[CsrPartnerRelationship, bool]:
    allowed, collaborator = csr_scope(db, tenant_id, user)
    row = db.scalar(select(CsrPartnerRelationship).where(
        CsrPartnerRelationship.id == relationship_id,
        CsrPartnerRelationship.tenant_id == tenant_id,
    ))
    if not row or allowed is not None and row.id not in allowed:
        raise HTTPException(404, "CSR partner relationship not found")
    if corporate_only and collaborator:
        raise HTTPException(403, "Corporate workspace access is required")
    if write:
        if user.role == "VIEWER":
            raise HTTPException(403, "Read-only accounts cannot modify CSR records")
        require_organization_access(db, tenant_id, row.organization_id, write=True, user_id=user.id)
    return row, collaborator


def _owner_names(db, ids: set[str]) -> dict[str, str]:
    return {row.id: row.name for row in db.scalars(select(User).where(User.id.in_(ids))).all()} if ids else {}


def _can_write(db, tenant_id: str, user, organization_id: str) -> bool:
    return user.role != "VIEWER" and organization_access_role(
        db, tenant_id, organization_id, user.id) in {"CONTRIBUTOR", "MANAGER"}


def partner_directory(db, tenant_id: str, user, query: str = "") -> list[dict]:
    allowed, collaborator = csr_scope(db, tenant_id, user)
    statement = select(CsrPartnerRelationship, Organization).join(
        Organization, Organization.id == CsrPartnerRelationship.organization_id,
    ).where(CsrPartnerRelationship.tenant_id == tenant_id, Organization.tenant_id == tenant_id)
    if allowed is not None:
        statement = statement.where(CsrPartnerRelationship.id.in_(allowed))
    if query.strip():
        term = query.strip().lower()
        statement = statement.where(or_(func.lower(Organization.name).contains(term, autoescape=True),
                                        func.lower(Organization.legal_type).contains(term, autoescape=True)))
    rows = db.execute(statement.order_by(Organization.name).limit(200)).all()
    relationship_ids = [row.id for row, _ in rows]
    organization_ids = [org.id for _, org in rows]
    details = {row.organization_id: json.loads(row.facts or "{}") for row in db.scalars(select(OrganizationDetails).where(
        OrganizationDetails.tenant_id == tenant_id, OrganizationDetails.organization_id.in_(organization_ids))).all()} if organization_ids else {}
    registrations = db.scalars(select(OrganizationRegistration).where(
        OrganizationRegistration.tenant_id == tenant_id,
        OrganizationRegistration.organization_id.in_(organization_ids))).all() if organization_ids else []
    today, horizon = date.today(), date.today() + timedelta(days=90)
    expiring_regs: dict[str, int] = {}
    for registration in registrations:
        if registration.expiry_date and registration.expiry_date <= horizon:
            expiring_regs[registration.organization_id] = expiring_regs.get(registration.organization_id, 0) + 1
    project_counts = dict(db.execute(select(CsrProject.relationship_id, func.count(CsrProject.id)).where(
        CsrProject.tenant_id == tenant_id, CsrProject.relationship_id.in_(relationship_ids),
        CsrProject.status.in_(("PLANNED", "ACTIVE", "ON_HOLD"))).group_by(CsrProject.relationship_id)).all()) if relationship_ids else {}
    review_counts = dict(db.execute(select(CsrDueDiligenceReview.relationship_id, func.count(CsrDueDiligenceReview.id)).where(
        CsrDueDiligenceReview.tenant_id == tenant_id, CsrDueDiligenceReview.relationship_id.in_(relationship_ids),
        CsrDueDiligenceReview.status.in_(("IN_PROGRESS", "SUBMITTED", "UNDER_REVIEW", "CHANGES_REQUESTED", "REVIEW_REQUIRED"))).group_by(CsrDueDiligenceReview.relationship_id)).all()) if relationship_ids else {}
    compliance_rows = db.execute(select(
        Compliance.organization_id, func.count(Compliance.id),
        func.sum(case((Compliance.status.in_(("FILED", "COMPLETED", "CANCELLED", "NOT_APPLICABLE")), 0), else_=1)),
        func.sum(case((and_(Compliance.statutory_deadline < today,
                           Compliance.status.not_in(("FILED", "COMPLETED", "CANCELLED", "NOT_APPLICABLE"))), 1), else_=0)),
    ).where(Compliance.tenant_id == tenant_id, Compliance.organization_id.in_(organization_ids)
    ).group_by(Compliance.organization_id)).all() if organization_ids else []
    compliance_summary = {organization_id: {"total": total, "open": open_count or 0, "overdue": overdue or 0}
                          for organization_id, total, open_count, overdue in compliance_rows}
    project_activity = dict(db.execute(select(CsrProject.relationship_id, func.max(CsrProject.updated_at)).where(
        CsrProject.tenant_id == tenant_id, CsrProject.relationship_id.in_(relationship_ids)
    ).group_by(CsrProject.relationship_id)).all()) if relationship_ids else {}
    review_activity = dict(db.execute(select(CsrDueDiligenceReview.relationship_id, func.max(CsrDueDiligenceReview.updated_at)).where(
        CsrDueDiligenceReview.tenant_id == tenant_id, CsrDueDiligenceReview.relationship_id.in_(relationship_ids)
    ).group_by(CsrDueDiligenceReview.relationship_id)).all()) if relationship_ids else {}
    owner_ids = {row.owner_user_id for row, _ in rows if row.owner_user_id}
    owners = _owner_names(db, owner_ids)
    items = []
    for row, org in rows:
        facts = details.get(org.id, {})
        populated = sum(bool(value) for value in (org.name, org.legal_type, org.registration_number, org.city,
                                                   org.pan, facts.get("contact_name"), facts.get("contact_email")))
        item = {
            "id": row.id, "organization_id": org.id, "organization_name": org.name,
            "organization_type": org.legal_type, "city": org.city, "contact_name": facts.get("contact_name", ""),
            "contact_email": facts.get("contact_email", ""), "profile_completeness": round(populated / 7 * 100),
            "status": row.status, "review_status": row.review_status, "onboarding_date": row.onboarding_date,
            "owner_user_id": row.owner_user_id, "owner_name": owners.get(row.owner_user_id, ""),
            "expiring_registrations": expiring_regs.get(org.id, 0), "open_reviews": review_counts.get(row.id, 0),
            "active_projects": project_counts.get(row.id, 0), "collaboration_enabled": row.collaboration_enabled,
            "shared_notes": row.shared_notes,
            "can_manage": not collaborator and _can_write(db, tenant_id, user, org.id),
            "can_grant_collaborators": not collaborator and user.role == "ADMIN",
            "compliance_summary": compliance_summary.get(org.id, {"total": 0, "open": 0, "overdue": 0}),
            "last_activity_at": max((value for value in (row.updated_at, project_activity.get(row.id),
                                                          review_activity.get(row.id)) if value is not None),
                                    key=lambda value: value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value),
            "requires_attention": bool(review_counts.get(row.id) or expiring_regs.get(org.id)),
        }
        if not collaborator:
            item["internal_notes"] = row.internal_notes
        items.append(item)
    return items


def dashboard(db, tenant_id: str, user) -> dict:
    _, collaborator = csr_scope(db, tenant_id, user)
    if collaborator:
        raise HTTPException(403, "NGO collaborators cannot access corporate portfolio analytics")
    partners = partner_directory(db, tenant_id, user)
    allowed = {row["id"] for row in partners}
    statuses = {state: sum(row["status"] == state for row in partners) for state in PARTNER_STATES}
    incomplete = db.scalar(select(func.count(CsrDueDiligenceItem.id)).join(
        CsrDueDiligenceReview, CsrDueDiligenceReview.id == CsrDueDiligenceItem.review_id).where(
        CsrDueDiligenceItem.tenant_id == tenant_id, CsrDueDiligenceReview.relationship_id.in_(allowed),
        CsrDueDiligenceItem.required.is_(True), CsrDueDiligenceItem.status.not_in(("APPROVED", "NOT_APPLICABLE")))) or 0 if allowed else 0
    changes = db.scalar(select(func.count(CsrDueDiligenceItem.id)).join(
        CsrDueDiligenceReview, CsrDueDiligenceReview.id == CsrDueDiligenceItem.review_id).where(
        CsrDueDiligenceItem.tenant_id == tenant_id, CsrDueDiligenceReview.relationship_id.in_(allowed),
        CsrDueDiligenceItem.status == "CHANGES_REQUESTED")) or 0 if allowed else 0
    active_projects = db.scalar(select(func.count(CsrProject.id)).where(
        CsrProject.tenant_id == tenant_id, CsrProject.relationship_id.in_(allowed), CsrProject.status == "ACTIVE")) or 0 if allowed else 0
    return {"summary": {"total_partners": len(partners), "prospective": statuses["PROSPECTIVE"],
                        "under_review": statuses["UNDER_REVIEW"], "active_partners": statuses["ACTIVE"],
                        "partners_requiring_attention": sum(row["requires_attention"] for row in partners),
                        "incomplete_due_diligence": incomplete, "changes_requested": changes,
                        "expiring_evidence": sum(row["expiring_registrations"] for row in partners),
                        "active_projects": active_projects}, "partners": partners}


def create_relationship(db, tenant_id: str, user, organization_id: str, values: dict) -> dict:
    require_csr(db, tenant_id, user)
    if user.role != "ADMIN":
        raise HTTPException(403, "Workspace administrator access is required")
    org = db.scalar(select(Organization).where(Organization.id == organization_id, Organization.tenant_id == tenant_id))
    if not org:
        raise HTTPException(404, "Organization not found")
    require_organization_access(db, tenant_id, org.id, write=True, user_id=user.id)
    owner_user_id = values.get("owner_user_id")
    if owner_user_id and not workspace_role(db, tenant_id, owner_user_id):
        raise HTTPException(422, "Owner must have active workspace access")
    if db.scalar(select(CsrPartnerRelationship.id).where(
        CsrPartnerRelationship.tenant_id == tenant_id, CsrPartnerRelationship.organization_id == org.id)):
        raise HTTPException(409, "Organization is already a CSR partner")
    row = CsrPartnerRelationship(tenant_id=tenant_id, organization_id=org.id, created_by=user.id, **values)
    db.add(row); db.flush()
    _audit(db, tenant_id, user, "CSR_PARTNER_CREATED", "CsrPartnerRelationship", row.id,
           f"Added organization {org.id} as a CSR partner")
    db.commit(); db.refresh(row)
    return next(item for item in partner_directory(db, tenant_id, user) if item["id"] == row.id)


def update_relationship(db, tenant_id: str, user, relationship_id: str, values: dict) -> dict:
    row, _ = relationship(db, tenant_id, user, relationship_id, write=True, corporate_only=True)
    owner_user_id = values.get("owner_user_id")
    if owner_user_id and not workspace_role(db, tenant_id, owner_user_id):
        raise HTTPException(422, "Owner must have active workspace access")
    for key, value in values.items():
        if value is not None:
            setattr(row, key, value)
    row.updated_at = utcnow()
    _audit(db, tenant_id, user, "CSR_PARTNER_UPDATED", "CsrPartnerRelationship", row.id,
           "Updated CSR partner relationship metadata")
    db.commit()
    return next(item for item in partner_directory(db, tenant_id, user) if item["id"] == row.id)


def add_collaborator(db, tenant_id: str, user, relationship_id: str, user_id: str) -> dict:
    row, _ = relationship(db, tenant_id, user, relationship_id, write=True, corporate_only=True)
    if user.role != "ADMIN":
        raise HTTPException(403, "Workspace administrator access is required")
    candidate = db.get(User, user_id)
    if not candidate or not workspace_role(db, tenant_id, user_id):
        raise HTTPException(422, "Collaborator must have active workspace access")
    require_organization_access(db, tenant_id, row.organization_id, user_id=user_id)
    link = db.scalar(select(CsrPartnerCollaborator).where(
        CsrPartnerCollaborator.relationship_id == row.id, CsrPartnerCollaborator.user_id == user_id))
    if not link:
        link = CsrPartnerCollaborator(tenant_id=tenant_id, organization_id=row.organization_id,
                                      relationship_id=row.id, user_id=user_id, invited_by=user.id)
        db.add(link)
    link.active = True; row.collaboration_enabled = True; row.updated_at = utcnow()
    _audit(db, tenant_id, user, "CSR_COLLABORATOR_GRANTED", "CsrPartnerRelationship", row.id,
           f"Granted explicitly shared CSR access to user {user_id}")
    db.commit()
    return {"id": link.id, "user_id": link.user_id, "relationship_id": link.relationship_id, "active": link.active}


def project_data(row: CsrProject, collaborator: bool) -> dict:
    data = {key: getattr(row, key) for key in ("id", "relationship_id", "organization_id", "name", "code",
        "description", "status", "start_date", "end_date", "owner_user_id", "ngo_contact", "approved_budget",
        "category", "location", "shared_with_ngo", "created_at", "updated_at")}
    if not collaborator:
        data["internal_notes"] = row.internal_notes
    return data


def projects(db, tenant_id: str, user, relationship_id: str | None = None) -> list[dict]:
    allowed, collaborator = csr_scope(db, tenant_id, user)
    statement = select(CsrProject).where(CsrProject.tenant_id == tenant_id)
    if allowed is not None: statement = statement.where(CsrProject.relationship_id.in_(allowed))
    if relationship_id:
        relationship(db, tenant_id, user, relationship_id)
        statement = statement.where(CsrProject.relationship_id == relationship_id)
    if collaborator: statement = statement.where(CsrProject.shared_with_ngo.is_(True))
    return [project_data(row, collaborator) for row in db.scalars(statement.order_by(CsrProject.updated_at.desc())).all()]


def create_project(db, tenant_id: str, user, relationship_id: str, values: dict) -> dict:
    partner, _ = relationship(db, tenant_id, user, relationship_id, write=True, corporate_only=True)
    row = CsrProject(tenant_id=tenant_id, relationship_id=partner.id, organization_id=partner.organization_id,
                     created_by=user.id, **values)
    db.add(row); db.flush()
    _audit(db, tenant_id, user, "CSR_PROJECT_CREATED", "CsrProject", row.id, f"Created CSR project {row.code}")
    db.commit(); db.refresh(row)
    return project_data(row, False)


def update_project(db, tenant_id: str, user, project_id: str, values: dict) -> dict:
    row = db.scalar(select(CsrProject).where(CsrProject.id == project_id, CsrProject.tenant_id == tenant_id))
    if not row:
        raise HTTPException(404, "CSR project not found")
    relationship(db, tenant_id, user, row.relationship_id, write=True, corporate_only=True)
    for key, value in values.items():
        if value is not None: setattr(row, key, value)
    if row.start_date and row.end_date and row.end_date < row.start_date:
        raise HTTPException(422, "Project end date cannot precede start date")
    row.updated_at = utcnow()
    _audit(db, tenant_id, user, "CSR_PROJECT_UPDATED", "CsrProject", row.id, "Updated CSR project")
    db.commit(); return project_data(row, False)


def template_data(db, row: CsrChecklistTemplate) -> dict:
    items = db.scalars(select(CsrChecklistTemplateItem).where(
        CsrChecklistTemplateItem.template_id == row.id,
        CsrChecklistTemplateItem.tenant_id == row.tenant_id).order_by(CsrChecklistTemplateItem.position)).all()
    return {"id": row.id, "name": row.name, "description": row.description, "version": row.version,
            "enabled": row.enabled, "created_at": row.created_at, "updated_at": row.updated_at,
            "items": [{key: getattr(item, key) for key in ("id", "position", "category", "title", "description",
                "requirement_type", "required", "registration_kind", "expiry_monitoring", "share_with_ngo")} for item in items]}


def templates(db, tenant_id: str, user) -> list[dict]:
    _, collaborator = csr_scope(db, tenant_id, user)
    if collaborator: raise HTTPException(403, "NGO collaborators cannot access checklist templates")
    return [template_data(db, row) for row in db.scalars(select(CsrChecklistTemplate).where(
        CsrChecklistTemplate.tenant_id == tenant_id).order_by(CsrChecklistTemplate.name, CsrChecklistTemplate.version.desc())).all()]


def create_template(db, tenant_id: str, user, values: dict, items: list[dict]) -> dict:
    require_csr(db, tenant_id, user)
    if user.role != "ADMIN" or collaborator_relationship_ids(db, tenant_id, user.id):
        raise HTTPException(403, "Workspace administrator access is required")
    row = CsrChecklistTemplate(tenant_id=tenant_id, created_by=user.id, **values)
    db.add(row); db.flush()
    for position, value in enumerate(items, 1):
        db.add(CsrChecklistTemplateItem(tenant_id=tenant_id, template_id=row.id, position=position, **value))
    _audit(db, tenant_id, user, "CSR_CHECKLIST_TEMPLATE_CREATED", "CsrChecklistTemplate", row.id,
           f"Created configurable checklist template with {len(items)} item(s)")
    db.commit(); return template_data(db, row)


def create_review(db, tenant_id: str, user, relationship_id: str, template_id: str,
                  project_id: str | None, title: str, due_date: date | None, shared: bool) -> dict:
    partner, _ = relationship(db, tenant_id, user, relationship_id, write=True, corporate_only=True)
    template = db.scalar(select(CsrChecklistTemplate).where(
        CsrChecklistTemplate.id == template_id, CsrChecklistTemplate.tenant_id == tenant_id,
        CsrChecklistTemplate.enabled.is_(True)))
    if not template: raise HTTPException(404, "Checklist template not found")
    if project_id and not db.scalar(select(CsrProject.id).where(CsrProject.id == project_id,
        CsrProject.tenant_id == tenant_id, CsrProject.relationship_id == partner.id)):
        raise HTTPException(404, "CSR project not found for this partner")
    row = CsrDueDiligenceReview(tenant_id=tenant_id, relationship_id=partner.id,
        organization_id=partner.organization_id, project_id=project_id, template_id=template.id,
        template_version=template.version, title=title, due_date=due_date, shared_with_ngo=shared, created_by=user.id)
    db.add(row); db.flush()
    source_items = db.scalars(select(CsrChecklistTemplateItem).where(
        CsrChecklistTemplateItem.template_id == template.id,
        CsrChecklistTemplateItem.tenant_id == tenant_id).order_by(CsrChecklistTemplateItem.position)).all()
    for source in source_items:
        db.add(CsrDueDiligenceItem(tenant_id=tenant_id, organization_id=partner.organization_id,
            review_id=row.id, template_item_id=source.id, position=source.position, category=source.category,
            title=source.title, description=source.description, requirement_type=source.requirement_type,
            required=source.required, registration_kind=source.registration_kind,
            expiry_monitoring=source.expiry_monitoring, shared_with_ngo=source.share_with_ngo))
    partner.review_status = "IN_PROGRESS"; partner.updated_at = utcnow()
    _audit(db, tenant_id, user, "CSR_REVIEW_CREATED", "CsrDueDiligenceReview", row.id,
           f"Created review from template {template.id} version {template.version}")
    db.commit(); return review_data(db, tenant_id, user, row.id)


def _review(db, tenant_id: str, user, review_id: str) -> tuple[CsrDueDiligenceReview, bool]:
    row = db.scalar(select(CsrDueDiligenceReview).where(
        CsrDueDiligenceReview.id == review_id, CsrDueDiligenceReview.tenant_id == tenant_id))
    if not row: raise HTTPException(404, "Due diligence review not found")
    _, collaborator = relationship(db, tenant_id, user, row.relationship_id)
    if collaborator and not row.shared_with_ngo: raise HTTPException(404, "Due diligence review not found")
    return row, collaborator


def review_data(db, tenant_id: str, user, review_id: str) -> dict:
    row, collaborator = _review(db, tenant_id, user, review_id)
    items = db.scalars(select(CsrDueDiligenceItem).where(
        CsrDueDiligenceItem.review_id == row.id, CsrDueDiligenceItem.tenant_id == tenant_id,
        *([CsrDueDiligenceItem.shared_with_ngo.is_(True)] if collaborator else [])).order_by(CsrDueDiligenceItem.position)).all()
    item_ids = [item.id for item in items]
    links = db.scalars(select(CsrEvidenceLink).where(CsrEvidenceLink.tenant_id == tenant_id,
        CsrEvidenceLink.item_id.in_(item_ids), CsrEvidenceLink.active.is_(True))).all() if item_ids else []
    blobs = {row.version_id: row for row in db.scalars(select(DocumentBlob).where(
        DocumentBlob.tenant_id == tenant_id, DocumentBlob.version_id.in_([link.version_id for link in links]))).all()} if links else {}
    docs = {row.id: row for row in db.scalars(select(Document).where(
        Document.tenant_id == tenant_id, Document.id.in_([link.document_id for link in links]))).all()} if links else {}
    version_ids = [link.version_id for link in links]
    runs = db.scalars(select(DocumentIntelligenceRun).where(
        DocumentIntelligenceRun.tenant_id == tenant_id,
        DocumentIntelligenceRun.version_id.in_(version_ids),
    ).order_by(DocumentIntelligenceRun.version_id, DocumentIntelligenceRun.attempt.desc())).all() if version_ids else []
    latest_runs = {}
    for run in runs:
        latest_runs.setdefault(run.version_id, run)
    facts_by_run: dict[str, list[ExtractedDocumentFact]] = {}
    run_ids = [run.id for run in latest_runs.values()]
    if run_ids:
        for fact in db.scalars(select(ExtractedDocumentFact).where(
            ExtractedDocumentFact.tenant_id == tenant_id,
            ExtractedDocumentFact.run_id.in_(run_ids),
        ).order_by(ExtractedDocumentFact.fact_type)).all():
            facts_by_run.setdefault(fact.run_id, []).append(fact)
    evidence: dict[str, list[dict]] = {}
    for link in links:
        blob, document = blobs.get(link.version_id), docs.get(link.document_id)
        if blob and document:
            run = latest_runs.get(blob.version_id)
            evidence.setdefault(link.item_id, []).append({"id": link.id, "document_id": document.id,
                "document_name": document.name, "version_id": blob.version_id, "version": blob.version_number,
                "expiry_at": blob.expiry_at, "expired": bool(blob.expiry_at and blob.expiry_at < date.today()),
                "intelligence": None if not run else {
                    "run_status": run.status, "proposed_document_type": run.proposed_document_type,
                    "classification_confidence": run.classification_confidence,
                    "facts": [{"type": fact.fact_type, "value": fact.reviewed_value or fact.proposed_value,
                               "status": fact.status, "confidence": fact.confidence,
                               "authoritative": fact.status == "APPLIED"}
                              for fact in facts_by_run.get(run.id, [])],
                    "notice": "Extracted values are proposals until a reviewer applies them.",
                }})
    task_links = db.execute(select(CsrTaskLink, Task).join(Task, Task.id == CsrTaskLink.task_id).where(
        CsrTaskLink.tenant_id == tenant_id, CsrTaskLink.item_id.in_(item_ids))).all() if item_ids else []
    tasks: dict[str, list[dict]] = {}
    for link, task in task_links:
        tasks.setdefault(link.item_id, []).append({"id": task.id, "title": task.title, "status": task.status,
                                                   "due_at": task.due_at, "priority": task.priority})
    history = db.scalars(select(AuditEvent).where(
        AuditEvent.tenant_id == tenant_id,
        or_(and_(AuditEvent.entity_type == "CsrDueDiligenceReview", AuditEvent.entity_id == row.id),
            and_(AuditEvent.entity_type == "CsrDueDiligenceItem", AuditEvent.entity_id.in_(item_ids))),
    ).order_by(AuditEvent.created_at.desc()).limit(200)).all() if item_ids else []
    item_output = []
    can_write = _can_write(db, tenant_id, user, row.organization_id)
    transitions = NGO_ITEM_TRANSITIONS if collaborator else CORPORATE_ITEM_TRANSITIONS
    for item in items:
        values = {key: getattr(item, key) for key in ("id", "position", "category", "title", "description",
            "requirement_type", "required", "registration_kind", "expiry_monitoring", "shared_with_ngo",
            "status", "reviewer_user_id", "response", "reviewer_comment", "expiry_at", "reviewed_at", "updated_at")}
        if not collaborator: values["internal_notes"] = item.internal_notes
        values["evidence"] = evidence.get(item.id, []); values["tasks"] = tasks.get(item.id, [])
        values["allowed_statuses"] = sorted({item.status} | transitions.get(item.status, set())) if can_write else []
        item_output.append(values)
    return {"id": row.id, "relationship_id": row.relationship_id, "organization_id": row.organization_id,
            "project_id": row.project_id, "template_id": row.template_id, "template_version": row.template_version,
            "title": row.title, "status": row.status, "reviewer_user_id": row.reviewer_user_id,
            "due_date": row.due_date, "shared_with_ngo": row.shared_with_ngo,
            "created_at": row.created_at, "submitted_at": row.submitted_at, "reviewed_at": row.reviewed_at,
            "updated_at": row.updated_at, "items": item_output, "collaborator_view": collaborator,
            "can_write": can_write,
            "history": [{"id": event.id, "action": event.action, "actor_name": event.actor_name,
                         "summary": event.summary, "created_at": event.created_at} for event in history],
            "disclaimer": "Operational due diligence status; not a legal compliance certification."}


def reviews(db, tenant_id: str, user, relationship_id: str | None = None) -> list[dict]:
    allowed, collaborator = csr_scope(db, tenant_id, user)
    query = select(CsrDueDiligenceReview).where(CsrDueDiligenceReview.tenant_id == tenant_id)
    if allowed is not None: query = query.where(CsrDueDiligenceReview.relationship_id.in_(allowed))
    if relationship_id:
        relationship(db, tenant_id, user, relationship_id)
        query = query.where(CsrDueDiligenceReview.relationship_id == relationship_id)
    if collaborator: query = query.where(CsrDueDiligenceReview.shared_with_ngo.is_(True))
    return [review_data(db, tenant_id, user, row.id) for row in db.scalars(query.order_by(CsrDueDiligenceReview.updated_at.desc()).limit(100)).all()]


def _notify(db, row: CsrDueDiligenceReview, *, event: str, title: str, message: str, user_ids: list[str]) -> None:
    if not user_ids: return
    from .notification_service import distribute_notification
    notification = Notification(tenant_id=row.tenant_id, title=title, message=message, kind="REVIEW")
    db.add(notification); db.flush()
    distribute_notification(db, notification, event_type=event, category="COMPLIANCE",
        organization_id=row.organization_id, entity_type="CsrDueDiligenceReview", entity_id=row.id,
        user_ids=list(dict.fromkeys(user_ids)), channels=("IN_APP", "EMAIL", "WHATSAPP"))


def update_item(db, tenant_id: str, user, item_id: str, status: str, response: str | None,
                reviewer_comment: str | None, internal_notes: str | None, expiry_at: date | None) -> dict:
    item = db.scalar(select(CsrDueDiligenceItem).where(
        CsrDueDiligenceItem.id == item_id, CsrDueDiligenceItem.tenant_id == tenant_id))
    if not item: raise HTTPException(404, "Due diligence item not found")
    review, collaborator = _review(db, tenant_id, user, item.review_id)
    if collaborator and not item.shared_with_ngo: raise HTTPException(404, "Due diligence item not found")
    if user.role == "VIEWER": raise HTTPException(403, "Read-only accounts cannot update reviews")
    require_organization_access(db, tenant_id, item.organization_id, write=True, user_id=user.id)
    transitions = NGO_ITEM_TRANSITIONS if collaborator else CORPORATE_ITEM_TRANSITIONS
    if status != item.status and status not in transitions.get(item.status, set()):
        raise HTTPException(409, f"Invalid due diligence transition: {item.status} -> {status}")
    if collaborator and (reviewer_comment is not None or internal_notes is not None or expiry_at is not None):
        raise HTTPException(403, "NGO collaborators cannot modify internal review fields")
    old = item.status; item.status = status
    if response is not None: item.response = response
    if reviewer_comment is not None: item.reviewer_comment = reviewer_comment
    if internal_notes is not None: item.internal_notes = internal_notes
    if expiry_at is not None: item.expiry_at = expiry_at
    if status in {"APPROVED", "REJECTED", "CHANGES_REQUESTED"}:
        item.reviewer_user_id = user.id; item.reviewed_at = utcnow()
    item.updated_at = utcnow()
    statuses = set(db.scalars(select(CsrDueDiligenceItem.status).where(
        CsrDueDiligenceItem.review_id == review.id, CsrDueDiligenceItem.id != item.id)).all()) | {status}
    review.status = "APPROVED" if statuses <= {"APPROVED", "NOT_APPLICABLE"} else "CHANGES_REQUESTED" if "CHANGES_REQUESTED" in statuses else "UNDER_REVIEW" if statuses & {"SUBMITTED", "UNDER_REVIEW"} else "IN_PROGRESS"
    if status == "SUBMITTED": review.submitted_at = utcnow()
    if review.status == "APPROVED": review.reviewed_at = utcnow()
    review.updated_at = utcnow()
    partner = db.get(CsrPartnerRelationship, review.relationship_id)
    if partner: partner.review_status = review.status; partner.updated_at = utcnow()
    _audit(db, tenant_id, user, "CSR_DUE_DILIGENCE_STATUS_CHANGED", "CsrDueDiligenceItem", item.id,
           f"Changed operational review item from {old} to {status}")
    recipient_ids = [review.reviewer_user_id] if collaborator and review.reviewer_user_id else list(db.scalars(select(CsrPartnerCollaborator.user_id).where(
        CsrPartnerCollaborator.relationship_id == review.relationship_id, CsrPartnerCollaborator.active.is_(True))).all())
    _notify(db, review, event="CSR_EVIDENCE_SUBMITTED" if status == "SUBMITTED" else "CSR_REVIEW_UPDATED",
            title="CSR due diligence updated", message=f"{item.title}: {status.replace('_', ' ').title()}.",
            user_ids=[value for value in recipient_ids if value and value != user.id])
    db.commit(); return review_data(db, tenant_id, user, review.id)


def link_evidence(db, tenant_id: str, user, item_id: str, version_id: str) -> dict:
    item = db.scalar(select(CsrDueDiligenceItem).where(
        CsrDueDiligenceItem.id == item_id, CsrDueDiligenceItem.tenant_id == tenant_id))
    if not item: raise HTTPException(404, "Due diligence item not found")
    review, collaborator = _review(db, tenant_id, user, item.review_id)
    if collaborator and not item.shared_with_ngo: raise HTTPException(404, "Due diligence item not found")
    if user.role == "VIEWER": raise HTTPException(403, "Read-only accounts cannot link evidence")
    require_organization_access(db, tenant_id, item.organization_id, write=True, user_id=user.id)
    blob = db.scalar(select(DocumentBlob).where(DocumentBlob.version_id == version_id,
        DocumentBlob.tenant_id == tenant_id, DocumentBlob.organization_id == item.organization_id,
        DocumentBlob.status == "AVAILABLE"))
    if not blob: raise HTTPException(404, "Available document version not found for this NGO partner")
    existing = db.scalar(select(CsrEvidenceLink).where(CsrEvidenceLink.item_id == item.id,
        CsrEvidenceLink.version_id == blob.version_id))
    if existing:
        existing.active = True; link = existing
    else:
        link = CsrEvidenceLink(tenant_id=tenant_id, organization_id=item.organization_id,
            relationship_id=review.relationship_id, review_id=review.id, item_id=item.id,
            project_id=review.project_id, document_id=blob.document_id, version_id=blob.version_id, linked_by=user.id)
        db.add(link)
    if item.status == "NOT_STARTED": item.status = "IN_PROGRESS"
    item.updated_at = review.updated_at = utcnow()
    _audit(db, tenant_id, user, "CSR_EVIDENCE_LINKED", "CsrDueDiligenceItem", item.id,
           f"Linked immutable document version {version_id}")
    db.commit()
    return {"id": link.id, "document_id": link.document_id, "version_id": link.version_id}


def link_task(db, tenant_id: str, user, relationship_id: str, task_id: str,
              project_id: str | None, item_id: str | None) -> dict:
    partner, collaborator = relationship(db, tenant_id, user, relationship_id, write=True)
    if collaborator: raise HTTPException(403, "NGO collaborators cannot manage internal task links")
    if bool(project_id) == bool(item_id): raise HTTPException(422, "Link exactly one project or due diligence item")
    task = db.scalar(select(Task).where(Task.id == task_id, Task.tenant_id == tenant_id,
        Task.organization_id == partner.organization_id))
    if not task: raise HTTPException(404, "Task not found for this NGO partner")
    if project_id and not db.scalar(select(CsrProject.id).where(CsrProject.id == project_id,
        CsrProject.relationship_id == partner.id, CsrProject.tenant_id == tenant_id)):
        raise HTTPException(404, "CSR project not found")
    if item_id and not db.scalar(select(CsrDueDiligenceItem.id).join(CsrDueDiligenceReview,
        CsrDueDiligenceReview.id == CsrDueDiligenceItem.review_id).where(CsrDueDiligenceItem.id == item_id,
        CsrDueDiligenceItem.tenant_id == tenant_id, CsrDueDiligenceReview.relationship_id == partner.id)):
        raise HTTPException(404, "Due diligence item not found")
    duplicate = db.scalar(select(CsrTaskLink.id).where(
        CsrTaskLink.tenant_id == tenant_id, CsrTaskLink.task_id == task.id,
        CsrTaskLink.project_id == project_id, CsrTaskLink.item_id == item_id))
    if duplicate:
        raise HTTPException(409, "Task is already linked to this CSR record")
    row = CsrTaskLink(tenant_id=tenant_id, organization_id=partner.organization_id,
        relationship_id=partner.id, project_id=project_id, item_id=item_id, task_id=task.id, linked_by=user.id)
    db.add(row); db.flush()
    _audit(db, tenant_id, user, "CSR_TASK_LINKED", "Task", task.id, "Associated existing task with CSR work")
    db.commit(); return {"id": row.id, "task_id": row.task_id, "project_id": row.project_id, "item_id": row.item_id}


def csr_search_scope(db, tenant_id: str, user) -> tuple[set[str], bool]:
    allowed, collaborator = csr_scope(db, tenant_id, user)
    return allowed or set(), collaborator


def expiry_scan(db, job, today: date) -> dict:
    links = db.execute(select(CsrDueDiligenceItem, CsrEvidenceLink, DocumentBlob).join(
        CsrEvidenceLink, CsrEvidenceLink.item_id == CsrDueDiligenceItem.id).join(
        DocumentBlob, DocumentBlob.version_id == CsrEvidenceLink.version_id).where(
        CsrDueDiligenceItem.tenant_id == job.tenant_id, CsrDueDiligenceItem.expiry_monitoring.is_(True),
        CsrDueDiligenceItem.status == "APPROVED", CsrEvidenceLink.tenant_id == job.tenant_id,
        CsrEvidenceLink.active.is_(True), DocumentBlob.tenant_id == job.tenant_id,
        DocumentBlob.expiry_at < today)).all()
    changed = 0
    for item, _link, blob in links:
        valid = db.scalar(select(CsrEvidenceLink.id).join(DocumentBlob,
            DocumentBlob.version_id == CsrEvidenceLink.version_id).where(
            CsrEvidenceLink.item_id == item.id, CsrEvidenceLink.tenant_id == job.tenant_id,
            CsrEvidenceLink.active.is_(True), or_(DocumentBlob.expiry_at.is_(None), DocumentBlob.expiry_at >= today)))
        if valid: continue
        item.status = "REVIEW_REQUIRED"; item.updated_at = utcnow(); changed += 1
        db.add(AuditEvent(tenant_id=job.tenant_id, actor_name="Automation worker", action="CSR_EVIDENCE_EXPIRED",
            entity_type="CsrDueDiligenceItem", entity_id=item.id,
            summary=f"Evidence version {blob.version_id} expired; operational review is required"))
    return {"review_required": changed}
