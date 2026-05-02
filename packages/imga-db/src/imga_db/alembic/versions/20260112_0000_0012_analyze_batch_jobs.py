"""analyze_batch_jobs table + reviews.batch_job_id FK

Revision ID: 0012
Revises: 0011
Create Date: 2026-01-12 00:00:00

Sprint 8.3.1 — bulk CSV/XLSX upload pipeline. Each upload becomes one
``analyze_batch_jobs`` row that the in-process APScheduler worker drains
chunk-by-chunk through ``AnalysisPipeline.analyze_batch`` and
``ReviewService.record_and_decide``. Reviews emitted by a job carry
``batch_job_id`` so the UI can filter "show me everything from THIS
upload" without joining through tickets.

Schema notes:

  * ``status`` is queued | processing | completed | failed | cancelled.
    Stored as varchar (not enum) for the same reason ticket states are:
    enum-evolution requires a migration round-trip and we'd rather
    extend with a code change.
  * ``file_path`` survives even after the on-disk file is reaped by
    the daily cleanup cron — the column is the audit trail of where
    the upload lived. Tests assert: cleanup nulls the disk file but
    NOT this column.
  * ``error_summary`` is a bounded JSONB list (worker caps at 100
    entries). Larger error rates fail the job outright rather than
    grow the column unbounded.
  * RLS+FORCE on tenant_id, identical policy convention to migration
    0006/0008/0010.
  * ``reviews.batch_job_id`` is nullable + FK ON DELETE SET NULL so a
    purged job leaves the review history intact. Partial index keeps
    the "filter by batch" query fast without paying for tickets that
    came from /analyze (which dominate the table).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers
revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "analyze_batch_jobs",
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
        sa.Column("file_name", sa.String(length=256), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("file_path", sa.String(length=512), nullable=False),
        sa.Column("text_column", sa.String(length=64), nullable=False),
        sa.Column("source_column", sa.String(length=64), nullable=True),
        sa.Column(
            "auto_create_tickets",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("total_rows", sa.Integer(), nullable=False),
        sa.Column(
            "processed_rows", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "succeeded_rows", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "failed_rows", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "tickets_created", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "duplicates_skipped", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "error_summary",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'processing', 'completed', 'failed', 'cancelled')",
            name="ck_analyze_batch_jobs_status",
        ),
        sa.CheckConstraint(
            "processed_rows <= total_rows",
            name="ck_analyze_batch_jobs_processed_le_total",
        ),
    )
    op.create_index(
        "ix_batch_jobs_tenant_status",
        "analyze_batch_jobs",
        ["tenant_id", "status"],
    )
    op.create_index(
        "ix_batch_jobs_tenant_created",
        "analyze_batch_jobs",
        ["tenant_id", sa.text("created_at DESC")],
    )

    op.execute("ALTER TABLE analyze_batch_jobs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE analyze_batch_jobs FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON analyze_batch_jobs
            FOR ALL
            USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
        """
    )

    # reviews.batch_job_id — nullable, SET NULL on job purge so soft-
    # deleting a job retains the analyze history.
    op.add_column(
        "reviews",
        sa.Column(
            "batch_job_id",
            UUID(as_uuid=True),
            sa.ForeignKey("analyze_batch_jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_reviews_batch",
        "reviews",
        ["batch_job_id"],
        postgresql_where=sa.text("batch_job_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_reviews_batch", table_name="reviews")
    op.drop_column("reviews", "batch_job_id")

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON analyze_batch_jobs")
    op.execute("ALTER TABLE analyze_batch_jobs DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_batch_jobs_tenant_created", table_name="analyze_batch_jobs")
    op.drop_index("ix_batch_jobs_tenant_status", table_name="analyze_batch_jobs")
    op.drop_table("analyze_batch_jobs")
