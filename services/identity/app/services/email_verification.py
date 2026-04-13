"""Email-verification token lifecycle: issue, confirm."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import EmailVerificationToken, User
from ..security import tokens

TOKEN_TTL = timedelta(hours=24)


class VerificationError(Exception):
    """Raised for any confirm-token failure.

    Route handlers collapse this to a single 400 response; we never
    reveal whether the token was wrong, expired, or already used.
    """


async def issue(db: AsyncSession, *, user_id: UUID) -> str:
    """Create a verification row and return the plaintext token."""
    plaintext, token_hash = tokens.new_refresh_token()
    row = EmailVerificationToken(
        user_id=user_id,
        token_hash=token_hash,
        expires_at=datetime.now(timezone.utc) + TOKEN_TTL,
    )
    db.add(row)
    await db.flush()
    return plaintext


async def confirm(db: AsyncSession, *, token: str) -> User:
    """Consume the token, mark user verified, return the user row."""
    token_hash = tokens.hash_refresh_token(token)
    result = await db.execute(
        select(EmailVerificationToken).where(
            EmailVerificationToken.token_hash == token_hash
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise VerificationError()

    now = datetime.now(timezone.utc)
    if row.consumed_at is not None or row.expires_at <= now:
        raise VerificationError()

    # Mark the token consumed and the user verified in the same tx.
    row.consumed_at = now

    user_result = await db.execute(select(User).where(User.id == row.user_id))
    user = user_result.scalar_one_or_none()
    if user is None:
        raise VerificationError()

    if user.email_verified_at is None:
        user.email_verified_at = now

    await db.flush()
    return user
