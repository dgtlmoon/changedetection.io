"""End-to-end invites flow: create → email → accept → membership appears in /me.

Also verifies:
- Non-admins cannot invite.
- Admin in org A cannot read or delete invites from org B.
- Invite email mismatch on accept returns 403.
- Owner role cannot be granted via invite (400).
"""

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
    from app.routes import invites as invites_route
    from app.routes import password_reset as pr_route
    from app.routes import verify_email as ve_route

    monkeypatch.setattr(ve_route, "build_sender", _build)
    monkeypatch.setattr(pr_route, "build_sender", _build)
    monkeypatch.setattr(invites_route, "build_sender", _build)
    return sender


@pytest.fixture
async def client():
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


_TOKEN_RE = re.compile(r"token=([A-Za-z0-9_\-]+)")


async def _signup(
    client: AsyncClient, *, email: str, org_name: str, slug: str | None = None
) -> dict:
    r = await client.post(
        "/v1/auth/signup",
        json={
            "email": email,
            "password": "correct horse battery staple",
            "org_name": org_name,
            "org_slug": slug,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_owner_invites_new_user_who_accepts_and_joins(
    client, console_sender
) -> None:
    owner = await _signup(
        client, email="owner@acme.test", org_name="Acme", slug="acme-c1"
    )
    access = owner["access_token"]

    # Owner creates invite for a brand-new email.
    r = await client.post(
        "/v1/orgs/acme-c1/invites",
        json={"email": "bob@example.test", "role": "member"},
        headers={"Authorization": f"Bearer {access}"},
    )
    assert r.status_code == 201, r.text
    invite = r.json()
    assert invite["email"] == "bob@example.test"
    assert invite["role"] == "member"
    assert invite["accepted_at"] is None

    # Listing returns the invite.
    r_list = await client.get(
        "/v1/orgs/acme-c1/invites",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert r_list.status_code == 200
    assert len(r_list.json()["invites"]) == 1

    # Invite email sent — pull token.
    assert console_sender.last_message is not None
    assert console_sender.last_message.to == "bob@example.test"
    m = _TOKEN_RE.search(console_sender.last_message.text_body)
    assert m
    token = m.group(1)

    # Bob accepts, creating his user.
    r_accept = await client.post(
        "/v1/auth/invites/accept",
        json={
            "token": token,
            "password": "bob-a-strong-password",
            "display_name": "Bob",
        },
    )
    assert r_accept.status_code == 200, r_accept.text
    accepted = r_accept.json()
    assert accepted["role"] == "member"
    assert accepted["user"]["email"] == "bob@example.test"
    assert accepted["org"]["slug"] == "acme-c1"
    bob_access = accepted["access_token"]

    # /me reflects the new membership.
    r_me = await client.get(
        "/v1/me", headers={"Authorization": f"Bearer {bob_access}"}
    )
    assert r_me.status_code == 200
    slugs = {m["org"]["slug"] for m in r_me.json()["memberships"]}
    assert slugs == {"acme-c1"}


@pytest.mark.asyncio
async def test_existing_user_accepts_invite_with_password(
    client, console_sender
) -> None:
    # Owner of org 1.
    await _signup(
        client, email="o@beta.test", org_name="Beta", slug="beta-c1"
    )
    owner_login = await client.post(
        "/v1/auth/login",
        json={"email": "o@beta.test", "password": "correct horse battery staple"},
    )
    assert owner_login.status_code == 200
    access = owner_login.json()["access_token"]

    # A DIFFERENT user exists in a different org already.
    await _signup(
        client, email="carol@example.test", org_name="Carol's Co", slug="carol-co"
    )

    # Owner invites Carol to beta-c1.
    r = await client.post(
        "/v1/orgs/beta-c1/invites",
        json={"email": "carol@example.test", "role": "admin"},
        headers={"Authorization": f"Bearer {access}"},
    )
    assert r.status_code == 201
    assert console_sender.last_message is not None
    token = _TOKEN_RE.search(console_sender.last_message.text_body).group(1)

    # Carol accepts with her existing password.
    r_accept = await client.post(
        "/v1/auth/invites/accept",
        json={
            "token": token,
            "password": "correct horse battery staple",
        },
    )
    assert r_accept.status_code == 200
    body = r_accept.json()
    assert body["role"] == "admin"

    # Carol's /me now shows both orgs.
    r_me = await client.get(
        "/v1/me",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    slugs = {m["org"]["slug"] for m in r_me.json()["memberships"]}
    assert slugs == {"beta-c1", "carol-co"}


@pytest.mark.asyncio
async def test_authenticated_accept_by_matching_user(
    client, console_sender
) -> None:
    # Owner creates org and invites existing user.
    await _signup(client, email="o2@gamma.test", org_name="Gamma", slug="gamma-c1")
    owner_login = await client.post(
        "/v1/auth/login",
        json={"email": "o2@gamma.test", "password": "correct horse battery staple"},
    )
    access_owner = owner_login.json()["access_token"]

    dan = await _signup(
        client, email="dan@example.test", org_name="Dan Co", slug="dan-co-c1"
    )
    dan_access = dan["access_token"]

    await client.post(
        "/v1/orgs/gamma-c1/invites",
        json={"email": "dan@example.test", "role": "member"},
        headers={"Authorization": f"Bearer {access_owner}"},
    )
    token = _TOKEN_RE.search(console_sender.last_message.text_body).group(1)

    # Dan is logged in — accept WITHOUT password.
    r = await client.post(
        "/v1/auth/invites/accept",
        json={"token": token},
        headers={"Authorization": f"Bearer {dan_access}"},
    )
    assert r.status_code == 200
    assert r.json()["role"] == "member"


# ---------------------------------------------------------------------------
# Authorization + cross-tenant isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_admin_cannot_invite(client, console_sender) -> None:
    # Owner creates org + invites Erin as a viewer.
    owner = await _signup(
        client, email="ow@delta.test", org_name="Delta", slug="delta-c1"
    )
    await client.post(
        "/v1/orgs/delta-c1/invites",
        json={"email": "erin@example.test", "role": "viewer"},
        headers={"Authorization": f"Bearer {owner['access_token']}"},
    )
    token = _TOKEN_RE.search(console_sender.last_message.text_body).group(1)

    # Erin accepts.
    erin = await client.post(
        "/v1/auth/invites/accept",
        json={"token": token, "password": "erin-strong-password-1"},
    )
    erin_access = erin.json()["access_token"]

    # Erin (viewer) tries to invite someone. Must 403.
    r = await client.post(
        "/v1/orgs/delta-c1/invites",
        json={"email": "someone@example.test", "role": "member"},
        headers={"Authorization": f"Bearer {erin_access}"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_non_member_sees_404_not_403(client) -> None:
    # Two separate orgs/users.
    _ = await _signup(
        client, email="a@orgone.test", org_name="OrgOne", slug="org-one-c1"
    )
    b = await _signup(
        client, email="b@orgtwo.test", org_name="OrgTwo", slug="org-two-c1"
    )

    # B (not a member of org-one-c1) probes the invite endpoint.
    r = await client.get(
        "/v1/orgs/org-one-c1/invites",
        headers={"Authorization": f"Bearer {b['access_token']}"},
    )
    # Must NOT reveal that the org exists — 404, not 403.
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_cross_tenant_delete_returns_404(client, console_sender) -> None:
    # Admin of org-x creates an invite.
    x = await _signup(
        client, email="ax@x.test", org_name="X Org", slug="x-org-c1"
    )
    await client.post(
        "/v1/orgs/x-org-c1/invites",
        json={"email": "target@example.test", "role": "member"},
        headers={"Authorization": f"Bearer {x['access_token']}"},
    )
    # Grab the invite id from the list.
    r_list = await client.get(
        "/v1/orgs/x-org-c1/invites",
        headers={"Authorization": f"Bearer {x['access_token']}"},
    )
    invite_id = r_list.json()["invites"][0]["id"]

    # Admin of DIFFERENT org tries to delete by id, addressing org-x-c1.
    y = await _signup(
        client, email="ay@y.test", org_name="Y Org", slug="y-org-c1"
    )
    r = await client.delete(
        f"/v1/orgs/x-org-c1/invites/{invite_id}",
        headers={"Authorization": f"Bearer {y['access_token']}"},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_owner_role_via_invite_is_400(client) -> None:
    owner = await _signup(
        client, email="ow2@zeta.test", org_name="Zeta", slug="zeta-c1"
    )
    r = await client.post(
        "/v1/orgs/zeta-c1/invites",
        json={"email": "zed@example.test", "role": "owner"},
        headers={"Authorization": f"Bearer {owner['access_token']}"},
    )
    # Pydantic rejects at 422, route check would 400; either is fine.
    assert r.status_code in (400, 422)


@pytest.mark.asyncio
async def test_accept_with_wrong_auth_user_is_403(client, console_sender) -> None:
    owner = await _signup(
        client, email="ow3@eta.test", org_name="Eta", slug="eta-c1"
    )
    await client.post(
        "/v1/orgs/eta-c1/invites",
        json={"email": "intended@example.test", "role": "member"},
        headers={"Authorization": f"Bearer {owner['access_token']}"},
    )
    token = _TOKEN_RE.search(console_sender.last_message.text_body).group(1)

    # An existing, unrelated user logged in — NOT the invitee.
    other = await _signup(
        client, email="other@example.test", org_name="Other Co", slug="other-co-c1"
    )
    r = await client.post(
        "/v1/auth/invites/accept",
        json={"token": token},
        headers={"Authorization": f"Bearer {other['access_token']}"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_garbage_token_is_400(client) -> None:
    r = await client.post(
        "/v1/auth/invites/accept",
        json={"token": "nope-not-a-real-token-xyz", "password": "abcdefghijkl"},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_invite_revoke_removes_it_from_listing(client, console_sender) -> None:
    owner = await _signup(
        client, email="ow4@theta.test", org_name="Theta", slug="theta-c1"
    )
    r_create = await client.post(
        "/v1/orgs/theta-c1/invites",
        json={"email": "tbd@example.test", "role": "viewer"},
        headers={"Authorization": f"Bearer {owner['access_token']}"},
    )
    invite_id = r_create.json()["id"]

    r_del = await client.delete(
        f"/v1/orgs/theta-c1/invites/{invite_id}",
        headers={"Authorization": f"Bearer {owner['access_token']}"},
    )
    assert r_del.status_code == 204

    r_list = await client.get(
        "/v1/orgs/theta-c1/invites",
        headers={"Authorization": f"Bearer {owner['access_token']}"},
    )
    assert r_list.json()["invites"] == []

    # The revoked token cannot be redeemed.
    token = _TOKEN_RE.search(console_sender.last_message.text_body).group(1)
    r_accept = await client.post(
        "/v1/auth/invites/accept",
        json={"token": token, "password": "irrelevant-abcdef"},
    )
    assert r_accept.status_code == 400
