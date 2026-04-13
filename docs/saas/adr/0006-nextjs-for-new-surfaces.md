# ADR 0006 — Next.js for new customer surfaces; Jinja stays for the watch dashboard

- **Status:** Accepted
- **Date:** 2026-04-13
- **Deciders:** Sairo engineering
- **Decision reference:** D5 in [`../decisions.md`](../decisions.md)

## Context

The legacy app's UI is server-rendered Jinja templates with a small
vanilla-JS layer. The SaaS rewrite introduces new customer surfaces
(marketing site, signup, billing, org switcher, admin console) that
don't have a legacy equivalent. We could:

1. Build everything new in Jinja too.
2. Rewrite the entire UI (including the watch dashboard) in a modern
   SPA.
3. Split: Next.js for new surfaces, keep Jinja for the watch dashboard
   until Phase 5.

Option (1) is the fastest to ship but leaves us with a server-rendered
dashboard that is hard to hire for and does not look like a 2026 SaaS.
Option (2) rewrites ~120k lines of Jinja + accessibility work we just
finished — a big regression risk.

## Decision

**Next.js for new customer surfaces; Jinja stays for the watch
dashboard until it's rewritten in Phase 5+.**

- `apps/web/` (Phase 2+): Next.js 15 + React 19, TypeScript, Tailwind
  (with design tokens imported from the existing CSS), consuming the
  FastAPI JSON API.
- Existing Jinja templates keep rendering the watch dashboard. They are
  served by the legacy Flask app, behind the same reverse proxy, at the
  same host. In `TENANTED_MODE=true` they are wrapped by a thin
  tenant-aware middleware injected in Phase 5.
- Design tokens (colours, spacing, type scale, focus ring) are defined
  once in a CSS file that both the Jinja templates and the Next.js app
  import, so `DESIGN.md` stays authoritative.

## Consequences

**Good**
- Signup, billing, admin — the surfaces where a modern SPA actually
  helps — get the modern SPA.
- The accessibility work that landed recently is preserved for the
  dashboard (no regression risk during the rewrite).
- Easier to hire for. Easier to build a design system.

**Bad**
- Two frontend stacks to keep in sync visually until Phase 5+.
- Next.js SSR adds operational complexity (Node runtime, build step).

**Obligations**
- Every Phase 2+ screen ships with a Storybook story and an axe-core
  accessibility test, so Next.js screens meet the same bar as the
  Jinja ones.
- Shared design tokens live in `apps/web/styles/tokens.css` and are
  re-exported to the Jinja build; a CI job diffs the two.
