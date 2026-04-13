"""Test fixtures for the core service.

Core tests all require Postgres (the store is the whole point), so
every test here is ``@pytest.mark.db`` implicitly via this conftest.
A module-level ``pytestmark`` in each test file makes the marker
explicit to readers.

Fixtures create disposable orgs via the identity-admin (BYPASSRLS)
path so test data is isolated per-test and trivially cleanable.
"""

from __future__ import annotations

import uuid
from uuid import UUID

import pytest
from sqlalchemy import text

from app.db import admin_session


@pytest.fixture
async def org_id() -> UUID:
    """A fresh org row, created for a single test.

    We insert directly — no identity service process needed. The row
    is torn down in the yield/finally so parallel tests don't collide
    on slug uniqueness.
    """
    new_id = uuid.uuid4()
    slug = f"test-{new_id.hex[:12]}"
    async with admin_session() as db:
        await db.execute(
            text(
                "INSERT INTO orgs (id, slug, name, plan_tier, status) "
                "VALUES (:id, :slug, :name, 'free', 'active')"
            ),
            {"id": str(new_id), "slug": slug, "name": f"Test Org {slug}"},
        )
    try:
        yield new_id
    finally:
        async with admin_session() as db:
            # ON DELETE CASCADE on watches/tags via FK → clean up
            # happens automatically.
            await db.execute(
                text("DELETE FROM orgs WHERE id = :id"), {"id": str(new_id)}
            )


@pytest.fixture
async def other_org_id() -> UUID:
    """Second org for cross-tenant isolation tests."""
    new_id = uuid.uuid4()
    slug = f"other-{new_id.hex[:12]}"
    async with admin_session() as db:
        await db.execute(
            text(
                "INSERT INTO orgs (id, slug, name, plan_tier, status) "
                "VALUES (:id, :slug, :name, 'free', 'active')"
            ),
            {"id": str(new_id), "slug": slug, "name": f"Other Org {slug}"},
        )
    try:
        yield new_id
    finally:
        async with admin_session() as db:
            await db.execute(
                text("DELETE FROM orgs WHERE id = :id"), {"id": str(new_id)}
            )
