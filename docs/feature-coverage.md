# Product feature coverage

This map follows the priority groups in the approved requirement analysis. “Implemented” means the workflow is usable in the local product and protected by tenant-scoped APIs. “Foundation” means the domain boundary or provider-neutral configuration exists, but a production provider or infrastructure service must still be selected and connected.

## Must-have capabilities

| Capability | Coverage |
| --- | --- |
| Organization onboarding, legal type, identifiers, duplicate checks and generated plan | Implemented |
| Versioned compliance catalogue and organization-specific obligations | Implemented |
| Deadlines, internal targets, lifecycle transitions, filing proof, exceptions and reopening | Implemented |
| Recurring compliance generation and overdue handling | Implemented through idempotent daily automation |
| Tasks, ownership, priorities and compliance-linked checklist work | Implemented |
| Document metadata, expiry and immutable version history | Implemented; private binary object storage is a production foundation item |
| Users, invitations, roles and read-only access | Implemented |
| Notifications, read state, reminders and delivery history | In-app implemented; email and WhatsApp are provider foundations |
| Dashboard, calendar, standard reports and CSV export | Implemented |
| Audit trail | Implemented for material mutations and automation |
| Consultant multi-organization portfolio | Implemented |
| Subscription limits and entitlement foundation | Implemented |

## Good-to-have capabilities

| Capability | Coverage |
| --- | --- |
| Configurable workflow | Controlled state machine implemented; visual workflow builder remains planned |
| OCR and structured extraction | Provider-neutral integration foundation |
| WhatsApp and advanced email automation | Provider-neutral integration foundation |
| Drive, OneDrive and Dropbox | Provider-neutral integration foundation |
| Google and Outlook calendar sync | Provider-neutral integration foundation |
| Digital signature | Provider-neutral integration foundation |
| Bulk import and export | CSV report export implemented; asynchronous bulk import remains planned |
| Advanced reports and custom dashboards | Standard interactive reports implemented; custom report builder remains planned |
| Client and consultant portal | Multi-organization switching and scoped memberships implemented |
| Approved integration APIs | Versioned tenant-scoped REST API implemented |

## Nice-to-have and expansion capabilities

| Capability | Coverage |
| --- | --- |
| Compliance assistant and natural-language operational search | Implemented as deterministic tenant-grounded assistance with record sources |
| AI document classification, review, summarization and missing-evidence detection | Provider and asynchronous-job foundation remains planned |
| Predictive risk scoring | Current rule-based risk summaries implemented; predictive model remains planned |
| RAG knowledge assistant | Authorized retrieval response contract implemented; approved knowledge corpus and model provider remain planned |
| Grant management | Implemented as tenant-scoped impact records |
| Donor management | Implemented as tenant-scoped impact records |
| CSR project management | Implemented as tenant-scoped impact records |
| Volunteer management | Implemented as tenant-scoped impact records |
| Mobile | Responsive web experience implemented; native apps remain planned |
| Multi-language UI | Planned |
| White-label SaaS | Planned |

## Production-only dependencies

PostgreSQL migrations, Redis workers and scheduler, private S3-compatible storage, malware scanning, managed OIDC/SSO, transactional email, official WhatsApp, cloud calendar/storage providers, digital signatures, OCR/AI providers, observability, encrypted backups, infrastructure as code and security-edge controls require deployment choices and credentials. The application keeps these behind explicit domain or provider boundaries so they can be connected without changing the compliance model.
