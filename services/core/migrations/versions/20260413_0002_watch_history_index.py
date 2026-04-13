"""Phase 3.2a — watch_history_index.

Revision ID: 0002_watch_history_index
Revises: 0001_watches_tags
Create Date: 2026-04-13

One row per persisted artefact (snapshot / screenshot / pdf /
browser step). The row points at an object-storage key; the blob
itself never lives in Postgres.

Tenant isolation is via the FK chain `watch_history_index.watch_id
→ watches.id` (watch is org-scoped). RLS policy uses an EXISTS-join
to `watches` — same pattern as `watch_tag_links` in 0001.
"""
from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_watch_history_index"
down_revision: str | None = "0001_watches_tags"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "watch_history_index",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid7()"),
        ),
        sa.Column(
            "watch_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("watches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("taken_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False, unique=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("hash_md5", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_whi_watch_id_taken",
        "watch_history_index",
        ["watch_id", sa.text("taken_at DESC")],
    )
    op.create_index(
        "ix_whi_watch_id_kind_taken",
        "watch_history_index",
        ["watch_id", "kind", sa.text("taken_at DESC")],
    )

    # RLS — EXISTS-join to watches (no direct org_id).
    op.execute("ALTER TABLE watch_history_index ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY p_watch_history_index_org_isolation ON watch_history_index
            USING (EXISTS (
                SELECT 1 FROM watches w
                WHERE w.id = watch_history_index.watch_id
                  AND w.org_id = NULLIF(current_setting('app.current_org', true), '')::uuid
            ));
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS p_watch_history_index_org_isolation "
        "ON watch_history_index"
    )
    op.execute("ALTER TABLE watch_history_index DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_whi_watch_id_kind_taken", table_name="watch_history_index")
    op.drop_index("ix_whi_watch_id_taken", table_name="watch_history_index")
    op.drop_table("watch_history_index")
