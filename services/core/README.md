# Core service

Tenant-scoped watch store + (eventually) HTTP API for onChange by
Sairo. Replaces the legacy file datastore +
Flask blueprints under `../../changedetectionio/`.

Design: [`../../docs/saas/phase-03-data-layer.md`](../../docs/saas/phase-03-data-layer.md).

## Status

**Phase 3.1 — scaffold + Postgres store.** This commit:

- Owns three tables: `watches`, `watch_tags`, `watch_tag_links`.
- Ships `PgWatchStore` and `PgTagStore` satisfying the `WatchStore`
  and `TagStore` protocols defined in
  [`app/store/protocol.py`](app/store/protocol.py).
- **No HTTP routes yet.** The store is the 3.1 deliverable; HTTP
  routes arrive in Phase 3.2.

## Running tests

```bash
# From repo root: bring up Postgres + Redis.
docker compose -f docker-compose.dev.yml up -d

# Apply BOTH migration sets, in order:
cd services/identity && uv run alembic upgrade head && cd -
cd services/core     && uv run alembic upgrade head && cd -

# Then:
cd services/core && uv run pytest
```

## Alembic ordering

The core service's migrations depend on the identity service's
`orgs` table. CI enforces the run order: **identity migrations
first**, then core. The two services use distinct
`alembic_version` tables:

- identity → `alembic_version` (default)
- core     → `alembic_version_core`

So they coexist without stepping on each other.

## Env

| Variable | Default | Notes |
|---|---|---|
| `CORE_DATABASE_URL` | `postgresql+asyncpg://app_runtime:app_runtime_dev_password@localhost:5432/onchange` | RLS-respecting runtime role. |
| `CORE_DATABASE_ADMIN_URL` | same URL as `identity_admin` | Used by Alembic for DDL. |
| `CORE_LOG_LEVEL` | `INFO` | |
