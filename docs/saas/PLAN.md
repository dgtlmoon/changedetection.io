# Multi-tenant SaaS rewrite — master plan

> Status: **active.** Last revised when Phase 1 scaffold landed.
>
> Do not edit phase definitions that are already `in progress` or
> `complete` — supersede them with a new ADR instead.

## 0. Non-negotiables

- **Strangler fig, not big-bang.** Every phase ships something working
  behind a feature flag, not an internal refactor that only pays off at
  the end.
- **Processors & fetchers are sacred.** The economic value of the
  codebase lives in [`changedetectionio/processors/`](../../changedetectionio/processors)
  and [`changedetectionio/content_fetchers/`](../../changedetectionio/content_fetchers).
  They get a thin tenant-aware adapter, not a rewrite.
- **Tenant leakage is an existential bug.** Every query, every realtime
  message, every object-storage key is tenant-scoped; RLS in the DB is
  belt-and-suspenders on top of ORM filters.
- **Feature flags from day one.** `TENANTED_MODE`, `NEW_STORE`,
  `NEW_QUEUE`, etc. Any phase must be revertible in one config change.
- **Data migration is first-class.** Every schema change ships with an
  Alembic up+down migration and an importer from the legacy JSON
  datastore.

## 1. Target end state

```
                       ┌────────────────────┐
                       │  Next.js SaaS UI   │
                       │ (marketing + app)  │
                       └──────────┬─────────┘
                                  │ HTTPS / WS
                      ┌───────────▼────────────┐
                      │   API Gateway (Nginx   │  tenant resolver
                      │   / Traefik)           │  subdomain → org
                      └───────────┬────────────┘
          ┌──────────────┬────────┴────────┬──────────────┐
          ▼              ▼                 ▼              ▼
  ┌──────────────┐ ┌───────────┐   ┌───────────┐  ┌──────────────┐
  │  Identity    │ │  Core API │   │  Realtime │  │ Billing svc  │
  │  (auth,      │ │ (FastAPI, │   │ (Socket.IO│  │ (Stripe/LS   │
  │  users, orgs,│ │  tenant-  │   │  w/ rooms)│  │  webhooks,   │
  │  sessions)   │ │  scoped)  │   │           │  │  quotas)     │
  └──────┬───────┘ └──────┬────┘   └─────┬─────┘  └──────┬───────┘
         │                │              │               │
         └──────────┬─────┴──────────────┴───────────────┘
                    ▼
         ┌─────────────────────────┐    ┌──────────────────┐
         │ Postgres (shared DB,    │    │  Redis           │
         │ RLS by tenant_id,       │    │  - job queue     │
         │ Alembic migrations)     │    │  - rate limits   │
         └─────────────────────────┘    │  - socket adapter│
                                        └──────────────────┘
         ┌─────────────────────────┐
         │ Object storage (S3/R2)  │    ┌──────────────────┐
         │ snapshots, screenshots, │◄───┤  Watch Workers   │
         │ PDFs, favicons          │    │  (N horizontal)  │
         └─────────────────────────┘    └──────────────────┘
```

## 2. Phases

| # | Phase | Goal | Status |
|---|---|---|---|
| 1 | Foundations & tenancy primitives | Orgs/Users/Memberships/Sessions/ApiKeys, tenant middleware, RLS | **in progress** |
| 2 | Identity & session | Real signup, login, OAuth, invites, transactional email | pending |
| 3 | New data layer | Replace file datastore with Postgres + S3 behind feature flag | pending |
| 4 | Distributed workers & queue | Redis-backed queue, horizontal workers, per-org fairness | pending |
| 5 | Tenant-scoped HTTP + realtime | All routes + Socket.IO rooms tenant-scoped | pending |
| 6 | Billing, plans, quotas | Checkout, webhooks, quota enforcement at 3 layers | pending |
| 7 | Abuse, rate-limits, SSRF hardening | Per-tenant egress policy, CAPTCHA, content-safety | pending |
| 8 | Observability, ops, admin console | Logs/metrics/traces with `tenant_id`, impersonation, backups | pending |
| 9 | Legal, compliance, launch | ToS/DPA/GDPR export/erasure, SOC 2 prep | pending |
| 10 | Deprecate legacy | Delete single-tenant code paths after EOL window | pending |

Detailed specs live in `phase-0N-*.md` next to this file. Phase 1 and 3
have specs today; the rest get written just-in-time before their phase
starts.

## 3. Code layout (monorepo)

```
/                             # repo root
├── changedetectionio/        # existing Flask engine (LEGACY — to be strangled)
├── services/
│   ├── identity/             # Phase 1: orgs/users/auth (FastAPI)
│   ├── core/                 # Phase 3–5: tenant-aware watch API (FastAPI)
│   ├── worker/               # Phase 4: distributed fetch worker
│   └── billing/              # Phase 6: billing + webhooks
├── packages/
│   └── shared/               # shared pydantic models, types, clients
├── apps/
│   └── web/                  # Phase 5+: Next.js SaaS UI
├── docs/
│   ├── saas/                 # THIS directory
│   └── api-spec.yaml         # existing legacy OpenAPI
├── docker-compose.yml        # legacy self-hosted compose
├── docker-compose.coolify.yml# Coolify deploy compose
└── docker-compose.dev.yml    # new: Postgres + Redis for local dev
```

Languages: Python 3.11+ for all services (keeps the processor code
reusable), TypeScript for `apps/web/`. Python dependency management per
service via [uv](https://github.com/astral-sh/uv) + `pyproject.toml`.

## 4. Risk register (condensed)

| Risk | Mitigation |
|---|---|
| Two-system drift — new and legacy diverge | Strict feature-flagging; `StoreAdapter` abstraction; adapter tests run against both |
| Processor contract creep — processors silently depend on singletons | Phase 3 includes an audit of every `from ... import datastore` / `signal.send()`; replace with explicit context |
| Tenant leakage IDOR | RLS + ORM filter + dedicated `tests/tenancy/` suite in every service |
| Migration data loss | Idempotent importer, dry-run, checksums, 30-day legacy retention |
| Scope blowup | Freeze legacy feature work during Phases 3–5 |
| AI cost runaway | Phase 6 metering is a blocker for opening free signups |
| Self-hosted revolt over new deps | "Simple mode" Coolify compose bundles Postgres + Redis + app |

## 5. How to propose a change to this plan

1. Draft an ADR under `docs/saas/adr/NNNN-title.md` (copy template from
   `adr/0001-record-architecture-decisions.md`).
2. Update the relevant `phase-*.md` with the new design.
3. Update this file's phase table status if needed.

Only the ADR is immutable; the rest is a living document.
