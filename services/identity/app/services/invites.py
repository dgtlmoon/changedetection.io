"""Invite lifecycle: create, list, revoke, accept.

This module is the first place in the codebase that mixes tenant-scoped
queries (``with_current_org``) and the admin path (``admin_session``):

* Creating / listing / revoking invites is tenant-scoped — the caller
  must be acting inside one resolved org, and RLS enforces that.
* Accepting an invite is global — the acceptor doesn't necessarily
  have membership in the org yet (that's what the accept creates), so
  we look up the invite via ``admin_session``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Invite, Membership, Org, User
from ..models.membership import MembershipRole
from ..security import tokens

INVITE_TTL = timedelta(days=7)


class InviteError(Exception):
    """Raised for any accept-token failure.

    Route handlers collapse this to a single 400 — no distinguishing
    wrong / expired / already-used.
    """


class InviteEmailMismatch(Exception):
    """Authenticated user's email doesn't match the invite's email."""


# ---------------------------------------------------------------------------
# Admin-side (tenant-scoped with RLS)
# ---------------------------------------------------------------------------


async def create(
    db: AsyncSession,
    *,
    org_id: UUID,
    email: str,
    role: MembershipRole,
    invited_by_user_id: UUID,
) -> tuple[Invite, str]:
    """Create a pending invite; return ``(row, plaintext_token)``.

    ``db`` MUST already have ``app.current_org`` set to ``org_id`` so
    RLS applies.
    """
    if role == MembershipRole.owner:
        # Defence in depth — the pydantic layer should reject first.
        raise ValueError("owner role cannot be granted via invite")

    plaintext, token_hash = tokens.new_refresh_token()
    row = Invite(
        org_id=org_id,
        email=email,
        role=role,
        token_hash=token_hash,
        invited_by_user_id=invited_by_user_id,
        expires_at=datetime.now(timezone.utc) + INVITE_TTL,
    )
    db.add(row)
    await db.flush()
    return row, plaintext


async def list_for_org(db: AsyncSession, *, org_id: UUID) -> list[Invite]:
    """All invites for ``org_id`` (newest first).

    ``with_current_org(org_id)`` on ``db`` makes RLS the safety net;
    the explicit ``where`` is the primary control and the only thing
    protecting us when the DB user happens to have ``BYPASSRLS`` (as
    happens in CI where the test Postgres runs as a superuser).
    """
    result = await db.execute(
        select(Invite)
        .where(Invite.org_id == org_id)
        .order_by(Invite.created_at.desc())
    )
    return list(result.scalars().all())


async def get_by_id(
    db: AsyncSession, *, invite_id: UUID, org_id: UUID
) -> Invite | None:
    result = await db.execute(
        select(Invite).where(Invite.id == invite_id, Invite.org_id == org_id)
    )
    return result.scalar_one_or_none()


async def delete_by_id(
    db: AsyncSession, *, invite_id: UUID, org_id: UUID
) -> bool:
    """Hard-delete. Returns True if a row was deleted, False otherwise.

    RLS means a caller scoped to org A cannot delete an invite belonging
    to org B — the SELECT (triggered by the ORM before DELETE) simply
    doesn't see it. We also filter explicitly by ``org_id`` as the
    primary control.
    """
    row = await get_by_id(db, invite_id=invite_id, org_id=org_id)
    if row is None:
        return False
    await db.delete(row)
    await db.flush()
    return True


# ---------------------------------------------------------------------------
# Acceptance (global; uses admin_session)
# ---------------------------------------------------------------------------


async def find_pending_by_token(
    db: AsyncSession, *, token: str
) -> tuple[Invite, Org] | None:
    """Look up a non-expired, non-accepted invite + its org. Admin path."""
    token_hash = tokens.hash_refresh_token(token)
    result = await db.execute(
        select(Invite, Org)
        .join(Org, Org.id == Invite.org_id)
        .where(Invite.token_hash == token_hash)
    )
    hit = result.first()
    if hit is None:
        return None
    invite, org = hit
    now = datetime.now(timezone.utc)
    if invite.accepted_at is not None or invite.expires_at <= now:
        return None
    if org.deleted_at is not None:
        return None
    return invite, org


async def consume(
    db: AsyncSession,
    *,
    invite: Invite,
    user: User,
) -> Membership:
    """Attach the user to the invite's org and mark the invite accepted.

    Idempotent on re-invite: if a membership already exists for
    ``(org_id, user_id)``, reuse it but still flip ``accepted_at``.

    The caller guarantees the user's email matches the invite — this
    function doesn't re-check.
    """
    now = datetime.now(timezone.utc)

    existing = await db.execute(
        select(Membership).where(
            Membership.org_id == invite.org_id,
            Membership.user_id == user.id,
        )
    )
    membership = existing.scalar_one_or_none()
    if membership is None:
        membership = Membership(
            org_id=invite.org_id,
            user_id=user.id,
            role=invite.role,
            invited_by_user_id=invite.invited_by_user_id,
        )
        db.add(membership)

    invite.accepted_at = now
    await db.flush()
    return membership
