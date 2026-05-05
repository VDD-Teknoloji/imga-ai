"""Sprint 9.0.5-A — analyze_batch_jobs worker handle columns

Revision ID: 0023
Revises: 0022
Create Date: 2026-01-23 00:00:00

Sprint 9.0.5-A. Batch dispatch moves from in-process APScheduler to an
arq-backed background worker container so a long-running BERT
inference can't block the API event loop (today's 21-min freeze
incident on a 2852-row CSV had processed_rows stuck at 0 because the
sync transformers C extension never yielded — the API itself stopped
serving /reviews / /insights until restart).

Two new columns let the route + UI follow the queued state through:

  * ``worker_job_id`` — arq's per-enqueue identifier. Lets us cancel
    or re-enqueue a specific run when the queue is shared across
    multiple containers.
  * ``queued_at`` — the moment the row entered the queue. Distinct
    from ``created_at`` because batch row creation and queue
    submission are now logically separate (the route writes the row
    on disk, then enqueues; failure between those two leaves a
    consistent QUEUED row that can be re-enqueued by hand).

Partial index on ``worker_job_id`` keeps the single-job lookup fast
without bloating the index for the (large) historic completed-job
tail where the column is NULL.

Forward-only — Sprint 8.3.5.2 dersi.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | Sequence[str] | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "analyze_batch_jobs",
        sa.Column("worker_job_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "analyze_batch_jobs",
        sa.Column(
            "queued_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_batch_jobs_worker_job_id",
        "analyze_batch_jobs",
        ["worker_job_id"],
        postgresql_where=sa.text("worker_job_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_batch_jobs_worker_job_id",
        table_name="analyze_batch_jobs",
    )
    op.drop_column("analyze_batch_jobs", "queued_at")
    op.drop_column("analyze_batch_jobs", "worker_job_id")
