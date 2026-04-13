# Multi-tenant SaaS rewrite — design index

This directory holds the design documentation for converting **onChange by
Sairo** from a single-tenant, self-hosted monolith into a multi-tenant SaaS.

It is a strangler-fig rewrite. The existing Flask app under
[`changedetectionio/`](../../changedetectionio) keeps shipping (and keeps
being deployable on Coolify — see [`COOLIFY.md`](../../COOLIFY.md)) until
each subsystem has a replacement behind a feature flag.

## Read in this order

1. [`PLAN.md`](./PLAN.md) — the overall phased roadmap (10 phases, strangler
   fig, vertical slices).
2. [`decisions.md`](./decisions.md) — the seven foundational decisions
   (D1–D7) that shape everything else, with the current default choices.
3. [`phase-01-foundations.md`](./phase-01-foundations.md) — detailed design
   for **Phase 1**: tenancy primitives, database schema, tenant-resolver
   middleware, row-level security. *In progress — code landing now.*
4. [`phase-03-data-layer.md`](./phase-03-data-layer.md) — detailed design
   for **Phase 3**: replacing `changedetectionio/store/*` with Postgres +
   object storage. The ceiling-setter; every later phase depends on these
   shapes being right. *Draft.*
5. [`adr/`](./adr/) — Architecture Decision Records. Short, immutable
   records of *why* a decision was made. New ADRs get appended; existing
   ADRs are superseded, never edited.

## Living docs

Everything in this directory is a living working document **except**
`adr/*`. If a design changes, update the relevant `phase-*.md` and write a
new ADR that supersedes any prior decision.

## What's out of scope for this directory

- Marketing copy (belongs with the future Next.js app).
- Customer-facing help center content.
- Runbooks (belong in an internal-ops repo once Phase 8 lands).
- Anything about the upstream changedetection.io project — see
  [`ATTRIBUTION.md`](../../ATTRIBUTION.md).
