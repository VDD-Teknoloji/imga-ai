"""Company knowledge, living PRD and retention observations.

Revision ID: 0051
Revises: 0050
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0051"
down_revision: str | Sequence[str] | None = "0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "intelligence_revisions",
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("kind", sa.String(16), primary_key=True),
        sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("content", JSONB(), nullable=False),
        sa.Column("actor_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("kind IN ('company', 'prd')", name="ck_intelligence_kind"),
        sa.CheckConstraint("status IN ('draft', 'approved')", name="ck_intelligence_status"),
        sa.CheckConstraint("revision > 0", name="ck_intelligence_revision"),
    )
    op.create_table(
        "customer_accounts",
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("external_id", sa.String(128), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("profile", JSONB(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("revision > 0", name="ck_customer_account_revision"),
    )
    op.create_table(
        "customer_observations",
        sa.Column("tenant_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("external_id", sa.String(128), primary_key=True),
        sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column("profile", JSONB(), nullable=False),
        sa.Column("risk", JSONB(), nullable=False),
        sa.Column("actor_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "external_id"],
            ["customer_accounts.tenant_id", "customer_accounts.external_id"],
            ondelete="CASCADE",
        ),
    )
    for table in ("intelligence_revisions", "customer_accounts", "customer_observations"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} FOR ALL "
            "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid) "
            "WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
        )
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO imga_app, imga_admin")
    op.add_column("reviews", sa.Column("customer_external_id", sa.String(128), nullable=True))
    op.add_column("reviews", sa.Column("analysis_profile", sa.String(16), nullable=True))
    op.add_column("reviews", sa.Column("analysis_language", sa.String(16), nullable=True))
    op.create_index(
        "ix_reviews_customer_date",
        "reviews",
        ["tenant_id", "customer_external_id", "review_date"],
        postgresql_where=sa.text("customer_external_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_column("reviews", "analysis_language")
    op.drop_column("reviews", "analysis_profile")
    op.drop_index("ix_reviews_customer_date", table_name="reviews")
    op.drop_column("reviews", "customer_external_id")
    for table in ("customer_observations", "customer_accounts", "intelligence_revisions"):
        op.drop_table(table)
