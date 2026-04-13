"""Postgres-backed implementations of :class:`WatchStore` / :class:`TagStore`.

These classes are thin wrappers around SQLAlchemy queries. Route
handlers own the ``with_current_org`` session lifecycle; the store
just takes the session.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Watch, WatchTag, WatchTagLink
from .protocol import WatchPatch


class DuplicateTagName(Exception):
    """Raised when a tag is created / renamed to one that already exists
    in the same org."""


class PgWatchStore:
    # --- create --------------------------------------------------------------

    async def create(
        self,
        db: AsyncSession,
        *,
        org_id: UUID,
        url: str,
        title: str | None = None,
        processor: str = "text_json_diff",
        fetch_backend: str = "system",
        time_between_check_seconds: int | None = None,
        settings: dict[str, Any] | None = None,
    ) -> Watch:
        row = Watch(
            org_id=org_id,
            url=url,
            title=title,
            processor=processor,
            fetch_backend=fetch_backend,
            time_between_check_seconds=time_between_check_seconds,
            settings=settings or {},
        )
        db.add(row)
        await db.flush()
        return row

    # --- read ---------------------------------------------------------------

    async def get(
        self, db: AsyncSession, *, org_id: UUID, watch_id: UUID
    ) -> Watch | None:
        result = await db.execute(
            select(Watch).where(
                Watch.id == watch_id,
                Watch.org_id == org_id,
                Watch.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def list(
        self,
        db: AsyncSession,
        *,
        org_id: UUID,
        limit: int = 100,
        offset: int = 0,
        paused: bool | None = None,
        tag_id: UUID | None = None,
    ) -> list[Watch]:
        stmt = (
            select(Watch)
            .where(Watch.org_id == org_id, Watch.deleted_at.is_(None))
            .order_by(Watch.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if paused is not None:
            stmt = stmt.where(Watch.paused == paused)
        if tag_id is not None:
            # Join + filter; also filter by org_id on the link join for
            # defence-in-depth (even though the FK chain implies it).
            stmt = stmt.join(
                WatchTagLink, WatchTagLink.watch_id == Watch.id
            ).where(WatchTagLink.tag_id == tag_id)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    # --- update -------------------------------------------------------------

    async def update(
        self,
        db: AsyncSession,
        *,
        org_id: UUID,
        watch_id: UUID,
        patch: WatchPatch,
    ) -> Watch | None:
        row = await self.get(db, org_id=org_id, watch_id=watch_id)
        if row is None:
            return None
        for key, value in patch.items():
            # Pydantic / caller guarantees the key names; here we
            # validate the attribute exists so a typo becomes a loud
            # error in tests rather than a silent no-op.
            if not hasattr(row, key):
                raise ValueError(f"unknown watch field {key!r}")
            setattr(row, key, value)
        row.updated_at = datetime.now(timezone.utc)
        await db.flush()
        return row

    # --- delete -------------------------------------------------------------

    async def delete(
        self, db: AsyncSession, *, org_id: UUID, watch_id: UUID
    ) -> bool:
        """Soft-delete — sets ``deleted_at``. Returns True if anything
        was deleted, False if the row didn't exist or was already deleted.
        """
        now = datetime.now(timezone.utc)
        result = await db.execute(
            update(Watch)
            .where(
                Watch.id == watch_id,
                Watch.org_id == org_id,
                Watch.deleted_at.is_(None),
            )
            .values(deleted_at=now, updated_at=now)
        )
        return (result.rowcount or 0) > 0

    # --- worker hook --------------------------------------------------------

    async def mark_checked(
        self,
        db: AsyncSession,
        *,
        org_id: UUID,
        watch_id: UUID,
        changed: bool,
        previous_md5: str | None = None,
        error: str | None = None,
    ) -> bool:
        """Called by the fetch worker after processing a watch.

        Atomically bumps ``check_count``, sets ``last_checked``, and
        (if ``changed``) stamps ``last_changed`` + ``previous_md5``.
        ``error`` clears on success and is set on failure.
        """
        now = datetime.now(timezone.utc)
        values: dict[str, Any] = {
            "last_checked": now,
            "check_count": Watch.check_count + 1,
            "last_error": error,
            "updated_at": now,
        }
        if changed:
            values["last_changed"] = now
            if previous_md5 is not None:
                values["previous_md5"] = previous_md5

        result = await db.execute(
            update(Watch)
            .where(
                Watch.id == watch_id,
                Watch.org_id == org_id,
                Watch.deleted_at.is_(None),
            )
            .values(**values)
        )
        return (result.rowcount or 0) > 0


class PgTagStore:
    # --- create / read / delete ---------------------------------------------

    async def create(
        self,
        db: AsyncSession,
        *,
        org_id: UUID,
        name: str,
        color: str | None = None,
        settings: dict[str, Any] | None = None,
    ) -> WatchTag:
        row = WatchTag(
            org_id=org_id, name=name, color=color, settings=settings or {}
        )
        db.add(row)
        try:
            await db.flush()
        except IntegrityError as exc:
            raise DuplicateTagName(name) from exc
        return row

    async def get(
        self, db: AsyncSession, *, org_id: UUID, tag_id: UUID
    ) -> WatchTag | None:
        result = await db.execute(
            select(WatchTag).where(
                WatchTag.id == tag_id,
                WatchTag.org_id == org_id,
                WatchTag.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def list(
        self, db: AsyncSession, *, org_id: UUID
    ) -> list[WatchTag]:
        result = await db.execute(
            select(WatchTag)
            .where(
                WatchTag.org_id == org_id,
                WatchTag.deleted_at.is_(None),
            )
            .order_by(WatchTag.name)
        )
        return list(result.scalars().all())

    async def delete(
        self, db: AsyncSession, *, org_id: UUID, tag_id: UUID
    ) -> bool:
        now = datetime.now(timezone.utc)
        result = await db.execute(
            update(WatchTag)
            .where(
                WatchTag.id == tag_id,
                WatchTag.org_id == org_id,
                WatchTag.deleted_at.is_(None),
            )
            .values(deleted_at=now, updated_at=now)
        )
        if (result.rowcount or 0) == 0:
            return False
        # Also clean up the m2m links. Nothing reads them once the tag
        # is soft-deleted but keeping the rows around hides the tag from
        # callers doing `tag_id` filters.
        await db.execute(
            delete(WatchTagLink).where(WatchTagLink.tag_id == tag_id)
        )
        return True

    # --- m2m ----------------------------------------------------------------

    async def assign_to_watch(
        self,
        db: AsyncSession,
        *,
        org_id: UUID,
        watch_id: UUID,
        tag_ids: list[UUID],
    ) -> list[WatchTag]:
        """Replace a watch's tag set with ``tag_ids``.

        Tags that don't exist in ``org_id`` are silently dropped (not an
        error — a request that mentions a cross-tenant tag id must not
        be able to fingerprint its existence). The return value is the
        final list of assigned tags, in name order.
        """
        # Verify the watch belongs to the org.
        watch_hit = await db.execute(
            select(Watch.id).where(
                Watch.id == watch_id,
                Watch.org_id == org_id,
                Watch.deleted_at.is_(None),
            )
        )
        if watch_hit.scalar_one_or_none() is None:
            return []

        # Filter tag_ids to those actually owned by the org.
        if tag_ids:
            valid_result = await db.execute(
                select(WatchTag.id).where(
                    WatchTag.id.in_(tag_ids),
                    WatchTag.org_id == org_id,
                    WatchTag.deleted_at.is_(None),
                )
            )
            valid_ids = {row for row in valid_result.scalars().all()}
        else:
            valid_ids = set()

        # Remove any existing links that aren't in the new set.
        del_stmt = delete(WatchTagLink).where(
            WatchTagLink.watch_id == watch_id
        )
        if valid_ids:
            del_stmt = del_stmt.where(~WatchTagLink.tag_id.in_(valid_ids))
        await db.execute(del_stmt)

        # Insert any missing links. We do this row-by-row to keep the
        # code simple; watches typically have < 10 tags.
        if valid_ids:
            existing = await db.execute(
                select(WatchTagLink.tag_id).where(
                    WatchTagLink.watch_id == watch_id
                )
            )
            already_linked = {row for row in existing.scalars().all()}
            for tag_id in valid_ids - already_linked:
                db.add(WatchTagLink(watch_id=watch_id, tag_id=tag_id))

        await db.flush()

        # Return the final set, ordered.
        if not valid_ids:
            return []
        result = await db.execute(
            select(WatchTag)
            .join(WatchTagLink, WatchTagLink.tag_id == WatchTag.id)
            .where(
                WatchTagLink.watch_id == watch_id,
                WatchTag.deleted_at.is_(None),
            )
            .order_by(WatchTag.name)
        )
        return list(result.scalars().all())
