"""API-key lifecycle: create, list, revoke, resolve-for-auth.

Key format:  ``sk_live_<28 chars urlsafe>`` (36 chars total).
  * ``key_prefix`` column stores the first 12 chars (``sk_live_AbCd``),
    indexed for O(log N) lookup.
  * ``key_hash``   column stores ``sha256(full_plaintext)``.
  * Verification is constant-time via :func:`hmac.compare_digest`.

Creation / listing / revocation are tenant-scoped. Resolution (the
path taken by every machine-authenticated request) is global —
incoming plaintext doesn't yet carry an org context; the key itself
tells us which org.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ApiKey, Org

KEY_BRAND = "sk_live_"
KEY_SECRET_LEN = 28  # chars of urlsafe base64 after the brand
PREFIX_LEN = 12  # total length of key_prefix column value


def _new_plaintext() -> str:
    """Generate a new plaintext key, e.g. ``sk_live_AbCdEfGhIj…``."""
    secret = secrets.token_urlsafe(24)[:KEY_SECRET_LEN]
    return KEY_BRAND + secret


def _hash(plaintext: str) -> bytes:
    return hashlib.sha256(plaintext.encode("utf-8")).digest()


def _prefix(plaintext: str) -> str:
    return plaintext[:PREFIX_LEN]


# ---------------------------------------------------------------------------
# CRUD (tenant-scoped)
# ---------------------------------------------------------------------------


async def create(
    db: AsyncSession,
    *,
    org_id: UUID,
    name: str,
    scopes: list[str],
    created_by_user_id: UUID,
    expires_at: datetime | None = None,
) -> tuple[ApiKey, str]:
    plaintext = _new_plaintext()
    row = ApiKey(
        org_id=org_id,
        name=name,
        key_prefix=_prefix(plaintext),
        key_hash=_hash(plaintext),
        scopes=scopes,
        created_by_user_id=created_by_user_id,
        expires_at=expires_at,
    )
    db.add(row)
    await db.flush()
    return row, plaintext


async def list_for_org(db: AsyncSession, *, org_id: UUID) -> list[ApiKey]:
    result = await db.execute(
        select(ApiKey)
        .where(ApiKey.org_id == org_id)
        .order_by(ApiKey.created_at.desc())
    )
    return list(result.scalars().all())


async def revoke_by_id(
    db: AsyncSession, *, api_key_id: UUID, org_id: UUID
) -> bool:
    result = await db.execute(
        select(ApiKey).where(ApiKey.id == api_key_id, ApiKey.org_id == org_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return False
    if row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
        await db.flush()
    return True


# ---------------------------------------------------------------------------
# Authentication (global — used by auth middleware)
# ---------------------------------------------------------------------------


async def resolve(
    db: AsyncSession, *, plaintext: str
) -> tuple[ApiKey, Org] | None:
    """Validate ``plaintext``. Returns ``(api_key_row, org_row)`` on success.

    ``None`` is returned for every failure mode (wrong prefix, wrong
    hash, revoked, expired, org deleted) — the caller MUST map it to a
    generic 401, no granular error messages.
    """
    if not plaintext.startswith(KEY_BRAND) or len(plaintext) < PREFIX_LEN + 8:
        return None

    prefix = _prefix(plaintext)
    expected_hash = _hash(plaintext)

    result = await db.execute(
        select(ApiKey, Org)
        .join(Org, Org.id == ApiKey.org_id)
        .where(ApiKey.key_prefix == prefix)
    )
    # Prefix collisions are vanishingly unlikely but theoretically
    # possible — iterate candidates.
    for api_key, org in result.all():
        if not hmac.compare_digest(api_key.key_hash, expected_hash):
            continue
        if api_key.revoked_at is not None:
            return None
        if api_key.expires_at is not None and api_key.expires_at <= datetime.now(
            timezone.utc
        ):
            return None
        if org.deleted_at is not None:
            return None
        return api_key, org
    return None


async def touch_last_used(
    db: AsyncSession, *, api_key_id: UUID
) -> None:
    """Fire-and-forget update of ``last_used_at``. Called off the hot path."""
    from sqlalchemy import update

    await db.execute(
        update(ApiKey)
        .where(ApiKey.id == api_key_id)
        .values(last_used_at=datetime.now(timezone.utc))
    )
