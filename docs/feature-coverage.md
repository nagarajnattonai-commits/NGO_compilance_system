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
| Multi-language UI | Implemented for en-IN, hi-IN, kn-IN and mr-IN with English fallback, route-preserving selectors, locale-aware dates/numbers/currency/percentages and localized auth/workspace navigation |
| Tenant localization administration | Implemented: enabled/default locales, accessible drag-and-drop ordering, completion/missing filters, tenant translation overrides, reset and audit events |
| User regional preferences | Implemented: preferred locale, timezone and 12/24-hour display stored independently per user |
| White-label SaaS | Planned |

## Dotskills Trust admin comparison

The Dotskills Trust demonstration portal was reviewed on 11 September 2026 using the account supplied by the product owner. Setu now provides an admin-only **NGO operations centre** that maps the reference portal's operational modules into Setu's tenant- and organization-scoped record model.

| Reference capability | Setu coverage |
| --- | --- |
| Membership applications, fees, verification, blocking and validity | Implemented as membership operational records with review states |
| Volunteers, approval/renewal and volunteer activity hours | Implemented as volunteer and activity records with approval states |
| Projects, funds, donations, 80G review and crowdfunding | Implemented as project, donation and campaign records; CSV reporting already available |
| Events, member messages and inquiries | Implemented as searchable operational records with module-specific statuses |
| Visitor certificates and document templates | Implemented as issuance/template workflows; generated PDFs and transactional email require production providers |
| News, gallery, testimonials, training and website content | Implemented as draft/publish/archive content workflows |
| Management body and sponsors | Implemented as active/inactive directory workflows |
| Dashboard, compliance, documents, reports, settings and access control | Setu's existing implementations are retained and are more deeply tenant-scoped and audit-oriented |
| Record deletion | Implemented for administrators and audit logged |

The operations centre uses a consistent secure record contract rather than duplicating the reference portal's separate PHP forms. Specialized media uploads, visual certificate canvas editing, online payment capture, receipt PDF rendering and outbound email delivery remain provider-backed production work; their workflows and statuses are represented without claiming that an external service is connected.

## Production-only dependencies

Automated continuous integration is implemented for API tests, frontend type/build validation and Docker Compose configuration on every push and pull request to `main`.

PostgreSQL migrations, Redis workers and scheduler, private S3-compatible storage, malware scanning, managed OIDC/SSO, transactional email, official WhatsApp, cloud calendar/storage providers, digital signatures, OCR/AI providers, observability, encrypted backups, deployment automation, infrastructure as code and security-edge controls require deployment choices and credentials. The application keeps these behind explicit domain or provider boundaries so they can be connected without changing the compliance model.
