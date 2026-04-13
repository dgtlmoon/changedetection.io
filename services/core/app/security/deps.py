"""FastAPI auth dependencies.

Unified principal model matches identity's Phase-2d design:

* JWT access token → :class:`UserPrincipal` (user_id + session_id).
* ``sk_live_*`` API key → :class:`ApiKeyPrincipal` (api_key_id + org_id + scopes).

Either is acceptable on every tenant-scoped route. Role- or
scope-based gating is layered on top via :func:`require_membership`
and :func:`require_scope`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..db import admin_session
from .identity_reads import ResolvedApiKey, get_membership_role, resolve_api_key
from .tokens import TokenError, decode_access_token

bearer_scheme = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# Principals
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class UserPrincipal:
    user_id: UUID
    session_id: UUID


@dataclass(slots=True, frozen=True)
class ApiKeyPrincipal:
    api_key_id: UUID
    org_id: UUID
    scopes: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class Principal:
    kind: Literal["user", "api_key"]
    user: UserPrincipal | None
    api_key: ApiKeyPrincipal | None

    @property
    def api_key_org_id(self) -> UUID | None:
        return self.api_key.org_id if self.api_key is not None else None


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="unauthorized",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="not found"
    )


async def get_current_principal(
    _request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> Principal:
    if creds is None or creds.scheme.lower() != "bearer":
        raise _unauthorized()

    token = creds.credentials

    # --- API-key path ------------------------------------------------------
    if token.startswith("sk_live_"):
        async with admin_session() as db:
            resolved: ResolvedApiKey | None = await resolve_api_key(
                db, plaintext=token
            )
        if resolved is None:
            raise _unauthorized()
        return Principal(
            kind="api_key",
            user=None,
            api_key=ApiKeyPrincipal(
                api_key_id=resolved.api_key_id,
                org_id=resolved.org_id,
                scopes=resolved.scopes,
            ),
        )

    # --- JWT path ----------------------------------------------------------
    try:
        claims = decode_access_token(token)
    except TokenError:
        raise _unauthorized() from None
    return Principal(
        kind="user",
        user=UserPrincipal(
            user_id=claims.user_id, session_id=claims.session_id
        ),
        api_key=None,
    )


# ---------------------------------------------------------------------------
# Role-gating (for user principals) + scope-gating (for api-key principals)
# ---------------------------------------------------------------------------

_ROLE_ORDER: dict[str, int] = {
    "viewer": 1,
    "member": 2,
    "admin": 3,
    "owner": 4,
}


def _role_satisfies(actual: str, minimum: str) -> bool:
    return _ROLE_ORDER.get(actual, 0) >= _ROLE_ORDER[minimum]


@dataclass(slots=True, frozen=True)
class TenantContext:
    """Handed to route handlers. Uniform shape whether the caller is a
    user or an API key."""

    principal: Principal
    org_id: UUID
    # For user principals the resolved role. For API-key principals
    # we synthesise the role from scopes: ``admin`` scope → admin,
    # ``watches:write`` → member, ``watches:read`` only → viewer.
    role: str


def _role_from_scopes(scopes: tuple[str, ...]) -> str:
    s = set(scopes)
    if "admin" in s:
        return "admin"
    if "watches:write" in s:
        return "member"
    if "watches:read" in s:
        return "viewer"
    return "none"


def require_membership(minimum: str):
    """Enforce ``caller's role >= minimum`` in the resolved org.

    For user principals: looks up the membership row. For API-key
    principals: the key's org_id MUST match the resolved org; the
    role is synthesised from scopes. Returns 404 when the caller has
    no claim to the org — never confirms existence to outsiders.
    """
    assert minimum in _ROLE_ORDER, f"unknown role {minimum!r}"

    async def _dep(
        request: Request,
        principal: Principal = Depends(get_current_principal),
    ) -> TenantContext:
        org_id: UUID | None = getattr(request.state, "org_id", None)
        if org_id is None:
            raise _not_found()

        if principal.kind == "user":
            assert principal.user is not None
            async with admin_session() as db:
                role = await get_membership_role(
                    db, org_id=org_id, user_id=principal.user.user_id
                )
            if role is None:
                raise _not_found()
            if not _role_satisfies(role, minimum):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="insufficient role",
                )
            return TenantContext(principal=principal, org_id=org_id, role=role)

        # API key path.
        assert principal.api_key is not None
        if principal.api_key.org_id != org_id:
            # The key belongs to a different org — don't leak which.
            raise _not_found()
        synth = _role_from_scopes(principal.api_key.scopes)
        if not _role_satisfies(synth, minimum):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="insufficient scope",
            )
        return TenantContext(principal=principal, org_id=org_id, role=synth)

    return _dep
