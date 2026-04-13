"""AuditLog — append-only log of security-relevant events.

Partitioned monthly on ``created_at``. See the initial Alembic migration
for the partition DDL.
"""

from __future__ import annotations

import enum
from datetime import datetime
from uuid import UUID

from sqlalchemy import Enum, ForeignKey, Text
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, created_at_column, uuid_pk


class ActorKind(str, enum.Enum):
    user = "user"
    api_key = "api_key"
    system = "system"


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[UUID] = uuid_pk()
    # org_id is nullable for pre-org events (signup before an org exists).
    org_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("orgs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor_kind: Mapped[ActorKind] = mapped_column(
        Enum(ActorKind, name="actor_kind", native_enum=True, create_type=False),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    target_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    audit_metadata: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = created_at_column()
