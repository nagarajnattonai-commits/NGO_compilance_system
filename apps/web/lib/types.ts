export type Organization = {
  id: string;
  name: string;
  legal_type: string;
  registration_number: string;
  status: string;
  city: string;
  pan: string;
  fcra_active: boolean;
};

export type Compliance = {
  id: string;
  template_version_id?: string | null;
  organization_id: string;
  code: string;
  title: string;
  category: string;
  period: string;
  statutory_deadline: string;
  internal_target: string | null;
  status: string;
  priority: string;
  owner_name: string;
  owner_initials: string;
  progress: number;
  legal_reference: string;
  risk_note: string;
};

export type ComplianceTask = {
  id: string;
  organization_id: string;
  compliance_id: string | null;
  title: string;
  due_at: string;
  status: string;
  priority: string;
  assignee_name: string;
  assignee_initials: string;
};

export type ComplianceDocument = {
  storage_status?:string;
  current_version_id?:string|null;
  effective_at?:string|null;
  expiry_status?:string;
  id: string;
  organization_id: string;
  compliance_id: string | null;
  name: string;
  category: string;
  file_type: string;
  version: number;
  size_label: string;
  expiry_at: string | null;
  uploaded_by: string;
  created_at: string;
};

export type Notification = {
  id: string;
  title: string;
  message: string;
  template_key?: string | null;
  template_variables?: { complianceName: string; names: Record<string, string>; dueDate: string; recipientRole: string; reminderText: string; reminderTexts: Record<string, string>; escalationLevel: number; templateVersionId: string };
  kind: string;
  is_read: boolean;
  created_at: string;
};

export type AuditEvent = {
  id: string;
  actor_name: string;
  action: string;
  entity_type: string;
  entity_id: string;
  summary: string;
  created_at: string;
};

export type ComplianceDefinition = {
  id: string;
  code: string;
  title: string;
  category: string;
  legal_reference: string;
  applicable_legal_types: string;
  requires_fcra: boolean;
  deadline_month: number | null;
  deadline_day: number | null;
  internal_lead_days: number;
  priority: string;
  rule_version: number;
  status: string;
};

export type Membership = {
  id: string;
  organization_id: string | null;
  name: string;
  email: string;
  role: string;
  status: string;
  invited_at: string;
  accepted_at: string | null;
};

export type Subscription = {
  id: string;
  plan_name: string;
  status: string;
  user_limit: number;
  organization_limit: number;
  storage_limit_gb: number;
  period_end: string;
};

export type DocumentVersion = {
  id: string;
  document_id: string;
  version: number;
  file_type: string;
  size_label: string;
  uploaded_by: string;
  created_at: string;
};

export type PortfolioRecord = {
  id: string;
  organization_id: string;
  record_type:
    | "GRANT" | "DONOR" | "CSR_PROJECT" | "VOLUNTEER"
    | "MEMBERSHIP" | "VOLUNTEER_ACTIVITY" | "EVENT" | "CAMPAIGN" | "DONATION"
    | "INQUIRY" | "MESSAGE" | "CERTIFICATE" | "NEWS" | "SPONSOR" | "TESTIMONIAL"
    | "MANAGEMENT_MEMBER" | "GALLERY_ITEM" | "DOCUMENT_TEMPLATE" | "TRAINING_VIDEO"
    | "CONTENT_PAGE";
  title: string;
  status: string;
  owner_name: string;
  value_label: string;
  due_at: string | null;
  notes: string;
  created_at: string;
  updated_at: string;
};

export type IntegrationConnection = {
  id: string;
  provider: string;
  category: string;
  status: "AVAILABLE" | "CONNECTED" | "PAUSED";
  description: string;
  last_synced_at: string | null;
};

export type AssistantAnswer = {
  answer: string;
  sources: { type: string; id: string; label: string }[];
  disclaimer: string;
};

export type ComplianceComment = {
  id: string;
  compliance_id: string;
  author_name: string;
  body: string;
  kind: "COMMENT" | "CORRECTION" | "EXCEPTION" | "RECOVERY_PLAN";
  created_at: string;
};

export type TenantLocale = {
  id: string;
  locale_code: string;
  display_name: string;
  enabled: boolean;
  is_default: boolean;
  sort_order: number;
};

export type UserPreference = {
  user_id: string;
  locale: string | null;
  timezone: string;
  time_format: "12h" | "24h";
  updated_at: string;
};

export type LocalizationSettings = {
  locales: TenantLocale[];
  preference: UserPreference;
};

export type TranslationOverride = {
  id: string;
  locale_code: string;
  translation_key: string;
  translation_value: string;
  updated_by: string;
  created_at: string;
  updated_at: string;
};
