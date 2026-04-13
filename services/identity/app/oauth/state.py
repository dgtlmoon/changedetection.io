"""Signed OAuth state cookie.

The browser starts at ``/v1/auth/oauth/{p}/start``. We:

1. Generate a random 32-byte nonce.
2. Pack `{nonce, timestamp, redirect_to}` as JSON.
3. HMAC-SHA256 sign with ``settings.secret_key``.
4. Set the cookie ``oauth_state`` (HttpOnly, SameSite=Lax, Secure in
   prod) to the signed payload.
5. Redirect the browser to the provider with ``state`` = the same
   signed payload in the URL.

On callback, we compare cookie vs query-string state by constant-time
equality, then verify signature + freshness.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass

from ..config import get_settings

STATE_COOKIE_NAME = "oauth_state"
STATE_TTL_SECONDS = 600  # 10 minutes


class InvalidStateError(Exception):
    """Raised for every decode failure. Route handlers collapse to 400."""


@dataclass(slots=True, frozen=True)
class OAuthState:
    nonce: str
    issued_at: int
    redirect_to: str | None = None


def _sign(payload: bytes, key: bytes) -> bytes:
    return hmac.new(key, payload, hashlib.sha256).digest()


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _b64d(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def encode_state(*, redirect_to: str | None = None) -> str:
    """Mint a fresh signed state string."""
    nonce = secrets.token_urlsafe(24)
    payload = {
        "nonce": nonce,
        "iat": int(time.time()),
        "redirect_to": redirect_to,
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    key = get_settings().secret_key.encode("utf-8")
    sig = _sign(raw, key)
    return f"{_b64e(raw)}.{_b64e(sig)}"


def decode_state(token: str) -> OAuthState:
    """Verify signature + freshness. Raises :class:`InvalidStateError`."""
    try:
        raw_b64, sig_b64 = token.split(".", 1)
        raw = _b64d(raw_b64)
        sig = _b64d(sig_b64)
    except Exception as exc:  # noqa: BLE001 — any parse error = invalid
        raise InvalidStateError("malformed state") from exc

    key = get_settings().secret_key.encode("utf-8")
    expected = _sign(raw, key)
    if not hmac.compare_digest(sig, expected):
        raise InvalidStateError("bad signature")

    try:
        payload = json.loads(raw.decode("utf-8"))
        iat = int(payload["iat"])
        nonce = str(payload["nonce"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise InvalidStateError("malformed payload") from exc

    if time.time() - iat > STATE_TTL_SECONDS:
        raise InvalidStateError("state expired")

    return OAuthState(
        nonce=nonce,
        issued_at=iat,
        redirect_to=payload.get("redirect_to"),
    )


def states_match(cookie_value: str, query_value: str) -> bool:
    """Constant-time equality check between the cookie and query values."""
    return hmac.compare_digest(cookie_value, query_value)
