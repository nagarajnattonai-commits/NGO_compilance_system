# Compliance Master implementation and handoff

The existing Next.js/FastAPI application is extended, not replaced. Global templates extend `compliance_definitions`; tenant obligations remain in `compliance_instances`. Published configuration is immutable and new versions never migrate historical obligations automatically. No new statutory requirements, thresholds or deadlines have been seeded.

## Plan and implemented scope

1. Preserve existing authentication, tenant enforcement, audit events, white-label tokens and next-intl.
2. Extend the catalogue with stable global identities, configurable categories, drafts, version history and optimistic concurrency.
3. Add an eleven-step responsive builder with typed rules, schedule, transitions, checklist, document requirements, responsibility, reminders, risk and template translations.
4. Require validation, review and approval before publication. Support change requests, cloning, archival, comparison and audit history.
5. Generate existing tenant compliance/task records from published configuration, attach immutable snapshots and deterministic reminder schedules, and reuse organization documents.
6. Verify backend security/runtime tests, browser governance/D&D/viewport tests, existing regressions, TypeScript and production build.

## Files created

Backend: `apps/api/app/compliance_template_schema.py`, `compliance_engine.py`, `compliance_master.py`, and `apps/api/tests/test_compliance_master.py`.

Frontend: `apps/web/lib/compliance-master.ts`; components `compliance-master.tsx`, `compliance-master-shell.tsx`, `compliance-master-sortable.tsx`, `compliance-template-builder.tsx`, `compliance-template-runtime.tsx`, `compliance-notification.tsx`, `organization-compliance-profile.tsx`, `platform-navigation.tsx`; route files/styles under `apps/web/app/admin/compliance-master`; module dictionaries `messages/{en-IN,hi-IN,kn-IN,mr-IN}/compliance-master.json`; `tests/white-label/compliance-master.spec.ts`.

## Files modified

Backend: `models.py`, `schemas.py`, `permissions.py`, `auth.py`, `main.py`.

Frontend: `lib/server-auth.ts`, `lib/types.ts`, `components/workspace.tsx`, `components/locale-switcher.tsx`, `i18n/messages.ts`.

Documentation: this file, README and feature coverage. Previously completed, uncommitted localization/main-page changes have been preserved.

## Database changes

Additive SQLAlchemy tables, compatible with the existing SQLite development database and PostgreSQL dialect:

| Table | Purpose |
| --- | --- |
| `compliance_categories` | Configurable global categories, enablement and order |
| `compliance_master` | One-to-one extension of the existing definition, globally unique code and active published-version pointer |
| `compliance_definition_versions` | Bounded validated JSON configuration, review/publish state, actors, timestamps, immutable published content and revision |
| `compliance_instance_snapshots` | Tenant/organization/version/cycle, complete frozen behavior, task references and original owner-resolution flag |
| `compliance_reminder_schedule` | Deterministic event key, due date, recipient/escalation configuration and delivery timestamp |
| `organization_compliance_profiles` | Explicit annual revenue and financial period; unknown financial data is not assumed to be zero |
| `compliance_notification_templates` | Localizable template key and variables attached to existing notification records |

Checklist, workflow, documents, reminders and translations are stored as bounded, typed version configuration. This avoids parallel mutable child records bypassing version immutability. The application already uses validated JSON-text configuration for white-label versions; the same persistence pattern is reused here.

Existing columns are not deleted or rewritten. The project's existing `Base.metadata.create_all` creates the new tables on API restart. It is not a production migration manager: introduce and review explicit PostgreSQL migrations before deployment. Back up production data first. Global definitions use reserved scope `platform-global` and are consumed only through the published-version engine, never the legacy month/day generator. Compatibility month/day metadata is not the source of statutory dates; non-fixed deadlines are returned as null in the existing catalogue API.

## API changes

All management endpoints require an authenticated, active ADMIN whose email is in the existing `PLATFORM_ADMIN_EMAILS` allowlist **and** has the appropriate named permission. Existing CSRF/origin/custom-domain protection applies. Tenant headers cannot grant platform access.

- `GET /api/v1/admin/compliance-master/access`
- `GET /api/v1/admin/compliance-master/metadata`
- `GET /api/v1/admin/compliance-master/organizations` — paged, explicitly platform-authorized sample selection
- `GET/POST /api/v1/admin/compliance-categories`
- `PATCH /api/v1/admin/compliance-categories/{id}`
- `GET/POST /api/v1/admin/compliance-templates`
- `GET/PATCH /api/v1/admin/compliance-templates/{id}` — optional GET `version`
- `POST .../{id}/validate`, `/submit-review`, `/approve`, `/request-changes`, `/publish`, `/archive`, `/new-version`, `/clone`, `/test-applicability`
- `GET .../{id}/versions`, `/compare?before=1&after=2`, `/audit`
- `GET /api/v1/compliance-templates` — tenant-authenticated, current published versions only; platform internal notes omitted
- `POST /api/v1/organizations/{id}/evaluate-compliance` — non-destructive applicability preview
- `GET/PATCH /api/v1/organizations/{id}/compliance-profile` — owned organization, existing admin mutation restrictions, audit logging
- `GET /api/v1/compliances/{id}/template-snapshot` — owned tenant only; snapshot evidence coverage and actor-permitted transitions

Existing onboarding and `POST /organizations/{id}/generate-plan` now use the engine. Generate-plan optionally accepts `{ "event_date": "2026-09-17" }` for explicitly entered event-based cycles, without altering existing instances. Existing `/compliance-definitions` includes published global definitions without duplicating claimed legacy codes. Existing compliance transition/PATCH endpoints enforce snapshot roles, approval, evidence, checklist and document rules. Legacy transitions remain unchanged for obligations without snapshots. Filing proof remains required if the configured workflow includes FILED; non-filing workflows do not inherit an unrelated filing requirement.

Existing `/automation/run` dispatches scheduled in-app reminders using the existing unique `automation_receipts`, and evaluates new cycles for the authenticated tenant. Template instances do not inherit the legacy fixed thirty-day reminder or automatic annual roll-forward. Overdue presentation continues to use unchanged statutory dates without replacing configured workflow states.

## Permissions and routes

Permissions: `compliance_master.view`, `.create`, `.edit`, `.review`, `.publish`, `.archive`, `.version`, `.clone`. These extend the existing role permission map; the platform email gate is mandatory in addition to the ADMIN role. Tenant administrators cannot manage global templates. The architecture can later map the named permissions to additional platform roles without changing endpoint contracts.

Routes: `/admin/compliance-master`, `/admin/compliance-master/new`, `/admin/compliance-master/[id]`. `#review` and `#history` open the corresponding builder view. Server layouts verify access through the API, and APIs independently enforce permissions. The existing Administration page shows platform links only after a successful access check and exposes owned-organization financial facts separately.

No new dependencies. Reuses next-intl, dnd-kit, lucide, FastAPI, Pydantic and SQLAlchemy. D&D uses Mouse/Touch/Keyboard sensors and button-based ordering. Touch delay/tolerance and `touch-action: manipulation` follow the installed-version [dnd-kit touch sensor documentation](https://dndkit.com/legacy/api-documentation/sensors/touch/) and keep ordinary page scrolling available outside active dragging.

## Runtime semantics

- Applicability supports AND/OR groups and datatype-specific operators, with no expressions, JavaScript or `eval`. Numeric comparisons use decimal facts; date comparisons use ISO dates. Empty text is distinct from unknown numeric data. Missing required data yields Requires Review rather than fabricated applicability.
- Revenue must have an explicitly entered financial period. Admins can include `revenue_period` in rules; the system does not infer which fiscal year's revenue a legal threshold uses.
- Fixed periodic dates advance by the configured interval; one-time dates do not recur. Period-end rules use an explicit first-of-month anchor. Fiscal-year context uses configured start month. Event deadlines require an explicitly provided event date. Certificate expiry comes from the organization's document category. Invalid dates in a short month require review rather than an invented legal adjustment.
- Deadline calculation uses date-only values. Internal target lead time never edits the statutory deadline. Server automation currently uses the server calendar date; a per-tenant-timezone worker remains production work.
- The unique `(tenant, organization, definition, cycle)` snapshot constraint and PostgreSQL organization lock prevent duplicate generation. Existing legacy instances with identical code/deadline are flagged for migration, not silently modified.
- An active current published pointer is required for new generation. Archival clears that pointer even when an unpublished draft exists. Historical content, tasks, evidence and completed instances are preserved.
- Responsibility resolves active organization/tenant memberships to active auth users; configured fallback is tried. Unknown owners are visibly flagged. Template rules refer to roles, never a hard-coded person.
- Required evidence can use existing organization documents. Completion checks minimum counts, expiry-through-deadline and required task completion. Document expiry absence currently means no configured expiry, not a verified certificate validity assertion.
- Global configuration is shared, but generated records, receipts, snapshots and notifications are tenant-owned. Branding does not duplicate templates. Internal platform notes are not returned to tenant consumers.
- English template content is the fallback. Four locale dictionaries cover the builder and runtime controls. Notification variables preserve localized names/reminder text from the frozen version and format the deadline through existing locale utilities.

## Tests added

`test_compliance_master.py`: creation, duplicate codes, filters, sorting, pagination, draft conflict, review/approval/publication, immutable versions, required change summary, clone, archive with pending draft, history/comparison, invalid rules/URLs/workflows/numeric values, AND/OR, unknown financial data, date/numeric comparisons, recurrence/deadlines, owner fallback, generated task snapshots, repository evidence reuse, reminder retries and non-platform denial.

`compliance-master.spec.ts`: complete UI governance flow, live applicability preview, persisted checklist reordering using keyboard/pointer input, version history/audit UI, generated snapshots, module dictionary parity, all eleven builder steps and table overflow at 320/360/375/390/425/768/1024/1280/1440/1920px in all four locales, and tenant URL/API denial. Browser QA uses disposable databases, separate build output and ports 3001/8001. Actual-device touch testing remains recommended.

## Known limitations and recommended next step

This is a tested configurable core, not a claim that all production infrastructure is connected:

1. Add explicit PostgreSQL migrations, PostgreSQL concurrency CI and a durable job queue/worker. Large all-tenant evaluation is not exposed as a synchronous bulk operation. Publishing activates configuration for future generation; it does not synchronously write obligations into every tenant.
2. Connect a scheduled worker for tenant-timezone recurrence/reminders. Daily automation is an existing explicit tenant-admin action, not an installed cron service.
3. In-app notifications use the existing tenant-wide inbox. Recipient roles and escalation levels are recorded, but private per-user recipient routing, email/WhatsApp delivery, verified delivery logs and entitlement-backed external channels remain provider work. Template key/variables prepare localized email delivery without claiming it is sending.
4. Only FUTURE_INSTANCES is supported. A reviewed, selected-instance migration UI/job should come next; completed historical obligations must remain untouched. No automatic migration or deletion on profile changes.
5. Existing demo legacy catalogue remains as a compatibility source until an administrator replaces it with reviewed master definitions. No automatic legal-data import or invented regulatory data.
6. New templates use existing stable workflow states; administrators configure transitions and labels rather than introduce unrecognized database states. Workflows are template-specific; a reusable global workflow library/rule-management hub can follow.
7. Save Draft is explicit, not autosave. Recoverable errors retain editor state. Conflict guidance asks the admin to preserve unsaved configuration and reload; automated three-way merges are not implemented.
8. Category editing/order/enablement uses the API and existing form pattern. No separate category drag-and-drop page. Version comparison displays structured section changes, not a rich side-by-side diff.
9. Audit endpoint is paginated; the builder initially displays the latest fifty audit entries. Sample organization picker searches the first thirty matches. Future tenant-owned custom definitions/inheritance are not implemented; existing tenant catalogue/instances remain distinguishable from global scope.

Recommended next implementation: reviewed database migrations plus durable, idempotent applicability/recurrence/reminder jobs, followed by controlled active-instance migration and private recipient delivery.

## Follow-up review

See [Compliance Master review and implementation](COMPLIANCE_MASTER_REVIEW.md) for the current draft-safety, checklist-localization, permission, accessibility, and browser-regression updates, including local platform access setup and production limitations.
