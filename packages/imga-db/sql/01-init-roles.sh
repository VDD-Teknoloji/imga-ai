#!/bin/bash
# Mounted into postgres container as /docker-entrypoint-initdb.d/01-init-roles.sh
# Runs on first container start when the data volume is empty.
#
# Three-role model:
#   imga_owner  - POSTGRES_USER, superuser, owns schema, runs migrations
#   imga_app    - default app role, NOBYPASSRLS (subject to all RLS policies)
#   imga_admin  - super-admin endpoints role, BYPASSRLS

set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    -- imga_app: regular app role; RLS is enforced even when this role is
    -- the table owner thanks to FORCE ROW LEVEL SECURITY in the migrations.
    CREATE ROLE imga_app LOGIN PASSWORD '${IMGA_APP_PASSWORD:-imga_app_password}'
        NOBYPASSRLS;

    -- imga_admin: super-admin endpoints; bypasses RLS so it can serve
    -- cross-tenant administrative queries.
    CREATE ROLE imga_admin LOGIN PASSWORD '${IMGA_ADMIN_PASSWORD:-imga_admin_password}'
        BYPASSRLS;

    GRANT CONNECT ON DATABASE "$POSTGRES_DB" TO imga_app, imga_admin;
    GRANT USAGE ON SCHEMA public TO imga_app, imga_admin;

    -- Default privileges so any future table created by imga_owner is
    -- readable + writable by both auxiliary roles.
    ALTER DEFAULT PRIVILEGES FOR ROLE "$POSTGRES_USER" IN SCHEMA public
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO imga_app, imga_admin;
    ALTER DEFAULT PRIVILEGES FOR ROLE "$POSTGRES_USER" IN SCHEMA public
        GRANT USAGE, SELECT ON SEQUENCES TO imga_app, imga_admin;
EOSQL
