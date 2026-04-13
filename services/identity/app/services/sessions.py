"""Session + refresh-token management.

A session is a server-side record of "this user is logged in from this
device". It holds the hashed refresh token and the metadata we need for
revocation + breach detection.

Rotation rules (see ``docs/saas/phase-02-identity-session.md``):

* Every successful ``/v1/auth/refresh`` call mints a new refresh token,
  inserts a new ``sessions`` row, and revokes the old one.
* Presenting a refresh token that matches a session with ``revoked_at``
  already set is treated as credential-stuffing and triggers a revoke
  of **every** session for that user.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Session
from ..security import tokens
from .errors import SessionNotFound, SessionReuseDetected


async def issue(
    db: AsyncSession,
    *,
    user_id: UUID,
    user_agent: str | None,
    ip_address: str | None,
) -> tuple[Session, str]:
    """Create a fresh session and return ``(row, refresh_plaintext)``."""
    plaintext, token_hash = tokens.new_refresh_token()
    row = Session(
        user_id=user_id,
        refresh_token_hash=token_hash,
        user_agent=user_agent,
        ip_address=ip_address,
        expires_at=tokens.refresh_expiry(),
    )
    db.add(row)
    await db.flush()
    return row, plaintext


async def rotate(
    db: AsyncSession,
    *,
    refresh_token: str,
    user_agent: str | None,
    ip_address: str | None,
) -> tuple[Session, str]:
    """Consume a refresh token and issue a fresh one.

    Raises :class:`SessionNotFound` if the token doesn't match any
    session. Raises :class:`SessionReuseDetected` if the matching
    session is already revoked — the caller should then revoke every
    session for the user.
    """
    token_hash = tokens.hash_refresh_token(refresh_token)
    result = await db.execute(
        select(Session).where(Session.refresh_token_hash == token_hash)
    )
    old = result.scalar_one_or_none()
    if old is None:
        raise SessionNotFound()

    now = datetime.now(timezone.utc)

    if old.revoked_at is not None:
        raise SessionReuseDetected(old.user_id)
    if old.expires_at <= now:
        # Expired but not revoked: just reject; don't escalate.
        raise SessionNotFound()

    # Mark the old session revoked.
    old.revoked_at = now
    old.last_used_at = now

    # Create a new session (new hash, fresh TTL).
    return await issue(
        db,
        user_id=old.user_id,
        user_agent=user_agent,
        ip_address=ip_address,
    )


async def revoke_by_id(db: AsyncSession, session_id: UUID) -> None:
    """Revoke a single session. Idempotent."""
    await db.execute(
        update(Session)
        .where(Session.id == session_id, Session.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )


async def revoke_all_for_user(db: AsyncSession, user_id: UUID) -> None:
    """Revoke every non-revoked session for the user.

    Called from the breach-detection path (``SessionReuseDetected``) and
    on password change. Idempotent.
    """
    await db.execute(
        update(Session)
        .where(Session.user_id == user_id, Session.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )
