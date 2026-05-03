"""analyze_batch_jobs.detected_nps_column + rows_with_nps

Revision ID: 0016
Revises: 0015
Create Date: 2026-01-16 00:00:00

Sprint 8.3.5 / Alt-Faz 8.3.5.2 (Data Layer). Two columns on
``analyze_batch_jobs`` so the upload summary card can report what NPS
column the parser auto-detected and how many rows landed with a
non-null score:

  * ``detected_nps_column`` VARCHAR(64), nullable. The original header
    name from the upload (e.g. ``"Score"``, ``"NPS"``). NULL means "no
    recognizable NPS header" — different from ``rows_with_nps == 0``,
    which can happen even when the column was detected if every cell
    was blank or out of range.

  * ``rows_with_nps`` INTEGER NOT NULL DEFAULT 0. Worker increments this
    per chunk via the BatchProgress.rows_with_nps_delta field as
    NPS-bearing reviews persist.

Originally planned to ship inside 0015 (the prework migration), but 0015
had been applied to the test stack at that point — amending an
already-applied revision is silent on environments where alembic_version
already says 0015. Splitting into 0016 keeps the upgrade path clean for
both fresh init and already-bootstrapped envs.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "0016"
down_revision: str | Sequence[str] | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "analyze_batch_jobs",
        sa.Column("detected_nps_column", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "analyze_batch_jobs",
        sa.Column(
            "rows_with_nps",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    op.drop_column("analyze_batch_jobs", "rows_with_nps")
    op.drop_column("analyze_batch_jobs", "detected_nps_column")
