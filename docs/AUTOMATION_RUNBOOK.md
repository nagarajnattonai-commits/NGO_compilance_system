# Scheduler and background worker runbook

Phase 6 uses the `scheduled_jobs` SQL queue. The API does not start a hidden loop. The scheduler only creates idempotent tenant scan jobs; workers claim and execute those jobs through the existing compliance runtime services.

## Apply the additive migration

Back up and rehearse the target database first, then run from `apps/api`:

```powershell
.venv\Scripts\python.exe -m app.migrate_automation --apply
```

This creates `scheduled_jobs` and records `20260919_scheduler_automation_v1`. It does not change existing compliance, snapshot, reminder, document, or integration rows.

## Start and stop

Run these as two separately supervised processes:

```powershell
.venv\Scripts\python.exe -m app.runtime_scheduler --loop --interval 60
.venv\Scripts\python.exe -m app.automation_worker --loop
.venv\Scripts\python.exe -m app.integration_worker --loop
```

Each process exits cleanly on the supervisor's normal termination signal. The integration worker retains the existing webhook delivery retry outbox. A compliance worker commits a claim before domain work. If it stops after claiming, another worker can reclaim the row after the five-minute lease expires. `docker compose up --build` starts the API, scheduler, both workers, and web process with the same persistent data volume.

## Operations

Platform operators can inspect `/admin/automation`. The view shows type, state, tenant, entity, schedule, attempt count, normalized error, duration, retry time, correlation ID, queue age, and dead-letter counts. It never returns job payloads, lease owner details, or provider credentials.

Only a platform administrator with `scheduler.manage` can retry a `FAILED`, `DEAD_LETTER`, or `CANCELLED` row. Manual retry resets attempts, records an audit event, and lets a worker claim the existing row. Do not create a replacement row by editing the database.

## Downtime recovery and duplicate protection

On restart, the scheduler enqueues the current daily scan bucket. Unique tenant/idempotency keys prevent duplicate scan jobs. Runtime generation additionally retains the frozen snapshot cycle constraint, `NextCycleGeneration` receipt, reminder receipt, and notification event receipt. A missed day is recovered because each scan evaluates current stored due dates, unfinished tasks, genuine document expiry, and completed recurring instances rather than assuming earlier polls ran.

Retries use bounded exponential backoff with jitter. Temporary provider, timeout, rate-limit, secret-store, and database-contention errors retry. Invalid context or malformed payloads fail immediately. Exhausted temporary failures become `DEAD_LETTER`; they are visible until an authorized operator retries them.

## Deployment validation

SQLite verifies behavior locally but is not evidence of PostgreSQL multi-worker correctness. Before production, run the opt-in PostgreSQL concurrency tests with multiple scheduler/worker processes and confirm `FOR UPDATE SKIP LOCKED`, compare-and-swap claims, migration, backup, monitoring, and alerting in the deployment environment.
