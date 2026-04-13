# ADR 0005 — FastAPI for new services; legacy Flask stays

- **Status:** Accepted
- **Date:** 2026-04-13
- **Deciders:** Sairo engineering
- **Decision reference:** D4 in [`../decisions.md`](../decisions.md)

## Context

The existing app is Flask-based and deeply coupled to the singleton
datastore. The SaaS rewrite introduces new services (identity, core,
worker, billing) that are a chance to pick the stack deliberately.

Three options:

1. Keep writing new code in Flask.
2. Rewrite the legacy app in FastAPI as part of the strangler-fig.
3. Keep Flask in legacy; write new services in FastAPI.

Flask has served the legacy app well and the WCAG / accessibility work
we inherited is tied to its Jinja templates. FastAPI gives us async
on the HTTP layer (aligning with the async workers and asyncpg),
first-class Pydantic types, and auto-generated OpenAPI that is useful
as a customer-facing artefact.

## Decision

**Mixed: FastAPI for all new services; legacy Flask stays until
Phase 10.**

- `services/identity/`, `services/core/`, `services/worker/`, and
  `services/billing/` are FastAPI + SQLAlchemy 2.x async + Pydantic 2.
- The legacy app under `changedetectionio/` keeps its Flask + Jinja
  stack. It is read-only feature-frozen during Phases 3–5 (see
  `PLAN.md` risk register).
- Python version: **3.11+** across the board.
- In production, FastAPI services and the Flask app run as separate
  containers fronted by the same reverse proxy.

## Consequences

**Good**
- Async hot path for the new services (important for the worker and
  the websocket bridge).
- Auto-generated OpenAPI per service ships as customer-facing API docs
  without a separate authoring step.
- Pydantic models become the single source of truth for request shapes,
  which flows into the Next.js client.

**Bad**
- Two HTTP frameworks to learn / debug in the monorepo until Phase 10.
- Some infra code (middleware, error handlers, logging) exists twice.

**Obligations**
- Cross-service shared types live in `packages/shared/` (Pydantic
  models). No shared Flask↔FastAPI helpers.
- The legacy Flask app does **not** get new feature work during
  Phases 3–5. Bug fixes only.
