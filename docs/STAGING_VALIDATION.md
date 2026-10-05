# Staging validation evidence

Evidence date: 2026-10-05

Candidate: `2b6b60225c7b330111376d2cff87ac7d81ee4d0d`

Repository: `nagarajnattonai-commits/NGO_compilance_system`

This record distinguishes checks that actually ran from checks blocked by missing infrastructure. It contains no credentials and is not a production certification.

## Decision

**READY FOR STAGING DEPLOYMENT — STAGING NOT YET VALIDATED.**

The release candidate and production-like CI gate are green. No deployable staging environment, hostname, PostgreSQL endpoint, private object storage, or approved provider credentials were available from the execution environment. A production-pilot recommendation is therefore not justified.

## Baseline CI

GitHub Actions run `37270976797` for Phase 26 completed successfully:

| Check | Status | Evidence |
| --- | --- | --- |
| Full API suite | PASS | GitHub `API tests` job |
| Web TypeScript and production build | PASS | GitHub `Web type-check and build` job |
| Compose configuration | PASS | GitHub `Container configuration` job |
| Empty PostgreSQL bootstrap, integrity, health and readiness | PASS | GitHub `Production release readiness` job using PostgreSQL 16 |
| en-IN white-label browser regression | PASS | GitHub `White-label browser regression` job |

The CI PostgreSQL service is disposable release-gate evidence. It is not a persistent staging environment and does not establish backup/restore, external TLS, private storage, monitoring, or RPO/RTO performance.

## Infrastructure inventory

Availability was determined from executable discovery and configuration presence without printing values.

| Dependency | Classification | Evidence |
| --- | --- | --- |
| Docker / Docker Compose | NOT AVAILABLE | Neither executable is installed |
| Staging PostgreSQL endpoint | NOT CONFIGURED | No staging/database URL configured |
| PostgreSQL backup/restore tools | NOT AVAILABLE | `psql`, `pg_dump`, and `pg_restore` unavailable |
| Private S3-compatible storage | NOT CONFIGURED | No bucket, endpoint, region, or workload credentials configured |
| External secret backend | NOT CONFIGURED | No staging secret-backend configuration available |
| Staging hostname and HTTPS edge | NOT CONFIGURED | No origin, trusted host, CNAME target, or certificate endpoint supplied |
| SMTP | NOT CONFIGURED | No approved staging configuration or recipient supplied |
| WhatsApp Cloud API | NOT CONFIGURED | No approved staging configuration or recipient supplied |
| Google OAuth/calendar | NOT CONFIGURED | No staging OAuth configuration or account supplied |
| AI, embedding and OCR | NOT CONFIGURED | No approved provider configuration supplied |
| Malware scanner | NOT AVAILABLE | No scanner executable or adapter configured |
| Monitoring and alert routing | NOT CONFIGURED | No metrics/error/alert destination supplied |
| Controlled HTTPS webhook receiver | NOT CONFIGURED | No staging receiver supplied |

## Intended staging topology

Reuse the existing Phase 25 deployment topology and configuration contract:

`HTTPS/Caddy → Next.js → FastAPI → PostgreSQL`

Separately supervised processes:

- automation worker;
- integration worker;
- scheduler.

Private document and brand objects use the configured S3-compatible backend. Existing email, WhatsApp, Google Calendar, webhook, AI and OCR providers remain optional and must use secret references. Redis is not part of the current runtime because durable jobs are database-backed; it must not be introduced merely for staging.

Use `deploy/.env.white-label.example` as the configuration inventory. Create the real environment file outside version control and validate it with the existing production configuration contract. Never commit the populated file.

## Validation matrix

| Area | Status | Result / blocker |
| --- | --- | --- |
| Production configuration contract | PASS | Automated Phase 25 security tests and CI release gate |
| Production Compose schema | PASS | GitHub container configuration job |
| Empty PostgreSQL bootstrap and integrity | PASS | Executed in ephemeral GitHub PostgreSQL; persistent staging remains BLOCKED |
| Staging API `/health` and `/ready` | BLOCKED | No staging hostname/database |
| Synthetic staging data | BLOCKED | No staging deployment |
| Private object upload/download/isolation | BLOCKED | No staging object store |
| Database backup and isolated restore | BLOCKED | No persistent database or PostgreSQL tools; no timings recorded |
| Object-storage recovery | BLOCKED | No versioned staging bucket/backup |
| API/web/worker/scheduler processes | BLOCKED | Docker/runtime target unavailable |
| Durable work across restart | BLOCKED | No controllable staging processes |
| External HTTPS/proxy/certificate/headers | BLOCKED | No staging hostname or TLS edge |
| Secret retrieval and rotation | BLOCKED | No staging secret backend |
| AI/embedding/OCR smoke | BLOCKED | No approved staging credentials; no live calls made |
| Email smoke | BLOCKED | No approved configuration/recipient; no message sent |
| WhatsApp smoke | BLOCKED | No approved configuration/recipient; no message sent |
| Google Calendar smoke | BLOCKED | No staging OAuth account; no event created |
| Webhook delivery/replay test | BLOCKED | No controlled HTTPS receiver |
| Malware scanning | BLOCKED | No scanner; `NOT_SCANNED` remains distinct from `CLEAN` |
| Structured logs/correlation IDs | PASS | Automated production observability tests |
| Real monitoring backend | BLOCKED | No destination configured |
| Alert routing | BLOCKED | No destination configured; no synthetic alert triggered |
| Integrated product acceptance | PASS | Phase 26: 342 backend and 32 en-IN browser tests |
| Real staging user journeys | BLOCKED | No deployed staging target |
| Tenant isolation in automated acceptance | PASS | Phase 26 backend/browser tests |
| Tenant isolation against staging | BLOCKED | No two-tenant staging dataset |
| Performance sanity on staging | BLOCKED | No staging endpoint; no timings recorded |
| Deployment/rollback rehearsal | BLOCKED | No deployment target/version controller |

## Execution procedure when infrastructure is supplied

1. Provision an empty staging PostgreSQL database and private versioned object buckets. Confirm public access is blocked.
2. Store populated configuration outside the repository using the approved secret backend. Set production mode, HTTPS origin, trusted hosts, CNAME edge, admin allowlist, PostgreSQL URL, private buckets, and secret references.
3. Run `python -m app.bootstrap_schema --apply` from `apps/api`, then `python -m app.production_ops --check`. Do not start the API until both succeed.
4. Build and start database, API, web, automation worker, integration worker, scheduler, and Caddy using `deploy/compose.white-label.yml` or equivalent controls on the authorized platform.
5. Verify `/health`, `/ready`, HTTPS redirect/certificate, secure cookies, trusted forwarding, security headers, body limits, and correlation IDs.
6. Create two synthetic tenants through supported APIs. Run the bounded NGO, consultant, CSR, document-intelligence and communications journeys, including safe cross-tenant denial attempts.
7. Create pending durable work; restart API, worker and scheduler separately; confirm recovery, retry visibility, and duplicate protection.
8. Run `scripts/production-smoke.py` against the deployed web/API endpoints.
9. Run `scripts/postgres-restore-rehearsal.py` with a separate isolated restore database. Record backup/restore durations and approximate size without exposing connection strings.
10. Rehearse restoration of synthetic versioned objects and verify database metadata/checksums still identify the restored immutable versions.
11. Run one bounded provider smoke only for each explicitly approved provider. Record accepted/ledger state without credentials or sensitive payloads.
12. Verify logs, metrics and safe alert routing; then rehearse application rollback without attempting a destructive schema downgrade.

## Findings and risks

| Severity | Finding |
| --- | --- |
| P0 | None found in available automated evidence |
| P1 | Staging cannot be validated until a deployment target and core infrastructure are supplied |
| P2 | Backup/restore, private storage recovery, restart durability, HTTPS and monitoring remain unexecuted |
| P2 | No real malware scanner is configured |
| P3 | Optional external providers remain unconfigured; this is acceptable only when they are not required for the pilot |

Unresolved production risks are real-infrastructure availability, secret retrieval/rotation, private storage policy, backup recovery, external HTTPS behavior, process supervision, monitoring/alerts, malware scanning, provider configuration, and measured RPO/RTO. These must remain open on the release checklist until evidence is captured.
