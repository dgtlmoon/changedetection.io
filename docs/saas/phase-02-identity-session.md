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

- `POST /v1/auth/verify-email/request` → sends email with a signed
  token.
- `POST /v1/auth/verify-email/confirm` → consumes token, sets
  `users.email_verified_at`.
- `POST /v1/auth/password-reset/request` → rate-limited; idempotent
  response (no enumeration).
- `POST /v1/auth/password-reset/confirm` → consumes token, updates
  `users.password_hash`, revokes all sessions for that user.
- Email adapter: `EmailSender` interface; `PostmarkSender` implementation.
- Rate limits via Redis bucket keyed on `(email, ip)`.

## 2c — Invites

- `POST /v1/orgs/{slug}/invites` — admin/owner can invite by email +
  role.
- `GET /v1/orgs/{slug}/invites` — list pending.
- `DELETE /v1/orgs/{slug}/invites/{id}` — revoke.
- `POST /v1/auth/invites/accept` — body `{ token }`. Creates user if
  new, creates membership, marks invite accepted.

## 2d — API keys

- `POST /v1/orgs/{slug}/api-keys` — body `{ name, scopes, expires_at? }`.
  Returns the plaintext key **once** (`sk_live_…`). We store only the
  prefix + hash.
- `GET /v1/orgs/{slug}/api-keys` — list (never returns plaintext).
- `DELETE /v1/orgs/{slug}/api-keys/{id}` — revoke.
- Auth middleware: bearer token starting with `sk_live_` is looked up
  by prefix then verified by constant-time hash compare.
- Scopes: a minimal alphabet (`watches:read`, `watches:write`,
  `admin`) at launch; extensible.

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
