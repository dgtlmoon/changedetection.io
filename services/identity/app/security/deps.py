"""FastAPI dependencies for authenticating a request.

Injectables:

* :func:`get_current_user` — resolves the bearer token on the request to
  the ``User`` row. Returns 401 on any failure.
* :func:`get_current_claims` — same but returns the decoded
  :class:`AccessTokenClaims` without hitting the DB.
* :func:`get_current_user_optional` — same as ``get_current_user`` but
  returns ``None`` when no token is present instead of raising.
* :func:`require_membership` — factory. The returned dep asserts the
  caller has at least the given role in the org resolved onto the
  request (via the tenant-resolver middleware). Returns 404 when the
  caller has no membership — never confirms org existence to outsiders.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from ..db import admin_session, with_current_org
from ..models import Membership, User
from ..models.membership import MembershipRole
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


async def get_current_user_optional(
    _request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> CurrentUser | None:
    """Same as :func:`get_current_user` but returns ``None`` when absent."""
    if creds is None or creds.scheme.lower() != "bearer":
        return None
    try:
        claims = decode_access_token(creds.credentials)
    except TokenError:
        return None
    async with admin_session() as db:
        user = await users_svc.find_by_id(db, claims.user_id)
    if user is None:
        return None
    return CurrentUser(user=user, claims=claims)


# ---------------------------------------------------------------------------
# Role-gating
# ---------------------------------------------------------------------------

# Strict ordering: higher number = more privileged. ``require_membership``
# compares with ``>=``.
_ROLE_ORDER: dict[MembershipRole, int] = {
    MembershipRole.viewer: 1,
    MembershipRole.member: 2,
    MembershipRole.admin: 3,
    MembershipRole.owner: 4,
}


def _role_satisfies(actual: MembershipRole, minimum: MembershipRole) -> bool:
    return _ROLE_ORDER[actual] >= _ROLE_ORDER[minimum]


@dataclass(slots=True, frozen=True)
class MembershipContext:
    """Handed to route handlers guarded by :func:`require_membership`."""

    user: CurrentUser
    org_id: UUID
    role: MembershipRole


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="not found",
    )


# ---------------------------------------------------------------------------
# API-key auth
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class CurrentApiKey:
    """Resolved-api-key context handed to route handlers."""

    api_key_id: UUID
    org_id: UUID
    scopes: tuple[str, ...]


async def get_current_api_key(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> CurrentApiKey:
    """Resolve an ``sk_live_*`` bearer to a :class:`CurrentApiKey`.

    Use this on endpoints that are machine-only. For endpoints that
    accept either a JWT or an API key, use :func:`get_current_principal`
    instead.
    """
    from ..db import admin_session
    from ..services import api_keys as api_keys_svc

    if creds is None or creds.scheme.lower() != "bearer":
        raise _unauthorized()
    if not creds.credentials.startswith(api_keys_svc.KEY_BRAND):
        raise _unauthorized()

    async with admin_session() as db:
        pair = await api_keys_svc.resolve(db, plaintext=creds.credentials)
    if pair is None:
        raise _unauthorized()
    api_key, _org = pair
    return CurrentApiKey(
        api_key_id=api_key.id,
        org_id=api_key.org_id,
        scopes=tuple(api_key.scopes or ()),
    )


# ---------------------------------------------------------------------------
# Unified principal (JWT OR API key) — consumed by future Phase-3 endpoints
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class Principal:
    """Discriminated container for either auth type."""

    kind: str  # "user" | "api_key"
    user: CurrentUser | None
    api_key: CurrentApiKey | None

    @property
    def org_id(self) -> UUID | None:
        if self.api_key is not None:
            return self.api_key.org_id
        return None  # JWT tokens don't carry org context


async def get_current_principal(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> Principal:
    """Accept both JWT and API-key bearers. 401 if neither resolves."""
    from ..db import admin_session
    from ..services import api_keys as api_keys_svc

    if creds is None or creds.scheme.lower() != "bearer":
        raise _unauthorized()

    token = creds.credentials
    if token.startswith(api_keys_svc.KEY_BRAND):
        async with admin_session() as db:
            pair = await api_keys_svc.resolve(db, plaintext=token)
        if pair is None:
            raise _unauthorized()
        api_key, _org = pair
        return Principal(
            kind="api_key",
            user=None,
            api_key=CurrentApiKey(
                api_key_id=api_key.id,
                org_id=api_key.org_id,
                scopes=tuple(api_key.scopes or ()),
            ),
        )

    try:
        claims = decode_access_token(token)
    except TokenError:
        raise _unauthorized() from None
    async with admin_session() as db:
        user = await users_svc.find_by_id(db, claims.user_id)
    if user is None:
        raise _unauthorized()
    return Principal(
        kind="user",
        user=CurrentUser(user=user, claims=claims),
        api_key=None,
    )


def require_membership(minimum: MembershipRole):
    """Return a FastAPI dep enforcing ``caller's role >= minimum`` in the
    org resolved onto the request.
    """

    async def _dep(
        request: Request,
        current: CurrentUser = Depends(get_current_user),
    ) -> MembershipContext:
        org_id: UUID | None = getattr(request.state, "org_id", None)
        if org_id is None:
            raise _not_found()

        async with with_current_org(org_id) as db:
            # RLS ensures this query only sees memberships in org_id.
            # The user_id filter narrows to the caller.
            result = await db.execute(
                select(Membership).where(
                    Membership.org_id == org_id,
                    Membership.user_id == current.id,
                )
            )
            membership = result.scalar_one_or_none()

        if membership is None:
            raise _not_found()
        if not _role_satisfies(membership.role, minimum):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="insufficient role",
            )
        return MembershipContext(
            user=current, org_id=org_id, role=membership.role
        )

    return _dep
