# Tasks and organization access

Phase 8 keeps workspace login membership separate from business responsibility and organization access. `User` and `WorkspaceAccess` determine whether a person can sign in to a workspace. `Membership` describes roles such as compliance officer or accountant and never grants access. `OrganizationAccess` grants `VIEWER`, `CONTRIBUTOR`, or `MANAGER` access to one organization.

Workspace administrators retain access to every organization. Existing workspaces remain in their historical workspace-wide mode until the first explicit organization grant is saved. Creating that first grant activates explicit organization scope for non-administrators, so administrators should grant every required organization before enabling the policy in production.

Apply the additive migration after the Phase 7 notification migration:

```powershell
cd apps/api
.venv\Scripts\python.exe -m app.migrate_phase8 --apply
```

The migration adds organization access, task comments, real-user assignment metadata, archival timestamps, and assignment indexes. It does not delete or rewrite legacy tasks. Older tasks with only an assignee display name remain readable and can be reassigned to a real account through the task interface.

Task permissions follow organization access. Contributors and managers can create and edit tasks. An assigned user can update their own task status. Viewers cannot edit unrelated work. Only an eligible active workspace account with access to the task's organization can be assigned. Assignment and reassignment fan out through the Phase 7 notification pipeline, and overdue automation targets the real assignee when available.

Task comments are tenant- and organization-scoped. Task attachments reuse immutable Phase 4 `DocumentEvidenceLink` records and require an available stored document version. Removing an attachment archives the link and retains file history.

Useful task query parameters include `organization_id`, `compliance_id`, `assignee_user_id`, `status`, `priority`, `search`, `due_from`, `due_to`, `overdue`, `mine`, and `include_archived`. Organization, compliance, document, runtime detail, applicability, owner assignment, dashboard, portfolio, and audit reads use the same centralized organization scope.

Audit events are written for access grants/revocations, task creation/update/reassignment, comments, and evidence changes. Organization-scoped users only receive audit rows connected to organizations they can access.
