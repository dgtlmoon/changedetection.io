"""Test fixtures for the core service.

Core tests fall into two buckets:

1. **Store-level** (``test_*_crud.py``, ``test_object_store_*.py``) —
   take ``org_id`` / ``other_org_id`` fixtures, drive the store
   classes directly. Already covered by the Phase-3.1 / 3.2a tests.

2. **HTTP-level** (``test_routes_*.py``) — drive the FastAPI app via
   httpx. Need an authenticated user + their membership in the org,
   and a way to mint a JWT signed with the same ``secret_key`` core
   uses. The ``user_jwt_factory`` fixture below does both.

All fixtures here clean up after themselves so parallel tests don't
collide on org slugs / user emails.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable
from uuid import UUID

import pytest
from jose import jwt
from sqlalchemy import text

from app.config import get_settings
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


# ---------------------------------------------------------------------------
# HTTP-test helpers
# ---------------------------------------------------------------------------


def _mint_access_jwt(user_id: UUID) -> str:
    """Sign a JWT exactly the way identity does it.

    The signature lives here so HTTP tests don't need to spin up the
    identity service — same shared ``secret_key``, same algorithm,
    same claim shape. If identity ever changes the claim format this
    test helper breaks loudly, which is the desired outcome.
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(user_id),
            "sid": str(uuid.uuid4()),
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=15)).timestamp()),
            "type": "access",
        },
        settings.secret_key,
        algorithm="HS256",
    )


@pytest.fixture
async def user_factory():
    """Yields ``async (org_id, role) -> (user_id, jwt)``.

    Creates a user, attaches them to ``org_id`` with ``role``, mints a
    JWT. Cleanup deletes the user (which CASCADEs the membership).
    """
    created_user_ids: list[UUID] = []

    async def _make(
        org_id: UUID, role: str = "member"
    ) -> tuple[UUID, str]:
        user_id = uuid.uuid4()
        async with admin_session() as db:
            await db.execute(
                text(
                    "INSERT INTO users (id, email, password_hash) "
                    "VALUES (:id, :email, :ph)"
                ),
                {
                    "id": str(user_id),
                    "email": f"u-{user_id.hex[:8]}@test.invalid",
                    "ph": "x",
                },
            )
            await db.execute(
                text(
                    "INSERT INTO memberships (org_id, user_id, role) "
                    "VALUES (:org_id, :user_id, :role)"
                ),
                {
                    "org_id": str(org_id),
                    "user_id": str(user_id),
                    "role": role,
                },
            )
        created_user_ids.append(user_id)
        return user_id, _mint_access_jwt(user_id)

    yield _make

    async with admin_session() as db:
        for uid in created_user_ids:
            await db.execute(
                text("DELETE FROM users WHERE id = :id"),
                {"id": str(uid)},
            )


@pytest.fixture
async def api_key_factory():
    """Yields ``async (org_id, scopes) -> plaintext``.

    Mints an ``sk_live_*`` key + records it in ``api_keys``.
    Mirrors identity's services/api_keys.py format exactly.
    """
    import secrets

    created_ids: list[UUID] = []

    async def _make(org_id: UUID, scopes: list[str]) -> str:
        plaintext = "sk_live_" + secrets.token_urlsafe(24)[:28]
        prefix = plaintext[:12]
        key_hash = hashlib.sha256(plaintext.encode("utf-8")).digest()
        new_id = uuid.uuid4()
        async with admin_session() as db:
            await db.execute(
                text(
                    "INSERT INTO api_keys "
                    "(id, org_id, name, key_prefix, key_hash, scopes) "
                    "VALUES (:id, :org_id, 'test', :prefix, :hash, "
                    "        CAST(:scopes AS jsonb))"
                ),
                {
                    "id": str(new_id),
                    "org_id": str(org_id),
                    "prefix": prefix,
                    "hash": key_hash,
                    "scopes": __import__("json").dumps(scopes),
                },
            )
        created_ids.append(new_id)
        return plaintext

    yield _make

    async with admin_session() as db:
        for kid in created_ids:
            await db.execute(
                text("DELETE FROM api_keys WHERE id = :id"),
                {"id": str(kid)},
            )


@pytest.fixture
async def http_client(monkeypatch, tmp_path):
    """ASGI-transport httpx client for hitting the core FastAPI app.

    Pins the object store backend to LocalObjectStore under tmp_path
    so history-upload tests don't need S3.
    """
    monkeypatch.setenv("CORE_OBJECT_STORE_BACKEND", "local")
    monkeypatch.setenv("CORE_OBJECT_STORE_LOCAL_ROOT", str(tmp_path / "blobs"))
    # Bust the cached settings so the env override actually takes.
    get_settings.cache_clear()

    from httpx import ASGITransport, AsyncClient

    from app.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as c:
        yield c

    get_settings.cache_clear()
