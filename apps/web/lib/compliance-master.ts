import { apiRequest } from "./http";

export type RuleCondition = { id: string; field: string; operator: string; value: string | boolean | number | string[] | null };
export type RuleGroup = { id: string; operator: "AND" | "OR"; conditions: RuleCondition[] };
export type WorkflowStage = { id: string; state: string; label: string };
export type WorkflowTransition = { from_state: string; to_state: string; allowed_roles: string[]; required_evidence: boolean; required_approval: boolean };
export type ChecklistItem = { id: string; title: string; description: string; instructions: string; required: boolean; responsible_role: string; relative_due_days: number };
export type DocumentRequirement = { id: string; document_type: string; required: boolean; minimum_count: number; must_be_valid: boolean; instructions: string };
export type ReminderRule = { id: string; offset_days: number; channel: "IN_APP" | "EMAIL" | "WHATSAPP"; recipient_role: string; escalation_level: number; enabled: boolean; text: string; provider_template?: string };
export type TemplateTranslation = { name: string; description: string; instructions: string; checklist: Record<string, string>; checklist_descriptions: Record<string, string>; checklist_instructions: Record<string, string>; document_instructions: Record<string, string>; reminder_text: Record<string, string> };
export type TemplateConfiguration = {
  name: string; category_id: string; subcategory: string; jurisdiction: string; description: string; purpose: string;
  instructions: string; legal_reference: string; authority: string; portal_url: string; tags: string[]; internal_notes: string;
  applicability: { match_all: boolean; operator: "AND" | "OR"; groups: RuleGroup[] };
  recurrence: { frequency: string; anchor_date: string | null; interval_months: number; fiscal_start_month: number };
  deadline: { strategy: string; fixed_date: string | null; offset_days: number; internal_lead_days: number; document_type: string; event_key?: string };
  workflow: { stages: WorkflowStage[]; transitions: WorkflowTransition[] };
  checklist: ChecklistItem[]; documents: DocumentRequirement[];
  responsibility: { owner_role: string; fallback_role: string; reviewer_role: string; approver_role: string };
  reminders: ReminderRule[]; risk_level: string; priority: string; translations: Record<string, TemplateTranslation>;
};
export type ComplianceTemplate = {
  id: string; code: string; category_id: string; category: string; name: string; jurisdiction: string;
  version_id: string; version: number; current_version: number | null; revision: number; status: string;
  frequency: string; risk_level: string; organization_types: string; change_summary: string;
  created_by: string; updated_by: string; reviewed_by: string | null; published_by: string | null; created_at: string; updated_at: string; published_at: string | null;
  configuration: TemplateConfiguration;
};
export type TemplateList = { items: ComplianceTemplate[]; total: number; page: number; page_size: number; counts: Record<string, number> };
export type ComplianceCategory = { id: string; name: string; sort_order: number; enabled: boolean };
export type MasterMetadata = { fields: Record<string, string>; operators: Record<string, string[]>; roles: string[]; states: string[]; channels: string[]; permissions: string[] };
export type ApplicabilityPreview = {
  applicable: boolean; requires_review?: string;
  schedule?: { statutory_deadline: string; internal_target: string; cycle: string };
  groups: { id: string; operator: string; satisfied: boolean | null; conditions: { id: string; field: string; operator: string; actual: unknown; expected: unknown; satisfied: boolean | null }[] }[];
};
export const templatePath = "/admin/compliance-templates";
export const getTemplate = (id: string, version?: number) => apiRequest<ComplianceTemplate>(`${templatePath}/${encodeURIComponent(id)}${version ? `?version=${version}` : ""}`);
export const actOnTemplate = (row: ComplianceTemplate, action: string, change_summary = "") => apiRequest<ComplianceTemplate>(`${templatePath}/${row.id}/${action}`, "POST", { expected_revision: row.revision, change_summary });
export function newConfiguration(): TemplateConfiguration {
  return {
    name: "", category_id: "", subcategory: "", jurisdiction: "", description: "", purpose: "", instructions: "", legal_reference: "", authority: "", portal_url: "", tags: [], internal_notes: "",
    applicability: { match_all: false, operator: "AND", groups: [] },
    recurrence: { frequency: "ANNUAL", anchor_date: null, interval_months: 12, fiscal_start_month: 4 },
    deadline: { strategy: "FIXED_DATE", fixed_date: null, offset_days: 0, internal_lead_days: 0, document_type: "" },
    workflow: { stages: [{ id: "start", state: "NOT_STARTED", label: "" }, { id: "work", state: "IN_PROGRESS", label: "" }, { id: "end", state: "COMPLETED", label: "" }], transitions: [
      { from_state: "NOT_STARTED", to_state: "IN_PROGRESS", allowed_roles: ["COMPLIANCE_OFFICER", "TENANT_ADMIN"], required_evidence: false, required_approval: false },
      { from_state: "IN_PROGRESS", to_state: "COMPLETED", allowed_roles: ["TENANT_ADMIN"], required_evidence: false, required_approval: true },
    ] },
    checklist: [], documents: [], responsibility: { owner_role: "COMPLIANCE_OFFICER", fallback_role: "ORGANIZATION_ADMIN", reviewer_role: "AUDITOR", approver_role: "ORGANIZATION_ADMIN" },
    reminders: [], risk_level: "MEDIUM", priority: "MEDIUM", translations: {},
  };
}
export function pruneTemplateTranslations(configuration: TemplateConfiguration): TemplateConfiguration {
  const ids = {
    checklist: new Set(configuration.checklist.map((item) => item.id)),
    checklist_descriptions: new Set(configuration.checklist.map((item) => item.id)),
    checklist_instructions: new Set(configuration.checklist.map((item) => item.id)),
    document_instructions: new Set(configuration.documents.map((item) => item.id)),
    reminder_text: new Set(configuration.reminders.map((item) => item.id)),
  };
  return { ...configuration, translations: Object.fromEntries(Object.entries(configuration.translations).map(([locale, translation]) => {
    const cleaned = { ...emptyTranslation(), ...translation };
    for (const key of Object.keys(ids) as (keyof typeof ids)[]) {
      cleaned[key] = Object.fromEntries(Object.entries(cleaned[key]).filter(([id]) => ids[key].has(id)));
    }
    return [locale, cleaned];
  })) };
}
export function emptyTranslation(): TemplateTranslation {
  return { name: "", description: "", instructions: "", checklist: {}, checklist_descriptions: {}, checklist_instructions: {}, document_instructions: {}, reminder_text: {} };
}
