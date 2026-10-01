# Production AI and OCR provider operations

Phase 23 connects the existing provider-neutral AI/RAG and document-intelligence services to production providers through the Phase 15 integration registry. It does not create a second provider or secret system.

## Supported adapters

- `openai_compatible` provides bounded chat generation and embeddings through an OpenAI-compatible HTTPS `/v1` endpoint.
- `openai_responses_ocr` provides bounded PDF and image transcription through the Responses API.

Provider endpoints, model names, timeouts, output limits and batch/page limits are non-secret connection configuration. API keys are write-only credentials referenced through the existing environment or AWS Secrets Manager backend. Secrets are never returned by an API or stored in integration operation logs.

## Configuration and precedence

Configure and test connections in **Settings → Integrations**. A production connection must pass its explicit connection test and then be activated before runtime use.

Runtime selection is deterministic:

1. an entitled tenant's connected `PRODUCTION` connection;
2. a connected platform `PRODUCTION` connection only when its platform administrator enabled tenant fallback;
3. the legacy Phase 16 development provider only when no production integration exists.

An explicitly disabled, unhealthy, inaccessible or incomplete production configuration never silently falls back. Tenant entitlements (`ai_rag` and `document_intelligence`) remain backend-enforced.

## Safety and reliability

- Outbound URLs require HTTPS, public DNS addresses and DNS-pinned connections; redirects and private-network targets are refused.
- Requests have bounded context, batch, output, page, response-size and timeout limits.
- OCR input is treated only as untrusted document content and cannot grant authority or update authoritative records.
- Generation and embeddings continue to use the existing authorization-before-retrieval and source-grounding controls.
- Retryable timeout, rate-limit and temporary provider errors use the existing durable scheduler backoff. Invalid credentials, models and requests do not retry.
- Operation telemetry records tenant, provider, capability, status, duration and safe error code only—never prompts, document contents, provider bodies or credentials.

## Credential rotation and rollback

Replace a connection credential through the existing write-only credential control, run **Test connection**, and activate it after success. To roll back, replace it with the previous secret version and repeat the test/activate flow. AWS Secrets Manager should retain provider-side versions according to the deployment's secret retention policy.

## Health and failures

Health checks occur only on an explicit test; loading a page does not call a paid provider. Safe failure codes distinguish missing/disabled configuration, invalid credentials, unsupported models, malformed bounded requests, rate limits, timeouts and provider unavailability. Inspect Integrations → Health and operation logs by request ID; raw upstream response bodies are intentionally unavailable.

No live paid provider calls are made by automated tests. Production smoke tests require operator-managed credentials and should use non-customer test content.
