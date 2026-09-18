# Development phases 1?5

This log records the implementation and verification of the requested sequential phases. Existing records and historical template snapshots are preserved. No destructive Git operations are used.

## Phase 1 ? Stabilization

Implemented configurable CANCELLED transitions, mandatory cancellation/reopening reasons, terminal workflow validation, centralized closed-state classification, consistent dashboard/risk/report/calendar handling, and localized cancellation labels in all four existing locales. Historical closed records remain available; cancelled/not-applicable records do not inflate active risk or the completion denominator.

Platform access now requires a verified, explicitly provisioned AuthAccount, allowlist membership, trusted platform host, and an admin-audience session. Legacy allowlisting alone does not confer access. Existing operators must use the existing offline `python -m app.auth_admin` provisioning command and sign in through `/admin/login`. Public signup cannot confer operator access.

Verification: backend regression suite, customer/platform authentication and compliance-master browser regressions, TypeScript strict lint/type check, and whitespace review. Results: 194 backend tests passed; 17 authentication/compliance-master browser tests passed; strict TypeScript check and `git diff --check` passed. OAuth and email integration tests use controlled provider responses. Live Google and SMTP delivery require deployment credentials and were not claimed as tested.

No database migration is needed for this phase.

## Remaining phases

2. Structured organization profile and typed organization facts.
3. Persistent, resumable onboarding using the existing profile and invitation services.
4. Private file storage, versioning and genuine evidence coverage.
5. Ownership, stored events, decision history, overrides and explicit next-cycle runtime services.

## Phase 2 ? Organization profile

Implemented `/organizations/[id]` with thirteen profile sections, revision-checked editing, save/cancel/validation/unsaved-change protection and controlled ACTIVE/SUSPENDED/ARCHIVED states. Existing organization and annual-revenue data remain authoritative. Companion details and registration records hold 12A/12AB/80G/FCRA/GST/CSR facts, dates, references and contact/address data. Profile setup completeness uses weighted sections and reports missing critical setup facts separately from legal health.

The existing typed attribute registry and AND/OR evaluator now resolve explicit organization and financial facts. Missing registration facts yield Requires Review. No statutory thresholds or arbitrary expressions were added. Both profile editing and the existing organization update endpoint enforce administrator access, tenant ownership, duplicate checks and tax identifier formatting. Audit entries contain field names rather than full PAN/TAN values.

Migration: `python -m app.migrate_organization --apply` creates only organization_details and organization_registrations plus an idempotent ledger entry. Migration tests preserve existing organization rows. No data is reseeded or removed by the migration.

Validation: 198 backend tests passed; profile browser regression passed including persistence, unsaved navigation protection, four locales and viewport widths 320/768/1024/1440; strict TypeScript check and whitespace review passed. New profile and attribute messages participate in the existing locale loader with explicit English fallback until reviewed legal translations are supplied. BrandIdentity and the existing theme/locale controls inherit the tenant branding context. Document records are displayed now; genuine file storage is delivered in Phase 4.
