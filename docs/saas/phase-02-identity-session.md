# Phase 2 — Identity & session

> Status: **in progress (sub-phase 2a landing now).** Later sub-phases
> get design notes appended as they're picked up.

## Goal

Turn the Phase-1 tenancy scaffold into a working authentication
system. By the end of Phase 2 a user can sign up, create an org, log
in, invite teammates, manage API keys, and authenticate via Google or
GitHub — all with proper session management, email verification, and
transactional emails.

## Sub-phases

| # | Sub-phase | Scope |
|---|---|---|
| **2a** | Core auth loop | signup, login, refresh, logout, `/me`, org creation at signup |
| 2b | Email verification + password reset + transactional email | Postmark adapter, verify-email flow, reset flow |
| 2c | Invites | Create invite, list, accept, revoke |
| 2d | API keys | Issue, list, revoke, scope enforcement |
| 2e | OAuth | Google + GitHub login / link / unlink |

This document covers **2a** in depth and outlines the others.

---

## 2a — Core auth loop

### Token model

Two-token flow. The access token is short-lived and stateless; the
refresh token is long-lived and stored server-side so we can revoke it.

| Token | Lifetime | Format | Storage |
|---|---|---|---|
| Access | 15 min | JWT HS256 signed with `IDENTITY_SECRET_KEY` | Stateless |
| Refresh | 30 days | 32 random bytes, urlsafe-base64 | Hashed (SHA-256) in `sessions.refresh_token_hash` |

Access-token claims: `sub=user_id`, `iat`, `exp`, `type="access"`,
`sid=session_id`. The `sid` lets logout-all-sessions invalidate in
flight access tokens early (via a revocation set in Redis, Phase 2b).

**Refresh rotation:** every refresh issues a new refresh-token
alongside the new access-token and marks the previous session row
`revoked_at`. Re-use of a revoked refresh token is a security event;
we respond with 401 and revoke every session for that user (breach
detection).

### Endpoints

```
POST /v1/auth/signup
    body: { email, password, org_name, org_slug? }
    → 201 { access_token, refresh_token, access_expires_in,
             user: { id, email, display_name? },
             org: { id, slug, name, role: "owner" } }

POST /v1/auth/login
    body: { email, password }
    → 200 { access_token, refresh_token, access_expires_in,
             user: { id, email, display_name? } }

POST /v1/auth/refresh
    body: { refresh_token }
    → 200 { access_token, refresh_token, access_expires_in }

POST /v1/auth/logout
    headers: Authorization: Bearer <access>
    → 204

GET /v1/me
    headers: Authorization: Bearer <access>
    → 200 { user: { id, email, display_name?, locale, timezone },
             memberships: [ { org: { id, slug, name }, role }, … ] }
```

Signup and login are **rate-limited** (Phase 2b; Redis bucket).
Login responds with a generic 401 on bad credentials — never reveals
whether the email exists.

### Data layer

Everything Phase 2a does touches the **global** identity tables
(`users`, `sessions`, `orgs`, `memberships`). None of it is tenant-
scoped at query time — the caller is authenticating precisely because
they don't yet have a tenant context. So Phase 2a uses the
`identity_admin` (`BYPASSRLS`) role exclusively, via
`db.admin_session()`.

Every admin-session call site lives inside a narrow function in
`app/services/` that takes primitive arguments. No raw SQLAlchemy
sessions leak into route handlers — if a route wants a user, it calls
`users.find_by_email(email)`, not `session.execute(select(User)...)`.

### Password rules

- Min 12 characters (NIST SP 800-63B).
- No complexity requirements (composition rules are anti-patterns per
  NIST).
- No top-10k breached-password check at signup (deferred; adds a DB
  load). Phase 2b will add it via HaveIBeenPwned's k-anonymity API.

### Slug allocation

At signup the client can either pass `org_slug` or omit it:

- If passed: validated against `^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$`, then
  checked for uniqueness. 409 on collision.
- If omitted: derived from `org_name` (lowercase, non-alpha-num →
  hyphen, collapse runs, trim). If derived slug collides, append
  random suffix. 50 ms cost in the worst case; acceptable for signup.

Reserved slugs (can never be assigned):
```
api, www, admin, auth, billing, docs, help, status, support, blog,
mail, smtp, ftp, about, pricing, terms, privacy, security, careers,
jobs, invoices, webhooks, oauth
```
List lives in `app/services/orgs.py::RESERVED_SLUGS`.

### Transactions

Signup is one transaction:

```
BEGIN
  INSERT orgs (slug, name) RETURNING id;
  INSERT users (email, password_hash) RETURNING id;
  INSERT memberships (org_id, user_id, role='owner', invited_by=NULL);
  INSERT sessions (user_id, refresh_token_hash, ...);
  INSERT audit_logs (action='user.signup', ...);
COMMIT
```

Partial failure means nothing persists — the caller can retry safely.

### Out of scope for 2a

- Email verification flow (user can sign up; their email is not yet
  verified; any route that gates on verification is added later).
- Password reset flow.
- Transactional email (there is nowhere to send signup confirmation
  emails to yet).
- Rate limiting (stubbed; real limits in Phase 2b with Redis).
- OAuth.
- Invites.
- API keys.

---

## 2b — Email verification, password reset, transactional email

### Endpoints

```
POST /v1/auth/verify-email/request
    body: { }  (authenticated; uses current user's email)
    → 204 No Content
    Idempotent; safe to call repeatedly. Rate-limited per user to 5/hour.

POST /v1/auth/verify-email/confirm
    body: { token }
    → 200 { verified_at }
    On success: sets users.email_verified_at, writes audit log.

POST /v1/auth/password-reset/request
    body: { email }
    → 204 No Content   (ALWAYS 204 — never reveal whether email exists)
    Rate-limited per (ip, email) to 3/hour.

POST /v1/auth/password-reset/confirm
    body: { token, new_password }
    → 204
    On success: updates password_hash, revokes every session for the
    user, writes audit log. Caller must log in again.
```

### Token model (both flows)

- 32 random bytes, urlsafe-base64.
- Only sha256(token) is persisted, matching the refresh-token pattern.
- Stored in dedicated tables (`email_verification_tokens`,
  `password_reset_tokens`) so we can revoke / audit independently.
- TTL: email verification 24 h, password reset 1 h.
- Single-use: `consumed_at` gate.

### Email delivery

- `EmailSender` protocol with `send_transactional(template, to, vars)`.
- Two implementations:
  - `ConsoleSender` — prints message to stdout; dev default; used in CI.
  - `PostmarkSender` — real Postmark API over HTTPS; prod default.
- Templates live under `app/email/templates/` as paired `{name}.txt`
  (required) + `{name}.html` (optional). Rendered via Jinja2 with
  variable safety.
- Sends are fired from a FastAPI `BackgroundTask` so the request path
  isn't blocked on SMTP.

### Rate limiting

- Redis-backed sliding-window limiter. Bucket key layout:
  `rl:{action}:{identifier}` — e.g. `rl:login:1.2.3.4:ada@example.com`.
- Applied on: `/v1/auth/login`, `/v1/auth/signup`,
  `/v1/auth/verify-email/request`, `/v1/auth/password-reset/request`.
- Default windows (overridable via env):
  - `signup`: 5 per IP per hour.
  - `login`: 10 per (IP, email) per hour.
  - `verify-email/request`: 5 per user per hour.
  - `password-reset/request`: 3 per (IP, email) per hour.
- Exceeded: `429 Too Many Requests` with `Retry-After` header.

### Security headers

Enforced by `SecurityHeadersMiddleware`:

- `Strict-Transport-Security: max-age=31536000; includeSubDomains; preload`
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy: geolocation=(), microphone=(), camera=()`
- `Cross-Origin-Opener-Policy: same-origin`
- `X-Frame-Options: DENY` (the API is never iframed)

### Data model additions

New table `email_verification_tokens` mirroring
`password_reset_tokens`:

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` PK | |
| `user_id` | `uuid` FK | |
| `token_hash` | `bytea` unique | sha256 |
| `expires_at` | `timestamptz` | 24h |
| `consumed_at` | `timestamptz` nullable | single-use |
| `created_at` | `timestamptz` | |

### Done-when checklist (2b)

- [x] Redis connection + sliding-window limiter with a fake-clock unit test.
- [x] `EmailSender` protocol, `ConsoleSender`, `PostmarkSender`.
- [x] Verification request + confirm routes, fully tested.
- [x] Password-reset request + confirm routes, fully tested.
- [x] Revoke-all-sessions on password-reset confirm.
- [x] Security-headers middleware.
- [x] Rate limit applied to login/signup in addition to the new routes.

## 2c — Invites

### Endpoints

```
POST /v1/orgs/{slug}/invites
    auth: bearer access token AND caller must be owner|admin of {slug}
    body: { email, role }   // role ∈ { admin, member, viewer }
    → 201 { id, email, role, expires_at, created_at }
    Triggers invite email to {email} with a signed acceptance link.

GET /v1/orgs/{slug}/invites
    auth: owner|admin
    → 200 { invites: [ { id, email, role, expires_at, created_at, accepted_at? } ] }
    Lists pending + accepted; consumed invites stay for audit for 30 days.

DELETE /v1/orgs/{slug}/invites/{id}
    auth: owner|admin
    → 204
    Hard-deletes the invite row. Audit-logged.

POST /v1/auth/invites/accept
    body: { token, password?, display_name? }
    auth: optional bearer token.
    → 200 { access_token, refresh_token, access_expires_in, user, org, role }
    Accepts the invite and returns an active session.

    Three cases handled by one endpoint:
      a) Caller has a bearer token AND the invite email matches the
         user → attach membership, mint new session. Ignores password
         field.
      b) Caller has no bearer token AND invite email matches an
         existing user → requires password; authenticates, attaches
         membership.
      c) Caller has no bearer token AND no user exists for the email
         yet → creates the user (password required), attaches
         membership, mints session.

    Email mismatch between caller and invite returns 403. Expired /
    already-accepted / unknown token returns 400.
```

### Authorization — `require_membership(min_role)`

New FastAPI dependency. Resolution:

1. Calls `get_current_user` (bearer token required).
2. Reads `request.state.org_id` (populated by the tenant resolver from
   the `/v1/orgs/{slug}/…` path parameter).
3. Runs a tenant-scoped lookup via `db.with_current_org(org_id)` —
   RLS restricts visibility to the current org, so the same query
   serves as both the membership-exists check and the tenant-membership
   enforcement.
4. Compares the membership's role to `min_role` using a fixed ordering:
   `owner > admin > member > viewer`.
5. Raises `404` (not 403) when the caller has no membership in the
   org — don't confirm the org's existence to non-members.

### Data model

Phase 1's `invites` table already covers the need. No new migrations in
2c.

### Email

Reuses the Phase-2b email adapter + Jinja2 renderer. New paired
template `invite.{txt,html}`. The invite URL points at
`https://{root_domain}/invites/accept?token={token}`. The Next.js app
(Phase 5+) renders the UI; until then, the link yields a JSON 400 if
opened directly — expected, since the page needs to collect the
acceptance POST body.

### Cross-tenant isolation tests

The first phase that really exercises it. `tests/test_invites_flow.py`
asserts:

- Admin in org A cannot list invites of org B (`404`).
- An invite token issued for org A cannot be accepted into org B.
- An invited user's membership row is only visible inside `/v1/me` of
  the accepting account and inside the org's invite list — never
  across orgs.

### Done-when checklist (2c)

- [x] `invites/*` endpoints implemented.
- [x] `require_membership(min_role)` dep with role-ordering helper.
- [x] Acceptance endpoint handles all three auth cases.
- [x] Invite email template + link.
- [x] Cross-tenant isolation tests pass.
- [x] Audit log entries for invite.create, invite.revoke,
  invite.accept.

## 2d — API keys

### Endpoints

```
POST /v1/orgs/{slug}/api-keys       (owner|admin)
    body: { name, scopes: [scope, ...], expires_at? }
    → 201 { id, name, key_prefix, scopes, created_at,
             last_used_at, expires_at, revoked_at,
             plaintext_key }   ← shown ONCE
    The plaintext_key field appears only on this response. List /
    get never returns it.

GET /v1/orgs/{slug}/api-keys        (owner|admin)
    → 200 { api_keys: [ {id, name, key_prefix, scopes, ...} ] }

DELETE /v1/orgs/{slug}/api-keys/{id}   (owner|admin)
    → 204
    Sets revoked_at (soft-delete). Key is immediately unusable for
    authentication; row stays for audit.
```

### Key format

```
sk_live_<28 chars urlsafe base64>      — 36 chars total
```

- `key_prefix` column stores the first **12** chars (e.g.
  `sk_live_AbCd`). Indexed for O(1) lookup.
- `key_hash` column stores the SHA-256 of the full plaintext.
- Validation path:
  1. Extract bearer token.
  2. If it doesn't start with `sk_live_`, treat as JWT (Phase 2a path).
  3. Else look up by prefix (first 12 chars).
  4. Compare `sha256(plaintext)` to `key_hash` in **constant time**.
  5. Reject if `revoked_at` or `expires_at` have passed.
  6. Update `last_used_at` asynchronously (background task) — we don't
     block the request path on this write.

### Scopes

Minimal alphabet at launch, extensible:

- `watches:read`
- `watches:write`
- `admin` (implies everything)

Stored as a JSONB array. Scope-checking is a small helper function; the
core API (Phase 3+) will consume it via a dep factory
`require_scope("watches:write")` analogous to `require_membership`.

### Auth dependencies

- `get_current_api_key` — resolves an `sk_live_*` bearer to
  `(ApiKey, Org)`. Returns 401 on any failure.
- `get_current_principal` — **unified** auth that accepts either a JWT
  (→ User) or an API key (→ ApiKey). Future Phase-3 endpoints use this.

### Tests (`test_api_keys_flow.py` @db)

- Admin creates key, plaintext appears once, list hides it.
- Listing excludes revoked keys? — actually shows them with
  `revoked_at` set so admins can audit.
- Non-admin gets 403 on create.
- Cross-tenant delete returns 404.
- Validated: `get_current_api_key` resolves a fresh key; after revoke
  the same bearer returns 401; after `expires_at` passes, ditto.
- Tampered key (right prefix, wrong secret) is 401.

## 2e — OAuth

- `GET /v1/auth/oauth/{provider}/start` → redirect with state + nonce
  in signed cookie.
- `GET /v1/auth/oauth/{provider}/callback` → validate state, exchange
  code, look up or create `oauth_accounts` row, look up or create
  `users` row, create session.
- Providers at launch: Google, GitHub.
- `POST /v1/me/oauth/{provider}/unlink` — remove link; refuses if it
  would lock the user out (no password + no other OAuth).

## Cross-cutting

- **Auditing:** every Phase 2 endpoint writes an `audit_logs` row
  (`user.signup`, `user.login.success`, `user.login.failure`,
  `session.revoke`, `oauth.link`, `apikey.issue`, …). Log writes are
  fire-and-forget (a `BackgroundTask`) so they don't gate the hot
  path.
- **Observability:** structured logs include `user_id`, `org_id`,
  `session_id`, `request_id`.
- **Security headers:** HSTS, X-Content-Type-Options, Referrer-Policy,
  Permissions-Policy added by FastAPI middleware (Phase 2b when the
  first human-facing HTML lands).

## Done-when checklist (2a)

- [x] `tokens.py` issues+verifies JWT access and opaque refresh tokens.
- [x] `services/users.py`, `services/orgs.py`, `services/sessions.py`
  encapsulate DB access; route handlers never touch SQLAlchemy directly.
- [x] `/v1/auth/signup`, `/v1/auth/login`, `/v1/auth/refresh`,
  `/v1/auth/logout`, `/v1/me` implemented and unit-tested.
- [x] Reserved-slug list enforced; slug uniqueness enforced; collision
  auto-suffix implemented.
- [x] Token rotation on refresh; revoked-token replay triggers
  user-wide revoke.
- [x] Argon2id used for password hashing; invalid-hash branch tested.
- [ ] *(2b)* Email verification gate on sensitive routes — deferred.
- [ ] *(2b)* Real rate limiting — deferred.
