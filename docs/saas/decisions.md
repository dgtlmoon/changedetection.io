# Foundational decisions (D1–D7)

Seven decisions that shape the entire rewrite. Each has a **current
default** that the Phase 1 scaffold assumes. Override by writing an ADR in
[`adr/`](./adr/).

---

## D1 — Tenant isolation model

**Choices**

| Option | Isolation | Ops cost | Notes |
|---|---|---|---|
| Shared DB + RLS | Row-level | Low | Standard SaaS default. Postgres RLS + ORM filters. |
| Schema-per-tenant | Schema | Medium | N schemas, one migration set per deploy. Hard to retrofit. |
| DB-per-tenant | Physical | High | Usually reserved for enterprise tier. |

**Default: Shared DB + RLS.**
Schema-per-tenant can be added later for the enterprise SKU without a
rewrite — the `org_id` column is always present; an enterprise tenant
just lives in its own schema that carries the same tables.

**Recorded in:** [`adr/0002-multi-tenancy-isolation-model.md`](./adr/0002-multi-tenancy-isolation-model.md)

---

## D2 — URL scheme

**Choices**

| Option | Example | Pros | Cons |
|---|---|---|---|
| Path-based | `change.sairo.app/acme/watches` | Simple TLS, one cert | Cookies span all orgs; CSRF surface |
| Subdomain | `acme.change.sairo.app/watches` | Clean cookie scope, SSO-friendly | Wildcard cert; DNS work |
| Custom domains | `watch.acme.com` | White-label, enterprise | Automated Let's Encrypt pipeline required |

**Default: Subdomain + opt-in custom domains on paid plans.**
Wildcard cert (`*.change.sairo.app`) via Let's Encrypt DNS-01 challenge.
Custom domains land in Phase 5; each domain gets its own cert issued via
HTTP-01 by the reverse proxy.

---

## D3 — Self-hosted story

**Choices**

| Option | Implication |
|---|---|
| Sunset self-hosted | Easier eng; loses the "own your data" crowd |
| Dual-ship — free self-hosted + paid cloud | Largest audience; 2× the testing matrix |
| Paid "enterprise self-host" SKU | Best of both; needs licence server |

**Default: Dual-ship.**
The new multi-tenant stack also runs as a single-tenant deployment — the
`TENANTED_MODE=false` feature flag leaves the app single-org. Coolify
compose bundles Postgres + Redis for an easy self-hosted deploy.

---

## D4 — Language & framework for new services

**Choices**

| Option | Pros | Cons |
|---|---|---|
| Keep Flask | Zero ramp; existing code style | Sync, no native types, older ecosystem |
| Port to FastAPI | async-native, pydantic types, auto-OpenAPI | ~2× files to touch in Phase 5 |
| Mixed: FastAPI for new services, Flask stays in legacy | Incremental | Two HTTP frameworks in one repo |

**Default: Mixed — FastAPI for new services; legacy Flask stays until
Phase 10.**
Both frameworks run on the same Python process pool in dev via `uvicorn`.
In production they run as separate containers fronted by the same
gateway.

---

## D5 — Frontend

**Choices**

| Option | Pros | Cons |
|---|---|---|
| Keep Jinja + vanilla JS | Ship today; reuses the existing WCAG work | Not what SaaS dashboards look like |
| Next.js SPA | Modern; easy to hire for | Rewrites all UI; separate build pipeline |
| Next.js for new surfaces only; Jinja for legacy | Incremental | Two UIs to style consistently |

**Default: Next.js for new surfaces (signup, billing, org switcher,
admin), Jinja stays for the watch dashboard until Phase 5.**
Both share the design tokens defined in `DESIGN.md`.

---

## D6 — Billing vendor

**Choices**

| Option | Role | Notes |
|---|---|---|
| Stripe | Seller of Record for card only | Full control, most features, most tax work |
| Lemon Squeezy | Merchant of Record | Handles VAT/sales tax globally; smaller feature set |
| Paddle | Merchant of Record | Similar to LS, different pricing |

**Default: Lemon Squeezy for launch, Stripe-compatible abstraction in
code so swap is cheap.**
At ≤$5M ARR the MoR tax burden is not worth the eng time.

---

## D7 — Region strategy

**Choices**

| Option | Notes |
|---|---|
| Single region (US-east) at launch | Fastest; EU customers get latency |
| US + EU from day one | GDPR residency story; 2× infra + replication plan |
| Region-ready infra, single region deploy | Pick DB/object-storage vendors with regional pinning now |

**Default: Region-ready infra, single region at launch.**
Postgres via Neon/Supabase (regional), object storage via Cloudflare R2
(auto-replicated, any region), Redis via Upstash (regional). An EU
region can be spun up in Phase 9 without a rewrite.

---

## Summary table

| # | Decision | Current default |
|---|---|---|
| D1 | Tenant isolation | Shared DB + RLS |
| D2 | URL scheme | Subdomain + opt-in custom domains |
| D3 | Self-hosted story | Dual-ship |
| D4 | Framework | FastAPI (new) + Flask (legacy) |
| D5 | Frontend | Next.js (new surfaces) + Jinja (legacy) |
| D6 | Billing | Lemon Squeezy |
| D7 | Region | Region-ready, single at launch |

If you want to override any of these, open an ADR — don't just edit this
file.
