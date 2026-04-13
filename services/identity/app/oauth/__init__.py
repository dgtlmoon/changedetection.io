"""OAuth sign-in / sign-up support.

Entry points:

* :class:`OAuthProvider` — protocol concrete providers implement.
* :class:`OAuthProfile` — normalised user profile returned by a
  provider after a successful token exchange.
* :func:`get_registry` — process-wide provider registry; only
  providers with both ``client_id`` and ``client_secret`` configured
  are registered.
"""

from .provider import OAuthProfile, OAuthProvider, ProviderRegistry, get_registry
from .state import (
    decode_state,
    encode_state,
    OAuthState,
    STATE_COOKIE_NAME,
    STATE_TTL_SECONDS,
)

__all__ = [
    "OAuthProfile",
    "OAuthProvider",
    "OAuthState",
    "ProviderRegistry",
    "STATE_COOKIE_NAME",
    "STATE_TTL_SECONDS",
    "decode_state",
    "encode_state",
    "get_registry",
]
