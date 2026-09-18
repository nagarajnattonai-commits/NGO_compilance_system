# Integrations and API management

## Inspection and implementation plan

Existing architecture: Next.js App Router/React/TypeScript, FastAPI/SQLAlchemy, SQLite development persistence and opt-in PostgreSQL deployment. Authentication resolves an active session to a workspace. ADMIN/MEMBER/VIEWER roles use named permissions; platform operators additionally require PLATFORM_ADMIN_EMAILS. White label resolves verified hosts and applies shared branding tokens. next-intl supports module dictionaries, language ordering, tenant overrides and display preferences in en-IN, hi-IN, kn-IN and mr-IN.

The existing integration_connections table and /api/v1/integrations were capability-readiness placeholders. SMTP credentials lived in auth.py environment settings; branding already used BrandStorage with deployment S3 credentials. Notifications, evidence metadata, synchronous daily compliance automation, subscriptions, explicit TenantEntitlement and AuditEvent records were reusable. No vault references, verified webhook ingress, public API keys or durable integration queue existed.

Phases implemented: registry/vault foundation; platform and tenant management; required provider protocols/adapters; signed ingress and persistent webhook outbox; scoped read-only public API; health/log metrics and alerts; backend/browser security and responsive QA. Existing authentication, tenant context, branding, localization, audit, entitlement, notification templates and connection table are reused. OAuth is deferred to an approved identity provider.

## Architecture implemented

Application service -> integration resolver -> registry -> adapter -> server-only vault -> provider.

Platform/tenant connections reuse integration_connections with one-to-one integration_connection_settings. To preserve the original non-null tenant_id column, PLATFORM uses reserved internal owner __platform__. Typed scope is separate; responses expose null tenant_id for platform entries. Clients cannot select this owner.

Resolver uses server tenant context, category, capability and environment. An active, entitled tenant connection wins. Platform fallback is explicit on each platform connection. Disabled providers, inactive/unactivated connections, wrong environments, expired entitlements/subscriptions and cooldown connections are skipped. Managed platform email policy overrides the historical environment SMTP bridge. WhatsApp never inherits email fallback.

Save -> credentials -> explicit test -> explicit activate. Successful tests leave CONFIGURED, not CONNECTED. Activation requires current configuration passed within 15 minutes. Configuration/credential replacement invalidates approval. Disconnect disables usage. Tests persist sanitized codes/timing/history, quotas/cooldowns and one localized alert after three consecutive failures. Health pages display recorded results and database metrics; they never test external providers on render.

Password recovery calls the centralized email service, preserving tenant branding and verified sender. Existing operator SMTP settings remain a compatibility adapter. In-app compliance reminders remain intact.

Public caller -> key hash -> tenant/verified-host check -> entitlement -> read scope -> atomic SQL quotas -> curated tenant records -> usage metadata. Strong keys use 320 random bits, SHA-256 hashes, non-secret prefix/suffix, granular scopes and mandatory 1-365 day expiration. Lists never return hashes or raw keys; creation displays the key once. Revocation denies subsequent requests immediately.

## Created files

Backend:
- apps/api/app/integration_models.py
- apps/api/app/integration_security.py
- apps/api/app/integration_providers.py
- apps/api/app/integration_service.py
- apps/api/app/integration_api.py
- apps/api/app/developer_api.py
- apps/api/app/integration_notifications.py
- apps/api/app/integration_worker.py
- apps/api/app/migrate_integrations.py
- apps/api/tests/test_integrations.py

Frontend:
- apps/web/lib/integrations.ts
- apps/web/components/integration-shell.tsx
- apps/web/components/integration-management.tsx
- apps/web/components/developer-management.tsx
- apps/web/components/integration-management.css
- apps/web/app/admin/integrations: layout.tsx, page.tsx, [section]/page.tsx
- apps/web/app/admin/developers: layout.tsx, page.tsx, [section]/page.tsx
- apps/web/app/settings/integrations: layout.tsx, page.tsx, [section]/page.tsx
- apps/web/app/settings/developers: layout.tsx, page.tsx, [section]/page.tsx
- apps/web/messages/en-IN/integrations.json
- apps/web/messages/hi-IN/integrations.json
- apps/web/messages/kn-IN/integrations.json
- apps/web/messages/mr-IN/integrations.json
- apps/web/tests/white-label/integrations.spec.ts
- docs/INTEGRATIONS_IMPLEMENTATION.md

## Modified files and dependencies

auth.py routes reset emails through the resolver; main.py registers routers and transactional domain events and secures the legacy register; permissions.py adds named permissions. platform-navigation.tsx/workspace.tsx add links; compliance-notification.tsx localizes provider alerts; i18n/messages.ts registers dictionaries. next-env.d.ts/tsconfig.json align default generated types and exclude obsolete isolated build/QA output. deploy/compose.white-label.yml adds the opt-in worker/vault environment. README.md and docs/feature-coverage.md document actual implementation and limits.

No new source packages. Uses existing FastAPI, SQLAlchemy, Pydantic, boto3, next-intl, Playwright and standard-library HMAC/SHA/SMTP/HTTPS.

## Database migrations

ID: 20260918_integrations_v1.

Additive tables: integration_providers, integration_connection_settings, integration_health_checks, integration_operation_logs, integration_rate_windows, integration_schema_versions, webhook_subscriptions, webhook_events, webhook_deliveries, api_applications, api_keys, api_usage_records.

Existing connection columns/rows and other legacy tables remain unchanged. No automatic secret import, data reset or destructive rollback. Idempotent SQLAlchemy migration creates tables in dependency order and records a receipt; tests verify old columns/rows survive two applications. Development startup also uses the existing create_all path.

After initializing the existing schema and reviewing backups, from apps/api:

    .venv/Scripts/python.exe -m app.migrate_integrations
    .venv/Scripts/python.exe -m app.migrate_integrations --apply

Use .venv/bin/python on Linux. Run migrations once before the worker.

## API endpoints

Prefix /api/v1. Session mutations retain X-Setu-Request and trusted-origin checks. scope is platform or tenant; platform requires role, allowlist and permission.

- GET /integrations-management/access
- GET /integrations-management/{scope}/providers
- PUT /integrations-management/platform/providers/{key}
- GET/POST /integrations-management/{scope}/connections
- PATCH /integrations-management/{scope}/connections/{id}
- PUT/DELETE /integrations-management/{scope}/connections/{id}/credential
- POST /integrations-management/{scope}/connections/{id}/{test|activate|disconnect}
- GET /integrations-management/{scope}/health
- GET /integrations-management/{scope}/logs
- GET /integrations-management/{scope}/audit
- GET /integrations-management/platform/tenants
- PUT /integrations-management/platform/tenants/{tenant}/entitlement
- GET /integrations-management/platform/webhooks
- GET /integrations-management/platform/developer/{applications|api-keys|usage}
- GET/POST /developer/applications
- GET/POST /developer/api-keys
- POST /developer/api-keys/{id}/revoke
- GET /developer/usage
- GET /developer/documentation
- GET/POST /developer/webhooks
- PATCH/DELETE /developer/webhooks/{id}
- POST /developer/webhooks/{id}/{rotate|test}
- GET /developer/webhooks/{id}/deliveries
- POST /inbound-webhooks/{id}: generic signature authentication, not session cookies.
- GET /public/{organizations|compliances|tasks|documents}: Bearer key, page/page_size.

Connection filters: page/category/status/environment and platform tenant_filter. Logs paginate and accept provider_key/status. There is no saved-credential GET API. Platform operators inspect tenant metadata but cannot mutate tenant secrets through platform connection endpoints. Legacy placeholders cannot claim CONNECTED without managed setup/testing.

## Permissions and entitlements

Named permissions, granted to ADMIN by default and absent for MEMBER/VIEWER:
integrations.platform.view, integrations.platform.manage, integrations.tenant.view, integrations.tenant.manage, integrations.credentials.rotate, integrations.webhooks.manage, integrations.logs.view, integrations.health.view, api_keys.view, api_keys.create, api_keys.revoke, oauth_clients.manage.

Platform role/allowlist and named permissions are independent backend checks. OAuth permission is reserved and does not enable unsupported endpoints.

Entitlements: custom_email, whatsapp_integration, google_calendar_integration, custom_storage, custom_webhooks, public_api. Availability requires ACTIVE, unexpired subscription and enabled, unexpired TenantEntitlement. No plan-name tests or implicit grant from branding. Platform operators configure at /admin/integrations/tenants. Disconnect/disable/revoke remain available for existing configuration.

Public read scopes: organization.read, compliance.read, tasks.read, documents.read. No full_access/default write scope.

## Provider adapters added

- SMTPAdapter: verified TLS SMTP, deployment-approved host allowlist, authentication/test/send_email; branded output and verified sender.
- WhatsAppAdapter: fixed Meta Graph API host, configured API version, test/send_message/send_template.
- GoogleCalendarAdapter: fixed Google API host, server token, test and deterministic event creation/update/cancellation.
- S3Adapter: fixed AWS SDK transport, validated bucket/region/prefix, server JSON credentials, test/upload/download/delete and encryption request.

Common and specialized protocols are reusable. AI/OCR/translation/payment/analytics/other categories are extension points, not fictional integrations. BrandStorage remains default brand asset storage. Document metadata stays independent from external drives.

## Environment and Secret Manager requirements

Existing: DATABASE_URL, APP_ENV, APP_ORIGIN, PLATFORM_ADMIN_EMAILS on API and web, BRAND_PROXY_KEY for the trusted internal proxy, existing AWS/SMTP/storage deployment settings.

New:
- INTEGRATION_SECRET_BACKEND: environment for local read-only development; aws for writable Secrets Manager. Production rejects the environment store.
- INTEGRATION_SECRET_PREFIX: default setu/integrations; separate dev/production namespaces.
- INTEGRATION_SECRET_KMS_KEY_ID: optional customer-managed encryption key.
- INTEGRATION_SMTP_HOSTS: comma-separated operator-approved managed SMTP hosts. Existing SMTP_HOST is also operator-approved.
- INTEGRATION_LEGACY_EMAIL_FALLBACK: 1 preserves historical environment EMAIL bridge; 0 disables. A managed platform email policy overrides it.
- PLATFORM_ALERT_TENANT_ID: optional operator workspace for internal platform alerts. Explicit management checks target the caller workspace.
- SETU_SECRET_<UUID_NO_HYPHENS_UPPERCASE>: per-connection local value, injected into the API process. Never NEXT_PUBLIC or tracked settings.

Development store is intentionally read-only. Create configuration first, inject its per-connection environment secret and test. Credential writes/rotation/webhook creation require a writable vault; UI explains disabled actions. AWS development should use its own restricted namespace.

References contain operator prefix, server-derived tenant hash and generated UUID; clients cannot select arbitrary references. Backend IAM requires CreateSecret/GetSecretValue/PutSecretValue/DeleteSecret/DescribeSecret/RestoreSecret restricted to the namespace, plus required KMS permissions when selecting a customer key. Prefer workload roles. AWS encrypts vault values; database stores only references/fingerprints. Rotation creates a new vault version. Delete uses seven-day recovery; explicit replacement can restore then overwrite.

Only backend services implement get_secret_for_server_use. API keys/generated webhook signing secrets have one-time issuance responses; all API responses have no-store headers. Temporary UI values remain only in component state, never browser storage/URLs/logs.

## Webhooks added and durable processing

Generic inbound protocol: HMAC-SHA256(timestamp + dot + exact body); X-Setu-Timestamp; X-Setu-Signature=sha256=<hex>; five-minute freshness; <=16 KB body; unique external ID per subscription. Admits exactly id/type/entity_id, approved event types and bounded identifiers. Invalid signatures/stale requests fail; verified duplicates safely succeed. Verification/vault access runs off the ASGI event loop. Generic ingress records metadata/audit, never completes compliance or payments.

Outbound endpoints must be public HTTPS port 443 without userinfo/query/fragment. DNS results are checked at setup/delivery; all addresses must be public. Transport connects to the checked IP with original-host TLS validation, does not re-resolve/follow redirects/use environment proxies, and discards response bodies.

Compliance create/complete/overdue, task complete and document upload events enqueue metadata in the domain transaction. webhook.test allows explicit testing. Catalogue reserves document.expiring/user.created for future hooks. Jobs enforce unique subscription/event ID, compare-and-swap leases/crash recovery, bounded exponential backoff/jitter/Retry-After, five attempts and permanent auth/configuration failure handling. Disabled/deleted/ineligible subscriptions cancel pending jobs.

Receivers deduplicate by event ID; network delivery is at least once.

Run from apps/api:

    .venv/Scripts/python.exe -m app.integration_worker
    .venv/Scripts/python.exe -m app.integration_worker --loop

Opt-in production Compose supervises the worker. Quota windows prune hourly. Fixed windows: 60/key/minute, 300/tenant/minute, 6000/platform/minute. Credential writes/tests, inbound hooks and outbound delivery have additional quotas. No worker runs silently inside web requests.

## Routes, white label, localization and accessibility

/admin/integrations/{providers,connections,credentials,webhooks,logs,health,tenants,audit}
/admin/developers/{applications,api-keys,webhooks,usage,documentation,oauth}
/settings/integrations/{connections,providers,webhooks,health,logs}
/settings/developers/{applications,api-keys,webhooks,usage,documentation,oauth}

Layouts require authentication and ADMIN; platform also requires allowlist. Backend repeats enforcement. Shared pages inherit branding, theme, language ordering/overrides and timezone/time-format preferences. Keyed native translations cover four locales; provider names, endpoints, API scopes and stored enum IDs remain stable. No unnecessary drag-and-drop. Inline forms, narrow cards, horizontal table scroll, safe wrapping/truncation with full text, labels, native keyboard controls, status text and one-time copy actions fit existing patterns. Failed saves preserve non-secret form values.

## Tests added

Backend: role/named permissions; tenant isolation across view/edit/test/use/delete/rotation; tenant headers; provider availability/entitlements; secret-bearing invalid configuration; vault failure; test-before-activate; rotation invalidation; key hashes/one-time values/expiry/revocation/scopes/rates/usage; fallback/environment separation; log redaction; signature/replay/duplicate/size validation; malicious URLs/DNS; retry/permanent errors/lease recovery/cancellation; migration preservation; provider operations; recorded health/metrics/threshold alerts; legacy activation safety.

Seven browser cases: actual connection/application/key workflow and one-time dismissal/reload/revocation; failed-save retry; denied platform/tenant header; four locale matrices verifying form/provider/credential/health/log/entitlement/webhook/key/usage/OAuth/docs views at 320, 360, 375, 390, 425, 768, 1024, 1280, 1440 and 1920px. Normal cases assert no unexpected console/page errors and valid native dictionary parity.

Final verification results are recorded below. Tests use disposable databases/storage and separate ports; existing user data is never reset.

## Security, known limitations and intentional deferrals

No live provider credentials were supplied. Real account permissions, sender verification, provider delivery and AWS IAM/KMS policies require deployment QA. Actual adapter transports exist; mocks do not mark unconfigured providers connected.

Docker Desktop's Linux engine is stopped here, preventing live PostgreSQL/concurrent multi-process tests and production Compose startup. Migration preservation and atomic quota/lease behavior are tested on isolated SQLite. Rehearse PostgreSQL migration/concurrency before release. No database reset or destructive Git operation was performed.

Worker processes generic webhook metadata/outbound deliveries. Existing synchronous daily compliance automation is not a durable scheduler. Automatic external reminder jobs, periodic provider probes, recipient-private routing, Prometheus/central tracing and on-call delivery remain operational extensions. Alerts reuse the tenant-wide inbox and contain no credentials.

Generic HMAC ingress is not a native Meta/Google/payment callback adapter. Delivery/read callback status mapping, Google consent/refresh, OAuth clients and identity-provider registration are intentionally deferred. Calendar/storage interfaces are backend foundations; meeting sync, external document mappings and custom storage migration remain opt-in domain work. No unused AI/OCR/payment/translation/Drive adapter is advertised.

Platform developer views inspect metadata; tenant area owns creation/revocation. Application/key/webhook lists cap at 100 tenant/200 platform; connections/logs paginate by 25; health card records cap at 200 while summaries aggregate all connections. Add broader pagination at enterprise scale. Deployment owns edge body limits, worker supervision, backups, vault monitoring and log policy; never enable sensitive provider request/debug logging.

## Recommended next step

Run isolated PostgreSQL migration/lease/quota concurrency rehearsal, configure scoped AWS vault and verified SMTP, then implement durable external notification jobs and official provider callbacks/Google consent through an approved identity integration. Extend the central registry for actual product requirements, keeping credentials out of business modules.


## Verification completed locally

- Full API suite: 167 tests passed.
- Full browser suite before the header correction: 23 tests passed, including integrations across four locales and ten viewport widths.
- After the header correction: six focused browser tests passed, including admin/member account and dashboard language selection, persistence, regional preferences, mobile widths, error recovery and API-key workflows.
- Updated production build passed; TypeScript lint and whitespace checks are included in the final project checks.
- Development and production Compose configuration validation passed. Docker engine startup and real provider credentials remain unavailable as described above.

Authenticated localization now uses the shared native-language selector in both account and dashboard headers. Updated files include components/account-settings.tsx, components/locale-switcher.tsx, app/auth.css, app/globals.css and tests/white-label/localization-reliability.spec.ts. The account settings form no longer nests label elements. Integration surfaces use the existing branding and dark-theme tokens.
