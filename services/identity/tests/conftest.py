"""Test fixtures for the identity service.

Tests fall into two buckets:

1. **Unit tests** — no database. Pure-Python logic (middleware regex,
   password hashing, config parsing). Run anywhere.
2. **Integration tests** — require Postgres from ``docker-compose.dev.yml``.
   These apply the full Alembic migration set to an ephemeral schema
   per test session, then tear it down at the end.

Integration tests are marked with ``@pytest.mark.db``. CI runs both
suites; developers can skip the db suite locally by passing
``-m "not db"``.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.fixture
def app():
    """A fresh FastAPI app per test, so middleware state can't leak."""
    return create_app()


@pytest.fixture
async def client(app) -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c
