"""Source-grounded, advisory-only compliance assistant service."""
from __future__ import annotations

import json
from datetime import date, timedelta

from fastapi import HTTPException
from sqlalchemy import or_, select

from .ai_assistant_models import AiConversation, AiMessage
from .ai_provider import AiProviderError, configured_provider, safe_provider_call
from .ai_service import (
    RetrievalFilters,
    TRUSTED_RAG_INSTRUCTIONS,
    boundary_json,
    build_context,
    require_workspace_ai,
    retrieve,
)
from .document_models import DocumentCurrent, DocumentEvidenceLink
from .document_intelligence_models import ExtractedDocumentFact
from .models import AuditEvent, Compliance, ComplianceSnapshot, Document, Organization, Submission, Task, utcnow
from .organization_access import require_organization_access
from .phase9_models import ComplianceApproval, ComplianceReview
from .runtime_models import ApplicabilityDecision

MAX_HISTORY = 12
MAX_STRUCTURED_SOURCES = 250
MAX_ANSWER_CHARACTERS = 20_000

ASSISTANT_INSTRUCTIONS = TRUSTED_RAG_INSTRUCTIONS + """
The trusted platform facts are authoritative for operational state. Never contradict or replace their values.
Clearly distinguish platform facts, document-derived information, and advisory explanation.
Document facts marked PROPOSED, NEEDS_REVIEW, CONFLICT, or APPROVED are non-authoritative suggestions; only APPLIED values are authoritative through the platform record.
Do not invent records, citations, laws, forms, deadlines, approvals, applicability, or filing state.
Do not give legal advice. If evidence is insufficient, say so plainly.
Never claim to execute an action. Do not put proposed actions in the answer narrative.
If a useful next step is warranted, put it on a separate line beginning exactly 'PROPOSED ACTION:'.
Do not emit source identifiers or citations in the narrative; the application attaches verified sources separately."""


def require_assistant(db, tenant_id: str, user) -> None:
    require_workspace_ai(db, tenant_id, user)
    if user.role == "VIEWER":
        raise HTTPException(403, "Read-only accounts cannot use the AI assistant")


def _organization(db, tenant_id: str, user, organization_id: str) -> Organization:
    row = db.scalar(select(Organization).where(
        Organization.id == organization_id,
        Organization.tenant_id == tenant_id,
    ))
    if not row:
        raise HTTPException(404, "Organization not found")
    require_organization_access(db, tenant_id, row.id, user_id=user.id)
    return row


def _conversation(db, tenant_id: str, user, conversation_id: str) -> AiConversation:
    row = db.scalar(select(AiConversation).where(
        AiConversation.id == conversation_id,
        AiConversation.tenant_id == tenant_id,
        AiConversation.created_by == user.id,
        AiConversation.status == "ACTIVE",
    ))
    if not row:
        raise HTTPException(404, "Conversation not found")
    _organization(db, tenant_id, user, row.organization_id)
    return row


def _json(value: str) -> list[dict]:
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except (TypeError, ValueError):
        return []


def message_data(row: AiMessage) -> dict:
    return {
        "id": row.id, "conversation_id": row.conversation_id, "role": row.role,
        "content": row.content, "structured_sources": _json(row.structured_sources),
        "document_sources": _json(row.document_sources), "proposed_actions": _json(row.proposed_actions),
        "insufficient_evidence": row.insufficient_evidence,
        "provider": row.provider, "model": row.model, "created_at": row.created_at,
    }


def conversation_data(row: AiConversation, messages: list[AiMessage] | None = None) -> dict:
    value = {
        "id": row.id, "organization_id": row.organization_id, "title": row.title,
        "status": row.status, "created_at": row.created_at, "updated_at": row.updated_at,
    }
    if messages is not None:
        value["messages"] = [message_data(message) for message in messages]
    return value


def create_conversation(db, tenant_id: str, user, organization_id: str, title: str = "") -> dict:
    require_assistant(db, tenant_id, user)
    _organization(db, tenant_id, user, organization_id)
    row = AiConversation(
        tenant_id=tenant_id, organization_id=organization_id, created_by=user.id,
        title=(title.strip() or "New conversation")[:160],
    )
    db.add(row); db.flush()
    db.add(AuditEvent(tenant_id=tenant_id, actor_name=user.name, action="AI_CONVERSATION_CREATED",
                      entity_type="AI", entity_id=row.id, summary=f"Created assistant conversation for organization {organization_id}"))
    db.commit(); db.refresh(row)
    return conversation_data(row, [])


def list_conversations(db, tenant_id: str, user, organization_id: str) -> list[dict]:
    require_assistant(db, tenant_id, user)
    _organization(db, tenant_id, user, organization_id)
    rows = db.scalars(select(AiConversation).where(
        AiConversation.tenant_id == tenant_id,
        AiConversation.organization_id == organization_id,
        AiConversation.created_by == user.id,
        AiConversation.status == "ACTIVE",
    ).order_by(AiConversation.updated_at.desc()).limit(50)).all()
    return [conversation_data(row) for row in rows]


def get_conversation(db, tenant_id: str, user, conversation_id: str) -> dict:
    require_assistant(db, tenant_id, user)
    row = _conversation(db, tenant_id, user, conversation_id)
    messages = db.scalars(select(AiMessage).where(
        AiMessage.conversation_id == row.id,
        AiMessage.tenant_id == tenant_id,
        AiMessage.organization_id == row.organization_id,
        AiMessage.user_id == user.id,
    ).order_by(AiMessage.created_at, AiMessage.id).limit(200)).all()
    return conversation_data(row, messages)


def _validate_targets(db, tenant_id: str, organization_id: str,
                      compliance_id: str | None, document_id: str | None) -> tuple[Compliance | None, Document | None]:
    compliance = None
    document = None
    if compliance_id:
        compliance = db.scalar(select(Compliance).where(
            Compliance.id == compliance_id, Compliance.tenant_id == tenant_id,
            Compliance.organization_id == organization_id,
        ))
        if not compliance:
            raise HTTPException(404, "Compliance not found")
    if document_id:
        document = db.scalar(select(Document).where(
            Document.id == document_id, Document.tenant_id == tenant_id,
            Document.organization_id == organization_id,
        ))
        if not document:
            raise HTTPException(404, "Document not found")
        if compliance and document.compliance_id != compliance.id:
            linked = db.scalar(select(DocumentEvidenceLink.id).where(
                DocumentEvidenceLink.tenant_id == tenant_id,
                DocumentEvidenceLink.organization_id == organization_id,
                DocumentEvidenceLink.document_id == document.id,
                DocumentEvidenceLink.compliance_id == compliance.id,
                DocumentEvidenceLink.active.is_(True),
            ).limit(1))
            if not linked:
                raise HTTPException(422, "Document does not belong to the selected compliance")
    return compliance, document


def _source(kind: str, identifier: str, label: str, facts: dict) -> dict:
    return {"type": kind, "id": identifier, "label": label, "facts": facts}


def structured_sources(db, tenant_id: str, organization: Organization,
                       compliance: Compliance | None, document: Document | None) -> list[dict]:
    compliance_query = select(Compliance).where(
        Compliance.tenant_id == tenant_id, Compliance.organization_id == organization.id,
    )
    if compliance:
        compliance_query = compliance_query.where(Compliance.id == compliance.id)
    compliances = db.scalars(compliance_query.order_by(Compliance.statutory_deadline, Compliance.id).limit(75)).all()
    compliance_ids = [row.id for row in compliances]

    task_query = select(Task).where(Task.tenant_id == tenant_id, Task.organization_id == organization.id)
    if compliance:
        task_query = task_query.where(Task.compliance_id == compliance.id)
    tasks = db.scalars(task_query.order_by(Task.due_at, Task.id).limit(100)).all()

    document_query = select(Document).where(Document.tenant_id == tenant_id, Document.organization_id == organization.id)
    if document:
        document_query = document_query.where(Document.id == document.id)
    elif compliance:
        linked_document_ids = select(DocumentEvidenceLink.document_id).where(
            DocumentEvidenceLink.tenant_id == tenant_id,
            DocumentEvidenceLink.organization_id == organization.id,
            DocumentEvidenceLink.compliance_id == compliance.id,
            DocumentEvidenceLink.active.is_(True),
        )
        document_query = document_query.where(or_(Document.compliance_id == compliance.id, Document.id.in_(linked_document_ids)))
    documents = db.scalars(document_query.order_by(Document.created_at.desc(), Document.id).limit(100)).all()
    document_ids = [row.id for row in documents]

    submissions = db.scalars(select(Submission).where(
        Submission.tenant_id == tenant_id,
        Submission.compliance_id.in_(compliance_ids),
    ).order_by(Submission.submitted_at.desc()).limit(100)).all() if compliance_ids else []
    reviews = db.scalars(select(ComplianceReview).where(
        ComplianceReview.tenant_id == tenant_id,
        ComplianceReview.organization_id == organization.id,
        ComplianceReview.compliance_id.in_(compliance_ids),
    ).order_by(ComplianceReview.submitted_at.desc()).limit(100)).all() if compliance_ids else []
    approvals = db.scalars(select(ComplianceApproval).where(
        ComplianceApproval.tenant_id == tenant_id,
        ComplianceApproval.organization_id == organization.id,
        ComplianceApproval.compliance_id.in_(compliance_ids),
    ).order_by(ComplianceApproval.requested_at.desc()).limit(100)).all() if compliance_ids else []

    task_ids = [row.id for row in tasks]
    submission_ids = [row.id for row in submissions]
    link_scope = []
    if compliance_ids:
        link_scope.append(DocumentEvidenceLink.compliance_id.in_(compliance_ids))
    if task_ids:
        link_scope.append(DocumentEvidenceLink.task_id.in_(task_ids))
    if submission_ids:
        link_scope.append(DocumentEvidenceLink.submission_id.in_(submission_ids))
    if document_ids:
        link_scope.append(DocumentEvidenceLink.document_id.in_(document_ids))
    links = db.scalars(select(DocumentEvidenceLink).where(
        DocumentEvidenceLink.tenant_id == tenant_id,
        DocumentEvidenceLink.organization_id == organization.id,
        DocumentEvidenceLink.active.is_(True),
        or_(*link_scope),
    ).limit(150)).all() if link_scope else []

    snapshots = db.scalars(select(ComplianceSnapshot).where(
        ComplianceSnapshot.compliance_id.in_(compliance_ids),
        ComplianceSnapshot.tenant_id == tenant_id,
    )).all() if compliance_ids else []
    template_to_compliance = {row.definition_id: row.compliance_id for row in snapshots}
    decisions = db.scalars(select(ApplicabilityDecision).where(
        ApplicabilityDecision.tenant_id == tenant_id,
        ApplicabilityDecision.organization_id == organization.id,
        ApplicabilityDecision.template_id.in_(list(template_to_compliance)),
    ).order_by(ApplicabilityDecision.evaluated_at.desc(), ApplicabilityDecision.id.desc())).all() if template_to_compliance else []

    output = []
    today = date.today()
    for row in compliances:
        output.append(_source("compliance", row.id, f"{row.code} — {row.title}", {
            "status": row.status, "statutory_deadline": row.statutory_deadline.isoformat(),
            "internal_target": row.internal_target.isoformat() if row.internal_target else None,
            "priority": row.priority, "owner": row.owner_name,
            "overdue": row.status not in {"COMPLETED", "CANCELLED", "NOT_APPLICABLE"} and row.statutory_deadline < today,
            "due_within_30_days": today <= row.statutory_deadline <= today + timedelta(days=30),
        }))
    for row in tasks:
        output.append(_source("task", row.id, row.title, {
            "compliance_id": row.compliance_id, "status": row.status, "due_at": row.due_at.isoformat(),
            "priority": row.priority, "assignee": row.assignee_name,
            "incomplete": row.status != "DONE", "overdue": row.status != "DONE" and row.due_at < today,
        }))
    current_versions = dict(db.execute(select(DocumentCurrent.document_id, DocumentCurrent.version_id).where(
        DocumentCurrent.tenant_id == tenant_id, DocumentCurrent.document_id.in_(document_ids),
        DocumentCurrent.archived.is_(False),
    )).all()) if document_ids else {}
    for row in documents:
        output.append(_source("document", row.id, row.name, {
            "compliance_id": row.compliance_id, "category": row.category, "file_type": row.file_type,
            "current_version_id": current_versions.get(row.id),
            "expiry_at": row.expiry_at.isoformat() if row.expiry_at else None,
        }))
    extracted_facts = db.scalars(select(ExtractedDocumentFact).where(
        ExtractedDocumentFact.tenant_id == tenant_id,
        ExtractedDocumentFact.organization_id == organization.id,
        ExtractedDocumentFact.document_id.in_(document_ids),
        ExtractedDocumentFact.status.in_(("PROPOSED", "NEEDS_REVIEW", "CONFLICT", "APPROVED", "APPLIED")),
    ).order_by(ExtractedDocumentFact.extracted_at.desc()).limit(100)).all() if document_ids else []
    for row in extracted_facts:
        output.append(_source(
            "document_fact_applied" if row.status == "APPLIED" else "document_fact_proposed",
            row.id, row.fact_type,
            {"value": row.reviewed_value or row.proposed_value, "review_status": row.status,
             "authoritative": row.status == "APPLIED", "document_id": row.document_id,
             "version_id": row.version_id, "confidence": row.confidence,
             "source_location": row.source_location},
        ))
    document_names = {row.id: row.name for row in documents}
    for row in links:
        output.append(_source("evidence", row.id, document_names.get(row.document_id, "Evidence document"), {
            "document_id": row.document_id, "version_id": row.version_id,
            "compliance_id": row.compliance_id, "task_id": row.task_id, "submission_id": row.submission_id,
        }))
    for row in submissions:
        output.append(_source("filing", row.id, f"Filing {row.acknowledgement_ref or 'without reference'}", {
            "compliance_id": row.compliance_id, "reference": row.acknowledgement_ref,
            "proof_document_id": row.proof_document_id, "proof_version_id": row.proof_version_id,
            "proof_type": row.proof_type, "filing_channel": row.filing_channel,
            "filed_at": row.filed_at.isoformat() if row.filed_at else None,
        }))
    for row in reviews:
        output.append(_source("review", row.id, f"Review revision {row.revision}", {
            "compliance_id": row.compliance_id, "decision": row.decision,
            "submitted_at": row.submitted_at.isoformat(), "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
        }))
    for row in approvals:
        output.append(_source("approval", row.id, f"Approval revision {row.revision}", {
            "compliance_id": row.compliance_id, "target_status": row.target_status, "decision": row.decision,
            "requested_at": row.requested_at.isoformat(), "decided_at": row.decided_at.isoformat() if row.decided_at else None,
        }))
    seen_templates = set()
    for row in decisions:
        if row.template_id in seen_templates:
            continue
        seen_templates.add(row.template_id)
        output.append(_source("applicability", row.id, "Applicability decision", {
            "compliance_id": template_to_compliance[row.template_id], "rule_result": row.rule_result,
            "effective_result": row.effective_result, "reason": row.reason,
            "evaluated_at": row.evaluated_at.isoformat(),
        }))
    return output[:MAX_STRUCTURED_SOURCES]


def _history(db, conversation: AiConversation, user_id: str) -> list[dict]:
    rows = db.scalars(select(AiMessage).where(
        AiMessage.conversation_id == conversation.id,
        AiMessage.tenant_id == conversation.tenant_id,
        AiMessage.organization_id == conversation.organization_id,
        AiMessage.user_id == user_id,
    ).order_by(AiMessage.created_at.desc(), AiMessage.id.desc()).limit(MAX_HISTORY)).all()
    return [{"role": row.role.lower(), "content": row.content[:4000]} for row in reversed(rows)]


def _split_proposed_actions(value: str) -> tuple[str, list[dict]]:
    answer = []
    proposed = []
    for line in value.strip().splitlines():
        if line.strip().upper().startswith("PROPOSED ACTION:"):
            description = line.split(":", 1)[1].strip()
            if description and len(proposed) < 5:
                proposed.append({"type": "PROPOSED_ACTION", "description": description[:500], "executable": False})
        else:
            answer.append(line)
    return "\n".join(answer).strip()[:MAX_ANSWER_CHARACTERS], proposed


def ask(db, tenant_id: str, user, conversation_id: str, question: str,
        compliance_id: str | None = None, document_id: str | None = None) -> dict:
    require_assistant(db, tenant_id, user)
    conversation = _conversation(db, tenant_id, user, conversation_id)
    organization = _organization(db, tenant_id, user, conversation.organization_id)
    compliance, document = _validate_targets(
        db, tenant_id, organization.id, compliance_id, document_id,
    )
    configured = configured_provider(db, tenant_id)
    facts = structured_sources(db, tenant_id, organization, compliance, document)
    retrieval = retrieve(db, tenant_id, user, question, 6, RetrievalFilters(
        organization_id=organization.id,
        compliance_id=compliance.id if compliance else None,
        document_id=document.id if document else None,
    ))
    documents = [item["source"] | {"chunk_id": item["chunk_id"]} for item in retrieval["results"]]
    insufficient = not facts and not documents
    proposed = []
    if insufficient:
        answer = "The available authorized platform records and indexed evidence are insufficient to answer this question."
    else:
        user_context = (
            '<trusted_platform_facts_json trust="authoritative">\n'
            + boundary_json(facts)
            + '\n</trusted_platform_facts_json>\n<conversation_history_json trust="untrusted_application_input">\n'
            + boundary_json(_history(db, conversation, user.id))
            + "\n</conversation_history_json>\n"
            + build_context(question, retrieval)
        )
        generated = safe_provider_call(lambda: configured.provider.generate(
            system=ASSISTANT_INSTRUCTIONS, user=user_context,
            model=configured.configuration.generation_model,
            timeout_seconds=configured.configuration.timeout_seconds,
        ))
        if not isinstance(generated, str) or not generated.strip():
            raise AiProviderError("PROVIDER_UNAVAILABLE")
        answer, proposed = _split_proposed_actions(generated)
        if not answer:
            answer = "The provider returned no advisory explanation. Review the verified sources below."

    now = utcnow()
    if conversation.title == "New conversation":
        conversation.title = question.strip()[:157] + ("…" if len(question.strip()) > 157 else "")
    conversation.updated_at = now
    user_message = AiMessage(
        conversation_id=conversation.id, tenant_id=tenant_id, organization_id=organization.id,
        user_id=user.id, role="USER", content=question.strip(),
    )
    assistant_message = AiMessage(
        conversation_id=conversation.id, tenant_id=tenant_id, organization_id=organization.id,
        user_id=user.id, role="ASSISTANT", content=answer,
        structured_sources=json.dumps(facts, separators=(",", ":")),
        document_sources=json.dumps(documents, separators=(",", ":")),
        proposed_actions=json.dumps(proposed, separators=(",", ":")),
        insufficient_evidence=insufficient,
        provider=configured.configuration.provider,
        model=configured.configuration.generation_model,
    )
    db.add_all((user_message, assistant_message))
    db.add(AuditEvent(
        tenant_id=tenant_id, actor_name=user.name, action="AI_ASSISTANT_ANSWERED",
        entity_type="AI", entity_id=conversation.id,
        summary=(f"Answered from {len(facts)} structured source(s) and {len(documents)} authorized document source(s) "
                 f"for organization {organization.id} using {configured.configuration.provider}/{configured.configuration.generation_model}")[:280],
    ))
    db.commit(); db.refresh(assistant_message)
    return message_data(assistant_message)
