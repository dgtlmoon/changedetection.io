"""FastAPI dependencies for authenticating a request.

Two injectables:

* :func:`get_current_user` — resolves the bearer token on the request to
  the ``User`` row. Returns 401 on any failure.
* :func:`get_current_claims` — same but returns the decoded
  :class:`AccessTokenClaims` without hitting the DB; cheaper when you
  only need ``user_id`` / ``session_id``.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..db import admin_session
from ..models import User
from ..services import users as users_svc
from .tokens import AccessTokenClaims, TokenError, decode_access_token

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(slots=True, frozen=True)
class CurrentUser:
    """Container bundle handed to route handlers."""

    user: User
    claims: AccessTokenClaims

    @property
    def id(self) -> UUID:
        return self.user.id


def _unauthorized(detail: str = "unauthorized") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_claims(
    _request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> AccessTokenClaims:
    if creds is None or creds.scheme.lower() != "bearer":
        raise _unauthorized()
    try:
        return decode_access_token(creds.credentials)
    except TokenError:
        raise _unauthorized() from None


async def get_current_user(
    claims: AccessTokenClaims = Depends(get_current_claims),
) -> CurrentUser:
    async with admin_session() as db:
        user = await users_svc.find_by_id(db, claims.user_id)
    if user is None:
        raise _unauthorized()
    return CurrentUser(user=user, claims=claims)
