from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    AuditEvent,
    Compliance,
    ComplianceDefinition,
    Document,
    DocumentVersion,
    IntegrationConnection,
    Membership,
    Notification,
    Organization,
    PortfolioRecord,
    Subscription,
    Task,
)


TENANT_ID = "tenant-demo"


def seed_demo_data(db: Session) -> None:
    if db.scalar(select(Organization.id).where(Organization.tenant_id == TENANT_ID).limit(1)):
        seed_extended_data(db)
        return

    orgs = [
        Organization(id="org-aarohan", tenant_id=TENANT_ID, name="Aarohan Foundation", legal_type="SECTION 8", registration_number="U85300MH2018NPL312490", city="Mumbai", pan="AABCA1234F", fcra_active=True),
        Organization(id="org-udaan", tenant_id=TENANT_ID, name="Udaan Education Trust", legal_type="TRUST", registration_number="E-28491 (MUM)", city="Pune", pan="AAATU4821D", fcra_active=False),
        Organization(id="org-jal", tenant_id=TENANT_ID, name="Jal Jeevan Society", legal_type="SOCIETY", registration_number="MAH/1124/2014", city="Nashik", pan="AABCJ9128K", fcra_active=True),
    ]
    db.add_all(orgs)

    compliances = [
        Compliance(id="cmp-fcra", tenant_id=TENANT_ID, organization_id="org-aarohan", code="FCRA-FC4", title="FCRA Annual Return (FC-4)", category="FCRA", period="FY 2025–26", statutory_deadline=date(2026, 12, 31), internal_target=date(2026, 12, 15), status="IN_PROGRESS", priority="HIGH", owner_name="Riya Mehta", owner_initials="RM", progress=64, legal_reference="Foreign Contribution (Regulation) Rules", risk_note="Bank reconciliation evidence is still pending."),
        Compliance(id="cmp-aoc4", tenant_id=TENANT_ID, organization_id="org-aarohan", code="MCA-AOC4", title="Financial Statements Filing (AOC-4)", category="MCA", period="FY 2025–26", statutory_deadline=date(2026, 10, 29), internal_target=date(2026, 10, 15), status="UNDER_REVIEW", priority="HIGH", owner_name="Arjun Shah", owner_initials="AS", progress=82, legal_reference="Companies Act, 2013", risk_note="Reviewer approval due this week."),
        Compliance(id="cmp-itr", tenant_id=TENANT_ID, organization_id="org-udaan", code="ITR-7", title="Income Tax Return (ITR-7)", category="Income Tax", period="AY 2026–27", statutory_deadline=date(2026, 10, 31), internal_target=date(2026, 10, 20), status="NOT_STARTED", priority="CRITICAL", owner_name="Neha Kulkarni", owner_initials="NK", progress=12, legal_reference="Income-tax Act, 1961", risk_note="Tax audit inputs have not been received."),
        Compliance(id="cmp-audit", tenant_id=TENANT_ID, organization_id="org-udaan", code="AUD-10B", title="Audit Report in Form 10B", category="Audit", period="FY 2025–26", statutory_deadline=date(2026, 9, 30), internal_target=date(2026, 9, 18), status="IN_PROGRESS", priority="HIGH", owner_name="Kabir Rao", owner_initials="KR", progress=48, legal_reference="Rule 16CC, Income-tax Rules", risk_note="Four schedules need supporting documents."),
        Compliance(id="cmp-gstr", tenant_id=TENANT_ID, organization_id="org-jal", code="GST-3B", title="GSTR-3B Monthly Return", category="GST", period="Aug 2026", statutory_deadline=date(2026, 9, 20), internal_target=date(2026, 9, 17), status="READY_TO_FILE", priority="MEDIUM", owner_name="Riya Mehta", owner_initials="RM", progress=96, legal_reference="CGST Rules, 2017", risk_note="Ready after final sign-off."),
        Compliance(id="cmp-board", tenant_id=TENANT_ID, organization_id="org-aarohan", code="GOV-BM", title="Quarterly Board Meeting", category="Governance", period="Q2 FY 2026–27", statutory_deadline=date(2026, 9, 12), internal_target=date(2026, 9, 8), status="COMPLETED", priority="LOW", owner_name="Priya Nair", owner_initials="PN", progress=100, legal_reference="Companies Act, 2013", risk_note=""),
    ]
    db.add_all(compliances)

    tasks = [
        Task(id="task-bank", tenant_id=TENANT_ID, organization_id="org-aarohan", compliance_id="cmp-fcra", title="Reconcile designated FCRA bank account", due_at=date(2026, 9, 3), status="IN_PROGRESS", priority="HIGH", assignee_name="Riya Mehta", assignee_initials="RM"),
        Task(id="task-audit", tenant_id=TENANT_ID, organization_id="org-udaan", compliance_id="cmp-audit", title="Collect utilization certificates", due_at=date(2026, 9, 6), status="TODO", priority="HIGH", assignee_name="Kabir Rao", assignee_initials="KR"),
        Task(id="task-review", tenant_id=TENANT_ID, organization_id="org-aarohan", compliance_id="cmp-aoc4", title="Review signed financial statements", due_at=date(2026, 9, 8), status="TODO", priority="MEDIUM", assignee_name="Arjun Shah", assignee_initials="AS"),
        Task(id="task-gst", tenant_id=TENANT_ID, organization_id="org-jal", compliance_id="cmp-gstr", title="Approve GSTR-3B computation", due_at=date(2026, 9, 15), status="TODO", priority="MEDIUM", assignee_name="Riya Mehta", assignee_initials="RM"),
        Task(id="task-minutes", tenant_id=TENANT_ID, organization_id="org-aarohan", compliance_id="cmp-board", title="Upload signed board minutes", due_at=date(2026, 8, 25), status="DONE", priority="LOW", assignee_name="Priya Nair", assignee_initials="PN"),
    ]
    db.add_all(tasks)

    documents = [
        Document(id="doc-fcra", tenant_id=TENANT_ID, organization_id="org-aarohan", compliance_id="cmp-fcra", name="FCRA Registration Certificate.pdf", category="Registration", file_type="PDF", version=2, size_label="1.8 MB", expiry_at=date(2027, 3, 31), uploaded_by="Riya Mehta"),
        Document(id="doc-audit", tenant_id=TENANT_ID, organization_id="org-udaan", compliance_id="cmp-audit", name="Audited Financials FY25-26.pdf", category="Financial", file_type="PDF", version=3, size_label="4.2 MB", uploaded_by="Kabir Rao"),
        Document(id="doc-80g", tenant_id=TENANT_ID, organization_id="org-udaan", name="80G Approval Order.pdf", category="Tax Registration", file_type="PDF", version=1, size_label="920 KB", expiry_at=date(2026, 11, 30), uploaded_by="Neha Kulkarni"),
        Document(id="doc-pan", tenant_id=TENANT_ID, organization_id="org-jal", name="PAN Card.pdf", category="Identity", file_type="PDF", version=1, size_label="380 KB", uploaded_by="Riya Mehta"),
    ]
    db.add_all(documents)

    db.add_all([
        Notification(id="not-1", tenant_id=TENANT_ID, title="4 tasks need attention", message="Two high-priority tasks are due within 10 days.", kind="WARNING"),
        Notification(id="not-2", tenant_id=TENANT_ID, title="AOC-4 ready for review", message="Arjun moved the filing package to Under Review.", kind="REVIEW"),
        Notification(id="not-3", tenant_id=TENANT_ID, title="80G certificate expires soon", message="Udaan Education Trust certificate expires in 95 days.", kind="DOCUMENT"),
    ])
    db.add_all([
        AuditEvent(tenant_id=TENANT_ID, actor_name="Arjun Shah", action="STATUS_CHANGED", entity_type="Compliance", entity_id="cmp-aoc4", summary="Moved AOC-4 to Under Review"),
        AuditEvent(tenant_id=TENANT_ID, actor_name="Riya Mehta", action="DOCUMENT_UPLOADED", entity_type="Document", entity_id="doc-fcra", summary="Uploaded version 2 of FCRA Registration Certificate"),
        AuditEvent(tenant_id=TENANT_ID, actor_name="Priya Nair", action="TASK_COMPLETED", entity_type="Task", entity_id="task-minutes", summary="Completed: Upload signed board minutes"),
    ])
    db.commit()
    seed_extended_data(db)


def seed_extended_data(db: Session) -> None:
    if not db.scalar(select(ComplianceDefinition.id).where(ComplianceDefinition.tenant_id == TENANT_ID).limit(1)):
        db.add_all([
            ComplianceDefinition(
                id="def-audit", tenant_id=TENANT_ID, code="AUD-ANNUAL", title="Annual audit and financial statements",
                category="Audit", legal_reference="Configured compliance catalogue - validate before production",
                applicable_legal_types="ALL", deadline_month=9, deadline_day=30, internal_lead_days=14, priority="HIGH",
            ),
            ComplianceDefinition(
                id="def-tax", tenant_id=TENANT_ID, code="TAX-ANNUAL", title="Annual income tax compliance",
                category="Income Tax", legal_reference="Configured compliance catalogue - validate before production",
                applicable_legal_types="ALL", deadline_month=10, deadline_day=31, internal_lead_days=14, priority="HIGH",
            ),
            ComplianceDefinition(
                id="def-fcra", tenant_id=TENANT_ID, code="FCRA-ANNUAL", title="FCRA annual compliance",
                category="FCRA", legal_reference="Configured compliance catalogue - validate before production",
                applicable_legal_types="ALL", requires_fcra=True, deadline_month=12, deadline_day=31,
                internal_lead_days=21, priority="CRITICAL",
            ),
            ComplianceDefinition(
                id="def-governance", tenant_id=TENANT_ID, code="GOV-ANNUAL", title="Annual governance review",
                category="Governance", legal_reference="Internal governance calendar",
                applicable_legal_types="TRUST,SOCIETY,SECTION 8", deadline_month=3, deadline_day=31,
                internal_lead_days=14, priority="MEDIUM",
            ),
        ])

    if not db.scalar(select(Membership.id).where(Membership.tenant_id == TENANT_ID).limit(1)):
        db.add_all([
            Membership(id="mem-admin", tenant_id=TENANT_ID, name="Ananya Desai", email="ananya@example.org", role="TENANT_ADMIN", status="ACTIVE", accepted_at=datetime.now(timezone.utc)),
            Membership(id="mem-riya", tenant_id=TENANT_ID, organization_id="org-aarohan", name="Riya Mehta", email="riya@example.org", role="COMPLIANCE_OFFICER", status="ACTIVE", accepted_at=datetime.now(timezone.utc)),
            Membership(id="mem-kabir", tenant_id=TENANT_ID, organization_id="org-udaan", name="Kabir Rao", email="kabir@example.org", role="ACCOUNTANT", status="ACTIVE", accepted_at=datetime.now(timezone.utc)),
        ])

    if not db.scalar(select(Subscription.id).where(Subscription.tenant_id == TENANT_ID)):
        db.add(Subscription(
            id="sub-demo", tenant_id=TENANT_ID, plan_name="BUSINESS", status="ACTIVE",
            user_limit=25, organization_limit=10, storage_limit_gb=25, period_end=date(2027, 3, 31),
        ))

    if not db.scalar(select(PortfolioRecord.id).where(PortfolioRecord.tenant_id == TENANT_ID).limit(1)):
        db.add_all([
            PortfolioRecord(id="grant-education", tenant_id=TENANT_ID, organization_id="org-udaan", record_type="GRANT", title="Learning access programme grant", status="ACTIVE", owner_name="Kabir Rao", value_label="INR 24 lakh", due_at=date(2026, 11, 15), notes="Utilization report and donor narrative due together."),
            PortfolioRecord(id="donor-water", tenant_id=TENANT_ID, organization_id="org-jal", record_type="DONOR", title="Jal sustainability donor partnership", status="ACTIVE", owner_name="Riya Mehta", value_label="Institutional donor", notes="Quarterly stewardship review."),
            PortfolioRecord(id="csr-digital", tenant_id=TENANT_ID, organization_id="org-aarohan", record_type="CSR_PROJECT", title="Digital skills CSR project", status="ON_TRACK", owner_name="Arjun Shah", value_label="68% delivered", due_at=date(2027, 3, 31), notes="Board-approved implementation plan."),
            PortfolioRecord(id="volunteer-audit", tenant_id=TENANT_ID, organization_id="org-udaan", record_type="VOLUNTEER", title="Financial controls volunteer cohort", status="ACTIVE", owner_name="Neha Kulkarni", value_label="12 volunteers", due_at=date(2026, 10, 10), notes="Access is limited to non-sensitive training records."),
        ])

    # Keep the operations centre useful for existing demo databases as new modules are introduced.
    operation_seed_records = [
        PortfolioRecord(id="ops-membership", tenant_id=TENANT_ID, organization_id="org-udaan", record_type="MEMBERSHIP", title="Priya Sharma annual membership", status="PENDING", owner_name="Priya Sharma", value_label="INR 1,500 / UPI-4821", due_at=date(2027, 9, 10), notes="Payment proof received; identity verification pending."),
        PortfolioRecord(id="ops-volunteer-activity", tenant_id=TENANT_ID, organization_id="org-udaan", record_type="VOLUNTEER_ACTIVITY", title="Community audit readiness workshop", status="LOGGED", owner_name="Neha Kulkarni", value_label="18 hours / Workshop", due_at=date(2026, 9, 8), notes="Three volunteers trained programme coordinators."),
        PortfolioRecord(id="ops-management", tenant_id=TENANT_ID, organization_id="org-aarohan", record_type="MANAGEMENT_MEMBER", title="Dr Meera Rao", status="ACTIVE", owner_name="Governance office", value_label="Trustee / Programmes", due_at=date(2028, 3, 31), notes="Public management profile approved."),
        PortfolioRecord(id="ops-donation", tenant_id=TENANT_ID, organization_id="org-jal", record_type="DONATION", title="Monsoon water security appeal", status="VERIFIED", owner_name="Arvind Menon", value_label="INR 75,000 / TXN-8806", due_at=date(2026, 9, 10), notes="80G receipt requested and PAN verified."),
        PortfolioRecord(id="ops-campaign", tenant_id=TENANT_ID, organization_id="org-jal", record_type="CAMPAIGN", title="100 village water kits", status="ACTIVE", owner_name="Fundraising team", value_label="INR 6.4L / INR 10L", due_at=date(2026, 12, 31), notes="Campaign is accepting public contributions."),
        PortfolioRecord(id="ops-sponsor", tenant_id=TENANT_ID, organization_id="org-aarohan", record_type="SPONSOR", title="Sampurna Technologies", status="ACTIVE", owner_name="Partnerships team", value_label="sampurna.example / Priority 1", notes="Logo and website placement approved."),
        PortfolioRecord(id="ops-event", tenant_id=TENANT_ID, organization_id="org-udaan", record_type="EVENT", title="Annual community impact forum", status="PUBLISHED", owner_name="Events desk", value_label="Bengaluru / 180 seats", due_at=date(2026, 11, 22), notes="Public registration is open."),
        PortfolioRecord(id="ops-inquiry", tenant_id=TENANT_ID, organization_id="org-jal", record_type="INQUIRY", title="Corporate volunteering partnership", status="IN_PROGRESS", owner_name="Riya Mehta", value_label="Partnership / High", due_at=date(2026, 9, 15), notes="Schedule a programme and safeguarding call."),
        PortfolioRecord(id="ops-certificate", tenant_id=TENANT_ID, organization_id="org-udaan", record_type="CERTIFICATE", title="Volunteer excellence — Asha Nair", status="ISSUED", owner_name="Programme office", value_label="Asha Nair / SETU-VC-104", due_at=date(2026, 9, 5), notes="Certificate issued for 120 verified service hours."),
        PortfolioRecord(id="ops-news", tenant_id=TENANT_ID, organization_id="org-aarohan", record_type="NEWS", title="Digital learning labs reach 2,000 learners", status="DRAFT", owner_name="Communications", value_label="digital-learning-impact", due_at=date(2026, 9, 18), notes="Awaiting final beneficiary consent review."),
        PortfolioRecord(id="ops-testimonial", tenant_id=TENANT_ID, organization_id="org-jal", record_type="TESTIMONIAL", title="Kavya — community coordinator", status="PUBLISHED", owner_name="Communications", value_label="Coordinator / 5 stars", notes="Approved for the public impact page."),
        PortfolioRecord(id="ops-content", tenant_id=TENANT_ID, organization_id="org-udaan", record_type="CONTENT_PAGE", title="About and mission page", status="PUBLISHED", owner_name="Site administrator", value_label="About / Mission", due_at=date(2026, 12, 1), notes="Quarterly content review scheduled."),
    ]
    for operation_record in operation_seed_records:
        if not db.get(PortfolioRecord, operation_record.id):
            db.add(operation_record)

    if not db.scalar(select(IntegrationConnection.id).where(IntegrationConnection.tenant_id == TENANT_ID).limit(1)):
        db.add_all([
            IntegrationConnection(id="int-email", tenant_id=TENANT_ID, provider="Transactional email", category="Notifications", status="AVAILABLE", description="Reminder, approval, invitation and security messages."),
            IntegrationConnection(id="int-whatsapp", tenant_id=TENANT_ID, provider="WhatsApp Business", category="Notifications", status="AVAILABLE", description="Optional high-priority reminder channel through an official provider."),
            IntegrationConnection(id="int-calendar", tenant_id=TENANT_ID, provider="Google / Outlook Calendar", category="Calendar", status="AVAILABLE", description="Two-way calendar synchronization foundation."),
            IntegrationConnection(id="int-storage", tenant_id=TENANT_ID, provider="Drive / OneDrive / Dropbox", category="Documents", status="AVAILABLE", description="Approved external document source connectors."),
            IntegrationConnection(id="int-signature", tenant_id=TENANT_ID, provider="Digital signature", category="Approvals", status="AVAILABLE", description="Provider-neutral signature workflow adapter."),
            IntegrationConnection(id="int-ocr", tenant_id=TENANT_ID, provider="OCR and document intelligence", category="Automation", status="AVAILABLE", description="Asynchronous extraction with confidence and human confirmation."),
        ])

    for document in db.scalars(select(Document).where(Document.tenant_id == TENANT_ID)).all():
        for version_number in range(1, document.version + 1):
            if db.scalar(select(DocumentVersion.id).where(
                DocumentVersion.document_id == document.id,
                DocumentVersion.version == version_number,
            ).limit(1)):
                continue
            db.add(DocumentVersion(
                tenant_id=TENANT_ID, document_id=document.id, version=version_number,
                file_type=document.file_type, size_label=document.size_label, uploaded_by=document.uploaded_by,
                created_at=document.created_at - timedelta(days=(document.version - version_number) * 14),
            ))

    db.commit()
