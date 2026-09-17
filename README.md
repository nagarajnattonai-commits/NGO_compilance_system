# Setu — NGO Compliance Management

Setu is a working MVP derived from the three approved documents in `Development Documents`. It focuses on the operational core the requirements identify: organization profile → obligation → deadline → owner/task → evidence → review → completion → audit trail.

## Included

- Multi-organization portfolio dashboard and organization switcher
- Guided organization onboarding with duplicate checks and rule-driven compliance-plan generation
- Compliance register with search, status filters and detailed lifecycle drawer
- Server-validated compliance state transitions, reopening reasons and filing acknowledgement capture
- Task creation, assignment, compliance linking and completion updates
- Statutory deadline calendar
- Version-aware evidence/document library with immutable version-history records
- Notifications, portfolio reporting and recent audit activity
- Compliance comments, correction requests, exceptions and recovery-plan entries
- Tenant administration for scoped member invitations, roles and plan-entitlement usage
- Versioned compliance catalogue entries evaluated against legal type and FCRA status
- Idempotent daily automation for overdue compliance, task reminders, document expiry and annual roll-forward
- Impact portfolio modules for grants, donors, CSR projects and volunteers
- Provider-neutral integration registry for email, WhatsApp, calendars, cloud drives, digital signatures and OCR
- Tenant-grounded compliance assistant with record-level sources and a professional-review disclaimer
- Tenant-scoped FastAPI endpoints with SQLite persistence for local development
- Seed data for a consultant managing three Indian NGOs
- Responsive UI for desktop, tablet and mobile
- Docker setup and API isolation tests

The seeded regulatory items and onboarding rules are demonstrations only. As required by the source documents, statutory rules and dates must be validated by qualified legal/compliance experts before production use.

## Run locally

### 1. API

```powershell
cd apps/api
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m uvicorn app.main:app --reload
```

The API is available at `http://127.0.0.1:8000`; interactive API docs are at `http://127.0.0.1:8000/docs`.

### 2. Web app

In a second terminal:

```powershell
cd apps/web
npm.cmd install
npm.cmd run dev
```

Open `http://localhost:3000`. The authenticated workspace requires the API; an unavailable API produces a recoverable error state and never substitutes unrelated demo data.

The root route is a public pre-login website explaining the platform, compliance workflow, Donor and Donation (D&D) services, audiences, security model, plans and provider-dependent capabilities. Authenticated application work is available at `/dashboard`; administrators can also use `/admin`.

### Docker

```powershell
docker compose up --build
```

## Verify

```powershell
cd apps/api
.venv\Scripts\python -m pytest

cd ..\web
npm.cmd run build
```

Every push and pull request to `main` also runs these API tests, frontend checks and Docker Compose validation through `.github/workflows/ci.yml`.

## Architecture

### Reference-based admin theme

The administrative interface follows the supplied `ngo.codexa.co.in.zip` screenshots: a full-height slate sidebar, green active navigation and actions, gradient dashboard cards, white statistics panels, and striped registers. Existing compliance workflows are preserved; the reference site's unrelated donation, membership and public CMS features are not implied by this visual update.

The theme is maintained in `apps/web/app/reference-theme.css`, loaded after the base workflow styles. It uses system fonts, supports mobile navigation and reduced motion, and keeps all dashboard figures derived from workspace data. The compliance register includes search, status filtering, page size and previous/next controls. Reference PNGs are stored in `design-reference/` for comparison only and are not served as application assets.

```text
apps/web   Next.js App Router + TypeScript presentation layer
apps/api   FastAPI modular API + tenant-scoped persistence
```

The API requires tenant context on every domain query. The local demo falls back to `tenant-demo`; production authentication should replace this with verified OIDC claims. Documents currently store metadata and immutable version records only. The production path should use private S3-compatible object storage, signed URLs and malware scanning as specified in the architecture document.

The implementation coverage map is maintained in `docs/feature-coverage.md`. It separates working product behavior from provider or infrastructure readiness so optional features are not represented as production integrations before credentials, contracts and regulatory validation exist.

### Localization

The UI uses `next-intl` with module-split dictionaries for `en-IN`, `hi-IN`, `kn-IN` and `mr-IN`. English is the safe fallback. Authenticated users can store locale, timezone and 12/24-hour preferences independently; administrators can configure enabled/default languages and order at `/settings/localization`, and can manage tenant-scoped translation overrides at `/settings/localization/translations`. Internal status, role, priority and workflow values remain language-neutral.

## Production roadmap

### White-label branding

Tenant administrators can configure branding at `/settings/white-label`; approved
platform operators manage access at `/admin/white-label`. The implementation uses
the existing tenancy, authentication, localization, and audit model with explicit
entitlements, immutable draft/published versions, validated image assets, theme
tokens, verified custom domains, branded reset emails, and printable reports.
See [white-label operations](docs/WHITE_LABEL.md) for permissions, lifecycle,
security controls, test commands, and the opt-in PostgreSQL/S3/Caddy deployment.

Before deployment, replace the local identity fallback and SQLite with managed OIDC and PostgreSQL, add Redis-backed scheduled workers, connect S3-compatible document storage, configure an email provider, and migrate the validated compliance catalogue into versioned rules. These are intentionally isolated behind the current API boundaries.
