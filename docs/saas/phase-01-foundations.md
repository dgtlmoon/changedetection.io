# Phase 1 — Foundations & tenancy primitives

> Status: **in progress.** Scaffold landing now; auth endpoints
> (signup/login/OAuth) are explicitly out of scope — those are Phase 2.

## Goal

Stand up a dedicated **Identity service** (`services/identity/`) with the
tenancy primitives — organisations, users, memberships, sessions, API
keys, invites, audit logs — and enforce isolation via Postgres row-level
security. Every subsequent phase assumes these tables exist and that
`request.state.org_id` is populated by a tenant-resolver middleware.

Nothing user-visible. No existing code changes. The Flask app keeps
running untouched.

## Non-goals for Phase 1

- Signup/login endpoints (Phase 2).
- OAuth providers (Phase 2).
- Password reset emails (Phase 2).
- API key issuance UI (Phase 2).
- The actual watch API (Phase 3 and later).

## Deliverables

1. `services/identity/` Python package with:
   - FastAPI app that exposes `/healthz` and `/readyz`.
   - SQLAlchemy 2.x async models for the nine Phase 1 tables.
   - Alembic initial migration creating those tables + RLS policies.
   - Tenant-resolver middleware (subdomain-based; path fallback).
   - Argon2 password hashing module (used from Phase 2).
   - `pytest` test scaffold with an ephemeral Postgres fixture.
2. `docker-compose.dev.yml` at repo root: Postgres 16 + Redis 7 for local
   development.
3. CI additions: a matrix job that runs identity-service tests against
   the real Postgres service.
4. ADR 0002 recording the shared-DB-plus-RLS decision.

## Data model

All times are `timestamptz`. All PKs are `uuid v7` (stored as `uuid`
type; generated app-side for index locality). Soft-delete is
`deleted_at nullable`. All tenant-scoped tables have `org_id uuid not null`.

### `orgs`

The tenant. One row per customer organisation.

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` PK | uuid v7 |
| `slug` | `citext` unique not null | subdomain label, `[a-z0-9-]{3,40}` |
| `name` | `text` not null | human-visible |
| `plan_tier` | `plan_tier` enum | `free` / `pro` / `team` / `enterprise` |
| `status` | `org_status` enum | `active` / `trial` / `suspended` / `cancelled` |
| `billing_customer_id` | `text` nullable | vendor-specific (LS/Stripe) |
| `created_at` | `timestamptz` not null default `now()` | |
| `updated_at` | `timestamptz` not null default `now()` | trigger-updated |
| `deleted_at` | `timestamptz` nullable | |

Index: `slug` unique (enforced by column); partial index on `deleted_at IS NULL`.

### `users`

Global identity; a user belongs to zero-or-more orgs via `memberships`.

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` PK | |
| `email` | `citext` unique not null | |
| `email_verified_at` | `timestamptz` nullable | |
| `password_hash` | `text` nullable | null for SSO-only users |
| `display_name` | `text` nullable | |
| `avatar_url` | `text` nullable | |
| `locale` | `text` not null default `'en'` | BCP-47 |
| `timezone` | `text` not null default `'UTC'` | IANA |
| `mfa_secret` | `text` nullable | TOTP secret (encrypted) |
| `last_seen_at` | `timestamptz` nullable | |
| `created_at` | `timestamptz` not null | |
| `updated_at` | `timestamptz` not null | |
| `deleted_at` | `timestamptz` nullable | |

### `memberships`

The join table, and the place where RBAC lives.

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` PK | |
| `org_id` | `uuid` FK → `orgs.id` | |
| `user_id` | `uuid` FK → `users.id` | |
| `role` | `membership_role` enum | `owner` / `admin` / `member` / `viewer` |
| `invited_by_user_id` | `uuid` FK nullable | |
| `joined_at` | `timestamptz` not null | |
| `created_at` | `timestamptz` not null | |

Unique `(org_id, user_id)`. Index on `user_id` (for "orgs I belong to"
lookups).

### `invites`

Pending invitations; delete or mark consumed on accept.

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` PK | |
| `org_id` | `uuid` FK → `orgs.id` | |
| `email` | `citext` not null | |
| `role` | `membership_role` enum | |
| `token_hash` | `bytea` unique not null | sha256 of the emailed token |
| `invited_by_user_id` | `uuid` FK | |
| `expires_at` | `timestamptz` not null | 7-day default |
| `accepted_at` | `timestamptz` nullable | |
| `created_at` | `timestamptz` not null | |

### `sessions`

Refresh-token-backed sessions. Short-lived JWT access tokens are NOT
stored.

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` PK | |
| `user_id` | `uuid` FK → `users.id` | |
| `refresh_token_hash` | `bytea` unique not null | sha256 |
| `user_agent` | `text` nullable | |
| `ip_address` | `inet` nullable | |
| `expires_at` | `timestamptz` not null | rolling, default 30 days |
| `last_used_at` | `timestamptz` not null | |
| `revoked_at` | `timestamptz` nullable | |
| `created_at` | `timestamptz` not null | |

### `api_keys`

Per-org machine credentials.

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` PK | |
| `org_id` | `uuid` FK → `orgs.id` | |
| `name` | `text` not null | |
| `key_prefix` | `text` not null | e.g. `sk_live_AbCdEf` (first 12 chars) |
| `key_hash` | `bytea` unique not null | sha256 of full key |
| `scopes` | `jsonb` not null default `'[]'` | list of scope strings |
| `created_by_user_id` | `uuid` FK nullable | |
| `last_used_at` | `timestamptz` nullable | |
| `expires_at` | `timestamptz` nullable | |
| `revoked_at` | `timestamptz` nullable | |
| `created_at` | `timestamptz` not null | |

Index on `key_prefix` for fast lookup in auth middleware.

### `oauth_accounts`

Linked OAuth identities. Populated in Phase 2; table created now.

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` PK | |
| `user_id` | `uuid` FK → `users.id` | |
| `provider` | `oauth_provider` enum | `google` / `github` / `microsoft` |
| `provider_user_id` | `text` not null | |
| `email` | `citext` not null | |
| `access_token_encrypted` | `bytea` nullable | envelope-encrypted |
| `refresh_token_encrypted` | `bytea` nullable | |
| `expires_at` | `timestamptz` nullable | |
| `created_at` | `timestamptz` not null | |

Unique `(provider, provider_user_id)`.

### `password_reset_tokens`

Ephemeral tokens for password reset. Populated in Phase 2.

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` PK | |
| `user_id` | `uuid` FK → `users.id` | |
| `token_hash` | `bytea` unique not null | |
| `expires_at` | `timestamptz` not null | 1h default |
| `consumed_at` | `timestamptz` nullable | |
| `created_at` | `timestamptz` not null | |

### `audit_logs`

Append-only log of security-relevant events. Partition by `created_at`
monthly from the start to avoid a painful repartition later.

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` PK | |
| `org_id` | `uuid` nullable | null for pre-org events (signup) |
| `actor_user_id` | `uuid` nullable | |
| `actor_kind` | `actor_kind` enum | `user` / `api_key` / `system` |
| `action` | `text` not null | e.g. `org.member.invite` |
| `target_type` | `text` nullable | |
| `target_id` | `text` nullable | |
| `metadata` | `jsonb` not null default `'{}'` | |
| `ip_address` | `inet` nullable | |
| `user_agent` | `text` nullable | |
| `created_at` | `timestamptz` not null | |

## Row-level security

Enabled on every tenant-scoped table:

```sql
ALTER TABLE orgs             ENABLE ROW LEVEL SECURITY;
ALTER TABLE memberships      ENABLE ROW LEVEL SECURITY;
ALTER TABLE invites          ENABLE ROW LEVEL SECURITY;
ALTER TABLE api_keys         ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_logs       ENABLE ROW LEVEL SECURITY;
```

Policy template:

```sql
CREATE POLICY p_org_isolation ON memberships
    USING (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid);
```

The middleware issues `SET LOCAL app.current_org = '<uuid>'` at the
start of every request. The identity service's internal "look up user
across orgs" queries run as the `identity_admin` role, which has
`BYPASSRLS` set.

## Tenant-resolver middleware

Resolution order:

1. **Subdomain** — `acme.change.sairo.app` → look up `orgs.slug = 'acme'`.
2. **Custom domain** — `watch.acme.com` → look up `custom_domains` (Phase 5 table, placeholder now).
3. **Path fallback** — `api.change.sairo.app/v1/orgs/acme/...` → read the
   path parameter. Used for API calls from tooling that can't set Host.

If none match, 404.

Outcome: `request.state.org = Org` (fully loaded) and
`request.state.org_id = UUID`. The DB session context manager
immediately issues `SET LOCAL app.current_org = :id`.

Routes that are org-agnostic (signup, the user's own `/me`, login) live
under the `api.change.sairo.app` hostname and bypass the resolver via an
explicit `@public_route` marker.

## Out-of-scope reminders

Phase 1 creates **tables and middleware only.** The Phase 2 list:
- `/v1/auth/signup`
- `/v1/auth/login`
- `/v1/auth/refresh`
- `/v1/auth/logout`
- `/v1/auth/password-reset/{request,confirm}`
- `/v1/auth/oauth/{provider}/{start,callback}`
- `/v1/orgs` (POST, create org)
- `/v1/orgs/{slug}/invites` (POST/GET/DELETE)
- `/v1/me`
- `/v1/api-keys` (POST/GET/DELETE)

Each of those gets its own design note in `phase-02-identity-session.md`
before Phase 2 starts.

## Done-when checklist

- [x] `services/identity/` scaffold compiles; `uv run pytest` passes on
  a stock developer machine with `docker-compose.dev.yml` up.
- [x] Alembic `upgrade head` applies cleanly and `downgrade base` is
  reversible.
- [x] RLS policies on all tenant tables verified by an
  `test_rls_blocks_cross_tenant_reads` test.
- [x] Tenant-resolver middleware unit test covers subdomain + path +
  not-found cases.
- [x] CI runs the new test suite against Postgres 16.
- [ ] Phase-2 design note exists. *(Written at the start of Phase 2.)*
