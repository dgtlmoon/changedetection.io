"""OAuth provider protocol + registry.

Providers implement two methods:

* :meth:`authorize_url` — returns the URL to redirect the browser to
  (the front-channel).
* :meth:`exchange_code` — the back-channel: swap ``code`` for access
  token and fetch the normalised :class:`OAuthProfile`.

The registry is a module-level dict keyed by the provider name (the
same string that appears in the ``/v1/auth/oauth/{provider}/…`` URLs).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True, frozen=True)
class OAuthProfile:
    """Normalised view of the provider's profile response."""

    provider: str
    provider_user_id: str
    email: str
    email_verified: bool
    display_name: str | None = None
    avatar_url: str | None = None


class OAuthProvider(Protocol):
    name: str

    def authorize_url(self, *, state: str, redirect_uri: str) -> str: ...

    async def exchange_code(
        self, *, code: str, redirect_uri: str
    ) -> OAuthProfile: ...


ProviderRegistry = dict[str, OAuthProvider]

_registry: ProviderRegistry = {}


def register(provider: OAuthProvider) -> None:
    _registry[provider.name] = provider


def unregister(name: str) -> None:
    _registry.pop(name, None)


def get_registry() -> ProviderRegistry:
    return _registry


def reset_registry() -> None:
    """Clear every registered provider. Used only from tests."""
    _registry.clear()
