"""Password-reset token lifecycle: issue, confirm.

Distinct from email verification on purpose — different TTLs, different
auditing, and a successful reset revokes every session for the user.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import PasswordResetToken, User
from ..security import tokens
from ..security.passwords import hash_password
from . import sessions as sessions_svc

TOKEN_TTL = timedelta(hours=1)


class ResetError(Exception):
    """Raised for any confirm-token failure.

    Route handlers map this to a single 400 so callers can't distinguish
    "wrong token" from "expired" from "already used".
    """


async def issue(db: AsyncSession, *, user_id: UUID) -> str:
    """Create a reset-token row; return the plaintext token."""
    plaintext, token_hash = tokens.new_refresh_token()
    row = PasswordResetToken(
        user_id=user_id,
        token_hash=token_hash,
        expires_at=datetime.now(timezone.utc) + TOKEN_TTL,
    )
    db.add(row)
    await db.flush()
    return plaintext


async def confirm(db: AsyncSession, *, token: str, new_password: str) -> User:
    """Consume the token, set the new password, revoke all sessions."""
    token_hash = tokens.hash_refresh_token(token)
    result = await db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == token_hash
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise ResetError()

    now = datetime.now(timezone.utc)
    if row.consumed_at is not None or row.expires_at <= now:
        raise ResetError()

    user_result = await db.execute(select(User).where(User.id == row.user_id))
    user = user_result.scalar_one_or_none()
    if user is None:
        raise ResetError()

    row.consumed_at = now
    user.password_hash = hash_password(new_password)

    # Revoke everything — any session that existed before the reset is
    # presumed to be the attacker's.
    await sessions_svc.revoke_all_for_user(db, user.id)

    await db.flush()
    return user
