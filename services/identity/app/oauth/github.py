"""GitHub OAuth provider.

Docs: https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps

GitHub's main profile endpoint only returns the *public* email. We must
hit ``/user/emails`` (which requires the ``user:email`` scope) to find
the primary + verified address.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from .provider import OAuthProfile, OAuthProvider

_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
_TOKEN_URL = "https://github.com/login/oauth/access_token"
_USER_URL = "https://api.github.com/user"
_EMAILS_URL = "https://api.github.com/user/emails"


@dataclass(slots=True)
class GitHubProvider(OAuthProvider):
    client_id: str
    client_secret: str
    name: str = "github"
    http_client: httpx.AsyncClient | None = None

    def authorize_url(self, *, state: str, redirect_uri: str) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "scope": "read:user user:email",
            "allow_signup": "true",
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
                },
                headers={"Accept": "application/json"},
            )
            token_resp.raise_for_status()
            access_token = token_resp.json()["access_token"]
            auth_headers = {
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }

            user_resp = await client.get(_USER_URL, headers=auth_headers)
            user_resp.raise_for_status()
            user = user_resp.json()

            emails_resp = await client.get(_EMAILS_URL, headers=auth_headers)
            emails_resp.raise_for_status()
            emails = emails_resp.json()
        finally:
            if self.http_client is None:
                await client.aclose()

        # Pick the primary verified email; fall back to primary;
        # fall back to anything verified; fall back to user["email"].
        primary = next(
            (e for e in emails if e.get("primary") and e.get("verified")),
            None,
        ) or next(
            (e for e in emails if e.get("primary")), None
        ) or next(
            (e for e in emails if e.get("verified")), None
        )
        email = (primary or {}).get("email") or user.get("email")
        if not email:
            # Shouldn't happen with read:user + user:email, but handle.
            raise ValueError("github provider did not return an email")
        verified = bool(primary and primary.get("verified"))

        return OAuthProfile(
            provider=self.name,
            provider_user_id=str(user["id"]),
            email=email,
            email_verified=verified,
            display_name=user.get("name") or user.get("login"),
            avatar_url=user.get("avatar_url"),
        )
