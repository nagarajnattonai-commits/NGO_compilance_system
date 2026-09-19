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

## Phase 3 ? Persistent onboarding

Implemented `/onboarding`, a dashboard continuation prompt and ten server-tracked steps after the existing account/workspace flow. Organization creation, profile editing, login invitations, responsibility records, rules, generation, checklist creation, frozen snapshots and reminders reuse existing services. Login access and responsibility records are explicitly distinguished.

Progress includes tenant/organization, current/completed steps, revision and UTC start/update/completion timestamps. Profile and progress saves share a transaction; stale writes roll back both. Save & Exit and subsequent login/resume restore actual server data. Conditional registration fields collect facts without deciding statutory applicability. Review provides edit actions and setup completeness. Completion evaluates published templates and refuses missing rule/deadline facts without partially generating instances. Repeated completion does not generate duplicates. An empty master catalogue is clearly displayed and produces an empty plan.

Migration: `python -m app.migrate_onboarding --apply` adds organization_onboarding and a ledger entry. No existing records are rewritten. Documents remain optional in this step and are connected to actual upload in Phase 4.

Validation: 203 backend tests passed, including atomic revision conflict rollback, missing applicability/deadline gates and idempotent generation/completion; onboarding save/exit/resume/review/evaluate/dashboard browser journey passed; the organization profile browser regression passed; strict TypeScript check and whitespace review passed. The browser checks caught and fixed a draft overwrite caused by a delayed route reload. New messages use existing locale loading and English fallback. Live verification/invitation delivery continues to require the existing SMTP configuration.

## Phase 4 ? Private original files and genuine evidence

Implemented a dedicated document storage/service/API abstraction around existing Document/DocumentVersion records. Backend multipart upload validates tenant, organization, role, category, MIME/extension, file signatures, dates, configurable size and workspace storage quota. A database-unique tenant/request receipt makes completion retries idempotent. Replacement uploads require the expected version, use new immutable objects, retain every old version and support explicit current-version selection. Failed storage verification rolls back metadata and removes only the uncommitted object. No historical file is deleted.

Protected content endpoints return checksum-verified original bytes with attachment, no-store and nosniff headers. Validated images have a constrained preview; PDF and Office files are protected downloads. Document facts show explicit effective/expiry dates and factual expiry status. Archival retains versions and filing relationships. Evidence links cover organization/compliance/task/submission and pin the original proof version, so later renewal does not rewrite a filing record.

The shared file library replaces metadata-only upload/detail/download behavior in the workspace, profile and onboarding. Legacy metadata remains visible with no stored original. Required-document coverage now requires a matching organization/category, available current file, verified storage and configured validity. Metadata, quarantined/processing files, expired evidence, missing objects and checksum failures cannot satisfy coverage.

Migration: `python -m app.migrate_documents --apply` adds document_file_versions, document_current_files, document_upload_receipts and document_evidence_links plus the ledger entry. Existing metadata/version rows remain unchanged.

Configuration: development stores files outside the public web directory in DOCUMENT_FILE_DIR (default apps/api/data/private-documents). Production requires a configured managed aws_s3 connection or DOCUMENT_S3_BUCKET with server-side AWS credentials; DOCUMENT_S3_ENDPOINT must be HTTPS. Buckets must enable all four S3 Block Public Access settings. Original storage configuration/credential references are retained per file. Uploads use encryption and conditional object creation. DOCUMENT_MAX_SIZE_MB defaults to 25 and supports 1?100. DOCUMENT_SCAN_REQUIRED=true refuses upload without a real scanner. The scanner contract supports processing/quarantine/failure/clean outcomes. The default scanner status is honestly NOT_SCANNED.

Validation: 218 backend tests passed, including 15 dedicated file-security cases; original-byte/checksum download, replay/renewal, old-version download, selection/archive, size/chunked limits, invalid formats, storage-failure rollback/retry, storage quota, path injection, required evidence, expiry/corruption, pinned filing/task proof, scanner quarantine, tenant/read-only boundaries and migration preservation are covered by backend tests. The actual-file browser journey and onboarding regression passed; strict TypeScript and whitespace checks passed. Live S3 and antivirus operation require deployment configuration and are not claimed as verified.


## Phase 5 ? Compliance runtime integration

Implemented tenant-aware ownership, persistent event facts, saved applicability decisions, append-only manual overrides, explicit next-cycle generation, and a complete `/compliances/[id]` runtime view without replacing Compliance Master, the rule evaluator, deadline calculator, frozen snapshots, or the existing transition engine.

Owner resolution now combines primary workspace accounts and active additional `WorkspaceAccess`, then matches active organization/workspace responsibility records. Viewer/inactive access never resolves. A configured role with no eligible account remains `Owner Required`. Workspace administrators can assign/reassign an eligible owner with optimistic conflict detection, actor/time/reason audit, while historical audit records remain intact.

Applicability evaluation stores a safe material-facts snapshot/hash, frozen template version, rule result, effective result, explanations, actor/time and comparison. PAN/TAN values are redacted/fingerprinted. Overrides are append-only `FORCE_APPLICABLE`, `FORCE_NOT_APPLICABLE` or `CLEAR_OVERRIDE` records; the original rule is never changed. Clearing an override returns the effective result to the rule while keeping the complete override history. Re-evaluation never deletes or changes existing compliance, tasks, evidence, submissions, proofs or audit history.

Event deadlines now require a template-scoped event key, actual date, source, creator and time. The legacy explicit event-date generation API persists that authenticated request as an event fact for compatibility. Certificate-expiry deadlines use the structured registration expiry or a verified current original file; conflicting dates require review and no date is guessed.

Scheduler-ready boundaries `generate_due_instances`, `evaluate_organization`, `generate_next_cycle` and `dispatch_due_reminders` are explicit, tenant-scoped, transaction-aware and idempotent. No background loop was added. The existing tenant/organization/template/cycle snapshot uniqueness remains the final duplicate guard; SQLite concurrent-call tests exercise serialized generation and next-cycle receipts. PostgreSQL uses organization row locking but was not tested against a live deployment database.

Required-evidence transitions and completion now validate actual available, checksum-verifiable, correctly scoped and date-valid originals, with named requirement counts in errors. Completion still enforces the frozen required checklist and filing/submission behavior. The full lifecycle remains driven only by transitions frozen in the instance snapshot.

Migration: `python -m app.migrate_runtime --apply` adds `compliance_ownership`, `organization_event_facts`, `compliance_applicability_overrides`, `compliance_applicability_decisions`, and `compliance_next_cycle_receipts`, plus an idempotent ledger entry. It creates companion tables only and rewrites no existing record.

Validation: 228 backend tests passed. Ten Phase 5 tests cover additional workspace access, inactive/viewer exclusion, manual assignment and stale conflicts, effective-role isolation, Owner Required, material re-evaluation, saved/redacted decisions, override/create/clear authorization and history, event source/date/idempotency, certificate expiry/conflict, period next-cycle replay, real-evidence workflow completion, additive migration, cross-tenant denial, and concurrent generation. Strict TypeScript passed. Production Next build passed. All 37 browser tests passed across clean split runs, covering authentication, branding, integrations, localization, marketing, organization profile, Compliance Master in all locales, onboarding, original-file evidence and the verified-customer lifecycle. The first combined attempt was interrupted externally and produced invalid multi-hour timing failures; every affected case was rerun cleanly and passed.
