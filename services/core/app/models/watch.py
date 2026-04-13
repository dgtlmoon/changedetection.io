"""Watch — a single monitored URL."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, created_at_column, updated_at_column, uuid_pk


class Watch(Base):
    __tablename__ = "watches"

    id: Mapped[UUID] = uuid_pk()
    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False, index=True
    )

    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)

    processor: Mapped[str] = mapped_column(
        Text, nullable=False, default="text_json_diff"
    )
    fetch_backend: Mapped[str] = mapped_column(
        Text, nullable=False, default="system"
    )

    paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notification_muted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    time_between_check_seconds: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )

    last_checked: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_changed: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    check_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    previous_md5: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Long-tail config — filters, notification URLs, headers, body,
    # browser steps, etc. See phase-03 doc for the field inventory.
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )

    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
