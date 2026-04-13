"""Integration tests for email verification (signup -> request -> confirm)."""

from __future__ import annotations

import re

import pytest
from httpx import ASGITransport, AsyncClient

from app import email as email_pkg
from app.main import create_app

pytestmark = pytest.mark.db


@pytest.fixture
def console_sender(monkeypatch):
    """Pin the email backend to an in-memory Console sender we can read."""
    sender = email_pkg.ConsoleSender()

    def _build() -> email_pkg.EmailSender:
        return sender

    monkeypatch.setattr(email_pkg, "build_sender", _build)
    # Also patch the re-exports in the route modules (they did
    # ``from ..email import build_sender``).
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
async def test_verify_request_sends_email(client, console_sender) -> None:
    body = await _signup(client, email="eva@example.com")
    access = body["access_token"]

    r = await client.post(
        "/v1/auth/verify-email/request",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert r.status_code == 204

    # Let the BackgroundTask finish. In Starlette, background tasks run
    # *after* the response body is written on the same task, so awaiting
    # the response is enough.
    assert console_sender.last_message is not None
    assert console_sender.last_message.to == "eva@example.com"
    assert "Verify" in console_sender.last_message.subject
    m = _TOKEN_RE.search(console_sender.last_message.text_body)
    assert m is not None, "no token in email body"


@pytest.mark.asyncio
async def test_verify_confirm_marks_user_verified(client, console_sender) -> None:
    body = await _signup(client, email="frida@example.com")
    access = body["access_token"]

    await client.post(
        "/v1/auth/verify-email/request",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert console_sender.last_message is not None
    m = _TOKEN_RE.search(console_sender.last_message.text_body)
    assert m
    token = m.group(1)

    r = await client.post(
        "/v1/auth/verify-email/confirm", json={"token": token}
    )
    assert r.status_code == 200
    assert r.json()["verified_at"]

    # Second confirm with the same token must 400 (single-use).
    r2 = await client.post(
        "/v1/auth/verify-email/confirm", json={"token": token}
    )
    assert r2.status_code == 400


@pytest.mark.asyncio
async def test_verify_confirm_garbage_token_is_400(client) -> None:
    r = await client.post(
        "/v1/auth/verify-email/confirm",
        json={"token": "not-a-real-token-at-all-xyz"},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_request_without_auth_is_401(client) -> None:
    r = await client.post("/v1/auth/verify-email/request")
    assert r.status_code == 401
