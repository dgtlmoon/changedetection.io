# ADR 0002 — Multi-tenancy isolation model

- **Status:** Accepted
- **Date:** 2026-04-13
- **Deciders:** Sairo engineering
- **Supersedes:** —

## Context

The rewrite (see [`../PLAN.md`](../PLAN.md)) needs an isolation model
that protects tenant data from cross-reads, bugs, and operator error.
Three options were on the table:

1. **Shared database, row-level tenancy** — every table carries an
   `org_id` column, Postgres Row-Level Security enforces isolation.
2. **Schema-per-tenant** — one Postgres schema per organisation, same
   tables duplicated in each.
3. **Database-per-tenant** — one physical database per organisation.

Context pushing the decision:

- Starting population is expected to be hundreds-to-thousands of small
  orgs, not dozens of enterprise accounts. Option 3 is priced for the
  wrong audience.
- We want a **free tier**; option 3 puts a fixed floor under the cost
  of serving a free user.
- Cross-org analytics (admin dashboards, "top 10 watches by error
  rate") are much simpler against a single shared DB.
- Some enterprise customers will later demand physical isolation. The
  chosen model must not block that.
- The existing team has Postgres experience; nobody is interested in
  running hundreds of schemas.

## Decision

Adopt **shared database + Row-Level Security** as the default isolation
model.

- Every tenant-scoped table has a `org_id uuid not null` column.
- Every such table has RLS enabled with a policy that reads the session
  variable `app.current_org`:
  ```sql
  CREATE POLICY p_org_isolation ON <table>
      USING (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid);
  ```
- Application code uses two database roles:
  - `app_runtime` — respects RLS. This role is used by the request
    path; the middleware issues `SET LOCAL app.current_org = :id` on
    every session check-out.
  - `identity_admin` — `BYPASSRLS` set. Used only by the identity
    service's internal "look up which orgs a user belongs to" queries.
    A small, audited set of functions.
- Application code **also** adds `.where(org_id = current_org.id)` in
  SQLAlchemy queries (belt + suspenders). RLS is the safety net; the
  ORM filter is the primary control.
- The enterprise SKU can later adopt **schema-per-tenant** by promoting
  a tenant's schema from the shared `public` schema. The `org_id`
  column stays to keep the same ORM code working.

## Consequences

**Good**
- Cheapest per-tenant cost; makes a free tier possible.
- Single Alembic migration pipeline.
- Cross-org queries stay trivial for admins.
- Standard Postgres tooling (pg_dump, logical replication) works as-is.

**Bad**
- RLS bugs are silent — if the middleware forgets to set
  `app.current_org`, queries return **zero rows** rather than an error.
  Mitigation: the middleware also sets a "no org set" flag that the ORM
  checks and raises on; a cross-tenant test suite runs in CI.
- Every future table author must remember to enable RLS. Mitigation: a
  lint rule in `scripts/lint_migrations.py` (written in Phase 1) fails
  CI if a new table is created without a policy.
- Performance: an extra `WHERE org_id = ?` predicate on every query.
  Mitigation: composite indexes on `(org_id, …)` as a standard pattern.

**Obligations**
- Every new table in `services/*/migrations/` must either be org-scoped
  with RLS enabled, or be explicitly marked `-- GLOBAL` in the
  migration with a comment explaining why.
- A dedicated test suite `tests/tenancy/` must exist in each service and
  must cover: direct SELECT, JOIN, bulk update, delete, and RLS-bypass
  attempts via crafted `org_id` inputs.
