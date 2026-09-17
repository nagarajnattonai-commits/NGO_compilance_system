# White-label operations

White-labeling is a presentation configuration for the existing tenant, not a
new application, NGO identity, permission system, or translated business value.
Client organization names, registration identifiers, statutory evidence,
deadlines, workflow states, and CSV data are not rewritten by branding.

## Administration and access

- Tenant administrators: `/settings/white-label` (also available in the existing
  workspace sidebar). The API enforces `white_label.manage` through the current
  ADMIN role; MEMBER and VIEWER cannot configure branding.
- Platform operators: `/admin/white-label`. Their account must be ADMIN **and**
  its email must be explicitly listed in `PLATFORM_ADMIN_EMAILS` on both services.
  An ordinary tenant administrator cannot grant their own entitlement or act on
  other tenants.
- `can_use_feature(tenant_id, "white_label")` requires an active, unexpired
  subscription and an enabled, unexpired explicit tenant entitlement. Plan names
  are not authorization rules. The development demo alone is seeded with access.
  New workspaces require an operator grant.

An operator can enable the entitlement in the platform screen after the account
is provisioned through the existing signup/invitation process. No default
production operator account or password is created.

## Draft, preview, publish, and recovery

The editor has Brand, Theme, Login, Domain, Email, Reports & Documents, Support,
Advanced, and Preview tabs. It uses the existing layout, controls, localization,
and light/dark mode. Upload supports native file drag/drop, keyboard/touch file
selection, preview, replacement, and removal from a draft.

1. Edit the local draft and inspect dashboard/login/email/report previews.
2. Save draft. This creates an immutable numbered configuration version, with an
   optimistic revision check. It does **not** change the live application.
3. Publish the saved draft. Ownership of every referenced asset, field validation,
   subscription entitlement, and text/accent contrast are checked again by the API.
4. Publishing reloads the tenant's current page so SSR metadata, favicon, identity,
   and tokens all use the same published snapshot.

Unsaved drafts are guarded on navigation and browser unload. Concurrent edits
return HTTP 409 rather than silently overwriting a newer revision. Historical
versions can be restored into a draft, then deliberately saved and published.
Restore Defaults creates a default **draft**. Discard Draft keeps history and
returns to the published configuration. Operator reset disables active branding
but retains versions/assets. Operator suspend blocks tenant republishing.

Downgrade/expiry/suspension immediately disables branding on new API/server
requests and disables custom-domain authentication and certificate authorization.
Configuration/history remain available for recovery on the platform hostname.
Open authenticated pages recheck their brand on focus/visibility change, at most
once per 30 seconds, without discarding local editor state.

All configuration, publication, upload, removal, domain, entitlement, and operator
actions use the existing tenant-scoped audit event system. The settings screen
shows recent audit events and version actors/timestamps.

## Asset storage and safety

Supported inputs: PNG, JPEG, WEBP. SVG, arbitrary HTML/CSS/JS, animated images,
corrupt/mismatched images, excessive dimensions, and decompression bombs are
rejected. Logos/favicons are bounded to 2 MB; backgrounds to 5 MB. Minimum image
dimensions are 16 pixels; maximum input dimensions are 4096 pixels. Favicons must
be square. Images are decoded/re-encoded without metadata or embedded payloads.
Logos use PNG for broad email compatibility; backgrounds use WEBP.

Development: `BRAND_ASSET_DIR` (default `apps/api/data/brand-assets`).
Production: a **private** `BRAND_S3_BUCKET`, optional `BRAND_S3_ENDPOINT`,
`AWS_REGION`, and workload identity or scoped AWS credentials. Objects have
unguessable server-generated keys under the owning tenant, encryption at rest,
and no database binary storage. Credentials/storage keys are never public.

Draft asset reads require the owning tenant's administrator. Published brand
assets are public presentation resources. Every read rechecks publication and
entitlement and uses `nosniff`, restricted content policy, and `no-store` to avoid
serving an expired/suspended tenant's cached brand. Active published assets cannot
be deleted. Removal is soft deletion so audit/history remain intact; configure
operator-reviewed object lifecycle cleanup for genuinely unreferenced objects.
Statutory uploaded documents are never rebranded.

## Custom domains and SSL

Only public **subdomains** are accepted, e.g. `portal.customer.org`. A hostname is
unique across all tenants, including disabled historical registrations. IPs,
local/reserved hosts, URLs, paths, ports, and platform hostnames are rejected.

1. Add the domain in the Domain tab while using the platform hostname.
2. Add the exact `_setu-verification.<hostname>` TXT token shown by the editor.
3. Add a CNAME from the custom hostname to `WHITE_LABEL_CNAME_TARGET`. The target
   must route to your deployed TLS edge. DNS-only routing is recommended while
   validating the origin's certificate (a third-party proxy requires separate setup).
4. Click Verify. Ownership and routing are checked using bounded DNS lookups.
   Until a trusted HTTPS certificate exists, the domain stays VERIFIED/PENDING,
   cannot be primary, and cannot authenticate users.
5. With the included Caddy configuration, opening HTTPS on the verified hostname
   triggers on-demand ACME issuance. The internal ask endpoint authorizes only
   recorded ownership + routed DNS + live entitlement + non-suspended domains.
   It uses an indexed database lookup, not DNS/network calls in the TLS handshake.
6. After issuance, click Verify again (checks have a ten-second cooldown). The
   server verifies public DNS addresses and the trusted certificate for the exact
   hostname, connecting to the already-validated IP to prevent DNS rebinding/SSRF.
   The domain becomes ACTIVE/ACTIVE and can then be selected as primary.

Caddy manages issuance and renewal using persistent certificate storage. Its
[official on-demand TLS documentation](https://caddyserver.com/docs/caddyfile/options#on-demand-tls)
describes the mandatory authorization gate. Unknown, pending, suspended, expired,
or unrouted domains are denied. The deployment edge blocks public access to the
internal ask route. The API should remain reachable only on the private network.

Requests are tenant-bound on custom hosts, including login and invitation/reset
token redemption. A session from another tenant is rejected. Cookies are host-only
and secure in production: switching domains intentionally requires signing in
again. Primary-domain email links are used only when that domain is active.

`X-Forwarded-Host` and caller-supplied tenant headers are never authority.
Next's server proxy overwrites `X-Setu-Host` and `X-Setu-Proxy-Key`; the API trusts
the former only when the shared key matches. Use an identical random
`BRAND_PROXY_KEY` of at least 32 characters on both services. Never expose it as a
`NEXT_PUBLIC_*` value. `PLATFORM_HOSTS` lists any additional operator-owned entry
hostnames; custom tenants may not claim them.

## Production deployment template

The existing development Compose remains available. The separate opt-in template
uses PostgreSQL, private S3-compatible assets, the existing API/web images, and
Caddy as the only public service:

```powershell
# Populate a private deploy/.env.white-label using the example; do not commit it.
docker compose --env-file deploy/.env.white-label -f deploy/compose.white-label.yml config --quiet
docker compose --env-file deploy/.env.white-label -f deploy/compose.white-label.yml up --build -d
```

Required values are documented in `deploy/.env.white-label.example`. Create DNS
A/AAAA for `PLATFORM_DOMAIN` and the CNAME target, allow ports 80/443, configure
private bucket/IAM access, and supply ACME/SMTP operator values. `API_INTERNAL_URL`
is required **at build time and runtime** for the website because Next rewrites
are compiled into its route manifest. The Docker build now accepts that argument.

Production startup does not seed demo tenants/data. Following the existing schema
convention, startup creates the new tables if absent; take a database backup and
run a single controlled schema/bootstrap step before horizontally scaling.
Existing NGO rows are not migrated or modified. Changes to these new tables after
their initial release should use a reviewed migration. Add managed backup,
observability, secrets rotation, ACME staging/renewal monitoring, and an approved
infrastructure roll-out before serving real customers. This template was not
deployed to a live domain as part of implementation.

## Emails, reports, localization

The shared backend template renderer accepts `locale`, `template_key`, and
variables for password reset, invitation, and compliance deadline reminder.
Requested/user locale → tenant default → English. It escapes all tenant/business
text and accepts application links only on the authorized origin. Reset email is
integrated with existing SMTP delivery as text + HTML. Invitation/reminder
templates are available to the existing invitation/automation workflow; automated
delivery for those workflows still needs its scheduled delivery integration.

SMTP uses TLS on port 465 by default. Tenant branding can change sender display
name, Reply-To, signature, logo, support details, and footer, but **never** the
provider-verified `SMTP_FROM` address or provider credentials. Configure SPF/DKIM/
DMARC with the email provider. No email is represented as sent without SMTP.

Reports → PDF / Print opens a tenant-scoped, localized print-ready report using
the published report logo, provider name, footer, support details, user/timezone,
and separate client NGO identity. Browser Print/Save as PDF generates the PDF;
this is not an asynchronous server-side PDF job service. CSV export and business
statuses remain unchanged. English/Hindi/Kannada/Marathi UI dictionaries share
keys; brand names are literal, taglines optionally localized; existing tenant
translation overrides still apply to UI labels. The safe resolver falls back to
platform branding when the feature/configuration/assets are unavailable.

## Verification

```powershell
cd apps/api
.venv/Scripts/python.exe -m pytest -q
cd ../web
npm.cmd run lint
npm.cmd run build
npx.cmd playwright install chromium
npm.cmd run test:white-label
```

Browser QA uses a fresh temporary database/storage, isolated ports 3001/8001, and
separate build output. It never resets the developer's database or sessions. The
suite checks draft/publish, uploads, console errors, localization, long names,
light/dark modes, and editor layouts at 320/360/375/390/425/768/1024/1280/1440/1920
pixels. API tests cover RBAC, cross-tenant boundaries, stale revisions, asset
validation, contrast, DNS/TLS guards, domain binding, operator suspension,
certificate authorization, subscription downgrade, and output identity.
