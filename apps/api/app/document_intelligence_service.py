"""Secure document intelligence built on immutable files and existing profile services."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select

from .ai_extraction import extract_text_with_ocr_fallback
from .ai_models import DocumentExtraction
from .ai_provider import AiProviderError, configured_ocr_provider
from .ai_service import _content, _extraction, _owned_version
from .automation_service import queue_job
from .document_intelligence_models import DocumentIntelligenceRun, ExtractedDocumentFact
from .features import can_use_feature
from .models import AuditEvent, Organization, User, utcnow
from .organization_access import accessible_organization_ids, require_organization_access
from .organization_models import OrganizationDetails, OrganizationRegistration
from .organization_profile import CoreInput, DetailsInput, ProfileInput, RegistrationInput, profile_data, save_profile

FEATURE = "document_intelligence"
LOGIC_VERSION = "v1"
PENDING = {"PROPOSED", "NEEDS_REVIEW", "CONFLICT"}
DATE_PATTERN = r"(?:[0-3]?\d[/-][01]?\d[/-](?:19|20)\d{2}|(?:19|20)\d{2}-[01]\d-[0-3]\d)"


def _audit(db, tenant_id: str, actor_name: str, action: str, entity_id: str, summary: str) -> None:
    db.add(AuditEvent(tenant_id=tenant_id, actor_name=actor_name, action=action,
                      entity_type="DocumentIntelligence", entity_id=entity_id, summary=summary[:280]))


def require_entitlement(db, tenant_id: str, user) -> None:
    if getattr(user, "_admin_audience", False):
        raise HTTPException(403, "Workspace document intelligence is unavailable to platform administrator sessions")
    if not can_use_feature(db, tenant_id, FEATURE):
        raise HTTPException(403, "DOCUMENT_INTELLIGENCE_ENTITLEMENT_REQUIRED")


def _run(db, tenant_id: str, user, run_id: str, *, write: bool = False) -> DocumentIntelligenceRun:
    row = db.scalar(select(DocumentIntelligenceRun).where(
        DocumentIntelligenceRun.id == run_id, DocumentIntelligenceRun.tenant_id == tenant_id,
    ))
    if not row:
        raise HTTPException(404, "Document intelligence run not found")
    require_organization_access(db, tenant_id, row.organization_id, write=write, user_id=user.id)
    return row


def _fact(db, tenant_id: str, user, fact_id: str, *, write: bool = False) -> ExtractedDocumentFact:
    row = db.scalar(select(ExtractedDocumentFact).where(
        ExtractedDocumentFact.id == fact_id, ExtractedDocumentFact.tenant_id == tenant_id,
    ))
    if not row:
        raise HTTPException(404, "Extracted fact not found")
    require_organization_access(db, tenant_id, row.organization_id, write=write, user_id=user.id)
    return row


def _current_value(db, organization_id: str, fact_type: str) -> str:
    org = db.get(Organization, organization_id)
    if not org:
        return ""
    if fact_type == "organization.name":
        return org.name or ""
    if fact_type == "organization.pan":
        return org.pan or ""
    if fact_type.startswith("organization.details."):
        details = db.get(OrganizationDetails, organization_id)
        values = json.loads(details.facts) if details and details.facts else {}
        return str(values.get(fact_type.rsplit(".", 1)[-1]) or "")
    match = re.fullmatch(r"registration\.(12A|12AB|80G|FCRA|GST|CSR)\.(number|registration_date|effective_date|expiry_date)", fact_type)
    if match:
        row = db.scalar(select(OrganizationRegistration).where(
            OrganizationRegistration.organization_id == organization_id,
            OrganizationRegistration.kind == match.group(1),
        ))
        value = getattr(row, match.group(2), None) if row else None
        return value.isoformat() if isinstance(value, date) else str(value or "")
    return ""


def request_run(db, tenant_id: str, user, version_id: str, *, reprocess: bool = False) -> dict:
    require_entitlement(db, tenant_id, user)
    if user.role == "VIEWER":
        raise HTTPException(403, "Read-only accounts cannot request document intelligence")
    blob, document = _owned_version(db, tenant_id, user, version_id, write=True)
    previous_attempt = db.scalar(select(func.max(DocumentIntelligenceRun.attempt)).where(
        DocumentIntelligenceRun.tenant_id == tenant_id,
        DocumentIntelligenceRun.version_id == version_id,
        DocumentIntelligenceRun.logic_version == LOGIC_VERSION,
    )) or 0
    if previous_attempt and not reprocess:
        existing = db.scalar(select(DocumentIntelligenceRun).where(
            DocumentIntelligenceRun.tenant_id == tenant_id,
            DocumentIntelligenceRun.version_id == version_id,
            DocumentIntelligenceRun.logic_version == LOGIC_VERSION,
            DocumentIntelligenceRun.attempt == previous_attempt,
        ))
        return run_data(db, existing)
    attempt = previous_attempt + 1
    request_key = f"{version_id}:{LOGIC_VERSION}:{attempt}:{blob.checksum}"
    run = DocumentIntelligenceRun(
        tenant_id=tenant_id, organization_id=document.organization_id, document_id=document.id,
        version_id=version_id, requested_by=user.id, request_key=request_key,
        logic_version=LOGIC_VERSION, attempt=attempt, source_checksum=blob.checksum,
    )
    db.add(run)
    db.flush()
    queue_job(db, tenant_id, "DOCUMENT_INTELLIGENCE", f"document-intelligence:{request_key}",
              entity_type="DocumentIntelligenceRun", entity_id=run.id,
              payload={"run_id": run.id}, max_attempts=3)
    _audit(db, tenant_id, user.name, "DOCUMENT_INTELLIGENCE_REPROCESS_REQUESTED" if reprocess else "DOCUMENT_INTELLIGENCE_REQUESTED",
           run.id, f"Queued intelligence for immutable document version {version_id}")
    db.commit()
    return run_data(db, run)


def _classify(text: str) -> tuple[str, float, str]:
    lowered = text.lower()
    choices = (
        ("FCRA", ("fcra", "foreign contribution regulation")),
        ("80G", ("80g", "section 80g")),
        ("12AB", ("12ab", "section 12ab")),
        ("12A", ("12a", "section 12a")),
        ("GST", ("gstin", "goods and services tax")),
        ("PAN", ("permanent account number", "income tax department")),
        ("FILING_ACKNOWLEDGEMENT", ("acknowledgement number", "filing acknowledgement")),
        ("AUDIT_FINANCIAL", ("audit report", "balance sheet", "financial statements")),
        ("REGISTRATION_CERTIFICATE", ("registration certificate", "certificate of registration")),
    )
    for category, signals in choices:
        hits = [signal for signal in signals if signal in lowered]
        if hits:
            confidence = 0.92 if len(hits) > 1 else 0.78
            return category, confidence, ", ".join(hits)[:500]
    return "UNKNOWN", 0.2, "No sufficiently specific classification signal"


def _date_value(raw: str) -> str | None:
    value = raw.strip().replace("/", "-")
    parts = value.split("-")
    try:
        if len(parts[0]) == 4:
            return date.fromisoformat(value).isoformat()
        return date(int(parts[2]), int(parts[1]), int(parts[0])).isoformat()
    except (ValueError, IndexError):
        return None


def _candidates(text: str, category: str) -> list[tuple[str, str, float, str, str]]:
    candidates: list[tuple[str, str, float, str, str]] = []
    def add(kind: str, value: str, confidence: float, match: re.Match | None, validation: str = "VALID"):
        excerpt = text[max(0, (match.start() if match else 0) - 80):min(len(text), (match.end() if match else 0) + 80)]
        candidates.append((kind, value.strip(), confidence, excerpt.replace("\n", " ")[:500], validation))
    for kind, pattern in (("organization.pan", r"\b[A-Z]{5}[0-9]{4}[A-Z]\b"),
                          ("organization.details.tan", r"\b[A-Z]{4}[0-9]{5}[A-Z]\b")):
        match = re.search(pattern, text.upper())
        if match:
            add(kind, match.group(0), 0.95, match)
    name = re.search(r"(?:name of (?:the )?(?:organisation|organization|trust|society)|issued to)\s*[:\-]\s*([^\n]{3,200})", text, re.I)
    if name:
        add("organization.name", name.group(1), 0.82, name)
    authority = re.search(r"(?:issuing authority|issued by|authority)\s*[:\-]\s*([^\n]{3,200})", text, re.I)
    if authority:
        add("organization.details.registration_authority", authority.group(1), 0.78, authority)
    registration_kind = category if category in {"12A", "12AB", "80G", "FCRA", "GST"} else None
    if registration_kind:
        number = re.search(r"(?:registration|certificate|reference|gstin)\s*(?:number|no\.?|ref\.?)?\s*[:\-]\s*([A-Z0-9/\-]{4,100})", text, re.I)
        if number:
            add(f"registration.{registration_kind}.number", number.group(1).upper(), 0.88, number)
        for field, labels in (("effective_date", "effective date|valid from|issue date"), ("expiry_date", "expiry date|valid until|valid upto")):
            match = re.search(rf"(?:{labels})\s*[:\-]\s*({DATE_PATTERN})", text, re.I)
            if match:
                parsed = _date_value(match.group(1))
                add(f"registration.{registration_kind}.{field}", parsed or match.group(1), 0.86 if parsed else 0.4, match,
                    "VALID" if parsed else "INVALID_FORMAT")
    acknowledgement = re.search(r"(?:acknowledgement|acknowledgment)(?: number| no\.?| reference)?\s*[:\-]\s*([A-Z0-9/\-]{4,100})", text, re.I)
    if acknowledgement:
        add("filing.acknowledgement_reference", acknowledgement.group(1), 0.9, acknowledgement)
    period = re.search(r"(?:financial year|assessment year|period)\s*[:\-]\s*([0-9]{4}\s*[-/]\s*[0-9]{2,4})", text, re.I)
    if period:
        add("filing.period", period.group(1), 0.82, period)
    return candidates[:20]


def process_run(db, run_id: str, *, retry_attempt: int | None = None, max_attempts: int | None = None) -> dict:
    run = db.get(DocumentIntelligenceRun, run_id)
    if not run:
        raise ValueError("Document intelligence run not found")
    if run.status in {"READY_FOR_REVIEW", "COMPLETED"}:
        return {"run_id": run.id, "status": run.status, "idempotent": True}
    user = db.get(User, run.requested_by)
    if not user or user.tenant_id != run.tenant_id:
        raise ValueError("Invalid document intelligence actor")
    run.status = "EXTRACTING"
    run.started_at = run.updated_at = utcnow()
    try:
        blob, document = _owned_version(db, run.tenant_id, user, run.version_id)
        if blob.checksum != run.source_checksum:
            raise ValueError("Immutable source checksum changed")
        content = _content(db, run.tenant_id, blob)
        text, extractor, used_ocr = extract_text_with_ocr_fallback(
            content,
            blob.mime_type,
            lambda: configured_ocr_provider(db, run.tenant_id),
        )
        extraction = _extraction(db, blob)
        extraction.normalized_text = text
        extraction.text_checksum = hashlib.sha256(text.encode()).hexdigest()
        extraction.extractor = extractor
        extraction.status = "COMPLETED"
        extraction.error_code = ""
        extraction.started_at = run.started_at
        extraction.completed_at = extraction.updated_at = utcnow()
        run.status = "CLASSIFYING"
        run.extraction_method = extractor
        category, confidence, evidence = _classify(text)
        run.proposed_document_type = category
        run.classification_confidence = confidence
        run.classification_evidence = evidence
        run.status = "EXTRACTING_FACTS"
        for fact_type, value, fact_confidence, excerpt, validation in _candidates(text, category):
            fingerprint = hashlib.sha256(f"{fact_type}:{value}:{excerpt}".encode()).hexdigest()
            if db.scalar(select(ExtractedDocumentFact.id).where(
                ExtractedDocumentFact.run_id == run.id,
                ExtractedDocumentFact.fingerprint == fingerprint,
            )):
                continue
            fact = ExtractedDocumentFact(
                run_id=run.id, tenant_id=run.tenant_id, organization_id=run.organization_id,
                document_id=run.document_id, version_id=run.version_id, fact_type=fact_type,
                proposed_value=value, current_value_snapshot=_current_value(db, run.organization_id, fact_type),
                source_location="normalized document text", source_excerpt=excerpt,
                extraction_method=extractor, confidence=fact_confidence,
                validation_state=validation,
                status="PROPOSED" if validation == "VALID" and fact_confidence >= 0.75 else "NEEDS_REVIEW",
                fingerprint=fingerprint,
            )
            db.add(fact)
            db.flush()
            _audit(db, run.tenant_id, user.name, "DOCUMENT_FACT_PROPOSED", fact.id,
                   f"Proposed {fact_type} from version {run.version_id}")
        run.status = "READY_FOR_REVIEW"
        run.completed_at = run.updated_at = utcnow()
        _audit(db, run.tenant_id, user.name, "DOCUMENT_INTELLIGENCE_COMPLETED", run.id,
               f"Extraction completed with {extractor}; OCR used: {used_ocr}; classification: {category}")
        return {"run_id": run.id, "status": run.status, "ocr_used": used_ocr}
    except AiProviderError as error:
        retryable = error.code in {"RATE_LIMITED", "PROVIDER_UNAVAILABLE", "TIMEOUT"}
        will_retry = retryable and retry_attempt is not None and max_attempts is not None and retry_attempt < max_attempts
        run.status = "RETRYING" if will_retry else "FAILED"
        run.error_code = error.code
        run.completed_at = None if will_retry else utcnow()
        run.updated_at = utcnow()
        extraction = db.get(DocumentExtraction, run.version_id)
        if extraction:
            extraction.status = "RETRYING" if will_retry else "FAILED"
            extraction.error_code = error.code
            extraction.updated_at = utcnow()
        _audit(db, run.tenant_id, user.name, "DOCUMENT_INTELLIGENCE_FAILED", run.id,
               f"Document intelligence failed with safe error {error.code}")
        if will_retry:
            db.commit()
            raise
        return {"run_id": run.id, "status": run.status, "error_code": error.code}


def process_job(db, job, _today) -> dict:
    payload = json.loads(job.payload)
    run = db.scalar(select(DocumentIntelligenceRun).where(
        DocumentIntelligenceRun.id == payload.get("run_id"),
        DocumentIntelligenceRun.tenant_id == job.tenant_id,
    ))
    if not run or run.id != job.entity_id:
        raise ValueError("Invalid document intelligence job context")
    return process_run(db, run.id, retry_attempt=job.attempt_count, max_attempts=job.max_attempts)


def fact_data(fact: ExtractedDocumentFact, db=None) -> dict:
    result = {key: getattr(fact, key) for key in (
        "id", "run_id", "tenant_id", "organization_id", "document_id", "version_id", "fact_type",
        "proposed_value", "reviewed_value", "current_value_snapshot", "source_location", "source_excerpt",
        "extraction_method", "confidence", "validation_state", "status", "reviewed_at", "applied_at", "extracted_at",
    )}
    result["current_authoritative_value"] = _current_value(db, fact.organization_id, fact.fact_type) if db else fact.current_value_snapshot
    return result


def run_data(db, run: DocumentIntelligenceRun) -> dict:
    facts = db.scalars(select(ExtractedDocumentFact).where(
        ExtractedDocumentFact.run_id == run.id,
        ExtractedDocumentFact.tenant_id == run.tenant_id,
    ).order_by(ExtractedDocumentFact.extracted_at, ExtractedDocumentFact.id)).all()
    return {key: getattr(run, key) for key in (
        "id", "tenant_id", "organization_id", "document_id", "version_id", "logic_version", "attempt", "status",
        "extraction_method", "proposed_document_type", "classification_confidence", "classification_evidence",
        "error_code", "created_at", "started_at", "completed_at", "updated_at",
    )} | {"facts": [fact_data(row, db) for row in facts]}


def version_runs(db, tenant_id: str, user, version_id: str) -> list[dict]:
    require_entitlement(db, tenant_id, user)
    _owned_version(db, tenant_id, user, version_id)
    rows = db.scalars(select(DocumentIntelligenceRun).where(
        DocumentIntelligenceRun.tenant_id == tenant_id,
        DocumentIntelligenceRun.version_id == version_id,
    ).order_by(DocumentIntelligenceRun.attempt.desc())).all()
    return [run_data(db, row) for row in rows]


def review_queue(db, tenant_id: str, user, organization_id: str | None = None) -> list[dict]:
    require_entitlement(db, tenant_id, user)
    permitted = accessible_organization_ids(db, tenant_id, user.id)
    statement = select(ExtractedDocumentFact).where(
        ExtractedDocumentFact.tenant_id == tenant_id,
        ExtractedDocumentFact.status.in_(PENDING),
    )
    if permitted is not None:
        statement = statement.where(ExtractedDocumentFact.organization_id.in_(permitted))
    if organization_id:
        require_organization_access(db, tenant_id, organization_id, user_id=user.id)
        statement = statement.where(ExtractedDocumentFact.organization_id == organization_id)
    return [fact_data(row, db) for row in db.scalars(statement.order_by(ExtractedDocumentFact.extracted_at.desc()).limit(200)).all()]


def _complete_run_if_reviewed(db, run_id: str) -> None:
    pending = db.scalar(select(ExtractedDocumentFact.id).where(
        ExtractedDocumentFact.run_id == run_id,
        ExtractedDocumentFact.status.in_(("PROPOSED", "NEEDS_REVIEW", "CONFLICT")),
    ).limit(1))
    if not pending:
        run = db.get(DocumentIntelligenceRun, run_id)
        if run:
            run.status = "COMPLETED"
            run.updated_at = utcnow()


def _apply_fact(db, tenant_id: str, user, fact: ExtractedDocumentFact, value: str) -> bool:
    if fact.fact_type.startswith("filing."):
        return False
    data = profile_data(db, db.get(Organization, fact.organization_id))
    if fact.fact_type in {"organization.name", "organization.pan"}:
        core = dict(data["core"])
        allowed = set(CoreInput.model_fields)
        core = {key: core[key] for key in allowed}
        core[fact.fact_type.rsplit(".", 1)[-1]] = value
        payload = ProfileInput(expected_revision=data["revision"], core=CoreInput.model_validate(core))
    elif fact.fact_type.startswith("organization.details."):
        field = fact.fact_type.rsplit(".", 1)[-1]
        payload = ProfileInput(expected_revision=data["revision"], details=DetailsInput.model_validate({field: value}))
    else:
        match = re.fullmatch(r"registration\.(12A|12AB|80G|FCRA|GST|CSR)\.(number|registration_date|effective_date|expiry_date)", fact.fact_type)
        if not match:
            return False
        current = next(item for item in data["registrations"] if item["kind"] == match.group(1))
        current[match.group(2)] = value or None
        current["document_id"] = fact.document_id
        payload = ProfileInput(expected_revision=data["revision"], registrations=[RegistrationInput.model_validate(current)])
    save_profile(fact.organization_id, payload, db, tenant_id, user, commit=False)
    return True


def approve_fact(db, tenant_id: str, user, fact_id: str, edited_value: str | None = None) -> dict:
    require_entitlement(db, tenant_id, user)
    if user.role == "VIEWER":
        raise HTTPException(403, "Read-only accounts cannot approve extracted facts")
    fact = _fact(db, tenant_id, user, fact_id, write=True)
    if fact.status in {"APPLIED", "APPROVED"}:
        return fact_data(fact, db)
    if fact.status == "REJECTED":
        raise HTTPException(409, "Rejected facts cannot be approved")
    value = (edited_value if edited_value is not None else fact.proposed_value).strip()
    if not value or len(value) > 2000:
        raise HTTPException(422, "Approved value is invalid")
    current = _current_value(db, fact.organization_id, fact.fact_type)
    if current != fact.current_value_snapshot:
        fact.status = "CONFLICT"
        _audit(db, tenant_id, user.name, "DOCUMENT_FACT_CONFLICT", fact.id,
               "Authoritative value changed after extraction; approval was not applied")
        db.commit()
        raise HTTPException(409, "Authoritative value changed; review the current value before approving")
    if edited_value is not None and value != fact.proposed_value:
        _audit(db, tenant_id, user.name, "DOCUMENT_FACT_EDITED", fact.id, "Reviewer edited a proposed value")
    candidate_key = f"{fact.version_id}:{fact.fact_type}:{hashlib.sha256(value.encode()).hexdigest()}"
    already_applied = db.scalar(select(ExtractedDocumentFact.id).where(
        ExtractedDocumentFact.tenant_id == tenant_id,
        ExtractedDocumentFact.applied_key == candidate_key,
    ))
    try:
        applied = bool(already_applied) or _apply_fact(db, tenant_id, user, fact, value)
    except ValidationError as error:
        raise HTTPException(422, "Approved value does not satisfy the platform field validation") from None
    fact.reviewed_value = value
    fact.reviewed_by = user.id
    fact.reviewed_at = utcnow()
    fact.status = "APPLIED" if applied else "APPROVED"
    if applied:
        fact.applied_at = utcnow()
        if not already_applied:
            fact.applied_key = candidate_key
    _audit(db, tenant_id, user.name, "DOCUMENT_FACT_APPLIED" if applied else "DOCUMENT_FACT_APPROVED",
           fact.id, f"Human reviewed {fact.fact_type}; source version {fact.version_id}")
    _complete_run_if_reviewed(db, fact.run_id)
    db.commit()
    return fact_data(fact, db)


def reject_fact(db, tenant_id: str, user, fact_id: str) -> dict:
    require_entitlement(db, tenant_id, user)
    if user.role == "VIEWER":
        raise HTTPException(403, "Read-only accounts cannot reject extracted facts")
    fact = _fact(db, tenant_id, user, fact_id, write=True)
    if fact.status in {"APPLIED", "APPROVED"}:
        raise HTTPException(409, "Reviewed facts cannot be rejected")
    fact.status = "REJECTED"
    fact.reviewed_by = user.id
    fact.reviewed_at = utcnow()
    _audit(db, tenant_id, user.name, "DOCUMENT_FACT_REJECTED", fact.id,
           f"Rejected proposed {fact.fact_type} from version {fact.version_id}")
    _complete_run_if_reviewed(db, fact.run_id)
    db.commit()
    return fact_data(fact, db)
