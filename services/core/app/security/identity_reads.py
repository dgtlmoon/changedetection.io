"""Read-only access to identity-owned tables.

Core does NOT write to ``users`` / ``memberships`` / ``api_keys`` /
``orgs``. These helpers use ``sqlalchemy.text()`` so the coupling is
visible — when a third service needs the same tables we'll extract a
``packages/shared/identity-client/`` package and replace these.

Every function here uses ``admin_session()`` (BYPASSRLS) because the
caller is either:
  * the tenant resolver, which runs before org context exists, or
  * ``require_membership``, which reads membership rows of orgs the
    caller might not be a member of — RLS would hide them.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def resolve_org_by_slug(db: AsyncSession, slug: str) -> tuple[UUID, str] | None:
    """Return ``(org_id, slug)`` or ``None``."""
    result = await db.execute(
        text(
            "SELECT id, slug FROM orgs "
            "WHERE slug = :slug AND deleted_at IS NULL"
        ),
        {"slug": slug},
    )
    row = result.first()
    if row is None:
        return None
    return UUID(str(row[0])), str(row[1])


async def find_user_id_by_id(
    db: AsyncSession, user_id: UUID
) -> UUID | None:
    """Confirm the user row exists and isn't soft-deleted."""
    result = await db.execute(
        text(
            "SELECT id FROM users "
            "WHERE id = :user_id AND deleted_at IS NULL"
        ),
        {"user_id": str(user_id)},
    )
    row = result.first()
    return UUID(str(row[0])) if row else None


async def get_membership_role(
    db: AsyncSession, *, org_id: UUID, user_id: UUID
) -> str | None:
    """Return the membership role or ``None`` if the user isn't a member."""
    result = await db.execute(
        text(
            "SELECT role FROM memberships "
            "WHERE org_id = :org_id AND user_id = :user_id"
        ),
        {"org_id": str(org_id), "user_id": str(user_id)},
    )
    row = result.first()
    return str(row[0]) if row else None


# ---------------------------------------------------------------------------
# API-key resolution
# ---------------------------------------------------------------------------

# Must match identity/app/services/api_keys.py.
_KEY_BRAND = "sk_live_"
_PREFIX_LEN = 12


def _hash_plaintext(plaintext: str) -> bytes:
    return hashlib.sha256(plaintext.encode("utf-8")).digest()


@dataclass(slots=True, frozen=True)
class ResolvedApiKey:
    api_key_id: UUID
    org_id: UUID
    scopes: tuple[str, ...]


async def resolve_api_key(
    db: AsyncSession, *, plaintext: str
) -> ResolvedApiKey | None:
    """Global lookup, constant-time hash compare. Returns ``None`` on
    any failure."""
    if not plaintext.startswith(_KEY_BRAND) or len(plaintext) < _PREFIX_LEN + 8:
        return None

    prefix = plaintext[:_PREFIX_LEN]
    expected_hash = _hash_plaintext(plaintext)
    now = datetime.now(timezone.utc)

    result = await db.execute(
        text(
            "SELECT id, org_id, key_hash, scopes, revoked_at, expires_at "
            "FROM api_keys WHERE key_prefix = :prefix"
        ),
        {"prefix": prefix},
    )
    for row in result.all():
        stored_hash = bytes(row[2])
        if not hmac.compare_digest(stored_hash, expected_hash):
            continue
        if row[4] is not None:  # revoked_at
            return None
        if row[5] is not None and row[5] <= now:  # expires_at
            return None
        scopes = row[3] or []
        return ResolvedApiKey(
            api_key_id=UUID(str(row[0])),
            org_id=UUID(str(row[1])),
            scopes=tuple(scopes),
        )
    return None
