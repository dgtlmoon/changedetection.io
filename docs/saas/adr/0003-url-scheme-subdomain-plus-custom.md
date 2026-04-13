# ADR 0003 — URL scheme: subdomain per tenant + opt-in custom domains

- **Status:** Accepted
- **Date:** 2026-04-13
- **Deciders:** Sairo engineering
- **Decision reference:** D2 in [`../decisions.md`](../decisions.md)

## Context

Three options for locating a tenant in the URL:

1. **Path** — `change.sairo.app/acme/watches`. One cookie jar for every
   org, one TLS cert, but every session cookie is cross-tenant.
2. **Subdomain** — `acme.change.sairo.app/watches`. Cookie scope is
   per-tenant; wildcard cert needed; SSO redirect URIs are clean.
3. **Custom domains** — `watch.acme.com`. White-label; each domain needs
   its own cert.

We want per-tenant cookie isolation, a white-label story for
enterprise, and we do not want to retrofit URL schemes later (all SSO
redirects, all API clients, all email-embedded links break on change).

## Decision

**Subdomain per tenant** is the default URL scheme, with **custom
domains** available as an opt-in on paid plans from Phase 5 onward.

- Canonical URL: `https://<org-slug>.change.sairo.app/…`.
- Wildcard TLS: `*.change.sairo.app` issued via Let's Encrypt **DNS-01**
  challenge, renewed automatically by the reverse proxy.
- Custom domains (Phase 5): one `custom_domains` table row per host;
  HTTP-01 cert issued per domain.
- `api.change.sairo.app` is a reserved host — used for cross-tenant API
  calls that carry `/v1/orgs/{slug}/…` in the path.
- The tenant-resolver middleware implements the resolution order
  (subdomain → custom domain → path); see
  [`services/identity/app/middleware/tenant_resolver.py`](../../../services/identity/app/middleware/tenant_resolver.py).

## Consequences

**Good**
- Clean per-tenant cookie scope (no accidental cross-tenant session).
- White-label story for enterprise with no code change.
- Works with third-party SSO providers without custom redirect URIs
  per tenant.

**Bad**
- Needs DNS-01 for the wildcard cert — pick an ACME client that
  supports the DNS provider in use (Coolify's Traefik supports the
  common ones).
- Subdomain length caps are 63 characters per label; org slug regex
  matches this (`[a-z0-9][a-z0-9-]{1,38}[a-z0-9]`).

**Obligations**
- Every route in `services/identity/` and later in `services/core/`
  must either require a resolved tenant (`request.state.org_id` set) or
  explicitly mark itself `@public_route`. No route is org-agnostic by
  accident.
- Custom-domains table design is owned by Phase 5; Phase 1–4 code must
  not hard-code subdomain-only assumptions.
