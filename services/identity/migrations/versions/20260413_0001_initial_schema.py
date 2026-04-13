"""Phase 1 initial schema — orgs, users, memberships, sessions, API keys, invites, audit logs.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-04-13

This migration is intentionally a single revision. Phase-1 tables are a
unit; splitting them across revisions would let a developer land a
partial schema that leaves RLS half-configured — one of the risks called
out in the Phase-1 design note.

Notable DDL:
  * ``uuid7()`` — a plpgsql function producing sortable UUIDs. We don't
    want to pull in an extension for just one function.
  * Row-Level Security is enabled on every tenant-scoped table with an
    ``app.current_org`` predicate. The application middleware issues
    ``SET LOCAL app.current_org = '<uuid>'`` at the start of every
    request-bound transaction.
  * ``audit_logs`` is RANGE-partitioned monthly on ``created_at`` from
    the start; the first three partitions are created eagerly so dev
    and staging don't have to worry about the partition-manager job on
    day one.
"""
from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# ----------------------------------------------------------------------------
# uuid7(): sortable UUIDs without an extension.
#
# Format: 48-bit Unix-epoch milliseconds || 4-bit version (0x7) ||
# 12-bit sub-ms counter || 2-bit variant (0b10) || 62-bit random.
# Reference: https://www.ietf.org/archive/id/draft-ietf-uuidrev-rfc4122bis-14.html
# ----------------------------------------------------------------------------
_UUID7_FN = """
CREATE OR REPLACE FUNCTION uuid7() RETURNS uuid AS $$
DECLARE
    ts_ms   bigint;
    rand    bytea;
    uuid_b  bytea;
BEGIN
    ts_ms  := (EXTRACT(EPOCH FROM clock_timestamp()) * 1000)::bigint;
    rand   := gen_random_bytes(10);
    uuid_b := set_byte(
                set_byte(
                  set_byte(
                    set_byte(
                      set_byte(
                        set_byte(
                          rand,
                          0,
                          ((ts_ms >> 40) & 255)::int
                        ),
                        1,
                        ((ts_ms >> 32) & 255)::int
                      ),
                      2,
                      ((ts_ms >> 24) & 255)::int
                    ),
                    3,
                    ((ts_ms >> 16) & 255)::int
                  ),
                  4,
                  ((ts_ms >> 8) & 255)::int
                ),
                5,
                (ts_ms & 255)::int
              );
    -- Set version (7) in byte 6: top 4 bits = 0x7
    uuid_b := set_byte(uuid_b, 6, ((get_byte(uuid_b, 6) & 15) | 112));
    -- Set variant (RFC 4122) in byte 8: top 2 bits = 0b10
    uuid_b := set_byte(uuid_b, 8, ((get_byte(uuid_b, 8) & 63) | 128));
    RETURN encode(uuid_b, 'hex')::uuid;
END;
$$ LANGUAGE plpgsql VOLATILE;
"""


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Extensions & helper function
    # ------------------------------------------------------------------
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    op.execute(_UUID7_FN)

    # ------------------------------------------------------------------
    # Enum types (created once, reused by Enum column definitions)
    # ------------------------------------------------------------------
    plan_tier = sa.Enum(
        "free", "pro", "team", "enterprise", name="plan_tier"
    )
    org_status = sa.Enum(
        "active", "trial", "suspended", "cancelled", name="org_status"
    )
    membership_role = sa.Enum(
        "owner", "admin", "member", "viewer", name="membership_role"
    )
    oauth_provider = sa.Enum(
        "google", "github", "microsoft", name="oauth_provider"
    )
    actor_kind = sa.Enum("user", "api_key", "system", name="actor_kind")
    for enum in (plan_tier, org_status, membership_role, oauth_provider, actor_kind):
        enum.create(op.get_bind(), checkfirst=True)

    # ------------------------------------------------------------------
    # orgs
    # ------------------------------------------------------------------
    op.create_table(
        "orgs",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True),
                  primary_key=True, server_default=sa.text("uuid7()")),
        sa.Column("slug", sa.dialects.postgresql.CITEXT(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("plan_tier", plan_tier, nullable=False,
                  server_default=sa.text("'free'")),
        sa.Column("status", org_status, nullable=False,
                  server_default=sa.text("'active'")),
        sa.Column("billing_customer_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("uq_orgs_slug_active", "orgs", ["slug"], unique=True,
                    postgresql_where=sa.text("deleted_at IS NULL"))

    # ------------------------------------------------------------------
    # users
    # ------------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True),
                  primary_key=True, server_default=sa.text("uuid7()")),
        sa.Column("email", sa.dialects.postgresql.CITEXT(), nullable=False),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("locale", sa.Text(), nullable=False,
                  server_default=sa.text("'en'")),
        sa.Column("timezone", sa.Text(), nullable=False,
                  server_default=sa.text("'UTC'")),
        sa.Column("mfa_secret", sa.Text(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("uq_users_email_active", "users", ["email"], unique=True,
                    postgresql_where=sa.text("deleted_at IS NULL"))

    # ------------------------------------------------------------------
    # memberships
    # ------------------------------------------------------------------
    op.create_table(
        "memberships",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True),
                  primary_key=True, server_default=sa.text("uuid7()")),
        sa.Column("org_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", membership_role, nullable=False),
        sa.Column("invited_by_user_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("org_id", "user_id", name="uq_memberships_org_user"),
    )
    op.create_index("ix_memberships_org_id", "memberships", ["org_id"])
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])

    # ------------------------------------------------------------------
    # invites
    # ------------------------------------------------------------------
    op.create_table(
        "invites",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True),
                  primary_key=True, server_default=sa.text("uuid7()")),
        sa.Column("org_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.dialects.postgresql.CITEXT(), nullable=False),
        sa.Column("role", membership_role, nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False, unique=True),
        sa.Column("invited_by_user_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_invites_org_id", "invites", ["org_id"])

    # ------------------------------------------------------------------
    # sessions
    # ------------------------------------------------------------------
    op.create_table(
        "sessions",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True),
                  primary_key=True, server_default=sa.text("uuid7()")),
        sa.Column("user_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("refresh_token_hash", sa.LargeBinary(), nullable=False, unique=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("ip_address", sa.dialects.postgresql.INET(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])

    # ------------------------------------------------------------------
    # api_keys
    # ------------------------------------------------------------------
    op.create_table(
        "api_keys",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True),
                  primary_key=True, server_default=sa.text("uuid7()")),
        sa.Column("org_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("key_prefix", sa.Text(), nullable=False),
        sa.Column("key_hash", sa.LargeBinary(), nullable=False, unique=True),
        sa.Column("scopes", sa.dialects.postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_by_user_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_api_keys_org_id", "api_keys", ["org_id"])
    op.create_index("ix_api_keys_key_prefix", "api_keys", ["key_prefix"])

    # ------------------------------------------------------------------
    # oauth_accounts
    # ------------------------------------------------------------------
    op.create_table(
        "oauth_accounts",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True),
                  primary_key=True, server_default=sa.text("uuid7()")),
        sa.Column("user_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", oauth_provider, nullable=False),
        sa.Column("provider_user_id", sa.Text(), nullable=False),
        sa.Column("email", sa.dialects.postgresql.CITEXT(), nullable=False),
        sa.Column("access_token_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("refresh_token_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("provider", "provider_user_id",
                            name="uq_oauth_provider_user"),
    )
    op.create_index("ix_oauth_accounts_user_id", "oauth_accounts", ["user_id"])

    # ------------------------------------------------------------------
    # password_reset_tokens
    # ------------------------------------------------------------------
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True),
                  primary_key=True, server_default=sa.text("uuid7()")),
        sa.Column("user_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_prt_user_id", "password_reset_tokens", ["user_id"])

    # ------------------------------------------------------------------
    # audit_logs (partitioned monthly on created_at)
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE audit_logs (
            id           uuid        NOT NULL DEFAULT uuid7(),
            org_id       uuid        NULL REFERENCES orgs(id) ON DELETE SET NULL,
            actor_user_id uuid       NULL REFERENCES users(id) ON DELETE SET NULL,
            actor_kind   actor_kind  NOT NULL,
            action       text        NOT NULL,
            target_type  text        NULL,
            target_id    text        NULL,
            metadata     jsonb       NOT NULL DEFAULT '{}'::jsonb,
            ip_address   inet        NULL,
            user_agent   text        NULL,
            created_at   timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (id, created_at)
        ) PARTITION BY RANGE (created_at);
        """
    )
    op.create_index("ix_audit_logs_org_id", "audit_logs", ["org_id"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])

    # Seed three partitions (current month + next two) so day-one writes
    # don't fail if the partition-manager cron hasn't run yet.
    op.execute(
        """
        DO $$
        DECLARE
            start_m date := date_trunc('month', now())::date;
            i int;
            part_start date;
            part_end   date;
            part_name  text;
        BEGIN
            FOR i IN 0..2 LOOP
                part_start := start_m + (i || ' months')::interval;
                part_end   := start_m + ((i + 1) || ' months')::interval;
                part_name  := format('audit_logs_%s', to_char(part_start, 'YYYY_MM'));
                EXECUTE format(
                    'CREATE TABLE IF NOT EXISTS %I PARTITION OF audit_logs
                       FOR VALUES FROM (%L) TO (%L);',
                    part_name, part_start, part_end
                );
            END LOOP;
        END $$;
        """
    )

    # ------------------------------------------------------------------
    # Row-Level Security.
    #
    # Policy template: accept rows whose org_id matches the session
    # variable app.current_org. The middleware sets the variable per
    # request; if unset, the predicate evaluates NULL = NULL → false,
    # so all reads return zero rows (fails closed).
    # ------------------------------------------------------------------
    rls_tables = ["orgs", "memberships", "invites", "api_keys", "audit_logs"]
    for t in rls_tables:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        # orgs.id is the same as orgs.org_id conceptually.
        org_col = "id" if t == "orgs" else "org_id"
        op.execute(
            f"""
            CREATE POLICY p_{t}_org_isolation ON {t}
                USING ({org_col} = NULLIF(current_setting('app.current_org', true), '')::uuid);
            """
        )

    # users, sessions, password_reset_tokens, oauth_accounts are NOT
    # tenant-scoped — they live at the global identity layer. RLS is NOT
    # enabled on them; access is gated by application code + the
    # identity_admin role.


def downgrade() -> None:
    # Reverse order of creation.
    for t in ["orgs", "memberships", "invites", "api_keys", "audit_logs"]:
        op.execute(f"DROP POLICY IF EXISTS p_{t}_org_isolation ON {t}")
        op.execute(f"ALTER TABLE {t} DISABLE ROW LEVEL SECURITY")

    op.execute("DROP TABLE IF EXISTS audit_logs CASCADE")
    op.drop_table("password_reset_tokens")
    op.drop_table("oauth_accounts")
    op.drop_table("api_keys")
    op.drop_table("sessions")
    op.drop_table("invites")
    op.drop_table("memberships")
    op.drop_table("users")
    op.drop_table("orgs")

    for enum_name in ("actor_kind", "oauth_provider", "membership_role",
                      "org_status", "plan_tier"):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")

    op.execute("DROP FUNCTION IF EXISTS uuid7()")
    # citext / pgcrypto stay; they're harmless and might be used elsewhere.
