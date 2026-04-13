"""User creation, lookup, and credential verification.

All functions here operate on the global ``users`` table and therefore
use ``admin_session`` (BYPASSRLS). This is deliberate: a user has no
tenant context *before* they authenticate.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import User
from ..security.passwords import hash_password, verify_password
from .errors import EmailAlreadyRegistered, InvalidCredentials


async def find_by_email(session: AsyncSession, email: str) -> User | None:
    """Case-insensitive email lookup (``users.email`` is ``CITEXT``)."""
    result = await session.execute(
        select(User).where(User.email == email, User.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def find_by_id(session: AsyncSession, user_id: UUID) -> User | None:
    result = await session.execute(
        select(User).where(User.id == user_id, User.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def create(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    display_name: str | None = None,
) -> User:
    """Create a new user. Raises :class:`EmailAlreadyRegistered` on duplicate email."""
    existing = await find_by_email(session, email)
    if existing is not None:
        raise EmailAlreadyRegistered()

    user = User(
        email=email,
        password_hash=hash_password(password),
        display_name=display_name,
    )
    session.add(user)
    await session.flush()  # populate user.id without committing
    return user


async def authenticate(
    session: AsyncSession, *, email: str, password: str
) -> User:
    """Return the user if credentials match. Raises on any failure.

    Route handlers MUST map :class:`InvalidCredentials` to a generic
    401 without distinguishing "no such email" from "wrong password" —
    that distinction would enable user-enumeration attacks.
    """
    user = await find_by_email(session, email)
    if user is None:
        # Still hash a dummy password so timing looks identical to the
        # wrong-password path.
        _timing_equalizer(password)
        raise InvalidCredentials()

    if user.password_hash is None:
        # SSO-only user; they must log in through OAuth.
        _timing_equalizer(password)
        raise InvalidCredentials()

    if not verify_password(password, user.password_hash):
        raise InvalidCredentials()

    return user


def _timing_equalizer(password: str) -> None:
    """Spend roughly the same time as a real verify to resist timing
    attacks that try to enumerate registered emails."""
    # A single verify against a throwaway hash keeps the cost shape
    # identical. The hash string is precomputed so we don't pay for
    # hashing an unknown string every call.
    verify_password(password, _SENTINEL_HASH)


# Pre-computed Argon2id hash of the string "sentinel". Recomputed at
# import time so it matches the current hasher parameters.
_SENTINEL_HASH: str = hash_password("sentinel")
