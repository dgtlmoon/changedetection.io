"""Phase 3.1 initial schema — watches, watch_tags, watch_tag_links.

Revision ID: 0001_watches_tags
Revises:
Create Date: 2026-04-13

Depends logically on the identity service's ``orgs`` table; the FK
constraint below fails loudly if identity migrations haven't been
applied first.

This migration is conservative — it does not create ``uuid7()`` or
``citext``. Both come from the identity migration set. If you're
running core in isolation for some reason, apply identity first.
"""
from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_watches_tags"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # watches
    # ------------------------------------------------------------------
    op.create_table(
        "watches",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid7()"),
        ),
        sa.Column(
            "org_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orgs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column(
            "processor",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'text_json_diff'"),
        ),
        sa.Column(
            "fetch_backend",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'system'"),
        ),
        sa.Column(
            "paused", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "notification_muted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("time_between_check_seconds", sa.Integer(), nullable=True),
        sa.Column("last_checked", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_changed", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "check_count",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("previous_md5", sa.Text(), nullable=True),
        sa.Column(
            "settings",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_watches_org_id", "watches", ["org_id"])
    op.create_index(
        "ix_watches_org_id_active",
        "watches",
        ["org_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_watches_scheduler",
        "watches",
        ["org_id", "last_checked"],
        postgresql_where=sa.text("deleted_at IS NULL AND paused = false"),
    )

    # ------------------------------------------------------------------
    # watch_tags
    # ------------------------------------------------------------------
    op.create_table(
        "watch_tags",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid7()"),
        ),
        sa.Column(
            "org_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orgs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.dialects.postgresql.CITEXT(), nullable=False),
        sa.Column("color", sa.Text(), nullable=True),
        sa.Column(
            "settings",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_watch_tags_org_id", "watch_tags", ["org_id"])
    op.create_index(
        "uq_watch_tags_org_name_active",
        "watch_tags",
        ["org_id", "name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # ------------------------------------------------------------------
    # watch_tag_links
    # ------------------------------------------------------------------
    op.create_table(
        "watch_tag_links",
        sa.Column(
            "watch_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("watches.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "tag_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("watch_tags.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_watch_tag_links_tag_id", "watch_tag_links", ["tag_id"])

    # ------------------------------------------------------------------
    # Row-Level Security
    # ------------------------------------------------------------------
    op.execute("ALTER TABLE watches ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY p_watches_org_isolation ON watches
            USING (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid);
        """
    )

    op.execute("ALTER TABLE watch_tags ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY p_watch_tags_org_isolation ON watch_tags
            USING (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid);
        """
    )

    # watch_tag_links has no direct org_id; policy joins to watches.
    op.execute("ALTER TABLE watch_tag_links ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY p_watch_tag_links_org_isolation ON watch_tag_links
            USING (EXISTS (
                SELECT 1 FROM watches w
                WHERE w.id = watch_tag_links.watch_id
                  AND w.org_id = NULLIF(current_setting('app.current_org', true), '')::uuid
            ));
        """
    )


def downgrade() -> None:
    for t in ("watch_tag_links", "watch_tags", "watches"):
        op.execute(f"DROP POLICY IF EXISTS p_{t}_org_isolation ON {t}")
        op.execute(f"ALTER TABLE {t} DISABLE ROW LEVEL SECURITY")

    op.drop_index("ix_watch_tag_links_tag_id", table_name="watch_tag_links")
    op.drop_table("watch_tag_links")

    op.drop_index("uq_watch_tags_org_name_active", table_name="watch_tags")
    op.drop_index("ix_watch_tags_org_id", table_name="watch_tags")
    op.drop_table("watch_tags")

    op.drop_index("ix_watches_scheduler", table_name="watches")
    op.drop_index("ix_watches_org_id_active", table_name="watches")
    op.drop_index("ix_watches_org_id", table_name="watches")
    op.drop_table("watches")
