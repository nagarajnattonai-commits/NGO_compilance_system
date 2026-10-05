import { apiRequest } from "./http";
import type { AiConversation, AiMessage, AssistantAnswer, AuditEvent, Compliance, ComplianceComment, ComplianceDefinition, ComplianceDocument, ComplianceTask, DocumentVersion, EligibleAssignee, IntegrationConnection, LocalizationSettings, Membership, Notification, NotificationPreference, Organization, OrganizationAccess, PortfolioRecord, Subscription, TaskAttachment, TaskComment, TenantLocale, TranslationOverride, UserPreference } from "./types";

export type ComplianceCreateInput = Pick<
  Compliance,
  "organization_id" | "code" | "title" | "category" | "period" | "statutory_deadline" |
  "internal_target" | "priority" | "owner_name" | "owner_initials" | "legal_reference"
>;

export type DocumentCreateInput = Pick<
  ComplianceDocument,
  "organization_id" | "compliance_id" | "name" | "category" | "file_type" |
  "size_label" | "expiry_at" | "uploaded_by"
>;

export type TaskCreateInput = Pick<
  ComplianceTask,
  "organization_id" | "compliance_id" | "title" | "due_at" | "priority" |
  "assignee_user_id"
>;

export type OrganizationCreateInput = Pick<Organization, "name" | "legal_type" | "registration_number" | "city" | "pan" | "fcra_active"> & {
  generate_compliance_plan: boolean;
};

export type MembershipCreateInput = Pick<Membership, "organization_id" | "name" | "email" | "role">;

export type ComplianceTransitionInput = {
  target_status: string;
  reason?: string;
  submission_reference?: string;
  proof_document_id?: string;
};


export async function loadWorkspace(isAdmin = false) {
  const [organizations, compliances, tasks, documents, notifications, auditEvents, complianceDefinitions, memberships, subscription, portfolioRecords, integrations] = await Promise.all([
    apiRequest<Organization[]>("/organizations"),
    apiRequest<Compliance[]>("/compliances"),
    apiRequest<ComplianceTask[]>("/tasks"),
    apiRequest<ComplianceDocument[]>("/documents"),
    apiRequest<Notification[]>("/notifications"),
    apiRequest<AuditEvent[]>("/audit-events"),
    apiRequest<ComplianceDefinition[]>("/compliance-definitions"),
    isAdmin ? apiRequest<Membership[]>("/memberships") : Promise.resolve([] as Membership[]),
    apiRequest<Subscription>("/subscription"),
    apiRequest<PortfolioRecord[]>("/portfolio-records"),
    apiRequest<IntegrationConnection[]>("/integrations"),
  ]);
  return { organizations, compliances, tasks, documents, notifications, auditEvents, complianceDefinitions, memberships, subscription, portfolioRecords, integrations };
}

export const patchTask = (id: string, payload: string | Partial<Pick<ComplianceTask, "title" | "status" | "priority" | "due_at" | "assignee_user_id">> & {archived?: boolean}) => apiRequest<ComplianceTask>(`/tasks/${id}`, "PATCH", typeof payload === "string" ? { status: payload } : payload);
export const patchCompliance = (id: string, payload: Record<string, unknown>) => apiRequest<Compliance>(`/compliances/${id}`, "PATCH", payload);
export const transitionCompliance = (item: Compliance, payload: ComplianceTransitionInput) => apiRequest<Compliance>(`/compliances/${item.id}/transitions`, "POST", payload);
export const createOrganization = (payload: OrganizationCreateInput) => apiRequest<{ organization: Organization; generated_compliances: Compliance[] }>("/organizations", "POST", payload);
export const inviteMember = (payload: MembershipCreateInput) => apiRequest<Membership>("/memberships/invitations", "POST", payload);
export const loadDocumentVersions = (documentId: string) => apiRequest<DocumentVersion[]>(`/documents/${documentId}/versions`);
export const createDocumentVersion = (documentId: string, payload: { file_type: string; size_label: string; uploaded_by: string }) => apiRequest<ComplianceDocument>(`/documents/${documentId}/versions`, "POST", payload);
export const createCompliance = (payload: ComplianceCreateInput) => apiRequest<Compliance>("/compliances", "POST", payload);
export const createDocument = (payload: DocumentCreateInput) => apiRequest<ComplianceDocument>("/documents", "POST", payload);
export const createTask = (payload: TaskCreateInput) => apiRequest<ComplianceTask>("/tasks", "POST", payload);
export const loadEligibleAssignees = (organizationId: string) => apiRequest<EligibleAssignee[]>(`/organizations/${organizationId}/eligible-assignees`);
export const loadTaskComments = (taskId: string) => apiRequest<TaskComment[]>(`/tasks/${taskId}/comments`);
export const addTaskComment = (taskId: string, body: string) => apiRequest<TaskComment>(`/tasks/${taskId}/comments`, "POST", { body });
export const loadTaskAttachments = (taskId: string) => apiRequest<TaskAttachment[]>(`/tasks/${taskId}/attachments`);
export const addTaskAttachment = (taskId: string, documentId: string) => apiRequest<TaskAttachment>(`/tasks/${taskId}/attachments`, "POST", { document_id: documentId });
export const archiveTaskAttachment = (taskId: string, linkId: string) => apiRequest<void>(`/tasks/${taskId}/attachments/${linkId}`, "DELETE");
export const loadOrganizationAccess = (organizationId: string) => apiRequest<OrganizationAccess[]>(`/organizations/${organizationId}/access`);
export const grantOrganizationAccess = (organizationId: string, userId: string, accessRole: OrganizationAccess["access_role"]) => apiRequest<OrganizationAccess>(`/organizations/${organizationId}/access`, "PUT", { user_id: userId, access_role: accessRole });
export const revokeOrganizationAccess = (organizationId: string, userId: string) => apiRequest<void>(`/organizations/${organizationId}/access/${userId}`, "DELETE");
export const markNotificationRead = (id: string) => apiRequest<void>(`/notifications/${id}/read`, "PATCH");
export const createPortfolioRecord = (payload: Omit<PortfolioRecord, "id" | "created_at" | "updated_at">) => apiRequest<PortfolioRecord>("/portfolio-records", "POST", payload);
export const patchPortfolioRecord = (id: string, payload: Partial<Pick<PortfolioRecord, "title" | "status" | "owner_name" | "value_label" | "due_at" | "notes">>) => apiRequest<PortfolioRecord>(`/portfolio-records/${id}`, "PATCH", payload);
export const deletePortfolioRecord = (id: string) => apiRequest<void>(`/portfolio-records/${id}`, "DELETE");
export const patchIntegration = (id: string, status: IntegrationConnection["status"]) => apiRequest<IntegrationConnection>(`/integrations/${id}`, "PATCH", { status });
export const runAutomation = () => apiRequest<{ run_date: string; overdue_compliances: number; overdue_tasks: number; upcoming: number; expiring_documents: number; recurring_created: number }>("/automation/run", "POST");
export const askAssistant = (question: string, organization_id?: string) => apiRequest<AssistantAnswer>("/assistant/query", "POST", { question, organization_id });
export const loadAiConversations = (organizationId: string) => apiRequest<AiConversation[]>(`/ai/conversations?organization_id=${encodeURIComponent(organizationId)}`);
export const createAiConversation = (organizationId: string) => apiRequest<AiConversation>("/ai/conversations", "POST", { organization_id: organizationId });
export const loadAiConversation = (id: string) => apiRequest<AiConversation>(`/ai/conversations/${id}`);
export const sendAiMessage = (id: string, question: string) => apiRequest<AiMessage>(`/ai/conversations/${id}/messages`, "POST", { question });
export const loadComplianceComments = (complianceId: string) => apiRequest<ComplianceComment[]>(`/compliances/${complianceId}/comments`);
export const addComplianceComment = (complianceId: string, body: string, kind: ComplianceComment["kind"]) => apiRequest<ComplianceComment>(`/compliances/${complianceId}/comments`, "POST", { body, kind });
export const loadLocalizationSettings = () => apiRequest<LocalizationSettings>("/localization/settings");
export const updateLocalizationPreference = (payload: { locale: string | null; timezone: string; time_format: "12h" | "24h" }) => apiRequest<UserPreference>("/localization/preferences", "PATCH", payload);
export const loadNotificationPreference = () => apiRequest<NotificationPreference>("/notification-preferences");
export const updateNotificationPreference = (payload: Partial<Omit<NotificationPreference, "user_id" | "updated_at">>) => apiRequest<NotificationPreference>("/notification-preferences", "PATCH", payload);
export const updateTenantLocales = (payload: Array<Pick<TenantLocale, "locale_code" | "display_name" | "enabled" | "is_default" | "sort_order">>) => apiRequest<TenantLocale[]>("/localization/locales", "PUT", payload);
export const loadTranslationOverrides = (locale?: string) => apiRequest<TranslationOverride[]>(`/localization/overrides${locale ? `?locale_code=${encodeURIComponent(locale)}` : ""}`);
export const saveTranslationOverride = (payload: { locale_code: string; translation_key: string; translation_value: string }) => apiRequest<TranslationOverride>("/localization/overrides", "PUT", payload);
export const deleteTranslationOverride = (id: string) => apiRequest<void>(`/localization/overrides/${id}`, "DELETE");
