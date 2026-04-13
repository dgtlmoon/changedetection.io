"""Stateless JWT decode.

Identity mints the access tokens; core just verifies them against the
shared ``secret_key``. No DB round-trip in the hot path; that's the
whole point of using JWTs here rather than opaque bearer tokens.

Trade-off: a logged-out session's still-fresh access token remains
valid until expiry (≤ 15 min). That window is acceptable for now and
can be narrowed in Phase 8 with a Redis revocation set if we need it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from jose import JWTError, jwt

from ..config import get_settings

_ACCESS_ALG = "HS256"


@dataclass(slots=True, frozen=True)
class AccessTokenClaims:
    user_id: UUID
    session_id: UUID
    issued_at: datetime
    expires_at: datetime


class TokenError(Exception):
    """Raised for every access-token decode / validation failure."""


def decode_access_token(token: str) -> AccessTokenClaims:
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
