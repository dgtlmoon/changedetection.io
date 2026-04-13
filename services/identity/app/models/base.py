"""Declarative base and reusable column types."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for all identity-service ORM models."""


def uuid_pk() -> Mapped[UUID]:
    """Primary key column: server-side uuid v7 via the ``uuid7()`` SQL function."""
    return mapped_column(
        "id",
        primary_key=True,
        server_default=text("uuid7()"),
    )


def created_at_column() -> Mapped[datetime]:
    return mapped_column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


def updated_at_column() -> Mapped[datetime]:
    return mapped_column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
