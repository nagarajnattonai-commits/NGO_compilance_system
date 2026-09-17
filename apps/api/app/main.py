from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Annotated
import os

from fastapi import Depends, FastAPI, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .database import Base, SessionLocal, engine
from .auth import ALLOWED_ORIGINS, AdminUser, CurrentUser, get_db, router as auth_router, tenant_context as get_tenant_id
from .models import (
    AutomationReceipt,
    AuditEvent,
    Compliance,
    ComplianceComment,
    ComplianceDefinition,
    Document,
    DocumentVersion,
    IntegrationConnection,
    Membership,
    Notification,
    Organization,
    PortfolioRecord,
    Submission,
    Subscription,
    Task,
    TenantLocale,
    TranslationOverride,
    UserPreference,
)
from .schemas import (
    AssistantInput,
    AuditOut,
    ComplianceCommentCreate,
    ComplianceCommentOut,
    ComplianceCreate,
    ComplianceDefinitionOut,
    ComplianceOut,
    ComplianceTransition,
    ComplianceUpdate,
    DocumentCreate,
    DocumentOut,
    DocumentVersionCreate,
    DocumentVersionOut,
    IntegrationOut,
    IntegrationUpdate,
    LocalizationSettingsOut,
    MembershipCreate,
    MembershipOut,
    MembershipUpdate,
    NotificationOut,
    OrganizationCreate,
    OrganizationOnboardingOut,
    OrganizationOut,
    OrganizationUpdate,
    PortfolioRecordCreate,
    PortfolioRecordOut,
    PortfolioRecordUpdate,
    SubscriptionOut,
    TenantLocaleInput,
    TenantLocaleOut,
    TaskCreate,
    TaskOut,
    TaskUpdate,
    TranslationOverrideInput,
    TranslationOverrideOut,
    UserPreferenceOut,
    UserPreferenceUpdate,
)
from .seed import seed_demo_data
from .branding import router as branding_router
from .brand_outputs import router as brand_outputs_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    if os.getenv("APP_ENV") == "production" and len(os.getenv("BRAND_PROXY_KEY", "")) < 32:
        raise RuntimeError("Production requires a shared BRAND_PROXY_KEY of at least 32 characters")
    Base.metadata.create_all(bind=engine)
    if os.getenv("APP_ENV") != "production":
        with SessionLocal() as db:
            seed_demo_data(db)
    yield


app = FastAPI(
    title="Setu NGO Compliance API",
    version="0.2.0",
    description="Tenant-scoped compliance operations API derived from the approved product documents.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(ALLOWED_ORIGINS),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(auth_router)
app.include_router(branding_router)
app.include_router(brand_outputs_router)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_, error: RequestValidationError):
    # Do not echo passwords, tokens, or other submitted values in validation errors.
    return JSONResponse(status_code=422, content={"detail": [
        {"loc": list(item["loc"]), "msg": item["msg"], "type": item["type"]}
        for item in error.errors()
    ]})


@app.middleware("http")
async def private_api_responses(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
    return response


DB = Annotated[Session, Depends(get_db)]
Tenant = Annotated[str, Depends(get_tenant_id)]


def audit(db: Session, tenant_id: str, action: str, entity_type: str, entity_id: str, summary: str) -> None:
    db.add(AuditEvent(tenant_id=tenant_id, actor_name=db.info.get("actor_name", "System"), action=action, entity_type=entity_type, entity_id=entity_id, summary=summary))


def verify_org(db: Session, tenant_id: str, organization_id: str) -> Organization:
    org = db.scalar(select(Organization).where(Organization.id == organization_id, Organization.tenant_id == tenant_id))
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found in this tenant")
    return org


def person_initials(name: str) -> str:
    return "".join(part[0] for part in name.split() if part)[:3].upper()


def generate_compliance_plan(db: Session, tenant_id: str, organization: Organization) -> list[Compliance]:
    today = date.today()
    definitions = db.scalars(
        select(ComplianceDefinition).where(
            ComplianceDefinition.tenant_id == tenant_id,
            ComplianceDefinition.status == "ACTIVE",
        ).order_by(ComplianceDefinition.code)
    ).all()
    generated: list[Compliance] = []
    for definition in definitions:
        legal_types = {value.strip() for value in definition.applicable_legal_types.split(",")}
        if "ALL" not in legal_types and organization.legal_type not in legal_types:
            continue
        if definition.requires_fcra and not organization.fcra_active:
            continue
        deadline = date(today.year, definition.deadline_month, definition.deadline_day)
        if deadline < today:
            deadline = date(today.year + 1, definition.deadline_month, definition.deadline_day)
        period = f"Cycle {deadline.year}"
        existing = db.scalar(select(Compliance.id).where(
            Compliance.tenant_id == tenant_id,
            Compliance.organization_id == organization.id,
            Compliance.code == definition.code,
            Compliance.period == period,
        ))
        if existing:
            continue
        item = Compliance(
            tenant_id=tenant_id,
            organization_id=organization.id,
            code=definition.code,
            title=definition.title,
            category=definition.category,
            period=period,
            statutory_deadline=deadline,
            internal_target=deadline - timedelta(days=definition.internal_lead_days),
            status="PLANNED",
            priority=definition.priority,
            owner_name="Unassigned",
            owner_initials="",
            progress=0,
            legal_reference=f"{definition.legal_reference} (rule v{definition.rule_version})",
            risk_note="Assign an accountable owner and validate the configured deadline.",
        )
        db.add(item)
        db.flush()
        audit(db, tenant_id, "COMPLIANCE_GENERATED", "Compliance", item.id, f"Generated {item.title} from rule {definition.code} v{definition.rule_version}")
        generated.append(item)
    return generated


ALLOWED_TRANSITIONS = {
    "DRAFT": {"PLANNED", "IN_PROGRESS", "CANCELLED"},
    "PLANNED": {"IN_PROGRESS", "NOT_APPLICABLE", "ON_HOLD"},
    "NOT_STARTED": {"IN_PROGRESS", "NOT_APPLICABLE", "ON_HOLD"},
    "IN_PROGRESS": {"UNDER_REVIEW", "ON_HOLD"},
    "UNDER_REVIEW": {"CHANGES_REQUESTED", "READY_TO_FILE"},
    "CHANGES_REQUESTED": {"IN_PROGRESS", "ON_HOLD"},
    "READY_TO_FILE": {"FILED", "CHANGES_REQUESTED"},
    "FILED": {"COMPLETED"},
    "COMPLETED": {"IN_PROGRESS"},
    "ON_HOLD": {"IN_PROGRESS", "CANCELLED"},
    "NOT_APPLICABLE": {"IN_PROGRESS"},
    "OVERDUE": {"IN_PROGRESS", "UNDER_REVIEW", "ON_HOLD"},
}


def apply_compliance_transition(
    db: Session,
    tenant_id: str,
    item: Compliance,
    target_status: str,
    reason: str | None = None,
    submission_reference: str | None = None,
    proof_document_id: str | None = None,
) -> None:
    if target_status not in ALLOWED_TRANSITIONS.get(item.status, set()):
        raise HTTPException(status_code=409, detail=f"Cannot move compliance from {item.status} to {target_status}")
    if target_status in {"CHANGES_REQUESTED", "NOT_APPLICABLE", "ON_HOLD"} or item.status in {"COMPLETED", "NOT_APPLICABLE"}:
        if not reason or len(reason.strip()) < 3:
            raise HTTPException(status_code=422, detail="A reason is required for this transition")
    if proof_document_id:
        proof = db.scalar(select(Document.id).where(
            Document.id == proof_document_id,
            Document.tenant_id == tenant_id,
            Document.organization_id == item.organization_id,
        ))
        if not proof:
            raise HTTPException(status_code=404, detail="Proof document not found for this organization")
    if target_status == "FILED":
        if not submission_reference and not proof_document_id:
            raise HTTPException(status_code=422, detail="A submission reference or proof document is required to mark this compliance filed")
        db.add(Submission(
            tenant_id=tenant_id,
            compliance_id=item.id,
            acknowledgement_ref=submission_reference or "Proof document attached",
            proof_document_id=proof_document_id,
        ))
    if target_status == "COMPLETED" and not db.scalar(select(Submission.id).where(
        Submission.tenant_id == tenant_id,
        Submission.compliance_id == item.id,
    )):
        raise HTTPException(status_code=422, detail="Filing proof is required before completion")
    previous = item.status
    item.status = target_status
    item.updated_at = datetime.now(timezone.utc)
    progress_by_status = {
        "PLANNED": 5,
        "IN_PROGRESS": max(item.progress, 20),
        "UNDER_REVIEW": max(item.progress, 70),
        "CHANGES_REQUESTED": max(item.progress, 60),
        "READY_TO_FILE": max(item.progress, 90),
        "FILED": max(item.progress, 96),
        "COMPLETED": 100,
    }
    if target_status in progress_by_status:
        item.progress = progress_by_status[target_status]
    summary = f"Moved {item.title}: {previous} -> {target_status}"
    if reason:
        summary += f"; reason: {reason.strip()}"
    audit(db, tenant_id, "STATUS_CHANGED", "Compliance", item.id, summary)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "ngo-compliance-api"}


@app.get("/api/v1/organizations", response_model=list[OrganizationOut])
def organizations(db: DB, tenant_id: Tenant):
    return db.scalars(select(Organization).where(Organization.tenant_id == tenant_id, Organization.status != "ARCHIVED").order_by(Organization.name)).all()


@app.post("/api/v1/organizations", response_model=OrganizationOnboardingOut, status_code=status.HTTP_201_CREATED)
def create_organization(payload: OrganizationCreate, db: DB, tenant_id: Tenant):
    subscription = db.scalar(select(Subscription).where(Subscription.tenant_id == tenant_id))
    organization_count = db.scalar(select(func.count()).select_from(Organization).where(
        Organization.tenant_id == tenant_id,
        Organization.status != "ARCHIVED",
    )) or 0
    if subscription and organization_count >= subscription.organization_limit:
        raise HTTPException(status_code=403, detail="Organization limit reached for the current plan")
    duplicate_checks = [func.lower(Organization.registration_number) == payload.registration_number.lower()]
    if payload.pan:
        duplicate_checks.append(func.lower(Organization.pan) == payload.pan.lower())
    duplicate = db.scalar(select(Organization.id).where(
        Organization.tenant_id == tenant_id,
        or_(*duplicate_checks),
    ).limit(1))
    if duplicate:
        raise HTTPException(status_code=409, detail="An organization with this registration number or PAN already exists")
    values = payload.model_dump(exclude={"generate_compliance_plan"})
    item = Organization(tenant_id=tenant_id, status="ACTIVE", **values)
    db.add(item)
    db.flush()
    audit(db, tenant_id, "ORGANIZATION_CREATED", "Organization", item.id, f"Created {item.name}")
    generated = generate_compliance_plan(db, tenant_id, item) if payload.generate_compliance_plan else []
    db.commit()
    db.refresh(item)
    for compliance in generated:
        db.refresh(compliance)
    return {"organization": item, "generated_compliances": generated}


@app.patch("/api/v1/organizations/{organization_id}", response_model=OrganizationOut)
def update_organization(organization_id: str, payload: OrganizationUpdate, db: DB, tenant_id: Tenant):
    item = verify_org(db, tenant_id, organization_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    audit(db, tenant_id, "ORGANIZATION_UPDATED", "Organization", item.id, f"Updated {item.name}")
    db.commit()
    db.refresh(item)
    return item


@app.post("/api/v1/organizations/{organization_id}/generate-plan", response_model=list[ComplianceOut])
def generate_organization_plan(organization_id: str, db: DB, tenant_id: Tenant):
    organization = verify_org(db, tenant_id, organization_id)
    generated = generate_compliance_plan(db, tenant_id, organization)
    db.commit()
    for compliance in generated:
        db.refresh(compliance)
    return generated


@app.get("/api/v1/compliance-definitions", response_model=list[ComplianceDefinitionOut])
def compliance_definitions(db: DB, tenant_id: Tenant):
    return db.scalars(select(ComplianceDefinition).where(
        ComplianceDefinition.tenant_id == tenant_id,
        ComplianceDefinition.status == "ACTIVE",
    ).order_by(ComplianceDefinition.category, ComplianceDefinition.title)).all()


@app.get("/api/v1/dashboard")
def dashboard(db: DB, tenant_id: Tenant, organization_id: str | None = None):
    filters = [Compliance.tenant_id == tenant_id]
    task_filters = [Task.tenant_id == tenant_id]
    doc_filters = [Document.tenant_id == tenant_id]
    if organization_id:
        verify_org(db, tenant_id, organization_id)
        filters.append(Compliance.organization_id == organization_id)
        task_filters.append(Task.organization_id == organization_id)
        doc_filters.append(Document.organization_id == organization_id)

    compliances = list(db.scalars(select(Compliance).where(*filters)).all())
    tasks = list(db.scalars(select(Task).where(*task_filters).order_by(Task.due_at).limit(6)).all())
    documents = list(db.scalars(select(Document).where(*doc_filters).order_by(Document.expiry_at).limit(5)).all())
    active = [item for item in compliances if item.status != "COMPLETED"]
    completed = [item for item in compliances if item.status == "COMPLETED"]
    high_risk = [item for item in active if item.priority in {"HIGH", "CRITICAL"}]
    return {
        "summary": {
            "total": len(compliances),
            "completed": len(completed),
            "in_progress": len([item for item in active if item.status in {"IN_PROGRESS", "UNDER_REVIEW", "READY_TO_FILE"}]),
            "high_risk": len(high_risk),
            "completion_rate": round(len(completed) / len(compliances) * 100) if compliances else 0,
        },
        "compliances": compliances,
        "tasks": tasks,
        "documents": documents,
    }


@app.get("/api/v1/compliances", response_model=list[ComplianceOut])
def compliances(
    db: DB,
    tenant_id: Tenant,
    organization_id: str | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    search: str | None = None,
):
    filters = [Compliance.tenant_id == tenant_id]
    if organization_id:
        verify_org(db, tenant_id, organization_id)
        filters.append(Compliance.organization_id == organization_id)
    if status_filter:
        filters.append(Compliance.status == status_filter)
    if search:
        filters.append(func.lower(Compliance.title).contains(search.lower()))
    return db.scalars(select(Compliance).where(*filters).order_by(Compliance.statutory_deadline)).all()


@app.post("/api/v1/compliances", response_model=ComplianceOut, status_code=status.HTTP_201_CREATED)
def create_compliance(payload: ComplianceCreate, db: DB, tenant_id: Tenant):
    verify_org(db, tenant_id, payload.organization_id)
    item = Compliance(tenant_id=tenant_id, **payload.model_dump(), status="NOT_STARTED", progress=0)
    db.add(item)
    db.flush()
    audit(db, tenant_id, "COMPLIANCE_CREATED", "Compliance", item.id, f"Created {item.title}")
    db.commit()
    db.refresh(item)
    return item


@app.patch("/api/v1/compliances/{compliance_id}", response_model=ComplianceOut)
def update_compliance(compliance_id: str, payload: ComplianceUpdate, db: DB, tenant_id: Tenant):
    item = db.scalar(select(Compliance).where(Compliance.id == compliance_id, Compliance.tenant_id == tenant_id))
    if not item:
        raise HTTPException(status_code=404, detail="Compliance not found")
    values = payload.model_dump(exclude_unset=True)
    target_status = values.pop("status", None)
    if target_status:
        apply_compliance_transition(db, tenant_id, item, target_status)
    for field, value in values.items():
        setattr(item, field, value)
    item.updated_at = datetime.now(timezone.utc)
    if values:
        audit(db, tenant_id, "COMPLIANCE_UPDATED", "Compliance", item.id, f"Updated {item.title}")
    db.commit()
    db.refresh(item)
    return item


@app.post("/api/v1/compliances/{compliance_id}/transitions", response_model=ComplianceOut)
def transition_compliance(compliance_id: str, payload: ComplianceTransition, db: DB, tenant_id: Tenant):
    item = db.scalar(select(Compliance).where(Compliance.id == compliance_id, Compliance.tenant_id == tenant_id))
    if not item:
        raise HTTPException(status_code=404, detail="Compliance not found")
    apply_compliance_transition(
        db, tenant_id, item, payload.target_status, payload.reason,
        payload.submission_reference, payload.proof_document_id,
    )
    if payload.target_status == "UNDER_REVIEW":
        db.add(Notification(
            tenant_id=tenant_id,
            title=f"{item.code} ready for review",
            message=f"{item.title} was submitted for review.",
            kind="REVIEW",
        ))
    db.commit()
    db.refresh(item)
    return item


@app.get("/api/v1/tasks", response_model=list[TaskOut])
def tasks(db: DB, tenant_id: Tenant, organization_id: str | None = None):
    filters = [Task.tenant_id == tenant_id]
    if organization_id:
        verify_org(db, tenant_id, organization_id)
        filters.append(Task.organization_id == organization_id)
    return db.scalars(select(Task).where(*filters).order_by(Task.status, Task.due_at)).all()


@app.post("/api/v1/tasks", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
def create_task(payload: TaskCreate, db: DB, tenant_id: Tenant):
    verify_org(db, tenant_id, payload.organization_id)
    if payload.compliance_id:
        linked = db.scalar(
            select(Compliance.id).where(
                Compliance.id == payload.compliance_id,
                Compliance.tenant_id == tenant_id,
                Compliance.organization_id == payload.organization_id,
            )
        )
        if not linked:
            raise HTTPException(status_code=404, detail="Linked compliance not found for this organization")
    item = Task(tenant_id=tenant_id, **payload.model_dump(), status="TODO")
    db.add(item)
    db.flush()
    audit(db, tenant_id, "TASK_CREATED", "Task", item.id, f"Created task {item.title}")
    db.commit()
    db.refresh(item)
    return item


@app.patch("/api/v1/tasks/{task_id}", response_model=TaskOut)
def update_task(task_id: str, payload: TaskUpdate, db: DB, tenant_id: Tenant):
    item = db.scalar(select(Task).where(Task.id == task_id, Task.tenant_id == tenant_id))
    if not item:
        raise HTTPException(status_code=404, detail="Task not found")
    item.status = payload.status
    item.completed_at = datetime.now(timezone.utc) if payload.status == "DONE" else None
    audit(db, tenant_id, "TASK_UPDATED", "Task", item.id, f"Set {item.title} to {item.status}")
    db.commit()
    db.refresh(item)
    return item


@app.get("/api/v1/documents", response_model=list[DocumentOut])
def documents(db: DB, tenant_id: Tenant, organization_id: str | None = None):
    filters = [Document.tenant_id == tenant_id]
    if organization_id:
        verify_org(db, tenant_id, organization_id)
        filters.append(Document.organization_id == organization_id)
    return db.scalars(select(Document).where(*filters).order_by(Document.created_at.desc())).all()


@app.post("/api/v1/documents", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
def create_document(payload: DocumentCreate, db: DB, tenant_id: Tenant):
    verify_org(db, tenant_id, payload.organization_id)
    if payload.compliance_id:
        linked = db.scalar(
            select(Compliance.id).where(
                Compliance.id == payload.compliance_id,
                Compliance.tenant_id == tenant_id,
                Compliance.organization_id == payload.organization_id,
            )
        )
        if not linked:
            raise HTTPException(status_code=404, detail="Linked compliance not found for this organization")
    item = Document(tenant_id=tenant_id, **payload.model_dump())
    db.add(item)
    db.flush()
    db.add(DocumentVersion(
        tenant_id=tenant_id,
        document_id=item.id,
        version=1,
        file_type=item.file_type,
        size_label=item.size_label,
        uploaded_by=item.uploaded_by,
    ))
    audit(db, tenant_id, "DOCUMENT_UPLOADED", "Document", item.id, f"Uploaded {item.name}")
    db.commit()
    db.refresh(item)
    return item


@app.get("/api/v1/documents/{document_id}/versions", response_model=list[DocumentVersionOut])
def document_versions(document_id: str, db: DB, tenant_id: Tenant):
    document = db.scalar(select(Document.id).where(Document.id == document_id, Document.tenant_id == tenant_id))
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return db.scalars(select(DocumentVersion).where(
        DocumentVersion.document_id == document_id,
        DocumentVersion.tenant_id == tenant_id,
    ).order_by(DocumentVersion.version.desc())).all()


@app.post("/api/v1/documents/{document_id}/versions", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
def create_document_version(document_id: str, payload: DocumentVersionCreate, db: DB, tenant_id: Tenant):
    document = db.scalar(select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id))
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    latest = db.scalar(select(func.max(DocumentVersion.version)).where(
        DocumentVersion.document_id == document_id,
        DocumentVersion.tenant_id == tenant_id,
    )) or document.version
    next_version = latest + 1
    db.add(DocumentVersion(
        tenant_id=tenant_id,
        document_id=document.id,
        version=next_version,
        file_type=payload.file_type,
        size_label=payload.size_label,
        uploaded_by=payload.uploaded_by,
    ))
    document.version = next_version
    document.file_type = payload.file_type
    document.size_label = payload.size_label
    document.uploaded_by = payload.uploaded_by
    document.created_at = datetime.now(timezone.utc)
    audit(db, tenant_id, "DOCUMENT_VERSION_CREATED", "Document", document.id, f"Uploaded version {next_version} of {document.name}")
    db.commit()
    db.refresh(document)
    return document


@app.get("/api/v1/memberships", response_model=list[MembershipOut])
def memberships(db: DB, tenant_id: Tenant, organization_id: str | None = None):
    filters = [Membership.tenant_id == tenant_id]
    if organization_id:
        verify_org(db, tenant_id, organization_id)
        filters.append(Membership.organization_id == organization_id)
    return db.scalars(select(Membership).where(*filters).order_by(Membership.status, Membership.name)).all()


@app.post("/api/v1/memberships/invitations", response_model=MembershipOut, status_code=status.HTTP_201_CREATED)
def invite_member(payload: MembershipCreate, db: DB, tenant_id: Tenant):
    if payload.organization_id:
        verify_org(db, tenant_id, payload.organization_id)
    subscription = db.scalar(select(Subscription).where(Subscription.tenant_id == tenant_id))
    active_count = db.scalar(select(func.count()).select_from(Membership).where(
        Membership.tenant_id == tenant_id,
        Membership.status != "INACTIVE",
    )) or 0
    if subscription and active_count >= subscription.user_limit:
        raise HTTPException(status_code=403, detail="User limit reached for the current plan")
    duplicate = db.scalar(select(Membership.id).where(
        Membership.tenant_id == tenant_id,
        func.lower(Membership.email) == payload.email.lower(),
        Membership.status != "INACTIVE",
    ))
    if duplicate:
        raise HTTPException(status_code=409, detail="This email already has an active or pending membership")
    item = Membership(tenant_id=tenant_id, **payload.model_dump(), status="INVITED")
    db.add(item)
    db.flush()
    audit(db, tenant_id, "MEMBER_INVITED", "Membership", item.id, f"Invited {item.email} as {item.role}")
    db.commit()
    db.refresh(item)
    return item


@app.patch("/api/v1/memberships/{membership_id}", response_model=MembershipOut)
def update_membership(membership_id: str, payload: MembershipUpdate, db: DB, tenant_id: Tenant):
    item = db.scalar(select(Membership).where(Membership.id == membership_id, Membership.tenant_id == tenant_id))
    if not item:
        raise HTTPException(status_code=404, detail="Membership not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    if payload.status == "ACTIVE" and not item.accepted_at:
        item.accepted_at = datetime.now(timezone.utc)
    audit(db, tenant_id, "MEMBERSHIP_UPDATED", "Membership", item.id, f"Updated access for {item.email}")
    db.commit()
    db.refresh(item)
    return item


@app.get("/api/v1/subscription", response_model=SubscriptionOut)
def subscription(db: DB, tenant_id: Tenant):
    item = db.scalar(select(Subscription).where(Subscription.tenant_id == tenant_id))
    if not item:
        raise HTTPException(status_code=404, detail="Subscription not configured")
    return item


DEFAULT_LOCALES = [
    ("en-IN", "English", True, 1),
    ("hi-IN", "हिन्दी", False, 2),
    ("kn-IN", "ಕನ್ನಡ", False, 3),
    ("mr-IN", "मराठी", False, 4),
]


def ensure_localization(db: Session, tenant_id: str, user_id: str) -> tuple[list[TenantLocale], UserPreference, bool]:
    changed = False
    existing = {item.locale_code: item for item in db.scalars(select(TenantLocale).where(TenantLocale.tenant_id == tenant_id)).all()}
    for code, name, is_default, order in DEFAULT_LOCALES:
        if code not in existing:
            item = TenantLocale(tenant_id=tenant_id, locale_code=code, display_name=name, enabled=True, is_default=is_default, sort_order=order)
            db.add(item)
            existing[code] = item
            changed = True
    preference = db.get(UserPreference, user_id)
    if not preference:
        preference = UserPreference(user_id=user_id, tenant_id=tenant_id, locale=None, timezone="Asia/Kolkata", time_format="12h")
        db.add(preference)
        changed = True
    if changed:
        db.flush()
    return sorted(existing.values(), key=lambda item: item.sort_order), preference, changed


@app.get("/api/v1/localization/settings", response_model=LocalizationSettingsOut)
def localization_settings(db: DB, tenant_id: Tenant, user: CurrentUser):
    locales, preference, changed = ensure_localization(db, tenant_id, user.id)
    if changed:
        db.commit()
        db.refresh(preference)
    return LocalizationSettingsOut(locales=locales, preference=preference)


@app.patch("/api/v1/localization/preferences", response_model=UserPreferenceOut)
def update_localization_preference(payload: UserPreferenceUpdate, db: DB, tenant_id: Tenant, user: CurrentUser):
    locales, preference, _ = ensure_localization(db, tenant_id, user.id)
    if payload.locale and not any(item.locale_code == payload.locale and item.enabled for item in locales):
        raise HTTPException(status_code=422, detail="The selected locale is not enabled for this workspace")
    preference.locale = payload.locale
    preference.timezone = payload.timezone
    preference.time_format = payload.time_format
    preference.updated_at = datetime.now(timezone.utc)
    audit(db, tenant_id, "LOCALIZATION_PREFERENCE_UPDATED", "UserPreference", user.id, f"Updated locale preference to {payload.locale or 'workspace default'}")
    db.commit()
    db.refresh(preference)
    return preference


@app.put("/api/v1/localization/locales", response_model=list[TenantLocaleOut])
def update_tenant_locales(payload: list[TenantLocaleInput], db: DB, tenant_id: Tenant, admin: AdminUser):
    if len(payload) != len({item.locale_code for item in payload}):
        raise HTTPException(status_code=422, detail="Each locale may appear only once")
    defaults = [item for item in payload if item.is_default]
    if len(defaults) != 1 or not defaults[0].enabled:
        raise HTTPException(status_code=422, detail="Select exactly one enabled default locale")
    rows, _, _ = ensure_localization(db, tenant_id, admin.id)
    existing = {item.locale_code: item for item in rows}
    for locale_input in payload:
        item = existing.get(locale_input.locale_code)
        if not item:
            item = TenantLocale(tenant_id=tenant_id, locale_code=locale_input.locale_code)
            db.add(item)
        for field, value in locale_input.model_dump().items():
            setattr(item, field, value)
    audit(db, tenant_id, "TENANT_LOCALES_UPDATED", "TenantLocale", tenant_id, "Updated enabled languages, default locale and display order")
    db.commit()
    return db.scalars(select(TenantLocale).where(TenantLocale.tenant_id == tenant_id).order_by(TenantLocale.sort_order)).all()


@app.get("/api/v1/localization/overrides", response_model=list[TranslationOverrideOut])
def translation_overrides(db: DB, tenant_id: Tenant, _: CurrentUser, locale_code: str | None = None):
    filters = [TranslationOverride.tenant_id == tenant_id]
    if locale_code:
        filters.append(TranslationOverride.locale_code == locale_code)
    return db.scalars(select(TranslationOverride).where(*filters).order_by(TranslationOverride.translation_key)).all()


@app.put("/api/v1/localization/overrides", response_model=TranslationOverrideOut)
def upsert_translation_override(payload: TranslationOverrideInput, db: DB, tenant_id: Tenant, admin: AdminUser):
    locale = db.scalar(select(TenantLocale).where(TenantLocale.tenant_id == tenant_id, TenantLocale.locale_code == payload.locale_code))
    if not locale:
        raise HTTPException(status_code=404, detail="Locale is not configured for this workspace")
    item = db.scalar(select(TranslationOverride).where(
        TranslationOverride.tenant_id == tenant_id,
        TranslationOverride.locale_code == payload.locale_code,
        TranslationOverride.translation_key == payload.translation_key,
    ))
    if not item:
        item = TranslationOverride(tenant_id=tenant_id, locale_code=payload.locale_code, translation_key=payload.translation_key, translation_value=payload.translation_value, updated_by=admin.name)
        db.add(item)
    else:
        item.translation_value = payload.translation_value
        item.updated_by = admin.name
        item.updated_at = datetime.now(timezone.utc)
    db.flush()
    audit(db, tenant_id, "TRANSLATION_OVERRIDE_SAVED", "TranslationOverride", item.id, f"Updated {payload.translation_key} for {payload.locale_code}")
    db.commit()
    db.refresh(item)
    return item


@app.delete("/api/v1/localization/overrides/{override_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_translation_override(override_id: str, db: DB, tenant_id: Tenant, _: AdminUser):
    item = db.scalar(select(TranslationOverride).where(TranslationOverride.id == override_id, TranslationOverride.tenant_id == tenant_id))
    if not item:
        raise HTTPException(status_code=404, detail="Translation override not found")
    audit(db, tenant_id, "TRANSLATION_OVERRIDE_RESET", "TranslationOverride", item.id, f"Restored application translation for {item.translation_key}")
    db.delete(item)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/api/v1/notifications", response_model=list[NotificationOut])
def notifications(db: DB, tenant_id: Tenant):
    return db.scalars(select(Notification).where(Notification.tenant_id == tenant_id).order_by(Notification.created_at.desc())).all()


@app.patch("/api/v1/notifications/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
def read_notification(notification_id: str, db: DB, tenant_id: Tenant):
    item = db.scalar(select(Notification).where(Notification.id == notification_id, Notification.tenant_id == tenant_id))
    if not item:
        raise HTTPException(status_code=404, detail="Notification not found")
    item.is_read = True
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/api/v1/audit-events", response_model=list[AuditOut])
def audit_events(db: DB, tenant_id: Tenant, limit: int = Query(default=30, ge=1, le=100)):
    return db.scalars(select(AuditEvent).where(AuditEvent.tenant_id == tenant_id).order_by(AuditEvent.created_at.desc()).limit(limit)).all()


@app.get("/api/v1/compliances/{compliance_id}/comments", response_model=list[ComplianceCommentOut])
def compliance_comments(compliance_id: str, db: DB, tenant_id: Tenant):
    item = db.scalar(select(Compliance.id).where(Compliance.id == compliance_id, Compliance.tenant_id == tenant_id))
    if not item:
        raise HTTPException(status_code=404, detail="Compliance not found")
    return db.scalars(select(ComplianceComment).where(
        ComplianceComment.tenant_id == tenant_id,
        ComplianceComment.compliance_id == compliance_id,
    ).order_by(ComplianceComment.created_at.desc())).all()


@app.post("/api/v1/compliances/{compliance_id}/comments", response_model=ComplianceCommentOut, status_code=status.HTTP_201_CREATED)
def add_compliance_comment(compliance_id: str, payload: ComplianceCommentCreate, db: DB, tenant_id: Tenant):
    item = db.scalar(select(Compliance).where(Compliance.id == compliance_id, Compliance.tenant_id == tenant_id))
    if not item:
        raise HTTPException(status_code=404, detail="Compliance not found")
    comment = ComplianceComment(
        tenant_id=tenant_id,
        compliance_id=compliance_id,
        author_name=db.info.get("actor_name", "System"),
        body=payload.body.strip(),
        kind=payload.kind,
    )
    db.add(comment)
    db.flush()
    audit(db, tenant_id, "COMPLIANCE_COMMENTED", "Compliance", item.id, f"Added {payload.kind.lower().replace('_', ' ')} to {item.title}")
    db.commit()
    db.refresh(comment)
    return comment


@app.get("/api/v1/portfolio-records", response_model=list[PortfolioRecordOut])
def portfolio_records(
    db: DB,
    tenant_id: Tenant,
    organization_id: str | None = None,
    record_type: str | None = None,
):
    filters = [PortfolioRecord.tenant_id == tenant_id]
    if organization_id:
        verify_org(db, tenant_id, organization_id)
        filters.append(PortfolioRecord.organization_id == organization_id)
    if record_type:
        filters.append(PortfolioRecord.record_type == record_type)
    return db.scalars(select(PortfolioRecord).where(*filters).order_by(PortfolioRecord.updated_at.desc())).all()


@app.post("/api/v1/portfolio-records", response_model=PortfolioRecordOut, status_code=status.HTTP_201_CREATED)
def create_portfolio_record(payload: PortfolioRecordCreate, db: DB, tenant_id: Tenant):
    verify_org(db, tenant_id, payload.organization_id)
    item = PortfolioRecord(tenant_id=tenant_id, **payload.model_dump())
    db.add(item)
    db.flush()
    audit(db, tenant_id, f"{item.record_type}_CREATED", "PortfolioRecord", item.id, f"Created {item.title}")
    db.commit()
    db.refresh(item)
    return item


@app.patch("/api/v1/portfolio-records/{record_id}", response_model=PortfolioRecordOut)
def update_portfolio_record(record_id: str, payload: PortfolioRecordUpdate, db: DB, tenant_id: Tenant):
    item = db.scalar(select(PortfolioRecord).where(PortfolioRecord.id == record_id, PortfolioRecord.tenant_id == tenant_id))
    if not item:
        raise HTTPException(status_code=404, detail="Portfolio record not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    item.updated_at = datetime.now(timezone.utc)
    audit(db, tenant_id, f"{item.record_type}_UPDATED", "PortfolioRecord", item.id, f"Updated {item.title}")
    db.commit()
    db.refresh(item)
    return item


@app.delete("/api/v1/portfolio-records/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_portfolio_record(record_id: str, db: DB, tenant_id: Tenant, _: AdminUser):
    item = db.scalar(select(PortfolioRecord).where(PortfolioRecord.id == record_id, PortfolioRecord.tenant_id == tenant_id))
    if not item:
        raise HTTPException(status_code=404, detail="Portfolio record not found")
    audit(db, tenant_id, f"{item.record_type}_DELETED", "PortfolioRecord", item.id, f"Deleted {item.title}")
    db.delete(item)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/api/v1/integrations", response_model=list[IntegrationOut])
def integrations(db: DB, tenant_id: Tenant):
    return db.scalars(select(IntegrationConnection).where(
        IntegrationConnection.tenant_id == tenant_id,
    ).order_by(IntegrationConnection.category, IntegrationConnection.provider)).all()


@app.patch("/api/v1/integrations/{integration_id}", response_model=IntegrationOut)
def update_integration(integration_id: str, payload: IntegrationUpdate, db: DB, tenant_id: Tenant, _: AdminUser):
    item = db.scalar(select(IntegrationConnection).where(
        IntegrationConnection.id == integration_id,
        IntegrationConnection.tenant_id == tenant_id,
    ))
    if not item:
        raise HTTPException(status_code=404, detail="Integration not found")
    item.status = payload.status
    item.last_synced_at = datetime.now(timezone.utc) if payload.status == "CONNECTED" else None
    audit(db, tenant_id, "INTEGRATION_UPDATED", "Integration", item.id, f"Set {item.provider} to {item.status}")
    db.commit()
    db.refresh(item)
    return item


def create_automation_notice(db: Session, tenant_id: str, event_key: str, event_type: str, title: str, message: str, kind: str) -> bool:
    scoped_key = f"{tenant_id}:{event_key}"
    if db.scalar(select(AutomationReceipt.id).where(AutomationReceipt.event_key == scoped_key)):
        return False
    db.add(AutomationReceipt(tenant_id=tenant_id, event_key=scoped_key, event_type=event_type))
    db.add(Notification(tenant_id=tenant_id, title=title, message=message, kind=kind))
    return True


@app.post("/api/v1/automation/run")
def run_daily_automation(db: DB, tenant_id: Tenant, _: AdminUser):
    today = date.today()
    counters = {"overdue_compliances": 0, "overdue_tasks": 0, "upcoming": 0, "expiring_documents": 0, "recurring_created": 0}
    open_statuses = {"DRAFT", "PLANNED", "NOT_STARTED", "IN_PROGRESS", "UNDER_REVIEW", "CHANGES_REQUESTED", "READY_TO_FILE", "FILED", "ON_HOLD", "OVERDUE"}
    compliances = list(db.scalars(select(Compliance).where(Compliance.tenant_id == tenant_id)).all())
    for item in compliances:
        if item.status in open_statuses and item.statutory_deadline < today:
            if item.status != "OVERDUE":
                item.status = "OVERDUE"
                item.updated_at = datetime.now(timezone.utc)
                audit(db, tenant_id, "COMPLIANCE_OVERDUE", "Compliance", item.id, f"{item.title} passed its statutory deadline")
            if create_automation_notice(db, tenant_id, f"compliance-overdue:{item.id}:{item.statutory_deadline}", "COMPLIANCE_OVERDUE", f"{item.code} is overdue", f"{item.title} was due on {item.statutory_deadline.isoformat()}.", "WARNING"):
                counters["overdue_compliances"] += 1
        elif item.status in open_statuses and 0 <= (item.statutory_deadline - today).days <= 30:
            if create_automation_notice(db, tenant_id, f"compliance-upcoming:{item.id}:{item.statutory_deadline}:30", "COMPLIANCE_UPCOMING", f"{item.code} due soon", f"{item.title} is due on {item.statutory_deadline.isoformat()}.", "REMINDER"):
                counters["upcoming"] += 1
        # Only roll forward a completed obligation once its filing/submission is
        # evidenced. This prevents prematurely recurring manually closed work.
        if item.status == "COMPLETED" and item.statutory_deadline < today and db.scalar(
            select(Submission.id).where(Submission.tenant_id == tenant_id, Submission.compliance_id == item.id)
        ):
            try:
                next_deadline = item.statutory_deadline.replace(year=item.statutory_deadline.year + 1)
            except ValueError:
                next_deadline = item.statutory_deadline.replace(year=item.statutory_deadline.year + 1, day=28)
            exists = db.scalar(select(Compliance.id).where(
                Compliance.tenant_id == tenant_id,
                Compliance.organization_id == item.organization_id,
                Compliance.code == item.code,
                Compliance.statutory_deadline == next_deadline,
            ))
            if not exists:
                rolled = Compliance(
                    tenant_id=tenant_id, organization_id=item.organization_id, code=item.code,
                    title=item.title, category=item.category, period=f"Cycle {next_deadline.year}",
                    statutory_deadline=next_deadline,
                    internal_target=next_deadline - timedelta(days=max(1, (item.statutory_deadline - item.internal_target).days)) if item.internal_target else None,
                    status="PLANNED", priority=item.priority, owner_name=item.owner_name,
                    owner_initials=item.owner_initials, progress=0, legal_reference=item.legal_reference,
                    risk_note="Rolled forward automatically; validate the configured deadline.",
                )
                db.add(rolled)
                db.flush()
                audit(db, tenant_id, "COMPLIANCE_RECURRED", "Compliance", rolled.id, f"Rolled forward {item.title} from {item.id}")
                counters["recurring_created"] += 1
    for task in db.scalars(select(Task).where(Task.tenant_id == tenant_id, Task.status != "DONE", Task.due_at < today)).all():
        if create_automation_notice(db, tenant_id, f"task-overdue:{task.id}:{task.due_at}", "TASK_OVERDUE", "Task overdue", f"{task.title} was due on {task.due_at.isoformat()}.", "WARNING"):
            counters["overdue_tasks"] += 1
    for document in db.scalars(select(Document).where(Document.tenant_id == tenant_id, Document.expiry_at.is_not(None))).all():
        days = (document.expiry_at - today).days
        if 0 <= days <= 90 and create_automation_notice(db, tenant_id, f"document-expiry:{document.id}:{document.expiry_at}:90", "DOCUMENT_EXPIRY", "Document expiry approaching", f"{document.name} expires on {document.expiry_at.isoformat()}.", "DOCUMENT"):
            counters["expiring_documents"] += 1
    audit(db, tenant_id, "AUTOMATION_RUN", "Automation", tenant_id, "Daily compliance automation completed")
    db.commit()
    return {"run_date": today, **counters}


@app.post("/api/v1/assistant/query")
def assistant_query(payload: AssistantInput, db: DB, tenant_id: Tenant):
    filters = [Compliance.tenant_id == tenant_id]
    task_filters = [Task.tenant_id == tenant_id]
    document_filters = [Document.tenant_id == tenant_id]
    if payload.organization_id:
        verify_org(db, tenant_id, payload.organization_id)
        filters.append(Compliance.organization_id == payload.organization_id)
        task_filters.append(Task.organization_id == payload.organization_id)
        document_filters.append(Document.organization_id == payload.organization_id)
    today = date.today()
    compliances = list(db.scalars(select(Compliance).where(*filters)).all())
    question = payload.question.lower()
    sources: list[dict[str, str]] = []
    if "document" in question or "expir" in question:
        rows = [item for item in db.scalars(select(Document).where(*document_filters)).all() if item.expiry_at and item.expiry_at <= today + timedelta(days=90)]
        sources = [{"type": "document", "id": item.id, "label": item.name} for item in rows[:8]]
        answer = f"I found {len(rows)} document(s) expiring within 90 days. Review their renewal owners and evidence links."
    elif "task" in question:
        rows = list(db.scalars(select(Task).where(*task_filters, Task.status != "DONE").order_by(Task.due_at)).all())
        sources = [{"type": "task", "id": item.id, "label": item.title} for item in rows[:8]]
        answer = f"There are {len(rows)} open task(s). The earliest due task is {rows[0].title} on {rows[0].due_at.isoformat()}." if rows else "There are no open tasks in this scope."
    else:
        rows = [item for item in compliances if item.status == "OVERDUE" or (item.status not in {"COMPLETED", "NOT_APPLICABLE", "CANCELLED"} and item.statutory_deadline < today)]
        high = [item for item in compliances if item.status not in {"COMPLETED", "NOT_APPLICABLE", "CANCELLED"} and item.priority in {"HIGH", "CRITICAL"}]
        sources = [{"type": "compliance", "id": item.id, "label": f"{item.code} - {item.title}"} for item in (rows or high)[:8]]
        answer = f"This scope has {len(compliances)} compliance record(s), {len(rows)} overdue and {len(high)} open high-risk item(s). Open the cited records to validate deadlines, evidence and accountable owners."
    audit(db, tenant_id, "ASSISTANT_QUERIED", "Assistant", tenant_id, "Generated a tenant-grounded operational answer")
    db.commit()
    return {"answer": answer, "sources": sources, "disclaimer": "Operational assistance only. Validate statutory requirements with a qualified professional."}
