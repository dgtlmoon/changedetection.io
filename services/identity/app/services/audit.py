"""Append-only audit-log writer.

All writes go through :func:`record`; route handlers pass a minimal set
of structured fields and we take care of the DB row. Audit writes are
best-effort and MUST NOT throw out of the caller — a logged ``structlog``
warning is sufficient on failure.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AuditLog
from ..models.audit_log import ActorKind

_log = structlog.get_logger()


async def record(
    db: AsyncSession,
    *,
    action: str,
    actor_kind: ActorKind,
    org_id: UUID | None = None,
    actor_user_id: UUID | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> None:
    try:
        row = AuditLog(
            org_id=org_id,
            actor_user_id=actor_user_id,
            actor_kind=actor_kind,
            action=action,
            target_type=target_type,
            target_id=target_id,
            audit_metadata=metadata or {},
            ip_address=ip_address,
            user_agent=user_agent,
        )
        db.add(row)
        await db.flush()
    except Exception as exc:  # noqa: BLE001 - audit failures must not raise out
        _log.warning("audit.write_failed", action=action, error=str(exc))
