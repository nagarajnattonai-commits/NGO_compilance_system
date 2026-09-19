# NGO Compliance System ? Development Phases 1?5 final report

Date: 2026-09-19

## A. Phase 1 changes

- Centralized closed-state semantics for COMPLETED, CANCELLED and NOT_APPLICABLE across dashboard, risk, reports, calendar and filters.
- Added configurable cancellation, reasons and safe reopening rules while preserving historical records.
- Hardened Platform Admin access with verified provisioned accounts, admin-audience sessions, trusted host and allowlist checks.

## B. Phase 2 changes

- Added revision-controlled structured organization details and 12A/12AB/80G/FCRA/GST/CSR registration records.
- Added the 13-section tenant-branded profile, completeness, conditional fields, validation and safe audit summaries.
- Extended the existing attribute registry and rule evaluator with explicit typed organization/financial facts; unknown facts require review.

## C. Phase 3 changes

- Added persistent ten-step onboarding, Save & Exit/resume, atomic profile/progress updates and idempotent completion.
- Reused organization creation, invitations, responsibility records, applicability, generation, frozen tasks and reminders.
- Added dashboard continuation, review/edit links and honest empty/requires-review states.

## D. Phase 4 changes

- Added validated private original-file storage, immutable versions, checksum verification, quota/size/type protection and idempotent upload receipts.
- Added protected download/image preview, renewal, version selection, archive/restore, evidence links and pinned filing proof.
- Changed document coverage from metadata to real available stored bytes with configured validity.

## E. Phase 5 changes

- Fixed ownership for primary and additional authorized workspace accounts; added persisted manual assignment and Owner Required handling.
- Added template-scoped event facts and structured/real-file certificate expiry input.
- Persisted safe applicability decisions, comparisons, explanations and append-only overrides without changing rules or instances.
- Added explicit idempotent scheduler boundaries and next-cycle receipts; no worker loop was started.
- Connected real evidence and checklist completion to frozen workflow transitions with useful errors.
- Added a complete tenant-branded Compliance Detail for facts, owner, version, applicability, overrides, coverage, checklist/tasks, workflow, submission/proof, reminders and audit.

## Files created

Backend: `runtime_models.py`, `runtime_membership.py`, `runtime_decisions.py`, `runtime_cycles.py`, `runtime_api.py`, `migrate_runtime.py`, and `test_runtime_phase5.py`.

Frontend: `/compliances/[id]/page.tsx`, `runtime-detail.tsx`, `organization-runtime.tsx`, `lib/runtime.ts`, four runtime locale modules, and `phase5-lifecycle.spec.ts`.

Earlier phase files are recorded in this repository's preceding phase commits and `docs/DEVELOPMENT_PHASES_1_5.md`.

## Files modified

Phase 5 integrates with `compliance_engine.py`, `compliance_master.py`, `compliance_template_schema.py`, `main.py`, `onboarding.py`, the Compliance Master builder/runtime, organization profile/onboarding/workspace components, locale loader/catalogues, styling and browser fixtures. Existing engine bodies and frozen snapshots remain authoritative.

## Database migrations

Apply after backup and deployment review, in order:

```powershell
cd apps/api
.venv\Scripts\python.exe -m app.migrate_organization --apply
.venv\Scripts\python.exe -m app.migrate_onboarding --apply
.venv\Scripts\python.exe -m app.migrate_documents --apply
.venv\Scripts\python.exe -m app.migrate_runtime --apply
```

All migrations are additive, idempotent and ledger-recorded. Tests prove existing rows remain. No development or production database was automatically migrated, wiped or reseeded.

## Database models added/changed

Phase 5 adds `ComplianceOwnership`, `OrganizationEventFact`, `ApplicabilityOverride`, `ApplicabilityDecision`, and `NextCycleGeneration`. `Deadline` gains bounded `event_key`. Existing compliance, task, document, submission, template and snapshot tables are unchanged by this migration.

## API endpoints added/changed

Added:

- `GET/POST /api/v1/organizations/{id}/events`
- `POST /api/v1/organizations/{id}/events/{event_id}/generate`
- `GET /api/v1/organizations/{id}/applicability-history`
- `POST /api/v1/organizations/{id}/templates/{template_id}/override`
- `GET /api/v1/compliances/{id}/owner-candidates`
- `POST /api/v1/compliances/{id}/owner`
- `POST /api/v1/compliances/{id}/next-cycle`
- `GET /api/v1/compliances/{id}/runtime-detail`

Applicability preview/onboarding now persist important decisions. Generation uses saved effective decisions and explicit event/certificate facts. Snapshot transitions enforce genuine configured evidence.

## UI routes/components added/changed

`/compliances/[id]` is the full runtime detail. Organization Compliance and onboarding evaluation now expose re-evaluation and template event inputs. Existing drawers link to the full view and continue to use the existing frozen-template workflow component. All views use `OrganizationShell`, `BrandIdentity`, locale switching, theme tokens and responsive layouts.

## RBAC changes

Server authorization resolves the authenticated workspace and verifies every organization/compliance target. Only effective workspace administrators can create overrides, capture events, assign owners or generate next cycles. Candidates must have active non-viewer workspace access. Responsibility records do not grant login access. Read-only users can inspect authorized runtime records and cannot mutate them.

## Localization and design

New Runtime strings load for en-IN, hi-IN, kn-IN and mr-IN. English is the explicit fallback where reviewed legal translations are unavailable. Missing structured-profile field keys were filled with that declared fallback. No unverified machine translation was introduced. Responsive checks cover 320, 768, 1024 and 1440 widths.

## Security improvements

- Cross-tenant organization, compliance, document and runtime access returns not found/forbidden.
- Raw PAN/TAN are excluded from persisted decision/audit explanations.
- Optimistic owner/override checks prevent stale overwrites.
- File proof requires a genuine immutable version and tenant/organization match.
- Event keys are bounded and template-controlled; legal events and expiry dates are never guessed.
- Append-only decisions/overrides and frozen snapshots preserve forensic history.
- Concurrent generation retains the database uniqueness guard.

## Tests and results

- Backend: **228 passed**, one third-party Starlette deprecation warning.
- Phase 5 focused backend: **10 passed**.
- TypeScript strict/no-unused check: **passed**.
- Production build: **passed**, including `/compliances/[id]`.
- Browser/E2E: **37 passed** across clean split runs (12 compliance/onboarding/evidence/lifecycle cases plus 25 authentication/branding/integration/localization/marketing/profile cases; the two quota/race fixtures in the latter group were cleaned and rerun successfully).
- Final lifecycle covers verified signup, login/workspace, two NGOs, typed profile/registrations/PAN/TAN/financial facts, real upload, accepted team invitation and responsibility, evaluation/generation, ownership, task/evidence coverage, review/change loop, filing reference, immutable proof, completion, responsive runtime detail, and a second tenant denied from both NGOs/files/compliance.

## Known limitations

- Live SMTP, Google OAuth, S3 and malware scanner operation require deployment credentials and were not claimed as tested.
- S3 adapter behavior is covered with a controlled contract; a live bucket was not used.
- Concurrent generation was tested with disposable file-backed SQLite. PostgreSQL row-lock behavior was designed but not live-tested.
- Non-English legal/registration fallback text requires review by qualified translators.
- Deployment databases still require operator-reviewed migration execution and backup.

## Deferred items

No background scheduler, automatic email/WhatsApp reminders, calendar sync, OCR/AI extraction, payments, advanced reporting, mobile app, Kubernetes or microservice rewrite was added.

## Next recommended phase

Phase 6 should add a separately deployed scheduler/worker that calls the tested runtime service boundaries, with production PostgreSQL concurrency tests, delivery-provider retry/dead-letter handling, notification preferences, operational metrics and runbooks. It should keep generation explicit/idempotent and must not change frozen templates or historical evidence.
