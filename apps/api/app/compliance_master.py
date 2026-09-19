"""Platform-only governance, extending compliance_definitions and existing audit/auth."""
from __future__ import annotations

import json
import os
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from .auth import CurrentUser, DB, tenant_context
from .compliance_engine import actor_roles, calculate_deadline, document_coverage, evaluate_rules, organization_expiry, organization_facts, published_templates, validate_publish
from .compliance_template_schema import (ApplicabilityTest, CategoryInput, CreateTemplate, FIELDS, OPERATORS,
    ROLES, STATES, ComplianceProfileInput, TemplateAction, TemplateConfiguration, UpdateTemplate)
from .models import (AuditEvent, Compliance, ComplianceCategory, ComplianceDefinition, ComplianceMaster,
    ComplianceSnapshot, ComplianceTemplateVersion, Organization, OrganizationComplianceProfile, utcnow)
from .auth_policy import is_platform_admin
from .permissions import COMPLIANCE_MASTER_PERMISSIONS, has_permission

router = APIRouter(prefix="/api/v1")
Tenant = Annotated[str, Depends(tenant_context)]
GLOBAL_SCOPE = "platform-global"


def permission(action):
    def check(user: CurrentUser):
        allowed = {email.strip().lower() for email in os.getenv("PLATFORM_ADMIN_EMAILS", "").split(",") if email.strip()}
        if not is_platform_admin(user) or not has_permission(user, "compliance_master." + action):
            raise HTTPException(403, "Platform compliance master permission is required")
        return user
    return check


View = Annotated[object, Depends(permission("view"))]
Create = Annotated[object, Depends(permission("create"))]
Edit = Annotated[object, Depends(permission("edit"))]
Review = Annotated[object, Depends(permission("review"))]
Publish = Annotated[object, Depends(permission("publish"))]
Archive = Annotated[object, Depends(permission("archive"))]
Version = Annotated[object, Depends(permission("version"))]
Clone = Annotated[object, Depends(permission("clone"))]


def audit(db, user, action, version, summary):
    db.add(AuditEvent(tenant_id=user.tenant_id, actor_name=user.name, action="COMPLIANCE_MASTER_" + action,
        entity_type="ComplianceMaster", entity_id=version.definition_id, summary=f"v{version.version}: {summary}"[:280]))


def category(db, category_id, require_enabled=True):
    row = db.get(ComplianceCategory, category_id)
    if not row or (require_enabled and not row.enabled):
        raise HTTPException(422, "Select an enabled compliance category")
    return row


def get_version(db, definition_id, number=None):
    master = db.get(ComplianceMaster, definition_id)
    if not master:
        raise HTTPException(404, "Compliance template not found")
    query = select(ComplianceTemplateVersion).where(ComplianceTemplateVersion.definition_id == definition_id)
    if number is not None:
        query = query.where(ComplianceTemplateVersion.version == number)
    version = db.scalar(query.order_by(ComplianceTemplateVersion.version.desc()).limit(1))
    if not version:
        raise HTTPException(404, "Template version not found")
    return master, version


def summary_fields(config):
    types = sorted({str(condition.value) for group in config.applicability.groups for condition in group.conditions if condition.field == "legal_type" and condition.operator == "EQUALS"})
    return {"name": config.name, "category_id": config.category_id, "jurisdiction": config.jurisdiction, "frequency": config.recurrence.frequency,
        "risk_level": config.risk_level, "search_text": " ".join([config.name, config.description, config.legal_reference, *config.tags]).casefold(),
        "organization_types": ", ".join(types) if types else ("ALL" if config.applicability.match_all else "RULES")}


def serialize(db, master, version, details=True):
    row = category(db, version.category_id, require_enabled=False)
    result = {"id": master.id, "code": master.code, "category_id": version.category_id, "category": row.name,
        "version_id": version.id, "version": version.version, "current_version": master.current_version, "revision": version.revision,
        "name": version.name, "jurisdiction": version.jurisdiction, "frequency": version.frequency, "risk_level": version.risk_level,
        "organization_types": version.organization_types, "status": version.status, "change_summary": version.change_summary,
        "created_by": version.created_by, "updated_by": version.updated_by, "reviewed_by": version.reviewed_by, "published_by": version.published_by,
        "created_at": version.created_at, "updated_at": version.updated_at, "published_at": version.published_at}
    if details:
        result["configuration"] = TemplateConfiguration.model_validate_json(version.configuration).model_dump(mode="json")
    return result


def cas(db, version, expected_revision, values):
    result = db.execute(update(ComplianceTemplateVersion).where(ComplianceTemplateVersion.id == version.id,
        ComplianceTemplateVersion.revision == expected_revision).values(**values, revision=expected_revision + 1, updated_at=utcnow()).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "This template changed. Reload it before saving; your unsaved configuration is preserved in the builder")
    db.refresh(version)


def require_valid(db, version):
    config = TemplateConfiguration.model_validate_json(version.configuration)
    category(db, config.category_id)
    errors = validate_publish(config)
    if errors:
        raise HTTPException(422, "Invalid template: " + "; ".join(errors))
    return config


@router.get("/admin/compliance-master/access")
def access(user: CurrentUser):
    allowed = {email.strip().lower() for email in os.getenv("PLATFORM_ADMIN_EMAILS", "").split(",") if email.strip()}
    permissions = sorted(item for item in COMPLIANCE_MASTER_PERMISSIONS if has_permission(user, item)) if is_platform_admin(user) else []
    return {"allowed": "compliance_master.view" in permissions, "permissions": permissions}


@router.get("/admin/compliance-master/metadata")
def metadata(user: View):
    return {"fields": FIELDS, "operators": OPERATORS, "roles": sorted(ROLES), "states": sorted(STATES), "channels": ["IN_APP"],
        "permissions": sorted(item for item in COMPLIANCE_MASTER_PERMISSIONS if has_permission(user, item))}


@router.get("/admin/compliance-categories")
def categories(db: DB, _: View):
    return db.scalars(select(ComplianceCategory).order_by(ComplianceCategory.sort_order, ComplianceCategory.name)).all()


@router.post("/admin/compliance-categories", status_code=201)
def create_category(payload: CategoryInput, db: DB, user: Create):
    row = ComplianceCategory(**payload.model_dump())
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Category already exists") from None
    db.add(AuditEvent(tenant_id=user.tenant_id, actor_name=user.name, action="COMPLIANCE_CATEGORY_CREATED", entity_type="ComplianceCategory", entity_id=row.id, summary=row.name))
    db.commit()
    return row


@router.patch("/admin/compliance-categories/{category_id}")
def edit_category(category_id: str, payload: CategoryInput, db: DB, user: Edit):
    row = category(db, category_id, False)
    for key, value in payload.model_dump().items():
        setattr(row, key, value)
    db.add(AuditEvent(tenant_id=user.tenant_id, actor_name=user.name, action="COMPLIANCE_CATEGORY_UPDATED", entity_type="ComplianceCategory", entity_id=row.id, summary=row.name))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Category already exists") from None
    return row


@router.get("/admin/compliance-templates")
def list_templates(db: DB, _: View, search: str = Query(default="", max_length=200), status: str | None = None,
        category_id: str | None = None, jurisdiction: str | None = None, frequency: str | None = None, risk_level: str | None = None,
        organization_type: str | None = None, version: int | None = None, updated_from: date | None = None, updated_to: date | None = None,
        sort: str = "updated_at", order: str = "desc", page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100)):
    latest = select(ComplianceTemplateVersion.definition_id, func.max(ComplianceTemplateVersion.version).label("last_version")).group_by(ComplianceTemplateVersion.definition_id).subquery()
    query = select(ComplianceMaster, ComplianceTemplateVersion).join(latest, latest.c.definition_id == ComplianceMaster.id).join(ComplianceTemplateVersion,
        (ComplianceTemplateVersion.definition_id == ComplianceMaster.id) & (ComplianceTemplateVersion.version == latest.c.last_version)).join(ComplianceCategory, ComplianceCategory.id == ComplianceTemplateVersion.category_id)
    if search:
        term = search.casefold()
        from sqlalchemy import or_
        query = query.where(or_(ComplianceTemplateVersion.search_text.contains(term, autoescape=True), func.lower(ComplianceMaster.code).contains(term, autoescape=True), func.lower(ComplianceCategory.name).contains(term, autoescape=True)))
    for value, column in ((status, ComplianceTemplateVersion.status), (category_id, ComplianceTemplateVersion.category_id), (jurisdiction, ComplianceTemplateVersion.jurisdiction),
            (frequency, ComplianceTemplateVersion.frequency), (risk_level, ComplianceTemplateVersion.risk_level), (version, ComplianceTemplateVersion.version)):
        if value is not None:
            query = query.where(column == value)
    if organization_type:
        query = query.where(ComplianceTemplateVersion.organization_types.contains(organization_type, autoescape=True))
    if updated_from:
        query = query.where(func.date(ComplianceTemplateVersion.updated_at) >= updated_from.isoformat())
    if updated_to:
        query = query.where(func.date(ComplianceTemplateVersion.updated_at) <= updated_to.isoformat())
    sort_columns = {"name": ComplianceTemplateVersion.name, "code": ComplianceMaster.code, "category": ComplianceCategory.name,
        "updated_at": ComplianceTemplateVersion.updated_at, "version": ComplianceTemplateVersion.version, "status": ComplianceTemplateVersion.status}
    if updated_from and updated_to and updated_from > updated_to:
        raise HTTPException(422, "Updated from must be on or before updated through")
    if sort not in sort_columns or order not in {"asc", "desc"}:
        raise HTTPException(422, "Invalid sorting option")
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    column = sort_columns[sort]
    rows = db.execute(query.order_by(column.desc() if order == "desc" else column.asc(), ComplianceMaster.id).offset((page - 1) * page_size).limit(page_size)).all()
    counts = db.execute(select(ComplianceTemplateVersion.status, func.count()).join(latest,
        (latest.c.definition_id == ComplianceTemplateVersion.definition_id) & (latest.c.last_version == ComplianceTemplateVersion.version)).group_by(ComplianceTemplateVersion.status)).all()
    return {"items": [serialize(db, master, row, False) for master, row in rows], "total": total, "page": page, "page_size": page_size, "counts": dict(counts)}


@router.post("/admin/compliance-templates", status_code=201)
def create_template(payload: CreateTemplate, db: DB, user: Create):
    selected_category = category(db, payload.configuration.category_id)
    definition = ComplianceDefinition(tenant_id=GLOBAL_SCOPE, code=payload.code, title=payload.configuration.name,
        category=selected_category.name, deadline_month=1, deadline_day=1, status="DRAFT")
    db.add(definition)
    db.flush()
    master = ComplianceMaster(id=definition.id, code=payload.code, category_id=selected_category.id)
    db.add(master)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Compliance code already exists") from None
    row = ComplianceTemplateVersion(definition_id=master.id, version=1, configuration=payload.configuration.model_dump_json(),
        change_summary=payload.change_summary, created_by=user.name, updated_by=user.name, **summary_fields(payload.configuration))
    db.add(row)
    try:
        db.flush()
        audit(db, user, "CREATED", row, payload.change_summary)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Compliance code already exists") from None
    return serialize(db, master, row)


@router.get("/admin/compliance-templates/{definition_id}")
def template(definition_id: str, db: DB, _: View, version: int | None = None):
    return serialize(db, *get_version(db, definition_id, version))


@router.patch("/admin/compliance-templates/{definition_id}")
def edit_template(definition_id: str, payload: UpdateTemplate, db: DB, user: Edit):
    master, row = get_version(db, definition_id)
    if row.status != "DRAFT":
        raise HTTPException(409, "Only drafts can be edited. Create a new version of a published template")
    category(db, payload.configuration.category_id)
    previous = json.loads(row.configuration)
    cas(db, row, payload.expected_revision, {"configuration": payload.configuration.model_dump_json(), "updated_by": user.name, "change_summary": payload.change_summary, **summary_fields(payload.configuration)})
    master.category_id = payload.configuration.category_id
    audit(db, user, "EDITED", row, payload.change_summary)
    for section in ("applicability", "workflow", "checklist", "documents", "reminders", "deadline"):
        if previous[section] != payload.configuration.model_dump(mode="json")[section]:
            audit(db, user, section.upper() + "_CHANGED", row, payload.change_summary)
    db.commit()
    return serialize(db, master, row)


@router.post("/admin/compliance-templates/{definition_id}/validate")
def validate_template(definition_id: str, db: DB, _: View):
    _, row = get_version(db, definition_id)
    config = TemplateConfiguration.model_validate_json(row.configuration)
    errors = validate_publish(config)
    selected = db.get(ComplianceCategory, config.category_id)
    if not selected or not selected.enabled:
        errors.append("category: select an enabled category")
    return {"valid": not errors, "errors": errors, "warnings": ["Missing translations use English", "Publishing affects future instances only; existing instances keep their snapshots"]}


def lifecycle(db, user, definition_id, payload, source, target, action):
    master, row = get_version(db, definition_id)
    if row.status not in source:
        raise HTTPException(409, "Action is not allowed in the current template state")
    if target in {"UNDER_REVIEW", "APPROVED", "PUBLISHED"}:
        require_valid(db, row)
    values = {"status": target, "updated_by": user.name}
    if target == "DRAFT":
        values["reviewed_by"] = None
    if target == "APPROVED":
        values["reviewed_by"] = user.name
    if target == "PUBLISHED":
        values.update(published_by=user.name, published_at=utcnow())
    cas(db, row, payload.expected_revision, values)
    if target == "PUBLISHED":
        # Lock identity before changing its current pointer. Historical content is never edited.
        db.execute(select(ComplianceMaster.id).where(ComplianceMaster.id == master.id).with_for_update()).first()
        master.current_version = row.version
        config = TemplateConfiguration.model_validate_json(row.configuration)
        definition = db.get(ComplianceDefinition, master.id)
        definition.status, definition.title = "PUBLISHED", config.name
        definition.category = category(db, config.category_id).name
        definition.rule_version, definition.legal_reference = row.version, config.legal_reference
        definition.priority, definition.internal_lead_days = config.priority, config.deadline.internal_lead_days
        if config.deadline.fixed_date:
            definition.deadline_month, definition.deadline_day = config.deadline.fixed_date.month, config.deadline.fixed_date.day
    if target == "ARCHIVED":
        master.current_version = None
        db.get(ComplianceDefinition, master.id).status = "ARCHIVED"
    audit(db, user, action, row, payload.change_summary or row.change_summary)
    db.commit()
    return serialize(db, master, row)


@router.post("/admin/compliance-templates/{definition_id}/submit-review")
def submit(definition_id: str, payload: TemplateAction, db: DB, user: Edit):
    return lifecycle(db, user, definition_id, payload, {"DRAFT"}, "UNDER_REVIEW", "SUBMITTED_FOR_REVIEW")


@router.post("/admin/compliance-templates/{definition_id}/approve")
def approve(definition_id: str, payload: TemplateAction, db: DB, user: Review):
    return lifecycle(db, user, definition_id, payload, {"UNDER_REVIEW"}, "APPROVED", "APPROVED")


@router.post("/admin/compliance-templates/{definition_id}/request-changes")
def request_changes(definition_id: str, payload: TemplateAction, db: DB, user: Review):
    if len(payload.change_summary.strip()) < 3:
        raise HTTPException(422, "Explain the requested changes")
    return lifecycle(db, user, definition_id, payload, {"UNDER_REVIEW", "APPROVED"}, "DRAFT", "CHANGES_REQUESTED")


@router.post("/admin/compliance-templates/{definition_id}/publish")
def publish(definition_id: str, payload: TemplateAction, db: DB, user: Publish):
    return lifecycle(db, user, definition_id, payload, {"APPROVED"}, "PUBLISHED", "PUBLISHED")


@router.post("/admin/compliance-templates/{definition_id}/archive")
def archive(definition_id: str, payload: TemplateAction, db: DB, user: Archive):
    return lifecycle(db, user, definition_id, payload, {"DRAFT", "UNDER_REVIEW", "APPROVED", "PUBLISHED"}, "ARCHIVED", "ARCHIVED")


@router.post("/admin/compliance-templates/{definition_id}/new-version", status_code=201)
def new_version(definition_id: str, payload: TemplateAction, db: DB, user: Version):
    master, old = get_version(db, definition_id)
    if len(payload.change_summary.strip()) < 3:
        raise HTTPException(422, "Change summary is required for a new version")
    if old.status not in {"PUBLISHED", "ARCHIVED"} or old.revision != payload.expected_revision:
        raise HTTPException(409, "A draft already exists or the template changed. Reload before creating a version")
    db.execute(select(ComplianceMaster.id).where(ComplianceMaster.id == master.id).with_for_update()).first()
    result = db.execute(update(ComplianceMaster).where(ComplianceMaster.id == master.id, ComplianceMaster.revision == master.revision)
        .values(revision=ComplianceMaster.revision + 1).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "A new version was created concurrently. Reload before continuing")
    config = TemplateConfiguration.model_validate_json(old.configuration)
    row = ComplianceTemplateVersion(definition_id=master.id, version=old.version + 1, configuration=old.configuration,
        created_by=user.name, updated_by=user.name, change_summary=payload.change_summary, **summary_fields(config))
    db.add(row)
    try:
        db.flush()
        audit(db, user, "VERSION_CREATED", row, payload.change_summary)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A new version already exists") from None
    return serialize(db, master, row)


@router.post("/admin/compliance-templates/{definition_id}/clone", status_code=201)
def clone(definition_id: str, payload: CreateTemplate, db: DB, user: Clone):
    _, source = get_version(db, definition_id)
    # Clone the selected source configuration, not its history or an arbitrary payload.
    config = TemplateConfiguration.model_validate_json(source.configuration)
    config.name = payload.configuration.name or config.name
    result = create_template(CreateTemplate(code=payload.code, configuration=config, change_summary=payload.change_summary), db, user)
    _, row = get_version(db, result["id"])
    audit(db, user, "CLONED", row, f"Cloned {definition_id} v{source.version}")
    db.commit()
    return result


@router.get("/admin/compliance-templates/{definition_id}/versions")
def versions(definition_id: str, db: DB, _: View):
    master, _ = get_version(db, definition_id)
    return [serialize(db, master, row, False) for row in db.scalars(select(ComplianceTemplateVersion).where(ComplianceTemplateVersion.definition_id == definition_id).order_by(ComplianceTemplateVersion.version.desc())).all()]


@router.get("/admin/compliance-templates/{definition_id}/audit")
def template_audit(definition_id: str, db: DB, _: View, page: int = Query(default=1, ge=1)):
    get_version(db, definition_id)
    return db.scalars(select(AuditEvent).where(AuditEvent.entity_type == "ComplianceMaster", AuditEvent.entity_id == definition_id)
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id).offset((page - 1) * 50).limit(50)).all()


@router.get("/admin/compliance-templates/{definition_id}/compare")
def compare(definition_id: str, before: int, after: int, db: DB, _: View):
    _, a = get_version(db, definition_id, before)
    _, b = get_version(db, definition_id, after)
    left, right = json.loads(a.configuration), json.loads(b.configuration)
    return {"before": before, "after": after, "changes": [{"section": key, "before": left[key], "after": right[key]} for key in left if left[key] != right[key]]}


@router.get("/admin/compliance-master/organizations")
def sample_organizations(db: DB, _: View, search: str = Query(default="", max_length=200), page: int = Query(default=1, ge=1)):
    # Explicitly platform-scoped: no tenant header or URL trick enables this for tenant admins.
    query = select(Organization)
    if search:
        query = query.where(func.lower(Organization.name).contains(search.casefold(), autoescape=True))
    return db.scalars(query.order_by(Organization.name, Organization.id).offset((page - 1) * 30).limit(30)).all()


@router.post("/admin/compliance-templates/{definition_id}/test-applicability")
def test_applicability(definition_id: str, payload: ApplicabilityTest, db: DB, _: View):
    _, row = get_version(db, definition_id)
    config = payload.configuration or TemplateConfiguration.model_validate_json(row.configuration)
    organization = db.get(Organization, payload.organization_id)
    if not organization:
        raise HTTPException(404, "Sample organization not found")
    result = evaluate_rules(config, organization, organization_facts(db, organization))
    if result["applicable"]:
        try:
            result["schedule"] = calculate_deadline(config, payload.as_of or date.today(), payload.event_date, organization_expiry(db, organization.tenant_id, organization.id, config))
        except (ValueError, OverflowError) as error:
            result["requires_review"] = str(error)
    return result


@router.get("/compliance-templates")
def tenant_templates(db: DB, tenant_id: Tenant):
    result = [serialize(db, master, row) for master, row in published_templates(db)]
    for item in result:
        item["configuration"].pop("internal_notes", None)
    return result


@router.post("/organizations/{organization_id}/evaluate-compliance")
def evaluate_organization(organization_id: str, db: DB, tenant_id: Tenant):
    organization = db.scalar(select(Organization).where(Organization.id == organization_id, Organization.tenant_id == tenant_id))
    if not organization:
        raise HTTPException(404, "Organization not found in this tenant")
    from .runtime_decisions import evaluate_organization as evaluate_saved
    results = evaluate_saved(db, tenant_id, organization)
    db.commit()
    return {"results": results, "policy": "PREVIEW_ONLY_EXISTING_INSTANCES_UNCHANGED"}


@router.get("/organizations/{organization_id}/compliance-profile")
def compliance_profile(organization_id: str, db: DB, tenant_id: Tenant):
    organization = db.scalar(select(Organization).where(Organization.id == organization_id, Organization.tenant_id == tenant_id))
    if not organization:
        raise HTTPException(404, "Organization not found in this tenant")
    return organization_facts(db, organization)


@router.patch("/organizations/{organization_id}/compliance-profile")
def update_profile(organization_id: str, payload: ComplianceProfileInput, db: DB, tenant_id: Tenant, user: CurrentUser):
    organization = db.scalar(select(Organization).where(Organization.id == organization_id, Organization.tenant_id == tenant_id))
    if not organization:
        raise HTTPException(404, "Organization not found in this tenant")
    profile = db.get(OrganizationComplianceProfile, organization_id)
    if not profile:
        profile = OrganizationComplianceProfile(organization_id=organization_id, tenant_id=tenant_id, updated_by=user.name)
        db.add(profile)
    profile.annual_revenue, profile.revenue_period = payload.annual_revenue, payload.revenue_period
    profile.updated_by, profile.updated_at = user.name, utcnow()
    db.add(AuditEvent(tenant_id=tenant_id, actor_name=user.name, action="ORGANIZATION_COMPLIANCE_PROFILE_UPDATED", entity_type="Organization", entity_id=organization_id, summary="Financial facts updated; re-evaluate applicability explicitly"))
    db.commit()
    return organization_facts(db, organization)


@router.get("/compliances/{compliance_id}/template-snapshot")
def snapshot(compliance_id: str, db: DB, tenant_id: Tenant):
    row = db.get(ComplianceSnapshot, compliance_id)
    if not row or row.tenant_id != tenant_id:
        raise HTTPException(404, "Template snapshot not found in this tenant")
    item = db.get(Compliance, compliance_id)
    version = db.get(ComplianceTemplateVersion, row.version_id)
    config = TemplateConfiguration.model_validate_json(row.configuration)
    configuration = config.model_dump(mode="json")
    configuration.pop("internal_notes", None)
    roles = actor_roles(db, tenant_id, item.organization_id)
    source = "IN_PROGRESS" if item.status == "OVERDUE" else item.status
    available = [edge.model_dump() for edge in config.workflow.transitions if edge.from_state == source and roles.intersection(edge.allowed_roles)
        and (not edge.required_approval or roles.intersection({config.responsibility.reviewer_role, config.responsibility.approver_role}))]
    return {"definition_id": row.definition_id, "version": version.version, "cycle": row.cycle, "configuration": configuration,
        "owner_required": row.owner_required, "available_transitions": available, "checklist_tasks": json.loads(row.checklist_tasks), "documents": document_coverage(db, row, item.statutory_deadline)}
