# Compliance Master review and implementation

## Repository inspection and plan

The repository already implements the requested global template builder and runtime engine. Review covered the README, source documents in Development Documents, feature coverage, compliance/white-label operations, App Router pages/layouts and installed Next.js guidance, existing CSS/form/table patterns, dnd-kit, localization, authentication/RBAC, entitlements, database models, API conventions, instance generation, automation, and backend/browser tests.

Incremental plan:
1. Keep the existing global definition/version and tenant instance/snapshot architecture.
2. Fix incomplete draft saving without weakening publication validation or typed rule safety.
3. Complete checklist localization and remove obsolete translation references in the editor.
4. Make frontend actions reflect actual server permissions and clear obsolete reviewer attribution.
5. Verify isolated backend/browser regressions, responsive layouts, TypeScript and production build.

## Existing capabilities reused

- Routes: /admin/compliance-master, /admin/compliance-master/new, /admin/compliance-master/[id].
- Configurable categories; debounced search; server filters, sorting and pagination; KPI cards.
- Eleven-step builder covering basic information, structured AND/OR applicability, recurrence/deadlines, workflow, checklist, documents, responsibilities, reminders/escalation, independent risk/priority, localization and governance.
- Mouse/touch/keyboard dnd-kit sensors and accessible ordering buttons.
- Draft, review, approval, publication, cloning, archival, immutable published content, new draft versions, history, comparison and optimistic revision checks.
- Published global configuration drives tenant-owned instances, checklist tasks, evidence requirements, owner resolution, frozen configuration snapshots and idempotent in-app reminders.
- Organization documents satisfy evidence requirements without repeated uploads. Statutory and internal deadlines remain distinct. Historical instances are unchanged by new publication.
- Existing tenant, branding, localization, audit, calendar/dashboard/report and notification boundaries are retained.

## Changes in this implementation

Safe drafts may contain unfinished typed rule values (null, empty text/date, empty IN lists). Malformed fields/operators and wrong nonempty value types remain rejected. Publication/review validation reports the unfinished condition ID. Preview represents an unfinished condition as unknown instead of evaluating it as a match or raising a date error.

Checklist translations now include checklist_descriptions and checklist_instructions. The editor and tenant runtime expose them with English fallback. Missing translated content has a visible indicator. Removing checklist/document/reminder items prunes only their corresponding translation entries. Backend publish validation still rejects stale references submitted directly.

Builder controls now have explicit localized accessible names, independent of option/value text. Drag handles have explicit activator refs; keyboard tests wait for activation/movement before dropping. Responsive matrices run per locale with independent results.

Platform access and metadata return the actual permissions from the existing role map. Table and builder actions follow these permissions; server authorization remains mandatory. Requesting changes clears reviewed_by and still requires a fresh review/approval cycle. Reversed updated-date filters return a clear 422 response.

## Handoff

Files created: this review document.

Files modified:
- apps/api/app/compliance_template_schema.py
- apps/api/app/compliance_engine.py
- apps/api/app/compliance_master.py
- apps/api/tests/test_compliance_master.py
- apps/web/lib/compliance-master.ts
- apps/web/components/compliance-master-sortable.tsx
- apps/web/components/compliance-master.tsx
- apps/web/components/compliance-template-builder.tsx
- apps/web/components/compliance-template-runtime.tsx
- apps/web/tests/white-label/compliance-master.spec.ts
- docs/COMPLIANCE_MASTER.md
- docs/feature-coverage.md

Database changes: no new tables/columns or migrations. Two optional mappings extend the existing version JSON schema; older stored configuration is normalized on read without rewriting published data.

API changes: additive permissions in metadata, accurate access permissions, additive optional checklist translation mappings, draft-safe empty applicability values, and clear date-range validation. Existing endpoints remain in use.

Permissions: no new names. Reuses compliance_master.view, .create, .edit, .review, .publish, .archive, .version, .clone, together with the mandatory platform email allowlist.

Routes/dependencies: none added.

Tests added: nine parameterized/backend regressions for incomplete drafts, fresh approval, actual permissions, translation snapshots/backward-compatible defaults and date filters; three browser regressions for touch reordering, translation cleanup, failed-save recovery and permission-aware controls. Existing governance, rule/deadline/runtime, cross-tenant, responsive and drag-and-drop tests are retained.

## Local access

Create an ADMIN account through signup or python -m app.bootstrap_admin for the seeded demo workspace. Set PLATFORM_ADMIN_EMAILS to the approved account email in both API and web process environments before starting those processes. No default platform administrator or password is created.

PowerShell: $env:PLATFORM_ADMIN_EMAILS = 'your-approved-admin@example.org'

Visit /admin/compliance-master after signing in. Global regulatory templates are deliberately not invented or imported by this work; create a category and configure a sample or independently validated template.

## Production limitations

The feature runs on the repository's current SQLite development setup and SQLAlchemy PostgreSQL path. PostgreSQL concurrency has not been verified here. Explicit reviewed PostgreSQL migrations, durable scheduled workers, timezone-aware scheduling, deployment credentials and operational monitoring remain production infrastructure work documented in COMPLIANCE_MASTER.md.

Email/WhatsApp channels require provider delivery and entitlement integration; the builder exposes only the supported in-app channel. The existing inbox is tenant-wide with recipient roles recorded, rather than private per-user delivery. Bulk all-tenant evaluation, selected active-instance migration and tenant template inheritance remain later enhancements. Publication affects future generation and never automatically migrates completed instances. Actual-device touch QA remains separate from automated browser checks.

Recommended next implementation: reviewed PostgreSQL migrations and concurrency CI, followed by durable tenant-scoped recurrence/reminder jobs and private recipient delivery.


## Verification results

- Full API regression suite: 137 passed. The nine targeted new backend cases also passed after final review.
- Full isolated browser suite: 16 passed, including existing white-label/public/localization regressions, governance, permission controls, save recovery, and mobile touch ordering.
- All eleven builder steps plus the master table verified at 320, 360, 375, 390, 425, 768, 1024, 1280, 1440 and 1920px in en-IN, hi-IN, kn-IN and mr-IN. Normal builder and responsive cases report no unexpected browser console/page errors.
- Keyboard, pointer and mobile touch reordering verified. Actual-device testing remains recommended.
- TypeScript/no-unused checks and final production build passed.
- Existing local API health returns ok; website returns HTTP 200.
- No new source dependencies, destructive Git operations, database resets or automatic historical-instance migrations.
- Next.js-generated tsconfig/next-env changes from isolated build directories were restored to their committed content.

Initial browser failures exposed changing accessible names in form labels, a premature organization-option selection, a keyboard-drop timing assumption, an overly broad alert selector, and a fieldset assertion mismatch. These were corrected without replacing application modules. Splitting the viewport matrix by locale exposed repeated duplicate-signup calls consuming the signup rate limit; fixtures now reuse the test account. Production rate limits are unchanged.

The API suite emits one existing third-party BlockingPortal deprecation warning; it does not fail validation.
