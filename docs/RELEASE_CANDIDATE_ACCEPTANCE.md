# Release-candidate acceptance

This document records Phase 26 acceptance evidence. It is not a production certification. Infrastructure-specific checks must be repeated in staging with production-equivalent PostgreSQL, private object storage, secret management, provider credentials, backups, monitoring, and alerting.

## Product journeys

| Journey | Automated evidence | Result |
| --- | --- | --- |
| NGO onboarding through completed compliance and next cycle | Phase 5 runtime/backend tests and `phase5-lifecycle.spec.ts` | VERIFIED |
| Consultant multi-NGO portfolio, queue, assignment, import and invitation | Phase 19 and Phase 20 tests | VERIFIED |
| Corporate CSR partner, project, due diligence and NGO collaboration | Phase 22 tests | VERIFIED |
| Immutable document extraction, OCR fallback and human review | Phase 21 tests | VERIFIED with fake providers |
| Grounded AI, citations, insufficient evidence and isolation | Phase 17 tests | VERIFIED with fake providers |
| Email, WhatsApp, webhook, calendar and retry controls | Phase 10, Phase 15 and Phase 24 tests | VERIFIED with fake/mock providers |
| Automation trigger, conditions, actions, history and idempotency | Phase 14 tests and workflow-builder browser test | VERIFIED |
| Production bootstrap, readiness and integrity checks | GitHub production release-readiness job | VERIFIED in CI PostgreSQL |

## Security and consistency boundaries

- Tenant, organization and manipulated-ID isolation are exercised across organizations, compliances, tasks, documents, filings, saved views, imports, AI, document intelligence, portfolios, CSR, notifications and integrations.
- Platform Administrator sessions remain separate from tenant workspace APIs.
- Viewer and scoped consultant aggregates use the same organization authorization as direct APIs, search, reports and CSV exports.
- Closed compliance states are excluded from active/overdue reporting; exports retain authorization filters and protect spreadsheet formulas.
- Extraction and assistant outputs remain proposed/advisory until existing human-authorized domain services apply them.
- Provider credentials, prompts, document bodies, tokens and signing secrets are excluded from API responses and operational logs.

## Findings

| Severity | Finding | Disposition |
| --- | --- | --- |
| P0 | None confirmed | No action required |
| P1 | None confirmed | No action required |
| P2 | Real malware scanner adapter is not configured | Production must keep `DOCUMENT_SCAN_REQUIRED=false` or supply a reviewed adapter before requiring scanning |
| P2 | Backup/object-storage restore was not rehearsed locally | Rehearse in staging and record measured RPO/RTO |
| P3 | Some en-IN screens emit safe fallback warnings for missing optional labels | Deferred with the final localization phase; functional assertions pass |

## Manual pre-production checks

1. Complete the production release checklist with deployment-specific evidence.
2. Rehearse database and private object-storage restore in an isolated staging environment.
3. Verify bucket privacy, workload identity, secret rotation, TLS, proxy trust, monitoring and alert routing.
4. Configure and test each enabled external provider with non-production accounts.
5. Confirm worker/scheduler liveness, backlog alerts and duplicate scheduler protection under restart.
6. Run the bounded production smoke check after deployment and retain the results.

## Recommendation

**CONDITIONALLY READY FOR STAGING.** Automated product and CI acceptance may support a staging deployment. Production readiness remains conditional on the manual infrastructure, backup/restore, security-operation and provider checks above. This document does not claim readiness for production.
