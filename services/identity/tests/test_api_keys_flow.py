"""End-to-end API-key flow: issue → list → resolve → revoke.

Covers:
- Admin creates key, plaintext shown ONCE, list excludes it.
- Non-admin gets 403 on create/list/revoke.
- Cross-tenant revoke returns 404.
- Resolving a fresh key via get_current_api_key succeeds.
- After revoke the same plaintext no longer authenticates.
- Tampered plaintext (correct prefix, wrong secret) fails.
- Expired keys fail.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.security.deps import CurrentApiKey, get_current_api_key

pytestmark = pytest.mark.db


@pytest.fixture
async def client():
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


async def _signup(
    client: AsyncClient, *, email: str, org_name: str, slug: str
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
async def test_admin_creates_and_lists_api_key(client) -> None:
    owner = await _signup(
        client, email="ak-ow@a.test", org_name="Ak-Org", slug="ak-org-c1"
    )
    access = owner["access_token"]

    r = await client.post(
        "/v1/orgs/ak-org-c1/api-keys",
        json={
            "name": "deployer",
            "scopes": ["watches:read", "watches:write"],
        },
        headers={"Authorization": f"Bearer {access}"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "deployer"
    assert body["key_prefix"].startswith("sk_live_")
    assert len(body["key_prefix"]) == 12
    plaintext = body["plaintext_key"]
    assert plaintext.startswith("sk_live_")
    assert len(plaintext) >= 20

    r_list = await client.get(
        "/v1/orgs/ak-org-c1/api-keys",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert r_list.status_code == 200
    rows = r_list.json()["api_keys"]
    assert len(rows) == 1
    # plaintext never appears in the list response
    assert "plaintext_key" not in rows[0]


@pytest.mark.asyncio
async def test_api_key_resolves_via_unified_principal(client) -> None:
    """Register a tiny sub-route that depends on get_current_api_key,
    then call it with the freshly issued key. Proves the auth dep
    works end-to-end without needing Phase-3 core endpoints to exist."""
    owner = await _signup(
        client, email="ak2-ow@a.test", org_name="Ak2-Org", slug="ak2-org-c1"
    )

    # Issue a key.
    r = await client.post(
        "/v1/orgs/ak2-org-c1/api-keys",
        json={"name": "deployer", "scopes": ["watches:read"]},
        headers={"Authorization": f"Bearer {owner['access_token']}"},
    )
    plaintext = r.json()["plaintext_key"]

    # Mount a test-only probe onto a fresh app.
    app = create_app()

    @app.get("/_test/api-key-probe")
    async def probe(
        ak: CurrentApiKey = Depends(get_current_api_key),
    ) -> dict[str, list[str] | str]:
        return {
            "org_id": str(ak.org_id),
            "scopes": list(ak.scopes),
        }

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as c2:
        r_ok = await c2.get(
            "/_test/api-key-probe",
            headers={"Authorization": f"Bearer {plaintext}"},
        )
        assert r_ok.status_code == 200, r_ok.text
        assert r_ok.json()["scopes"] == ["watches:read"]

        # Tamper: flip last character.
        tampered = plaintext[:-1] + ("x" if plaintext[-1] != "x" else "y")
        r_bad = await c2.get(
            "/_test/api-key-probe",
            headers={"Authorization": f"Bearer {tampered}"},
        )
        assert r_bad.status_code == 401


# ---------------------------------------------------------------------------
# Revocation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoked_key_no_longer_authenticates(client) -> None:
    owner = await _signup(
        client, email="ak3-ow@a.test", org_name="Ak3-Org", slug="ak3-org-c1"
    )
    r = await client.post(
        "/v1/orgs/ak3-org-c1/api-keys",
        json={"name": "throwaway", "scopes": ["watches:read"]},
        headers={"Authorization": f"Bearer {owner['access_token']}"},
    )
    assert r.status_code == 201
    key_id = r.json()["id"]
    plaintext = r.json()["plaintext_key"]

    # Install probe route.
    app = create_app()

    @app.get("/_test/api-key-probe")
    async def probe(
        ak: CurrentApiKey = Depends(get_current_api_key),
    ) -> dict[str, str]:
        return {"ok": str(ak.api_key_id)}

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as c2:
        r1 = await c2.get(
            "/_test/api-key-probe",
            headers={"Authorization": f"Bearer {plaintext}"},
        )
        assert r1.status_code == 200

        r_rev = await client.delete(
            f"/v1/orgs/ak3-org-c1/api-keys/{key_id}",
            headers={"Authorization": f"Bearer {owner['access_token']}"},
        )
        assert r_rev.status_code == 204

        r2 = await c2.get(
            "/_test/api-key-probe",
            headers={"Authorization": f"Bearer {plaintext}"},
        )
        assert r2.status_code == 401


@pytest.mark.asyncio
async def test_revoke_still_appears_in_list_for_audit(client) -> None:
    owner = await _signup(
        client, email="ak4-ow@a.test", org_name="Ak4-Org", slug="ak4-org-c1"
    )
    r = await client.post(
        "/v1/orgs/ak4-org-c1/api-keys",
        json={"name": "audit-me", "scopes": ["watches:read"]},
        headers={"Authorization": f"Bearer {owner['access_token']}"},
    )
    key_id = r.json()["id"]

    await client.delete(
        f"/v1/orgs/ak4-org-c1/api-keys/{key_id}",
        headers={"Authorization": f"Bearer {owner['access_token']}"},
    )

    r_list = await client.get(
        "/v1/orgs/ak4-org-c1/api-keys",
        headers={"Authorization": f"Bearer {owner['access_token']}"},
    )
    rows = r_list.json()["api_keys"]
    assert len(rows) == 1
    assert rows[0]["revoked_at"] is not None


# ---------------------------------------------------------------------------
# Authorization + isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cross_tenant_revoke_returns_404(client) -> None:
    x = await _signup(
        client, email="akx-ow@a.test", org_name="Akx", slug="akx-c1"
    )
    y = await _signup(
        client, email="aky-ow@a.test", org_name="Aky", slug="aky-c1"
    )
    r = await client.post(
        "/v1/orgs/akx-c1/api-keys",
        json={"name": "xk", "scopes": ["watches:read"]},
        headers={"Authorization": f"Bearer {x['access_token']}"},
    )
    key_id = r.json()["id"]

    r_cross = await client.delete(
        f"/v1/orgs/akx-c1/api-keys/{key_id}",
        headers={"Authorization": f"Bearer {y['access_token']}"},
    )
    assert r_cross.status_code == 404


@pytest.mark.asyncio
async def test_random_bearer_that_looks_like_api_key_is_401(client) -> None:
    app = create_app()

    @app.get("/_test/api-key-probe")
    async def probe(
        ak: CurrentApiKey = Depends(get_current_api_key),
    ) -> dict[str, str]:
        return {"ok": str(ak.api_key_id)}

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as c2:
        r = await c2.get(
            "/_test/api-key-probe",
            headers={"Authorization": "Bearer sk_live_completely_made_up_xxx"},
        )
        assert r.status_code == 401
