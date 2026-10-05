# Production operations (technical runbook)

The consolidated release procedure is [PRODUCTION_RUNBOOK.md](PRODUCTION_RUNBOOK.md), with evidence tracking in [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md). This older concise reference is retained for existing operator links.

This is operational guidance, not a certification or availability guarantee. Target
RPO is at most 1 hour and target RTO is at most 4 hours; rehearse and measure both
in the actual hosting environment before making any service commitment.

## Before deployment

- Set all required values in a private `deploy/.env.white-label`. Keep it outside
  version control. Use HTTPS, a strong shared proxy key, a PostgreSQL URL, an AWS
  integration secret store, a private document bucket, and a separate private
  branding bucket. Configure verified email and provider credentials when enabled.
- Apply least-privilege bucket/IAM policy, S3 Block Public Access and versioning.
  Enable encryption, retention and cross-region backup as appropriate to the
  organization's data policy. Database backups alone cannot restore documents.
- Run `docker compose --env-file deploy/.env.white-label -f
  deploy/compose.white-label.yml config --quiet` before rollout. Only the TLS edge
  should have public ports. Never expose PostgreSQL, API, or workers directly.
- For a **new empty database only**, run `docker compose --env-file
  deploy/.env.white-label -f deploy/compose.white-label.yml run --rm api python
  -m app.bootstrap_schema --apply`. This command refuses a nonempty schema.
  Existing installations must apply the reviewed, explicit `app.migrate_* --apply`
  modules in release order after a backup. Do not rely on API startup for schema
  changes; it now refuses missing tables in production.

## Backup and restore

Schedule encrypted PostgreSQL `pg_dump -Fc` backups at least hourly. Keep a
separate, access-controlled copy and test restore to an isolated database. Use
provider versioning or snapshots for both document and branding object stores;
record the matching recovery point and preserve object metadata, including
checksums and version IDs. Monitor backup completion, age and restore tests.

To restore: stop writers and workers, select a consistent database backup and
object-store recovery point, restore to isolated infrastructure with restricted
credentials, apply any reviewed migrations needed by the target application
version, verify `/ready`, log in with a test operator, verify representative
documents and checksums, then switch traffic. Do not overwrite the live database
until the restored copy is validated. Document the actual recovery time.

## Rollout, rotation and incident response

Deploy the same reviewed image version to API and workers. Take a backup before
migration, run migrations explicitly once, then roll out API and web. Rollback
means returning to compatible application images; additive migrations are not
automatically reversed. Test rollback compatibility before production rollout.

Rotate `BRAND_PROXY_KEY` on API and web together. Rotate database, SMTP, S3 and
provider credentials in their stores; revoke old values after confirming new
connections. Webhook rotation issues a new signing secret, so coordinate the
consumer before enabling it. Do not print secrets in incident tickets or logs.

`/health` checks process liveness; `/ready` checks database connectivity.
Monitor readiness, HTTP 5xx/429 rates, worker backlog and failed webhook jobs,
backup age, certificate renewal, object-store errors and disk capacity. Audit
authentication, roles, subscriptions, document access, integrations and AI events
using tenant-scoped audit records. On incident, preserve relevant logs and audit
records, revoke affected sessions/keys, restrict traffic if needed, assess tenant
scope, restore from a verified backup when necessary, and record the timeline.

## Known limits

The shared quota uses the existing database for atomic counters; Redis is not
deployed. Validate throughput under expected load. Malware scanning remains an
optional configured scanner interface: `NOT_SCANNED` does not mean clean. The
provider timeout is configured and bounded, but external provider availability,
backup recovery targets and multi-worker PostgreSQL behavior require rehearsal.
