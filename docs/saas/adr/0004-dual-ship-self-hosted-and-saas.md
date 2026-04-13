# ADR 0004 — Dual-ship: self-hosted AND SaaS, from the same codebase

- **Status:** Accepted
- **Date:** 2026-04-13
- **Deciders:** Sairo engineering
- **Decision reference:** D3 in [`../decisions.md`](../decisions.md)

## Context

Three strategies were on the table:

1. Sunset self-hosted; SaaS-only.
2. Dual-ship — same code runs multi-tenant (SaaS) or single-tenant
   (self-hosted) depending on a feature flag.
3. Turn self-hosted into a paid "enterprise self-host" SKU with a
   licence server.

The upstream (`changedetection.io`) audience is strongly
self-host-first. We inherited that audience by forking the project, and
sunsetting self-hosted would break a promise that has not been made
noisily but is visible in our `README.md` and `COOLIFY.md`. Licence
servers for (3) cost more engineering than they return at our stage.

## Decision

**Dual-ship.** The new multi-tenant stack also runs as a single-tenant
deployment via the `TENANTED_MODE=false` feature flag:

- In `TENANTED_MODE=false`, the tenant-resolver middleware short-circuits
  and assigns a sentinel `default` org to every request. RLS policies
  still fire; the single-tenant deployment just has one row in `orgs`.
- The Coolify compose (`docker-compose.coolify.yml`) continues to be
  the supported self-hosted path. It will be updated in Phase 3 to
  bundle Postgres + Redis so self-hosted users get the same stack.
- Billing, multi-org, invites, quotas, and SSO are compiled out (or
  gated by flag) in `TENANTED_MODE=false` — the self-hosted admin
  doesn't see them.

## Consequences

**Good**
- Keeps the existing user base.
- Forces the code to stay well-architected — if a feature can only work
  in multi-tenant, it's probably leaking tenant assumptions.
- Self-hosted is the best possible integration test for tenancy
  correctness (one tenant, but all RLS paths exercised).

**Bad**
- Two runtime modes ≈ 2× the testing matrix. Mitigated by a shared
  test suite that parametrises on `TENANTED_MODE`.
- Every new feature lands with an explicit answer to "what does this do
  in self-hosted?" — adds design overhead.

**Obligations**
- No SaaS-only feature may be the only way to accomplish a task that
  worked before the rewrite. If Phase 6 billing gates a feature that
  used to be free in self-hosted, the self-hosted build keeps it.
- CI runs the integration suite twice: once with `TENANTED_MODE=true`,
  once with `false`.
