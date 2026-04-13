"""Org creation and membership management.

Org creation happens before the user has a tenant context (it *is* the
tenant-creating action), so this module uses ``admin_session``. The
same function also creates the initial owner ``Membership``.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models import Membership, Org, User
from ..models.membership import MembershipRole
from .errors import SlugUnavailable
from .slugs import derive_from_name, is_valid, with_random_suffix

_MAX_DERIVE_ATTEMPTS = 8


async def slug_available(session: AsyncSession, slug: str) -> bool:
    """True if the slug is syntactically valid, not reserved, and not taken."""
    if not is_valid(slug):
        return False
    existing = await session.execute(
        select(Org.id).where(Org.slug == slug, Org.deleted_at.is_(None))
    )
    return existing.scalar_one_or_none() is None


async def _pick_available_slug(
    session: AsyncSession, *, name: str, requested: str | None
) -> str:
    """Return a slug we've verified is free. Raises SlugUnavailable if not.

    If ``requested`` is truthy: single-shot check, no derivation.
    If falsy: derive from ``name``; on collision retry with a random suffix.

    A racing signup could still insert between our check and the INSERT
    in :func:`create_with_owner`. The caller catches that as a
    :class:`SlugUnavailable` from the unique-constraint violation.
    """
    if requested:
        if not await slug_available(session, requested):
            raise SlugUnavailable()
        return requested

    candidate = derive_from_name(name)
    for attempt in range(_MAX_DERIVE_ATTEMPTS):
        if await slug_available(session, candidate):
            return candidate
        candidate = with_random_suffix(derive_from_name(name))
    raise SlugUnavailable()


async def create_with_owner(
    session: AsyncSession,
    *,
    name: str,
    slug: str | None,
    owner: User,
) -> Org:
    """Create an org and its owner membership in one call.

    Pre-checks slug availability; the caller should still be prepared
    for a unique-constraint violation if two signups race (we let that
    bubble up as an IntegrityError from the outer transaction — the
    signup handler converts it to HTTP 409).
    """
    chosen = await _pick_available_slug(session, name=name, requested=slug)

    org = Org(slug=chosen, name=name)
    session.add(org)
    await session.flush()

    membership = Membership(
        org_id=org.id,
        user_id=owner.id,
        role=MembershipRole.owner,
    )
    session.add(membership)
    await session.flush()
    return org


async def memberships_for_user(
    session: AsyncSession, user_id: UUID
) -> list[Membership]:
    """All non-deleted memberships for a user, with the ``Org`` eagerly loaded."""
    result = await session.execute(
        select(Membership)
        .where(Membership.user_id == user_id)
        .options(selectinload(Membership.org))
        # newest first — clients typically show the most-recent org at
        # the top of the switcher
        .order_by(Membership.created_at.desc())
    )
    return list(result.scalars().all())
