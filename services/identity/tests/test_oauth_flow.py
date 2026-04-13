"""End-to-end OAuth sign-in / sign-up via a FakeProvider.

No real Google / GitHub calls. The FakeProvider returns a
caller-supplied OAuthProfile from ``exchange_code`` so every branch
of the sign-in / sign-up / implicit-link / takeover-guard logic is
exercised.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar
from urllib.parse import urlencode

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.oauth import provider as provider_mod
from app.oauth.provider import OAuthProfile

pytestmark = pytest.mark.db


@dataclass
class FakeProvider:
    """Deterministic test provider. Set ``next_profile`` to control
    what the callback will produce."""

    name: str = "fake"
    next_profile: OAuthProfile | None = None
    last_redirect_uri: str | None = None
    _authorize_host: ClassVar[str] = "https://fake.test/authorize"

    def authorize_url(self, *, state: str, redirect_uri: str) -> str:
        self.last_redirect_uri = redirect_uri
        params = urlencode({"state": state, "redirect_uri": redirect_uri})
        return f"{self._authorize_host}?{params}"

    async def exchange_code(
        self, *, code: str, redirect_uri: str
    ) -> OAuthProfile:
        assert self.next_profile is not None, "test forgot to set next_profile"
        return self.next_profile


@pytest.fixture
def fake_provider(monkeypatch):
    # Reset registry; register our fake.
    provider_mod.reset_registry()
    fake = FakeProvider()
    provider_mod.register(fake)
    yield fake
    provider_mod.reset_registry()


@pytest.fixture
async def client(fake_provider):
    # create_app() calls register_from_settings() which is a no-op if
    # no google/github credentials are set. fake_provider fixture runs
    # its setup before this, so the fake is registered by the time the
    # app is built.
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as c:
        yield c


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_redirects_and_sets_state_cookie(client, fake_provider) -> None:
    r = await client.get(
        "/v1/auth/oauth/fake/start", follow_redirects=False
    )
    assert r.status_code == 307
    assert r.headers["location"].startswith("https://fake.test/authorize")
    assert "state=" in r.headers["location"]
    cookies = r.headers.get_list("set-cookie")
    assert any(c.startswith("oauth_state=") for c in cookies)


@pytest.mark.asyncio
async def test_start_unknown_provider_is_404(client) -> None:
    r = await client.get("/v1/auth/oauth/bogus/start", follow_redirects=False)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# /callback — signup
# ---------------------------------------------------------------------------


async def _start_and_extract_state(client: AsyncClient) -> tuple[str, dict[str, str]]:
    """Hit /start, parse out the state value from the redirect URL.

    Also returns the cookies so we can echo them back on /callback.
    """
    r = await client.get(
        "/v1/auth/oauth/fake/start", follow_redirects=False
    )
    assert r.status_code == 307
    # Extract state from the Location URL.
    from urllib.parse import parse_qs, urlparse

    loc = urlparse(r.headers["location"])
    state = parse_qs(loc.query)["state"][0]

    # httpx AsyncClient preserves cookies across requests automatically,
    # so we don't need to re-attach them.
    return state, {"state": state}


@pytest.mark.asyncio
async def test_signup_via_oauth_creates_new_user(client, fake_provider) -> None:
    fake_provider.next_profile = OAuthProfile(
        provider="fake",
        provider_user_id="fake-1",
        email="new@example.test",
        email_verified=True,
        display_name="New User",
    )

    state, _ = await _start_and_extract_state(client)
    r = await client.get(
        "/v1/auth/oauth/fake/callback",
        params={"code": "c123", "state": state},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["is_new_user"] is True
    assert body["user"]["email"] == "new@example.test"
    assert body["access_token"]
    assert body["refresh_token"]

    # /me with the returned access token confirms the user.
    r_me = await client.get(
        "/v1/me",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert r_me.status_code == 200
    assert r_me.json()["user"]["email"] == "new@example.test"
    assert r_me.json()["memberships"] == []  # SSO-only user, no org yet


@pytest.mark.asyncio
async def test_sign_in_existing_oauth_account(client, fake_provider) -> None:
    # First signup via OAuth.
    fake_provider.next_profile = OAuthProfile(
        provider="fake",
        provider_user_id="fake-2",
        email="again@example.test",
        email_verified=True,
    )
    state, _ = await _start_and_extract_state(client)
    r1 = await client.get(
        "/v1/auth/oauth/fake/callback",
        params={"code": "a", "state": state},
    )
    assert r1.status_code == 200 and r1.json()["is_new_user"] is True

    # Second round should sign the SAME user back in (is_new_user = False).
    fake_provider.next_profile = OAuthProfile(
        provider="fake",
        provider_user_id="fake-2",
        email="again@example.test",
        email_verified=True,
    )
    state2, _ = await _start_and_extract_state(client)
    r2 = await client.get(
        "/v1/auth/oauth/fake/callback",
        params={"code": "b", "state": state2},
    )
    assert r2.status_code == 200
    assert r2.json()["is_new_user"] is False
    assert r2.json()["user"]["email"] == "again@example.test"


# ---------------------------------------------------------------------------
# /callback — implicit link
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_implicit_link_when_email_matches_and_verified(
    client, fake_provider
) -> None:
    # Create a user via password signup.
    r_up = await client.post(
        "/v1/auth/signup",
        json={
            "email": "existing@example.test",
            "password": "correct horse battery staple",
            "org_name": "Ex Co",
        },
    )
    assert r_up.status_code == 201

    # Now OAuth with a verified email that matches.
    fake_provider.next_profile = OAuthProfile(
        provider="fake",
        provider_user_id="fake-3",
        email="existing@example.test",
        email_verified=True,
    )
    state, _ = await _start_and_extract_state(client)
    r = await client.get(
        "/v1/auth/oauth/fake/callback",
        params={"code": "c", "state": state},
    )
    assert r.status_code == 200
    assert r.json()["is_new_user"] is False
    # Same email → same user; they can still log in with their password.


@pytest.mark.asyncio
async def test_unverified_email_collision_is_409(client, fake_provider) -> None:
    # Create a user via password signup.
    await client.post(
        "/v1/auth/signup",
        json={
            "email": "target@example.test",
            "password": "correct horse battery staple",
            "org_name": "Target",
        },
    )

    # Attacker OAuths with the victim's email but NOT verified.
    fake_provider.next_profile = OAuthProfile(
        provider="fake",
        provider_user_id="attacker-99",
        email="target@example.test",
        email_verified=False,
    )
    state, _ = await _start_and_extract_state(client)
    r = await client.get(
        "/v1/auth/oauth/fake/callback",
        params={"code": "d", "state": state},
    )
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# State validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_callback_without_cookie_is_400(client, fake_provider) -> None:
    state, _ = await _start_and_extract_state(client)
    # Clear the cookie jar on the client.
    client.cookies.clear()
    r = await client.get(
        "/v1/auth/oauth/fake/callback",
        params={"code": "c", "state": state},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_callback_state_mismatch_is_400(client, fake_provider) -> None:
    state, _ = await _start_and_extract_state(client)
    # Tamper: last char swap.
    bad = state[:-1] + ("A" if state[-1] != "A" else "B")
    r = await client.get(
        "/v1/auth/oauth/fake/callback",
        params={"code": "c", "state": bad},
    )
    assert r.status_code == 400
