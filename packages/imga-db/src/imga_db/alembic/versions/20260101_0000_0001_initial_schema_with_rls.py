"""initial schema with RLS

Revision ID: 0001
Revises:
Create Date: 2026-01-01 00:00:00

Creates the four bootstrap tables (tenants, users, user_tenants,
audit_logs), enables Row-Level Security with FORCE on the tenant-scoped
tables, and seeds a super-admin user from environment variables.
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSON, UUID

# revision identifiers
revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- tenants ----------------------------------------------------------
    op.create_table(
        "tenants",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        sa.Column("plan_tier", sa.String(32), nullable=False, server_default="trial"),
        sa.Column("automation_mode", sa.String(32), nullable=False, server_default="semi_auto"),
        sa.Column("category_overrides", JSON, nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("settings", JSON, nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_tenants_slug", "tenants", ["slug"], unique=True)
    op.create_index("ix_tenants_deleted_at", "tenants", ["deleted_at"])

    # --- users ------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_super_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_deleted_at", "users", ["deleted_at"])

    # --- user_tenants (RLS-tabi) -----------------------------------------
    op.create_table(
        "user_tenants",
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("invited_by_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("invitation_accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_user_tenants_tenant_id", "user_tenants", ["tenant_id"])

    # --- audit_logs (RLS-tabi when tenant_id is set) ---------------------
    op.create_table(
        "audit_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("actor_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("resource_id", UUID(as_uuid=True), nullable=True),
        sa.Column("details", JSON, nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_audit_logs_tenant_id", "audit_logs", ["tenant_id"])
    op.create_index("ix_audit_logs_actor_user_id", "audit_logs", ["actor_user_id"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])

    # --- RLS: tenant-scoped tables ---------------------------------------
    # FOR ALL covers SELECT/INSERT/UPDATE/DELETE in one policy.
    # FORCE makes the policy apply even to the table owner (imga_owner).
    for table in ("user_tenants", "audit_logs"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
                FOR ALL
                USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
                WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
            """
        )

    # --- Super-admin seed -------------------------------------------------
    super_admin_email = os.environ.get("SUPER_ADMIN_EMAIL", "admin@imga.ai")
    initial_password = os.environ.get("SUPER_ADMIN_INITIAL_PASSWORD", "change_on_first_login")
    # Hash with argon2 using the same library the API will verify with.
    try:
        from argon2 import PasswordHasher

        password_hash = PasswordHasher().hash(initial_password)
    except ImportError:
        # argon2 not available in this migration env; store a placeholder
        # marker. The API's first-login flow MUST refuse this token and force
        # password reset.
        password_hash = f"PLACEHOLDER:{secrets.token_urlsafe(16)}"

    op.execute(
        sa.text(
            """
            INSERT INTO users (email, password_hash, full_name, is_super_admin)
            VALUES (:email, :pw, 'Super Admin', true)
            ON CONFLICT (email) DO NOTHING
            """
        ).bindparams(email=super_admin_email, pw=password_hash)
    )


def downgrade() -> None:
    for table in ("audit_logs", "user_tenants"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.drop_index("ix_audit_logs_action", table_name="audit_logs")
    op.drop_index("ix_audit_logs_actor_user_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_tenant_id", table_name="audit_logs")
    op.drop_table("audit_logs")

    op.drop_index("ix_user_tenants_tenant_id", table_name="user_tenants")
    op.drop_table("user_tenants")

    op.drop_index("ix_users_deleted_at", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")

    op.drop_index("ix_tenants_deleted_at", table_name="tenants")
    op.drop_index("ix_tenants_slug", table_name="tenants")
    op.drop_table("tenants")
