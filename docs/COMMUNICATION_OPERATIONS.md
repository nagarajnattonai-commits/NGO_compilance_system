# Communication provider operations

Phase 24 extends the existing integration registry, secret store, notification delivery ledger, scheduler, and Google Calendar synchronization. It does not add a second delivery engine.

## Provider setup

- SMTP connections require an approved host from `INTEGRATION_SMTP_HOSTS` (or the deployment `SMTP_HOST`), SSL or STARTTLS, a bounded timeout, sender address, and a write-only credential reference. Tenant connection configuration never contains the password.
- Meta WhatsApp connections use the existing `meta_whatsapp` registry entry. Store a JSON credential containing `access_token`, `app_secret`, and `verify_token`. Template sends are the default; free-form messages require the explicit connection option.
- Google Calendar keeps the existing OAuth, mapping, deterministic event ID, and retry flow. Terminal credential failures move the connection to an honest error state without changing internal compliance deadlines.

Tenant administrators configure and test tenant connections in the existing Integrations area. Platform fallback connections remain separate and require Platform Admin authorization. Provider credentials cannot be read back through the API or UI.

## WhatsApp callbacks

Configure the provider callback as:

`/api/v1/integration-callbacks/whatsapp/{connection_id}`

The verification request must supply the configured verify token. Status callbacks require Meta's `X-Hub-Signature-256` HMAC, are limited to 256 KiB, and resolve the tenant and provider from the trusted connection ID rather than callback content. Provider message IDs map `sent`, `delivered`, `read`, and `failed` events to the existing delivery ledger. Repeated or older status callbacks are ignored.

## Delivery operations

Tenant administrators can review channel, event, masked recipient, provider, status, attempt count, safe error code, and next retry time under Integrations / Deliveries. Failed or cancelled deliveries can be manually re-queued. Manual retries use the existing scheduler retry primitive and create an audit event.

Automated retry uses the scheduler's bounded exponential backoff. SMTP uses a deterministic RFC Message-ID derived from the delivery ID, and WhatsApp stores the provider message ID for callback correlation. User notification preferences are checked again immediately before dispatch, so disabling a channel cancels a queued delivery.

## Incident response

1. Check connection health and recent safe error codes; logs never contain credentials or message bodies.
2. For `AUTHENTICATION_FAILED`, rotate the write-only credential and test the connection before activating it.
3. For `RATE_LIMITED`, `TIMEOUT`, or `PROVIDER_UNAVAILABLE`, allow bounded automatic retry, then manually retry only after provider recovery.
4. For invalid recipients or templates, correct the source data or approved template rather than repeatedly retrying.
5. If a provider is unavailable for an extended period, disable the connection. Durable in-app history and internal compliance state remain intact.

Do not paste provider secrets, callback bodies, message content, or recipient addresses into tickets or logs.
