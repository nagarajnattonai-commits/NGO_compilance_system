# Authentication implementation

The existing FastAPI cookie/session system, tenant resolver, shared integration secret store, role permissions, Next.js branding/localization providers and design tokens are reused. User authentication and platform administration now have separate routes and server authorization.

## 1. Files created

API: app/auth_models.py, auth_policy.py, auth_experience.py, auth_oauth.py, auth_admin.py, migrate_auth.py and tests/test_auth_experience.py.

Web: app/auth-experience.css; components/auth-password-input.tsx, auth-change-email.tsx, auth-provider-settings.tsx, workspace-selector.tsx; the routes listed below; four messages/<locale>/authentication.json dictionaries; public/google-g.png (official Google asset); tests/white-label/authentication.spec.ts and platform-operator.ts.

This document records operation and remaining deployment requirements.

## 2. Files modified

API: auth.py, main.py, brand_outputs.py, branding.py, compliance_master.py, integration_api.py and requirements.txt.

Web: existing login/signup/recovery/invitation pages, auth-form.tsx, password-guidance.tsx, public-locale-switcher.tsx, platform-navigation.tsx, workspace.tsx, branding/server.ts, i18n/messages.ts, lib/server-auth.ts, proxy.ts, existing admin integration/developer layouts, playwright.white-label.config.ts, scripts/auth-smoke.mjs, existing browser tests and tsconfig.json.

Deployment: deploy/compose.white-label.yml. README links to these operating instructions.

## 3. Routes

Existing /login, /signup, /forgot-password, /reset-password, /accept-invitation and /admin/login use the shared authentication components.

Added /verify-email, /auth/change-email, /auth/link-google, /auth/complete, /select-workspace, /access-denied, /admin/forgot-password, /admin/reset-password and /admin/authentication.

The shared /admin layout protects all platform routes. Public admin authentication pages use platform branding, including on custom domains, which redirect to the configured platform origin. Tenant administration remains in the authenticated workspace.

User login redirects to the dashboard or an authorized workspace selector. Admin login redirects to /admin. Authenticated sessions skip login pages. Logout clears the session and returns to the relevant login route.

## 4. APIs

All paths below are under /api/v1.

New: GET /auth/options; POST /auth/resend-verification, /auth/verify-email, /auth/change-unverified-email; GET /auth/workspaces; POST /auth/workspace; GET /auth/security-events, /auth/sessions; DELETE /auth/sessions/{session_id}; POST /auth/invitation-info, /auth/accept-workspace-invitation.

Google: GET /auth/google, /auth/google/callback; POST /auth/google/signup, /auth/google/link, /auth/google/complete.

Admin: POST /admin/auth/login, /admin/auth/forgot-password, /admin/auth/reset-password; GET /admin/auth/access; GET/PUT /admin/auth/providers/google.

Modified existing signup/login/logout/recovery/invitation/member-access endpoints preserve their original purpose and add verification, audience checks, membership context and security events. The original primary identity, tenant and password are retained when an existing identity joins another workspace.

## 5. Providers and dependencies

Email/password uses the existing scrypt password hashing and server-side session cookies.

Google OpenID Connect uses Authlib's OAuth2 client, authorization code flow with PKCE, and joserfc for signed Google identity tokens. Requests performs server-to-server HTTPS calls. Added requirements: Authlib >=1.8,<2; requests >=2.32,<3; joserfc >=1.6,<2.

No Microsoft, SAML or other provider is represented as configured.

## 6. Environment and local operation

API (PowerShell, from apps/api):

    .venv\Scripts\python.exe -m pip install -r requirements.txt
    $env:APP_ORIGIN = 'http://localhost:3000'
    $env:AUTH_REQUIRE_EMAIL_VERIFICATION = '1'
    .venv\Scripts\python.exe -m app.migrate_auth --apply
    .venv\Scripts\python.exe -m uvicorn app.main:app --reload

Web (second terminal, from apps/web):

    npm.cmd install
    npm.cmd run dev

Open http://localhost:3000/login. Platform administration is http://localhost:3000/admin/login.

Set real SMTP_HOST, SMTP_PORT (default 465), SMTP_USER, SMTP_PASSWORD and SMTP_FROM, or configure the existing enabled email integration. Missing mail configuration produces HTTP 503; signup and recovery do not claim that mail was delivered. Never paste production credentials into source control.

Common settings: DATABASE_URL, APP_ENV, APP_ORIGIN, PLATFORM_HOSTS, BRAND_PROXY_KEY and PLATFORM_ADMIN_EMAILS. Use HTTPS, a strong shared proxy key and a private database in production. API_INTERNAL_URL points the web server at the private API. PLATFORM_HOSTS is a comma-separated list of approved platform hostnames; APP_ORIGIN controls the OAuth callback.

AUTH_REQUIRE_EMAIL_VERIFICATION=1 enables verification even for older API clients; production always requires it and the current signup UI always requests it. Development legacy API calls that omit the new fields retain immediate signup for existing integrations/tests.

AUTH_TERMS_URL and AUTH_PRIVACY_URL should point to actual approved legal documents. Published tenant legal links can override them. No invented terms/privacy page was added.

AUTH_ADMIN_MFA_REQUIRED=1 blocks admin login until a real second-factor implementation exists. Default 0 does not claim that MFA is active.

Secret settings reuse INTEGRATION_SECRET_BACKEND, INTEGRATION_SECRET_PREFIX, INTEGRATION_SECRET_KMS_KEY_ID and AWS settings. The production Compose configuration uses AWS Secrets Manager by default. The environment secret store is development-only and read-only through the application.

Restart an existing API process after installing new dependencies or if its reloader has stopped responding.

## 7. Google configuration

Create a Google Cloud OAuth client of type Web application, configure its consent screen and authorized test users as appropriate, and register this exact authorized redirect URI:

    <APP_ORIGIN>/api/v1/auth/google/callback

Local example: http://localhost:3000/api/v1/auth/google/callback. Production must use the actual HTTPS platform origin. Custom tenant domains broker authentication through this single platform callback.

Provision an existing trusted active administrator identity by operator command, with its email explicitly included in PLATFORM_ADMIN_EMAILS:

    .venv\Scripts\python.exe -m app.auth_admin --email <trusted-existing-admin-email>

This command is privileged operator work. Public signup never grants platform access.

Production: open /admin/authentication, enter the Google client ID and write-only client secret, and choose the three independent settings: user login, public signup and platform-admin login. Saving the secret requires the writable AWS secret store and the existing oauth_clients.manage permission. Credentials never appear in API responses or the database; only a vault reference is stored.

Development: inject a secret using a valid existing environment-store reference env://SETU_SECRET_<32 hexadecimal characters>, then configure it with the operator CLI:

    .venv\Scripts\python.exe -m app.auth_admin --email <trusted-existing-admin-email> --google-client-id <client-id> --google-secret-ref <secret-reference> --enable-user-google --enable-signup-google

Only add --enable-admin-google when intentionally enabling it. The named environment variable after env:// must contain the real client secret in the API process environment. The CLI checks that the secret can be resolved. Do not put a secret literal in a command argument.

All three Google settings default off. Unknown Google identities can only enter the explicitly enabled public signup/onboarding flow. Google admin authentication requires an existing authorized platform identity.

References: [Google OpenID Connect](https://developers.google.com/identity/openid-connect/openid-connect), [Google branding guidelines](https://developers.google.com/identity/branding-guidelines), [Authlib OAuth client](https://docs.authlib.org/en/v1.6.9/client/starlette.html), [joserfc JWT validation](https://jose.authlib.org/en/guide/jwt/).

## 8. Database changes

Additive tables: auth_account_details, auth_workspace_access, auth_session_context, auth_provider_identities, auth_oauth_flows, auth_oauth_policy, auth_security_events, auth_workspace_invitations and auth_pending_google_identities. The exact table names are defined in auth_models.py.

No existing user, tenant, password, session or token columns are removed or rewritten. Existing primary workspace membership remains intact. Schema migration version 20260918_authentication_v1 is recorded in the existing integration migration ledger.

Review a database backup and run python -m app.migrate_auth --apply during deployment. Running the module without --apply reports the migration only. It checks for the existing auth schema, creates only additive tables and is idempotent. Current API startup also creates missing mapped tables, matching the repository's existing initialization strategy.

## 9. RBAC

Platform access requires an active existing ADMIN identity, approved platform hostname, platform-session audience and an email in PLATFORM_ADMIN_EMAILS. New accounts additionally need the operator-controlled platform_access flag and verified email.

Legacy identities without an AuthAccount record retain the previous allowlisted-admin eligibility. Provision all trusted legacy operators with the CLI to make that state explicit. Legacy session compatibility is retained; newly issued user sessions cannot access platform administration.

Google-provider settings also require the existing named oauth_clients.manage permission. Tenant ADMIN does not imply platform ADMIN.

Workspace switching accepts only active authorized memberships and rotates the session. Suspended/disabled workspaces are blocked. Secondary membership roles are applied to the request context without changing the identity's original primary tenant or role. Host headers alone cannot choose another tenant.

Organization type choices reuse the existing supported TRUST, SOCIETY and SECTION 8 types, rather than inventing roles or legal entities.

## 10. Security

HttpOnly session cookies; Secure in production; SameSite=Lax; random session secrets stored hashed; existing origin and mutation-header checks; atomic rate limits; password policy shared with the UI.

Verification/reset/invitation and Google pending identities use expiring single-use proofs. Verification lasts 24 hours; password reset one hour; invitation 48 hours. Admin reset uses a distinct token purpose. Password reset and access changes revoke sessions.

Google state is hashed, browser-bound, expiring and consumed before the code exchange. PKCE and nonce are validated. Tokens require a valid Google signature, issuer, audience, expiry, issued-at, subject, nonce and verified email, with authorized-party checks when present.

Provider identities use Google's immutable subject. Automatic email linking requires both application-verified email and authoritative Google email; other existing accounts require password proof. Provider credentials and tokens are not returned to the browser or written to the database.

Verified tenant domains use a one-minute, single-use, tenant-bound handoff proof. Callback and email proofs are captured from URL fragments and removed from browser history. OAuth callback query strings are excluded from the API access-log scope; authentication responses use no-store and no-referrer.

Security-event responses expose only the owner's events; raw session tokens and IP hashes are excluded. IP hashes support server-side audit without logging raw credentials or request bodies.

## 11. Tests

API authentication tests cover gated signup, terms/type validation, verification/resend/change-email, operator admin audience/host checks, admin recovery purposes, existing-identity invitations, workspace isolation, session revocation, actual signed JWT validation, real Authlib PKCE/callback behavior with isolated provider responses, replay/state binding, Google onboarding, MFA fail-closed, throttling, suspended workspaces and additive migration preservation/idempotency.

Eight browser tests add user/admin workflows, password visibility, validation, remember-me/logout, single-use email/reset handling, backend-outage field preservation and native language/viewport checks across ten authentication routes and widths 320 through 1920. Existing branding, compliance master, integration and localization suites remain in the regression run.

Browser tests use disposable databases, ports 3001/8001 and separate build output. The new authentication suite cleans its signup fixture quota afterward, solely in the guarded disposable database, so the larger suite does not hit the real signup limit on its shared loopback IP. Production throttling remains intact. Development API proxy connections close explicitly to prevent stale pooled sockets during reload/navigation. Platform operator fixtures are provisioned by the real operator CLI; no public test-only privilege endpoint is added. API tests use an in-memory database and cannot reset the local on-disk database.

Final validation: 191 API tests passed. All 33 distinct browser checks passed across the full regression run and focused reruns after fixture/proxy corrections. The final production build, TypeScript unused-code checks and production Compose configuration validation passed. The API suite reports one existing Starlette/AnyIO deprecation warning.

## 12. Known limitations

Live Google consent, real email delivery and AWS credential writes require the operator's actual accounts and credentials. Automated OAuth tests use real signed tokens and the real client library, with isolated transport responses.

MFA is prepared as a policy boundary, not a functioning second-factor enrollment/challenge. Microsoft/SAML are future integrations.

Production PostgreSQL and concurrent multi-node behavior require deployment verification; local API coverage uses SQLite. No production deployment is performed.

Native translations are complete in English, Hindi, Kannada and Marathi; an organization can apply its existing approved translation overrides.

Existing records and the development database are preserved.

## 13. Recommended next step

Configure actual email delivery and legal-document URLs, provision the approved operators, configure the Google web client and shared vault, then run live email/OAuth acceptance tests against the intended HTTPS platform and verified tenant domains. Add real MFA before enforcing AUTH_ADMIN_MFA_REQUIRED=1.
