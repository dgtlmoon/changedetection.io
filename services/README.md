# Services

This directory holds the new microservices that will, over the course
of the [SaaS rewrite](../docs/saas/PLAN.md), replace the single-tenant
Flask monolith under `../changedetectionio/`.

| Service | Purpose | Phase | Status |
|---|---|---|---|
| [`identity/`](./identity) | Orgs, users, memberships, sessions, API keys, audit logs | 1 | scaffold |
| `core/`                  | Tenant-scoped watch API (FastAPI) | 3–5 | not started |
| `worker/`                | Distributed fetch workers (Redis-backed queue) | 4 | not started |
| `billing/`               | Billing webhooks, quotas, metering | 6 | not started |

Each service is an independent Python package with its own
`pyproject.toml`, its own Alembic migration tree, and its own tests. They
share nothing except the Postgres database and conventions defined in
[`../docs/saas/`](../docs/saas).

## Local development

```bash
# One-off: start Postgres + Redis
docker compose -f docker-compose.dev.yml up -d

# Run a service
cd services/identity
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8001
```

See each service's own `README.md` for specifics.
