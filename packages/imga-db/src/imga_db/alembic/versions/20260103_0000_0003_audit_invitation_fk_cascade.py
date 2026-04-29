"""audit_logs and invitations FK on-delete behaviour

Revision ID: 0003
Revises: 0002
Create Date: 2026-01-03 00:00:00

The original FK definitions left audit_logs.tenant_id and
invitations.invited_by as RESTRICT, which made tenant / user deletion
fail when any audit row or invitation referenced them. Production
expects:
  - audit_logs.tenant_id      -> ON DELETE CASCADE (logs follow tenant)
  - audit_logs.actor_user_id  -> ON DELETE SET NULL (keep history when user gone)
  - invitations.invited_by    -> ON DELETE SET NULL (keep invitation record)

Rewriting FKs in PostgreSQL means DROP + ADD, so this migration is not
idempotent across major schema redesigns; it is for the current schema
only.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # user_tenants.invited_by_user_id -> SET NULL (admin can leave; link
    # survives; otherwise tenant member listings break when an admin who
    # invited people is removed).
    op.drop_constraint(
        "user_tenants_invited_by_user_id_fkey",
        "user_tenants",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "user_tenants_invited_by_user_id_fkey",
        "user_tenants",
        "users",
        ["invited_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # audit_logs.tenant_id -> CASCADE
    op.drop_constraint("audit_logs_tenant_id_fkey", "audit_logs", type_="foreignkey")
    op.create_foreign_key(
        "audit_logs_tenant_id_fkey",
        "audit_logs",
        "tenants",
        ["tenant_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # audit_logs.actor_user_id -> SET NULL (keep audit when actor deleted)
    op.drop_constraint("audit_logs_actor_user_id_fkey", "audit_logs", type_="foreignkey")
    op.create_foreign_key(
        "audit_logs_actor_user_id_fkey",
        "audit_logs",
        "users",
        ["actor_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # invitations.invited_by -> SET NULL (admin can leave; record stays)
    # invitations was created in 0002 with a generated FK name we need to discover.
    op.execute(
        """
        DO $$
        DECLARE
            cname text;
        BEGIN
            SELECT constraint_name INTO cname
            FROM information_schema.table_constraints
            WHERE table_name = 'invitations'
              AND constraint_type = 'FOREIGN KEY'
              AND constraint_name LIKE '%invited_by%';
            IF cname IS NOT NULL THEN
                EXECUTE format('ALTER TABLE invitations DROP CONSTRAINT %I', cname);
            END IF;
        END$$;
        """
    )
    op.create_foreign_key(
        "invitations_invited_by_fkey",
        "invitations",
        "users",
        ["invited_by"],
        ["id"],
        ondelete="SET NULL",
    )
    # invited_by was NOT NULL; relax it so SET NULL can fire.
    op.alter_column("invitations", "invited_by", nullable=True)


def downgrade() -> None:
    op.alter_column("invitations", "invited_by", nullable=False)
    op.drop_constraint("invitations_invited_by_fkey", "invitations", type_="foreignkey")
    op.create_foreign_key(
        "invitations_invited_by_fkey",
        "invitations",
        "users",
        ["invited_by"],
        ["id"],
    )

    op.drop_constraint("audit_logs_actor_user_id_fkey", "audit_logs", type_="foreignkey")
    op.create_foreign_key(
        "audit_logs_actor_user_id_fkey",
        "audit_logs",
        "users",
        ["actor_user_id"],
        ["id"],
    )

    op.drop_constraint("audit_logs_tenant_id_fkey", "audit_logs", type_="foreignkey")
    op.create_foreign_key(
        "audit_logs_tenant_id_fkey",
        "audit_logs",
        "tenants",
        ["tenant_id"],
        ["id"],
    )

    op.drop_constraint(
        "user_tenants_invited_by_user_id_fkey",
        "user_tenants",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "user_tenants_invited_by_user_id_fkey",
        "user_tenants",
        "users",
        ["invited_by_user_id"],
        ["id"],
    )
