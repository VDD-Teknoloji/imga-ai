"""tenant_deletion_audit + data_purge_audit — İmga v1 KVKK (contract §4.8/§9).

  * tenant_deletion_audit — DELETE /v1/data/{session_id} kanıtı: session_id →
    purge_job_id, requested_at, completed_at, rows_deleted. RLS+FORCE (tenant kendi).
  * data_purge_audit — 30-gün retention purge kanıtı (§9): cutoff, rows_purged.
    Sistem/ops kaydı; deny-all RLS (imga_app görmez, imga_admin BYPASSRLS).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0034"
down_revision: str = "0033"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tenant_deletion_audit",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id", UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("session_id", UUID(as_uuid=True), nullable=False),
        sa.Column("purge_job_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "requested_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("rows_deleted", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_tenant_deletion_audit_tenant", "tenant_deletion_audit", ["tenant_id"]
    )
    op.execute("ALTER TABLE tenant_deletion_audit ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenant_deletion_audit FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON tenant_deletion_audit
            FOR ALL
            USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
        """
    )

    # data_purge_audit — sistem/ops; deny-all RLS (yalnız BYPASSRLS erişir).
    op.create_table(
        "data_purge_audit",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "purged_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("cutoff_date", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("rows_purged", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.execute("ALTER TABLE data_purge_audit ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE data_purge_audit FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("ALTER TABLE data_purge_audit DISABLE ROW LEVEL SECURITY")
    op.drop_table("data_purge_audit")

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON tenant_deletion_audit")
    op.execute("ALTER TABLE tenant_deletion_audit DISABLE ROW LEVEL SECURITY")
    op.drop_index(
        "ix_tenant_deletion_audit_tenant", table_name="tenant_deletion_audit"
    )
    op.drop_table("tenant_deletion_audit")
