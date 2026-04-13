"""Organisation — the tenant."""

from __future__ import annotations

import enum
from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Enum, Text
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, created_at_column, updated_at_column, uuid_pk


class PlanTier(str, enum.Enum):
    free = "free"
    pro = "pro"
    team = "team"
    enterprise = "enterprise"


class OrgStatus(str, enum.Enum):
    active = "active"
    trial = "trial"
    suspended = "suspended"
    cancelled = "cancelled"


class Org(Base):
    __tablename__ = "orgs"

    id: Mapped[UUID] = uuid_pk()
    slug: Mapped[str] = mapped_column(CITEXT, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    plan_tier: Mapped[PlanTier] = mapped_column(
        Enum(PlanTier, name="plan_tier", native_enum=True, create_type=False),
        nullable=False,
        default=PlanTier.free,
    )
    status: Mapped[OrgStatus] = mapped_column(
        Enum(OrgStatus, name="org_status", native_enum=True, create_type=False),
        nullable=False,
        default=OrgStatus.active,
    )
    billing_customer_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
