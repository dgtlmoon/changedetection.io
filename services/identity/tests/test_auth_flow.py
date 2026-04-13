"""End-to-end auth flow: signup → login → refresh → logout → /me.

Requires a real Postgres with migrations applied. Marked ``db``; CI
runs these after ``alembic upgrade head``.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app

pytestmark = pytest.mark.db


@pytest.fixture
async def client():
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


async def _signup(client: AsyncClient, email: str, *, slug: str | None = None) -> dict:
    r = await client.post(
        "/v1/auth/signup",
        json={
            "email": email,
            "password": "correct horse battery staple",
            "org_name": "Acme Corp",
            "org_slug": slug,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.asyncio
async def test_signup_returns_tokens_user_and_org(client) -> None:
    body = await _signup(client, email="ada@example.com")
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["access_expires_in"] > 0
    assert body["user"]["email"] == "ada@example.com"
    assert body["org"]["name"] == "Acme Corp"
    assert body["role"] == "owner"
    # Derived slug matches the name.
    assert body["org"]["slug"].startswith("acme-corp")


@pytest.mark.asyncio
async def test_signup_duplicate_email_is_409(client) -> None:
    await _signup(client, email="grace@example.com")
    r = await client.post(
        "/v1/auth/signup",
        json={
            "email": "grace@example.com",
            "password": "correct horse battery staple",
            "org_name": "Other",
        },
    )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_signup_reserved_slug_is_409(client) -> None:
    r = await client.post(
        "/v1/auth/signup",
        json={
            "email": "ken@example.com",
            "password": "correct horse battery staple",
            "org_name": "api",
            "org_slug": "api",  # reserved
        },
    )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_login_wrong_password_is_401(client) -> None:
    await _signup(client, email="linus@example.com")
    r = await client.post(
        "/v1/auth/login",
        json={"email": "linus@example.com", "password": "wrong-wrong-wrong"},
    )
    assert r.status_code == 401
    # Must NOT reveal whether the email exists.
    assert r.json()["detail"] == "invalid credentials"


@pytest.mark.asyncio
async def test_login_unknown_email_is_401_with_same_body(client) -> None:
    r = await client.post(
        "/v1/auth/login",
        json={"email": "nobody@example.com", "password": "whatever-password"},
    )
    assert r.status_code == 401
    assert r.json()["detail"] == "invalid credentials"


@pytest.mark.asyncio
async def test_full_login_then_me(client) -> None:
    await _signup(client, email="barbara@example.com")
    r = await client.post(
        "/v1/auth/login",
        json={"email": "barbara@example.com", "password": "correct horse battery staple"},
    )
    assert r.status_code == 200
    access = r.json()["access_token"]

    r = await client.get(
        "/v1/me", headers={"Authorization": f"Bearer {access}"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["email"] == "barbara@example.com"
    assert len(body["memberships"]) == 1
    assert body["memberships"][0]["role"] == "owner"


@pytest.mark.asyncio
async def test_me_without_token_is_401(client) -> None:
    r = await client.get("/v1/me")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_refresh_rotates_tokens(client) -> None:
    body = await _signup(client, email="alan@example.com")
    original_refresh = body["refresh_token"]

    r = await client.post(
        "/v1/auth/refresh", json={"refresh_token": original_refresh}
    )
    assert r.status_code == 200
    rotated = r.json()
    assert rotated["access_token"] != body["access_token"]
    assert rotated["refresh_token"] != original_refresh

    # Old refresh token must now be rejected.
    r2 = await client.post(
        "/v1/auth/refresh", json={"refresh_token": original_refresh}
    )
    assert r2.status_code == 401


@pytest.mark.asyncio
async def test_refresh_reuse_revokes_all_sessions(client) -> None:
    """Presenting a revoked refresh token revokes every session for the user.

    After the reuse is detected, the *rotated* refresh token (issued in
    the first ``/refresh`` call) must also be rejected.
    """
    body = await _signup(client, email="ada2@example.com")
    r1 = await client.post(
        "/v1/auth/refresh", json={"refresh_token": body["refresh_token"]}
    )
    assert r1.status_code == 200
    rotated_refresh = r1.json()["refresh_token"]

    # Reuse the *original* token — breach signal.
    r_reuse = await client.post(
        "/v1/auth/refresh", json={"refresh_token": body["refresh_token"]}
    )
    assert r_reuse.status_code == 401

    # The rotated token must now ALSO be rejected (revoke-all fired).
    r_after = await client.post(
        "/v1/auth/refresh", json={"refresh_token": rotated_refresh}
    )
    assert r_after.status_code == 401


@pytest.mark.asyncio
async def test_logout_revokes_current_session(client) -> None:
    body = await _signup(client, email="hopper@example.com")
    access = body["access_token"]
    refresh = body["refresh_token"]

    r = await client.post(
        "/v1/auth/logout", headers={"Authorization": f"Bearer {access}"}
    )
    assert r.status_code == 204

    # The refresh token bound to that session must no longer work.
    r2 = await client.post("/v1/auth/refresh", json={"refresh_token": refresh})
    assert r2.status_code == 401
