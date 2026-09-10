import { apiRequest } from "./http";
import type { AssistantAnswer, AuditEvent, Compliance, ComplianceComment, ComplianceDefinition, ComplianceDocument, ComplianceTask, DocumentVersion, IntegrationConnection, Membership, Notification, Organization, PortfolioRecord, Subscription } from "./types";

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
  "assignee_name" | "assignee_initials"
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

export const patchTask = (id: string, status: string) => apiRequest<ComplianceTask>(`/tasks/${id}`, "PATCH", { status });
export const patchCompliance = (id: string, payload: Record<string, unknown>) => apiRequest<Compliance>(`/compliances/${id}`, "PATCH", payload);
export const transitionCompliance = (item: Compliance, payload: ComplianceTransitionInput) => apiRequest<Compliance>(`/compliances/${item.id}/transitions`, "POST", payload);
export const createOrganization = (payload: OrganizationCreateInput) => apiRequest<{ organization: Organization; generated_compliances: Compliance[] }>("/organizations", "POST", payload);
export const inviteMember = (payload: MembershipCreateInput) => apiRequest<Membership>("/memberships/invitations", "POST", payload);
export const loadDocumentVersions = (documentId: string) => apiRequest<DocumentVersion[]>(`/documents/${documentId}/versions`);
export const createDocumentVersion = (documentId: string, payload: { file_type: string; size_label: string; uploaded_by: string }) => apiRequest<ComplianceDocument>(`/documents/${documentId}/versions`, "POST", payload);
export const createCompliance = (payload: ComplianceCreateInput) => apiRequest<Compliance>("/compliances", "POST", payload);
export const createDocument = (payload: DocumentCreateInput) => apiRequest<ComplianceDocument>("/documents", "POST", payload);
export const createTask = (payload: TaskCreateInput) => apiRequest<ComplianceTask>("/tasks", "POST", payload);
export const markNotificationRead = (id: string) => apiRequest<void>(`/notifications/${id}/read`, "PATCH");
export const createPortfolioRecord = (payload: Omit<PortfolioRecord, "id" | "created_at" | "updated_at">) => apiRequest<PortfolioRecord>("/portfolio-records", "POST", payload);
export const patchPortfolioRecord = (id: string, payload: Partial<Pick<PortfolioRecord, "title" | "status" | "owner_name" | "value_label" | "due_at" | "notes">>) => apiRequest<PortfolioRecord>(`/portfolio-records/${id}`, "PATCH", payload);
export const patchIntegration = (id: string, status: IntegrationConnection["status"]) => apiRequest<IntegrationConnection>(`/integrations/${id}`, "PATCH", { status });
export const runAutomation = () => apiRequest<{ run_date: string; overdue_compliances: number; overdue_tasks: number; upcoming: number; expiring_documents: number; recurring_created: number }>("/automation/run", "POST");
export const askAssistant = (question: string, organization_id?: string) => apiRequest<AssistantAnswer>("/assistant/query", "POST", { question, organization_id });
export const loadComplianceComments = (complianceId: string) => apiRequest<ComplianceComment[]>(`/compliances/${complianceId}/comments`);
export const addComplianceComment = (complianceId: string, body: string, kind: ComplianceComment["kind"]) => apiRequest<ComplianceComment>(`/compliances/${complianceId}/comments`, "POST", { body, kind });
