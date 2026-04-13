# ADR 0008 — Region-ready infra, single region at launch

- **Status:** Accepted
- **Date:** 2026-04-13
- **Deciders:** Sairo engineering
- **Decision reference:** D7 in [`../decisions.md`](../decisions.md)

## Context

Three options for region strategy:

1. Single region (US-east), fix later if it matters.
2. US + EU from day one.
3. Region-ready infra (vendors with regional pinning), single region
   at launch.

EU customers will ask about data residency as soon as we approach
enterprise sales. Running two regions from day one multiplies ops cost
and adds cross-region replication complexity we don't yet need. Picking
infra vendors that *cannot* add a region later paints us into a corner.

## Decision

**Region-ready infra, single-region (US-east) launch.** An EU region
can be spun up in Phase 9 without a rewrite.

- **Postgres**: Neon or Supabase — both support regional pinning and
  cross-region read replicas. Single primary in `us-east-1` at launch.
- **Object storage**: Cloudflare R2 — automatically replicated across
  Cloudflare's network; regional pinning available if required later.
  Single bucket at launch.
- **Redis**: Upstash — regional. Single region at launch.
- **Edge / CDN**: Cloudflare in front of the Coolify reverse proxy.
- **Email**: Postmark (transactional) or Resend — both are global.
- **DNS**: Cloudflare.
- `org_id`-prefixed object-storage keys (`s3://bucket/{org_id}/…`) so
  splitting to per-region buckets later is a rename, not a schema
  change.

## Consequences

**Good**
- Lowest launch cost; one Postgres primary, one bucket, one Redis.
- No cross-region replication to reason about until we need it.
- Vendor choices don't close the door on GDPR residency later.

**Bad**
- EU customers eat ~80–100 ms of extra latency until Phase 9.
- Cloudflare R2 eventual-consistency semantics need care in the
  snapshot-write path (a read-your-own-write test is part of the
  Phase 3 benchmark).

**Obligations**
- Every piece of infra purchased in Phases 1–8 must support a
  second-region deploy or be explicitly flagged as "replace before
  Phase 9" in the service README.
- Phase 9 scope includes the EU region spin-up, with a customer-facing
  region-picker at signup.
