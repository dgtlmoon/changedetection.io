"""Declarative base + reusable columns."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for all core-service ORM models."""


def uuid_pk() -> Mapped[UUID]:
    """Primary key using the server-side ``uuid7()`` function.

    The function is defined by the identity service's migration — we
    rely on it being present at migration time. Core's migration
    checks with ``CREATE OR REPLACE FUNCTION IF NOT EXISTS`` as a
    safety belt.
    """
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
