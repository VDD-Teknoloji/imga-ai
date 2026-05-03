"""reviews.nps_score + nps_category computed column

Revision ID: 0015
Revises: 0014
Create Date: 2026-01-15 00:00:00

Sprint 8.3.5 / Alt-Faz 8.3.5.1 (Prework). Adds NPS support to the
``reviews`` table:

  * ``nps_score`` SMALLINT (0–10), nullable. NULL means "no NPS captured
    for this row" — pre-migration rows + manual /analyze calls without a
    score + batch uploads where no NPS column was detected.

  * ``nps_category`` GENERATED ALWAYS AS STORED column derived from
    ``nps_score`` via the standard NPS bucketing:
      0–6  → 'detractor'
      7–8  → 'passive'
      9–10 → 'promoter'
      NULL → NULL
    Stored (not virtual) so analytics filters can hit a B-tree index
    instead of recomputing the CASE per query.

  * Partial index on ``nps_category`` (only the rows that have NPS) for
    fast distribution counts.
  * Partial composite index on ``(tenant_id, created_at)`` filtered to
    rows with NPS, for the monthly trend aggregation.

The check constraint ``ck_reviews_nps_score_range`` is the only place the
0..10 invariant is enforced — at the schema layer, not in app code.

The ``analyze_batch_jobs`` metadata columns (``detected_nps_column`` +
``rows_with_nps``) ship in 0016 (Alt-Faz 8.3.5.2). They were originally
planned to land in this same migration, but 0015 had already been
applied to the test stack at that point so amending it would have been
silent (alembic skips already-applied revisions). 0016 is forward-only
and clean for both fresh + already-bootstrapped envs.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "0015"
down_revision: str | Sequence[str] | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "reviews",
        sa.Column("nps_score", sa.SmallInteger(), nullable=True),
    )
    op.create_check_constraint(
        "ck_reviews_nps_score_range",
        "reviews",
        "nps_score IS NULL OR (nps_score >= 0 AND nps_score <= 10)",
    )

    # GENERATED ALWAYS STORED column. Postgres maintains it on every
    # insert/update; the ORM never writes it.
    op.execute(
        """
        ALTER TABLE reviews
        ADD COLUMN nps_category VARCHAR(16)
        GENERATED ALWAYS AS (
            CASE
                WHEN nps_score IS NULL THEN NULL
                WHEN nps_score <= 6 THEN 'detractor'
                WHEN nps_score <= 8 THEN 'passive'
                ELSE 'promoter'
            END
        ) STORED
        """
    )

    op.create_index(
        "ix_reviews_nps_category",
        "reviews",
        ["nps_category"],
        postgresql_where=sa.text("nps_category IS NOT NULL"),
    )
    op.create_index(
        "ix_reviews_tenant_nps_created",
        "reviews",
        ["tenant_id", "created_at"],
        postgresql_where=sa.text("nps_score IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_reviews_tenant_nps_created", table_name="reviews")
    op.drop_index("ix_reviews_nps_category", table_name="reviews")
    op.drop_column("reviews", "nps_category")
    op.drop_constraint("ck_reviews_nps_score_range", "reviews", type_="check")
    op.drop_column("reviews", "nps_score")
