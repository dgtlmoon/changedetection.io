"""WatchHistoryEntry — one row per persisted artefact."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, created_at_column, uuid_pk


class WatchHistoryEntry(Base):
    __tablename__ = "watch_history_index"

    id: Mapped[UUID] = uuid_pk()
    watch_id: Mapped[UUID] = mapped_column(
        ForeignKey("watches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    taken_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(Text, nullable=False)
    object_key: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    hash_md5: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = created_at_column()
