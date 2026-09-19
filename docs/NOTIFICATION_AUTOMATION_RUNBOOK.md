# Notification automation runbook

Phase 7 turns a logical notification into recipient-specific, immutable delivery records. Apply the additive schema after the Phase 6 scheduler migration:

```powershell
cd apps/api
.venv\Scripts\python.exe -m app.migrate_notifications --apply
```

The existing `automation-worker` service processes `NOTIFICATION_DELIVERY` jobs. Keep at least one worker running; no separate notification process is required. In-app deliveries are available immediately. Email and WhatsApp deliveries remain queued until the provider call succeeds or the job reaches a terminal failure.

Recipient resolution uses active authenticated accounts with effective workspace access. Compliance reminder roles use active organization or workspace membership assignments. If the requested role has no account, the frozen template's fallback role is used. Notification rows created before Phase 7 are adopted into each user's inbox on first read so old seeded data remains available without making new notifications tenant-wide.

Each delivery stores its resolved locale, subject, text, branded HTML, recipient address, provider template reference, attempts, timestamps, and safe error code. It never stores provider credentials. Content is frozen when queued, so later template or translation edits do not rewrite history.

Users manage channel and category preferences in **Account Settings → Notifications**. In-app history is mandatory by default. Tenant administrators can inspect or update the mandatory-channel policy through `/api/v1/admin/notification-policy`. A mandatory channel overrides the user's channel preference, while a missing address produces a terminal `RECIPIENT_UNAVAILABLE` delivery rather than a fake success.

Use `/api/v1/admin/notification-deliveries` to filter operational history by `status` or `channel`. Recipient addresses are masked in this administrator response. Users can inspect only their own delivery history at `/api/v1/notification-deliveries`.

Retryable provider errors such as `PROVIDER_UNAVAILABLE`, `RATE_LIMITED`, `TIMEOUT`, and secret-store outages follow the scheduler's exponential backoff and dead-letter policy. Invalid configuration and permission failures stop immediately. After correcting a provider, a platform operator can reset the failed scheduled job through the Phase 6 automation screen or API; the linked delivery returns to `QUEUED`.

Email uses the existing tenant-first SMTP resolver and tenant branding. WhatsApp uses the tenant-first Meta provider resolver and sends an approved template when a template name is present; otherwise it uses the configured text-message operation. Provider responses are recorded as `SENT`. This system does not claim `DELIVERED` unless a future authenticated provider callback confirms delivery.

Recommended alerts:

- Any `DEAD_LETTER` notification job.
- A rising `RETRY` count or oldest queue age.
- `INTEGRATION_NOT_CONFIGURED` after enabling a mandatory external channel.
- Repeated `RECIPIENT_UNAVAILABLE`, which indicates incomplete user contact data.
