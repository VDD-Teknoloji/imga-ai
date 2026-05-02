"""report_jobs table — multi-sheet Excel/CSV export pipeline

Revision ID: 0013
Revises: 0012
Create Date: 2026-01-13 00:00:00

Sprint 8.3.2. Each ``POST /tenants/me/reports/generate`` upload writes
one row here; the in-process APScheduler worker drains it (xlsxwriter
or csv-zip), saves to ``/var/imga/reports/{tenant}/{job}.{ext}``, and
flips the row to ``completed``. The 24h cleanup cron reaps both the
file AND eventually the row (via ``expires_at`` filter), but ``file_path``
survives as audit trail even after the on-disk blob is gone — same
pattern as ``analyze_batch_jobs``.

Filter validation lives at request time:

  * date_to - date_from <= 90 days
  * estimated row count <= 50K

so that we never queue a generation that we know we cannot deliver.

RLS+FORCE on tenant_id, identical policy convention to migration
0006/0008/0010/0012.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers
revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "report_jobs",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "triggered_by_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="queued"),
        sa.Column("report_type", sa.String(length=32), nullable=False),
        sa.Column("format", sa.String(length=8), nullable=False),
        sa.Column("filters", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("file_path", sa.String(length=512), nullable=True),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'generating', 'completed', 'failed')",
            name="ck_report_jobs_status",
        ),
        sa.CheckConstraint(
            "report_type IN ('comprehensive', 'reviews_only', 'tickets_only')",
            name="ck_report_jobs_type",
        ),
        sa.CheckConstraint(
            "format IN ('xlsx', 'csv')",
            name="ck_report_jobs_format",
        ),
    )
    op.create_index(
        "ix_report_jobs_tenant_created",
        "report_jobs",
        ["tenant_id", sa.text("created_at DESC")],
    )
    # Partial index for the cleanup cron — only completed rows have an
    # ``expires_at`` worth scanning. Worth its disk cost since the
    # cleanup query runs hourly across all tenants.
    op.create_index(
        "ix_report_jobs_completed_expires",
        "report_jobs",
        ["expires_at"],
        postgresql_where=sa.text("status = 'completed'"),
    )

    op.execute("ALTER TABLE report_jobs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE report_jobs FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON report_jobs
            FOR ALL
            USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON report_jobs")
    op.execute("ALTER TABLE report_jobs DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_report_jobs_completed_expires", table_name="report_jobs")
    op.drop_index("ix_report_jobs_tenant_created", table_name="report_jobs")
    op.drop_table("report_jobs")
