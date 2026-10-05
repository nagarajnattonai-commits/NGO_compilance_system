# Production deployment and operations runbook

This runbook is an operating procedure, not evidence that a production environment, backups, monitoring, or recovery targets exist. The target RPO is at most one hour and target RTO is at most four hours; they remain unverified targets until measured in the chosen infrastructure.

## Supported topology

Internet traffic terminates at Caddy or an equivalent trusted HTTPS load balancer, then reaches the Next.js web container. Next.js proxies API requests to FastAPI. FastAPI, the automation worker, integration worker, and scheduler share PostgreSQL and private S3-compatible storage. External AI/OCR, SMTP, WhatsApp, Google Calendar, and webhook providers remain optional integrations.

The durable job and quota implementation is PostgreSQL-backed. Redis is not currently consumed by the application and is deliberately not deployed. Do not add Redis as an unobserved dependency; reassess it only after measured contention or throughput requires a supported queue/cache design.

## Configuration contract

Required core production settings are `APP_ENV=production`, HTTPS `APP_ORIGIN`, `PLATFORM_HOSTS`, `WHITE_LABEL_CNAME_TARGET`, `BRAND_PROXY_KEY`, PostgreSQL `DATABASE_URL`, `PLATFORM_ADMIN_EMAILS`, AWS-backed `INTEGRATION_SECRET_BACKEND`, `BRAND_S3_BUCKET`, and either `DOCUMENT_S3_BUCKET` or an explicitly configured managed storage connection. Configure database pool and timeout values within the validated bounds. `RELEASE_VERSION` and `BUILD_SHA` may contain only safe identifier characters.

Optional provider configuration includes SMTP, WhatsApp, Google OAuth/Calendar, AI/OCR, tenant provider connections, and webhook destinations. An optional provider outage does not make core `/ready` fail. Provider health is reported through the existing Integrations health view.

No malware scanner adapter is bundled. `NOT_SCANNED` never means clean. Setting `DOCUMENT_SCAN_REQUIRED=true` deliberately prevents production startup until a reviewed scanner adapter is implemented and configured.

Keep `deploy/.env.white-label` outside source control. Prefer workload identity over static AWS keys. Provider secrets belong in the existing AWS Secrets Manager backend; never place them in Next.js public variables, Compose files, tickets, or logs.

## Deploy

1. Record the release image digest and `BUILD_SHA`. Confirm the release checklist status.
2. Take an encrypted PostgreSQL backup and a coordinated private object-storage recovery point. Verify the latest backup artifact can be read.
3. Render configuration without starting services:
   `docker compose --env-file deploy/.env.white-label -f deploy/compose.white-label.yml config --quiet`
4. For a fresh, empty database only, run:
   `docker compose --env-file deploy/.env.white-label -f deploy/compose.white-label.yml run --rm api python -m app.bootstrap_schema --apply`
   The command refuses a non-empty schema.
5. For an existing database, restore a recent copy into an isolated rehearsal database first, apply only the reviewed additive `app.migrate_* --apply` modules introduced since the deployed release, then run `python -m app.production_ops --check`. Never run fresh bootstrap against an existing database.
6. Deploy API, worker, integration-worker, scheduler, and web from the same reviewed commit. Start the database first; start application processes only after migration checks succeed.
7. Verify `/health`, `/ready`, container state, `python -m app.production_ops --check`, scheduler/worker process state, and the bounded smoke script. Confirm the build SHA returned by `/health`.
8. Review provider health separately. Do not make a release appear unavailable solely because an optional provider is down.

API startup never creates or alters the production schema. It fails if PostgreSQL is unavailable or required tables are missing. SQLite remains local/test-only.

## Worker and scheduler operation

The scheduler only enqueues daily catch-up scans. Stable database idempotency keys prevent multiple scheduler replicas from creating duplicate scans. The automation worker claims durable jobs with leases and compare-and-swap protection; expired leases can be reclaimed after interruption. The integration worker processes the durable webhook outbox. Notification, communication retry, document intelligence, AI indexing, reminders, overdue scans, and CSR expiry work reuse these durable mechanisms.

Processes finish their current bounded batch on `SIGTERM`, stop polling, close scoped database sessions, and should receive at least 45 seconds of shutdown grace. Restarting the API does not delete queued work. Alert if a worker stops, the queue age grows, retry/dead-letter counts spike, or the scheduler stops producing expected daily scans.

## Private storage and malware status

Document buckets must have all S3 Block Public Access controls enabled, encryption, versioning, lifecycle/retention rules, and least-privilege IAM. Downloads remain application-authorized; do not expose permanent public URLs. Object keys remain tenant/organization/document/version scoped. Preserve object versions and metadata during recovery.

Brand assets use a separate private bucket. The application checks document bucket privacy before writes. Confirm these controls with the cloud provider because repository validation cannot prove remote bucket policy.

## Backup and restore

Run encrypted `pg_dump -Fc` backups at least hourly, retain them according to legal and business policy, copy them to a separate access boundary, and alert on age or failure. Coordinate each database recovery point with S3 versioning/snapshots for document and brand buckets and retain secret references/configuration—not plaintext secret exports.

For a rehearsal, create an empty isolated database whose name contains `rehearsal` or `restore`, set `SOURCE_DATABASE_URL` and `RESTORE_DATABASE_URL`, then run `python scripts/postgres-restore-rehearsal.py`. The script keeps passwords out of command arguments, restores with no ownership/privilege replay, runs read-only schema/integrity checks, and deletes its temporary dump. Never target the live database.

After database restore, restore matching object versions, apply only required forward migrations, run integrity checks, start isolated services, verify representative document checksums and authorization, then execute smoke checks. Record backup time, restored recovery point, duration, findings, and measured RPO/RTO. Object-storage restore remains unverified until executed against the selected provider.

## Rollback

Rollback application images only to a release compatible with the current additive schema. Migration rollback is not automatic and destructive schema reversal is prohibited. If a release writes data incompatible with the previous version, keep traffic stopped and restore the verified pre-deploy database/object recovery point into isolated infrastructure before cutover.

## Incidents and provider outages

- Database: stop writers/workers, preserve evidence, restore to isolated PostgreSQL, run integrity checks, then switch traffic.
- Object storage: disable uploads if privacy or integrity is uncertain; preserve database records and recover matching object versions.
- Worker/scheduler: restart the supervised process; durable leases and idempotency handle recovery. Inspect backlog and dead letters before manual retry.
- AI/OCR: disable or correct the provider connection; deterministic compliance records remain authoritative.
- Email/WhatsApp: allow bounded retry for transient failures; correct invalid recipients/templates or credentials before audited manual retry.
- Google Calendar: reconnect credentials and resume synchronization. Never change internal deadlines because the projection failed.
- Webhooks: preserve signing and SSRF controls, inspect safe delivery history, and use the existing audited retry operation.

Rotate database, proxy, storage, OAuth, SMTP, WhatsApp, webhook, and AI/OCR credentials independently. Deploy `BRAND_PROXY_KEY` to web and API together. Confirm new credentials before revoking old ones, and never log their values.

## Observability and alerts

Production API access logs are structured JSON with request ID, safe tenant ID when authenticated, path without query parameters, status, and duration. `/health` exposes only service, environment, release version, and build SHA. Operational tables/views already expose safe job, integration, webhook, notification, AI, and OCR status/latency/error categories. Do not use tenant IDs as high-cardinality external metric labels.

Recommended alerts: readiness failure, PostgreSQL connection failure/pool exhaustion, worker or scheduler stopped, oldest queued job age, dead-letter growth, repeated provider failures, notification/webhook failure spikes, object-storage errors, TLS renewal failure, and backup/restore-check failure. No alerting vendor is configured by this repository.

## Smoke verification

Run `python scripts/production-smoke.py --web https://platform.example --api https://platform.example`. It checks the login surface, lightweight health, database readiness, and the unauthenticated authorization boundary without modifying data. An optional `SETU_SMOKE_SESSION` can verify `/api/v1/auth/me`; treat that short-lived session as a secret and remove it immediately. Worker/scheduler state, bucket privacy, backups, and external providers require separate operator verification.
