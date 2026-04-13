-- =============================================================================
-- Local-development Postgres bootstrap.
--
-- Loaded by the `postgres` service in docker-compose.dev.yml via
-- /docker-entrypoint-initdb.d/. Runs once on first container boot.
--
-- In production these roles are created by the infrastructure code
-- (Terraform/Pulumi) with stronger passwords sourced from a secret
-- manager — this file is dev-only.
-- =============================================================================

-- Application runtime role: respects Row-Level Security.
-- Hot-path queries run as this role; the middleware sets
-- `app.current_org` at the start of every request-bound transaction.
CREATE ROLE app_runtime LOGIN PASSWORD 'app_runtime_dev_password';

-- Identity admin role: BYPASSRLS.
-- Used only by narrow functions in the identity service (e.g. look up a
-- user by email across all orgs). Every call site is audited.
CREATE ROLE identity_admin LOGIN PASSWORD 'identity_admin_dev_password' BYPASSRLS;

-- Grant baseline connect + schema usage.
GRANT CONNECT ON DATABASE onchange TO app_runtime, identity_admin;
GRANT USAGE ON SCHEMA public TO app_runtime, identity_admin;

-- Grant DML on all existing and future tables in the public schema.
-- Migrations run as identity_admin and must also include explicit
-- GRANTs for any new table added later; this ALTER DEFAULT PRIVILEGES
-- statement handles the common case.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_runtime;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO app_runtime;

-- identity_admin owns the schema so it can run DDL during migrations.
ALTER SCHEMA public OWNER TO identity_admin;
