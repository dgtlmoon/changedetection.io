"""Access and refresh token issuance + verification.

Two tokens, two lifetimes, two storage models:

* **Access** — 15-minute JWT (HS256). Stateless. Signed with
  ``settings.secret_key``. Claims: ``sub`` (user id),
  ``sid`` (session id), ``iat``, ``exp``, ``type="access"``.

* **Refresh** — 30-day opaque 32-byte random string, urlsafe-base64
  encoded. Stored as ``sha256(token)`` in ``sessions.refresh_token_hash``
  so a DB dump cannot be replayed back into live sessions.

Refresh rotation: every use of a refresh token mints a new one and
marks the old session row ``revoked_at``. Replay of a revoked token is
a breach signal — the caller should revoke every session for that user.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from jose import JWTError, jwt

from ..config import get_settings

ACCESS_TOKEN_TTL = timedelta(minutes=15)
REFRESH_TOKEN_TTL = timedelta(days=30)
_ACCESS_ALG = "HS256"


@dataclass(slots=True, frozen=True)
class AccessTokenClaims:
    user_id: UUID
    session_id: UUID
    issued_at: datetime
    expires_at: datetime


class TokenError(Exception):
    """Raised for any access-token decode / validation failure."""


def issue_access_token(*, user_id: UUID, session_id: UUID) -> tuple[str, int]:
    """Return ``(jwt, expires_in_seconds)``."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    exp = now + ACCESS_TOKEN_TTL
    claims = {
        "sub": str(user_id),
        "sid": str(session_id),
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "type": "access",
    }
    token = jwt.encode(claims, settings.secret_key, algorithm=_ACCESS_ALG)
    return token, int(ACCESS_TOKEN_TTL.total_seconds())


def decode_access_token(token: str) -> AccessTokenClaims:
    """Verify + decode an access token. Raises :class:`TokenError` on failure.

    We swallow the specific jose error types and rethrow a single typed
    exception so route handlers don't accidentally leak JWT internals in
    error responses.
    """
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[_ACCESS_ALG])
    except JWTError as exc:
        raise TokenError(str(exc)) from exc

    if payload.get("type") != "access":
        raise TokenError("wrong token type")

    try:
        return AccessTokenClaims(
            user_id=UUID(payload["sub"]),
            session_id=UUID(payload["sid"]),
            issued_at=datetime.fromtimestamp(payload["iat"], tz=timezone.utc),
            expires_at=datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
        )
    except (KeyError, ValueError) as exc:
        raise TokenError("malformed claims") from exc


# ---------------------------------------------------------------------------
# Refresh tokens — opaque random strings, hashed at rest.
# ---------------------------------------------------------------------------

_REFRESH_BYTES = 32


def new_refresh_token() -> tuple[str, bytes]:
    """Return ``(plaintext, sha256_hash_bytes)``.

    The plaintext is returned to the client exactly once. Only the hash
    is persisted.
    """
    plaintext = secrets.token_urlsafe(_REFRESH_BYTES)
    return plaintext, hash_refresh_token(plaintext)


def hash_refresh_token(plaintext: str) -> bytes:
    """Deterministic sha256 hash used for session-row lookup."""
    return hashlib.sha256(plaintext.encode("utf-8")).digest()


def refresh_expiry() -> datetime:
    """Wall-clock expiry for a newly minted refresh token."""
    return datetime.now(timezone.utc) + REFRESH_TOKEN_TTL
