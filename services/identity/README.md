# Identity service

Owns the Phase-1 tenancy primitives: **orgs**, **users**,
**memberships**, **sessions**, **API keys**, **invites**,
**audit logs**.

Design: [`../../docs/saas/phase-01-foundations.md`](../../docs/saas/phase-01-foundations.md).

## Quick start

```bash
# From repo root: spin up Postgres + Redis
docker compose -f docker-compose.dev.yml up -d

# In this directory:
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8001

curl http://localhost:8001/healthz
# {"status":"ok"}
```

## Layout

```
services/identity/
├── pyproject.toml
├── alembic.ini
├── migrations/
│   ├── env.py
│   ├── script.py.mako
│   ├── sql/
│   │   └── dev-init.sql            # bootstrap roles for local dev
│   └── versions/
│       └── 20260413_0001_initial_schema.py
├── app/
│   ├── main.py                     # FastAPI app
│   ├── config.py                   # pydantic-settings
│   ├── db.py                       # async engine, session, RLS helpers
│   ├── middleware/
│   │   └── tenant_resolver.py
│   ├── models/                     # SQLAlchemy ORM
│   ├── routes/
│   │   └── health.py
│   └── security/
│       └── passwords.py            # Argon2id
└── tests/
    ├── conftest.py
    ├── test_health.py
    └── test_tenant_resolver.py
```

## Environment variables

| Variable | Default | Notes |
|---|---|---|
| `IDENTITY_DATABASE_URL` | `postgresql+asyncpg://onchange:onchange_dev_password@localhost:5432/onchange` | Uses the `app_runtime` role in prod (RLS-respecting). |
| `IDENTITY_DATABASE_ADMIN_URL` | same URL but as `identity_admin` | Used for `BYPASSRLS` queries (cross-org lookups). |
| `IDENTITY_REDIS_URL` | `redis://localhost:6379/0` | Used by rate limits later. |
| `IDENTITY_ROOT_DOMAIN` | `change.sairo.app` | Used by the tenant resolver to strip the root when reading a subdomain. |
| `IDENTITY_SECRET_KEY` | *required in prod* | Signs short-lived access JWTs (Phase 2). |
| `IDENTITY_LOG_LEVEL` | `INFO` | |

See [`.env.example`](./.env.example).

## Out of scope for this phase

- Signup / login / OAuth (Phase 2).
- API-key issuance endpoints (Phase 2).
- Tenant-scoped watch data (Phase 3).

## Running tests

```bash
docker compose -f ../../docker-compose.dev.yml up -d
uv run pytest
```
