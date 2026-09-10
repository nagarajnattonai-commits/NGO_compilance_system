import type { AuditEvent, Compliance, ComplianceDefinition, ComplianceDocument, ComplianceTask, Membership, Notification, Organization, Subscription } from "./types";

export const organizations: Organization[] = [
  { id: "org-aarohan", name: "Aarohan Foundation", legal_type: "SECTION 8", registration_number: "U85300MH2018NPL312490", status: "ACTIVE", city: "Mumbai", pan: "AABCA1234F", fcra_active: true },
  { id: "org-udaan", name: "Udaan Education Trust", legal_type: "TRUST", registration_number: "E-28491 (MUM)", status: "ACTIVE", city: "Pune", pan: "AAATU4821D", fcra_active: false },
  { id: "org-jal", name: "Jal Jeevan Society", legal_type: "SOCIETY", registration_number: "MAH/1124/2014", status: "ACTIVE", city: "Nashik", pan: "AABCJ9128K", fcra_active: true },
];

export const compliances: Compliance[] = [
  { id: "cmp-fcra", organization_id: "org-aarohan", code: "FCRA-FC4", title: "FCRA Annual Return (FC-4)", category: "FCRA", period: "FY 2025–26", statutory_deadline: "2026-12-31", internal_target: "2026-12-15", status: "IN_PROGRESS", priority: "HIGH", owner_name: "Riya Mehta", owner_initials: "RM", progress: 64, legal_reference: "Foreign Contribution (Regulation) Rules", risk_note: "Bank reconciliation evidence is still pending." },
  { id: "cmp-aoc4", organization_id: "org-aarohan", code: "MCA-AOC4", title: "Financial Statements Filing (AOC-4)", category: "MCA", period: "FY 2025–26", statutory_deadline: "2026-10-29", internal_target: "2026-10-15", status: "UNDER_REVIEW", priority: "HIGH", owner_name: "Arjun Shah", owner_initials: "AS", progress: 82, legal_reference: "Companies Act, 2013", risk_note: "Reviewer approval due this week." },
  { id: "cmp-itr", organization_id: "org-udaan", code: "ITR-7", title: "Income Tax Return (ITR-7)", category: "Income Tax", period: "AY 2026–27", statutory_deadline: "2026-10-31", internal_target: "2026-10-20", status: "NOT_STARTED", priority: "CRITICAL", owner_name: "Neha Kulkarni", owner_initials: "NK", progress: 12, legal_reference: "Income-tax Act, 1961", risk_note: "Tax audit inputs have not been received." },
  { id: "cmp-audit", organization_id: "org-udaan", code: "AUD-10B", title: "Audit Report in Form 10B", category: "Audit", period: "FY 2025–26", statutory_deadline: "2026-09-30", internal_target: "2026-09-18", status: "IN_PROGRESS", priority: "HIGH", owner_name: "Kabir Rao", owner_initials: "KR", progress: 48, legal_reference: "Rule 16CC, Income-tax Rules", risk_note: "Four schedules need supporting documents." },
  { id: "cmp-gstr", organization_id: "org-jal", code: "GST-3B", title: "GSTR-3B Monthly Return", category: "GST", period: "Aug 2026", statutory_deadline: "2026-09-20", internal_target: "2026-09-17", status: "READY_TO_FILE", priority: "MEDIUM", owner_name: "Riya Mehta", owner_initials: "RM", progress: 96, legal_reference: "CGST Rules, 2017", risk_note: "Ready after final sign-off." },
  { id: "cmp-board", organization_id: "org-aarohan", code: "GOV-BM", title: "Quarterly Board Meeting", category: "Governance", period: "Q2 FY 2026–27", statutory_deadline: "2026-09-12", internal_target: "2026-09-08", status: "COMPLETED", priority: "LOW", owner_name: "Priya Nair", owner_initials: "PN", progress: 100, legal_reference: "Companies Act, 2013", risk_note: "" },
];

export const tasks: ComplianceTask[] = [
  { id: "task-bank", organization_id: "org-aarohan", compliance_id: "cmp-fcra", title: "Reconcile designated FCRA bank account", due_at: "2026-09-03", status: "IN_PROGRESS", priority: "HIGH", assignee_name: "Riya Mehta", assignee_initials: "RM" },
  { id: "task-audit", organization_id: "org-udaan", compliance_id: "cmp-audit", title: "Collect utilization certificates", due_at: "2026-09-06", status: "TODO", priority: "HIGH", assignee_name: "Kabir Rao", assignee_initials: "KR" },
  { id: "task-review", organization_id: "org-aarohan", compliance_id: "cmp-aoc4", title: "Review signed financial statements", due_at: "2026-09-08", status: "TODO", priority: "MEDIUM", assignee_name: "Arjun Shah", assignee_initials: "AS" },
  { id: "task-gst", organization_id: "org-jal", compliance_id: "cmp-gstr", title: "Approve GSTR-3B computation", due_at: "2026-09-15", status: "TODO", priority: "MEDIUM", assignee_name: "Riya Mehta", assignee_initials: "RM" },
  { id: "task-minutes", organization_id: "org-aarohan", compliance_id: "cmp-board", title: "Upload signed board minutes", due_at: "2026-08-25", status: "DONE", priority: "LOW", assignee_name: "Priya Nair", assignee_initials: "PN" },
];

export const documents: ComplianceDocument[] = [
  { id: "doc-fcra", organization_id: "org-aarohan", compliance_id: "cmp-fcra", name: "FCRA Registration Certificate.pdf", category: "Registration", file_type: "PDF", version: 2, size_label: "1.8 MB", expiry_at: "2027-03-31", uploaded_by: "Riya Mehta", created_at: "2026-08-21T10:00:00Z" },
  { id: "doc-audit", organization_id: "org-udaan", compliance_id: "cmp-audit", name: "Audited Financials FY25-26.pdf", category: "Financial", file_type: "PDF", version: 3, size_label: "4.2 MB", expiry_at: null, uploaded_by: "Kabir Rao", created_at: "2026-08-20T10:00:00Z" },
  { id: "doc-80g", organization_id: "org-udaan", compliance_id: null, name: "80G Approval Order.pdf", category: "Tax Registration", file_type: "PDF", version: 1, size_label: "920 KB", expiry_at: "2026-11-30", uploaded_by: "Neha Kulkarni", created_at: "2026-08-18T10:00:00Z" },
  { id: "doc-pan", organization_id: "org-jal", compliance_id: null, name: "PAN Card.pdf", category: "Identity", file_type: "PDF", version: 1, size_label: "380 KB", expiry_at: null, uploaded_by: "Riya Mehta", created_at: "2026-08-12T10:00:00Z" },
];

export const notifications: Notification[] = [
  { id: "not-1", title: "4 tasks need attention", message: "Two high-priority tasks are due within 10 days.", kind: "WARNING", is_read: false, created_at: "2026-08-27T08:30:00Z" },
  { id: "not-2", title: "AOC-4 ready for review", message: "Arjun moved the filing package to Under Review.", kind: "REVIEW", is_read: false, created_at: "2026-08-26T15:20:00Z" },
  { id: "not-3", title: "80G certificate expires soon", message: "Udaan Education Trust certificate expires in 95 days.", kind: "DOCUMENT", is_read: false, created_at: "2026-08-25T12:00:00Z" },
];

export const auditEvents: AuditEvent[] = [
  { id: "aud-1", actor_name: "Arjun Shah", action: "STATUS_CHANGED", entity_type: "Compliance", entity_id: "cmp-aoc4", summary: "Moved AOC-4 to Under Review", created_at: "2026-08-27T09:42:00Z" },
  { id: "aud-2", actor_name: "Riya Mehta", action: "DOCUMENT_UPLOADED", entity_type: "Document", entity_id: "doc-fcra", summary: "Uploaded version 2 of FCRA Registration Certificate", created_at: "2026-08-26T14:25:00Z" },
  { id: "aud-3", actor_name: "Priya Nair", action: "TASK_COMPLETED", entity_type: "Task", entity_id: "task-minutes", summary: "Completed: Upload signed board minutes", created_at: "2026-08-25T11:10:00Z" },
];

export const complianceDefinitions: ComplianceDefinition[] = [
  { id: "def-audit", code: "AUD-ANNUAL", title: "Annual audit and financial statements", category: "Audit", legal_reference: "Configured compliance catalogue - validate before production", applicable_legal_types: "ALL", requires_fcra: false, deadline_month: 9, deadline_day: 30, internal_lead_days: 14, priority: "HIGH", rule_version: 1, status: "ACTIVE" },
  { id: "def-tax", code: "TAX-ANNUAL", title: "Annual income tax compliance", category: "Income Tax", legal_reference: "Configured compliance catalogue - validate before production", applicable_legal_types: "ALL", requires_fcra: false, deadline_month: 10, deadline_day: 31, internal_lead_days: 14, priority: "HIGH", rule_version: 1, status: "ACTIVE" },
  { id: "def-fcra", code: "FCRA-ANNUAL", title: "FCRA annual compliance", category: "FCRA", legal_reference: "Configured compliance catalogue - validate before production", applicable_legal_types: "ALL", requires_fcra: true, deadline_month: 12, deadline_day: 31, internal_lead_days: 21, priority: "CRITICAL", rule_version: 1, status: "ACTIVE" },
  { id: "def-governance", code: "GOV-ANNUAL", title: "Annual governance review", category: "Governance", legal_reference: "Internal governance calendar", applicable_legal_types: "TRUST,SOCIETY,SECTION 8", requires_fcra: false, deadline_month: 3, deadline_day: 31, internal_lead_days: 14, priority: "MEDIUM", rule_version: 1, status: "ACTIVE" },
];

export const memberships: Membership[] = [
  { id: "mem-admin", organization_id: null, name: "Ananya Desai", email: "ananya@example.org", role: "TENANT_ADMIN", status: "ACTIVE", invited_at: "2026-08-01T09:00:00Z", accepted_at: "2026-08-01T09:10:00Z" },
  { id: "mem-riya", organization_id: "org-aarohan", name: "Riya Mehta", email: "riya@example.org", role: "COMPLIANCE_OFFICER", status: "ACTIVE", invited_at: "2026-08-02T09:00:00Z", accepted_at: "2026-08-02T10:00:00Z" },
  { id: "mem-kabir", organization_id: "org-udaan", name: "Kabir Rao", email: "kabir@example.org", role: "ACCOUNTANT", status: "ACTIVE", invited_at: "2026-08-03T09:00:00Z", accepted_at: "2026-08-03T11:00:00Z" },
];

export const subscription: Subscription = {
  id: "sub-demo", plan_name: "BUSINESS", status: "ACTIVE", user_limit: 25,
  organization_limit: 10, storage_limit_gb: 25, period_end: "2027-03-31",
};
