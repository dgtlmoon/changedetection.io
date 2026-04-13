"""Integration tests for password reset (request -> confirm -> session revoke)."""

from __future__ import annotations

import re

import pytest
from httpx import ASGITransport, AsyncClient

from app import email as email_pkg
from app.main import create_app

pytestmark = pytest.mark.db


@pytest.fixture
def console_sender(monkeypatch):
    sender = email_pkg.ConsoleSender()

    def _build() -> email_pkg.EmailSender:
        return sender

    monkeypatch.setattr(email_pkg, "build_sender", _build)
    from app.routes import password_reset as pr_route
    from app.routes import verify_email as ve_route

    monkeypatch.setattr(ve_route, "build_sender", _build)
    monkeypatch.setattr(pr_route, "build_sender", _build)
    return sender


@pytest.fixture
async def client():
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


_TOKEN_RE = re.compile(r"token=([A-Za-z0-9_\-]+)")


async def _signup(client: AsyncClient, email: str) -> dict:
    r = await client.post(
        "/v1/auth/signup",
        json={
            "email": email,
            "password": "correct horse battery staple",
            "org_name": "Acme",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.asyncio
async def test_request_for_known_email_sends_mail(client, console_sender) -> None:
    await _signup(client, email="rose@example.com")
    console_sender.last_message = None

    r = await client.post(
        "/v1/auth/password-reset/request", json={"email": "rose@example.com"}
    )
    assert r.status_code == 204
    assert console_sender.last_message is not None
    assert console_sender.last_message.to == "rose@example.com"


@pytest.mark.asyncio
async def test_request_for_unknown_email_still_204(client, console_sender) -> None:
    console_sender.last_message = None
    r = await client.post(
        "/v1/auth/password-reset/request",
        json={"email": "nobody@example.com"},
    )
    assert r.status_code == 204
    # Must NOT send an email when the user doesn't exist.
    assert console_sender.last_message is None


@pytest.mark.asyncio
async def test_full_reset_flow_revokes_existing_sessions(
    client, console_sender
) -> None:
    body = await _signup(client, email="sam@example.com")
    original_refresh = body["refresh_token"]
    original_access = body["access_token"]
    console_sender.last_message = None

    # Request a reset; grab the token from the sent email.
    await client.post(
        "/v1/auth/password-reset/request", json={"email": "sam@example.com"}
    )
    assert console_sender.last_message is not None
    m = _TOKEN_RE.search(console_sender.last_message.text_body)
    assert m
    token = m.group(1)

    # Confirm — new password, session revoke.
    r = await client.post(
        "/v1/auth/password-reset/confirm",
        json={"token": token, "new_password": "brand new password 123"},
    )
    assert r.status_code == 204

    # Old refresh token must no longer rotate.
    r2 = await client.post(
        "/v1/auth/refresh", json={"refresh_token": original_refresh}
    )
    assert r2.status_code == 401

    # Old access token can still technically verify its signature, but
    # the session it's bound to is gone — logout returns 204 which is
    # idempotent, so that path stays safe. We don't additionally gate
    # access tokens on session state in 2b (that's the Redis revocation
    # set in 2c+).

    # Login with new password must succeed.
    r3 = await client.post(
        "/v1/auth/login",
        json={"email": "sam@example.com", "password": "brand new password 123"},
    )
    assert r3.status_code == 200

    # Old password no longer works.
    r4 = await client.post(
        "/v1/auth/login",
        json={"email": "sam@example.com", "password": "correct horse battery staple"},
    )
    assert r4.status_code == 401


@pytest.mark.asyncio
async def test_reset_confirm_garbage_token_is_400(client) -> None:
    r = await client.post(
        "/v1/auth/password-reset/confirm",
        json={"token": "not-a-real-token-xyz-zzz", "new_password": "abcdefghijkl"},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_reset_confirm_single_use(client, console_sender) -> None:
    await _signup(client, email="turing@example.com")
    console_sender.last_message = None

    await client.post(
        "/v1/auth/password-reset/request",
        json={"email": "turing@example.com"},
    )
    assert console_sender.last_message is not None
    m = _TOKEN_RE.search(console_sender.last_message.text_body)
    assert m
    token = m.group(1)

    r = await client.post(
        "/v1/auth/password-reset/confirm",
        json={"token": token, "new_password": "first new password"},
    )
    assert r.status_code == 204

    # Same token, second try — must be rejected.
    r2 = await client.post(
        "/v1/auth/password-reset/confirm",
        json={"token": token, "new_password": "second new password"},
    )
    assert r2.status_code == 400
