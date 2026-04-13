"""Google OAuth 2.0 provider.

Docs: https://developers.google.com/identity/protocols/oauth2/openid-connect

We request only the minimum scopes needed to identify the user:
``openid email profile``.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from .provider import OAuthProfile, OAuthProvider

_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


@dataclass(slots=True)
class GoogleProvider(OAuthProvider):
    client_id: str
    client_secret: str
    name: str = "google"
    http_client: httpx.AsyncClient | None = None

    def authorize_url(self, *, state: str, redirect_uri: str) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "access_type": "offline",
            "prompt": "select_account",
        }
        return f"{_AUTHORIZE_URL}?{urlencode(params)}"

    async def exchange_code(
        self, *, code: str, redirect_uri: str
    ) -> OAuthProfile:
        client = self.http_client or httpx.AsyncClient(timeout=httpx.Timeout(10.0))
        try:
            token_resp = await client.post(
                _TOKEN_URL,
                data={
                    "code": code,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
                headers={"Accept": "application/json"},
            )
            token_resp.raise_for_status()
            access_token = token_resp.json()["access_token"]

            profile_resp = await client.get(
                _USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            profile_resp.raise_for_status()
            profile = profile_resp.json()
        finally:
            if self.http_client is None:
                await client.aclose()

        return OAuthProfile(
            provider=self.name,
            provider_user_id=str(profile["sub"]),
            email=profile["email"],
            # Google always returns email_verified for Google-managed
            # accounts; treat missing as unverified.
            email_verified=bool(profile.get("email_verified", False)),
            display_name=profile.get("name"),
            avatar_url=profile.get("picture"),
        )
