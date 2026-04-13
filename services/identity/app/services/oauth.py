"""OAuth business logic: sign-in, sign-up, implicit link.

Called from the callback route after the provider has returned a
normalised :class:`OAuthProfile`. This module decides, given the
profile, which :class:`User` row to use:

1. Exact match via ``(provider, provider_user_id)`` → that user.
2. Email match + provider-verified email → existing user, *with new
   ``oauth_accounts`` row attached*.
3. Email match + provider-unverified email → reject with
   :class:`UnverifiedEmailCollision` (route maps to 409).
4. No match → create a new SSO-only user + ``oauth_accounts`` row.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import OAuthAccount, User
from ..models.oauth_account import OAuthProvider as OAuthProviderEnum
from ..oauth import OAuthProfile


class UnverifiedEmailCollision(Exception):
    """A provider-unverified email collides with an existing user row."""


async def _find_oauth_account(
    db: AsyncSession, *, provider: str, provider_user_id: str
) -> OAuthAccount | None:
    result = await db.execute(
        select(OAuthAccount).where(
            OAuthAccount.provider == OAuthProviderEnum(provider),
            OAuthAccount.provider_user_id == provider_user_id,
        )
    )
    return result.scalar_one_or_none()


async def _find_user_by_email(
    db: AsyncSession, email: str
) -> User | None:
    result = await db.execute(
        select(User).where(
            User.email == email, User.deleted_at.is_(None)
        )
    )
    return result.scalar_one_or_none()


async def _find_user_by_id(db: AsyncSession, user_id: UUID) -> User | None:
    result = await db.execute(
        select(User).where(
            User.id == user_id, User.deleted_at.is_(None)
        )
    )
    return result.scalar_one_or_none()


async def sign_in_or_register(
    db: AsyncSession, *, profile: OAuthProfile
) -> tuple[User, bool]:
    """Resolve or create a user for ``profile``. Returns ``(user, is_new)``.

    Raises :class:`UnverifiedEmailCollision` when the provider-supplied
    email is NOT verified AND a user already exists for that email.
    """
    # 1. Existing oauth_accounts link?
    existing_link = await _find_oauth_account(
        db,
        provider=profile.provider,
        provider_user_id=profile.provider_user_id,
    )
    if existing_link is not None:
        user = await _find_user_by_id(db, existing_link.user_id)
        if user is not None:
            return user, False
        # Stale link — user got deleted. Fall through to re-create.

    # 2/3. Email collision?
    by_email = await _find_user_by_email(db, profile.email)
    if by_email is not None:
        if not profile.email_verified:
            raise UnverifiedEmailCollision()
        # Implicit link.
        link = OAuthAccount(
            user_id=by_email.id,
            provider=OAuthProviderEnum(profile.provider),
            provider_user_id=profile.provider_user_id,
            email=profile.email,
        )
        db.add(link)
        # If the user's display_name/avatar is empty, opportunistically
        # populate from the provider.
        if not by_email.display_name and profile.display_name:
            by_email.display_name = profile.display_name
        if not by_email.avatar_url and profile.avatar_url:
            by_email.avatar_url = profile.avatar_url
        if profile.email_verified and by_email.email_verified_at is None:
            by_email.email_verified_at = datetime.now(timezone.utc)
        await db.flush()
        return by_email, False

    # 4. New user.
    user = User(
        email=profile.email,
        password_hash=None,  # SSO-only
        display_name=profile.display_name,
        avatar_url=profile.avatar_url,
        email_verified_at=(
            datetime.now(timezone.utc) if profile.email_verified else None
        ),
    )
    db.add(user)
    await db.flush()

    link = OAuthAccount(
        user_id=user.id,
        provider=OAuthProviderEnum(profile.provider),
        provider_user_id=profile.provider_user_id,
        email=profile.email,
    )
    db.add(link)
    await db.flush()
    return user, True
