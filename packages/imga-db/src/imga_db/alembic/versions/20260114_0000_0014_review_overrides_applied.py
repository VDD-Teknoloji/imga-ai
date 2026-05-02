"""reviews.overrides_applied jsonb — override layer trace per review

Revision ID: 0014
Revises: 0013
Create Date: 2026-01-14 00:00:00

Sprint 8.3.4. Sprint 8.3.3 stubbed the override-stats endpoint with
zero counts because the column wasn't here yet; this migration adds
``reviews.overrides_applied`` as JSONB and the analytics service flips
to the real aggregation. Existing rows stay NULL — they were analyzed
before the trace was persisted, so we have no data to backfill.

Schema of the array (validated on the way in by ReviewService):

    [
      {
        "layer": "critical|knowledge_base|tier1|sla|tier2",
        "matched_keywords": ["..."],
        "score": -0.85,
        "detail": "optional human-readable trigger reason"
      },
      ...
    ]

The empty case is `[]`, NOT `null` — distinguishes "we ran the pipeline
and nothing fired" from "this row predates the column". The jsonb_path
GIN index supports the analytics service's lateral-unnest query
(`SELECT layer, count(*) FROM reviews, jsonb_array_elements(...) ...`).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers
revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "reviews",
        sa.Column("overrides_applied", JSONB(), nullable=True),
    )
    # GIN index on the JSONB column. Analytics queries unnest the
    # array via LATERAL jsonb_array_elements; the index doesn't speed
    # that scan directly, but it makes the "rows where any override
    # fired" filter cheap (used by override-stats trigger_count vs
    # total_reviews ratio when the user filters on a date range).
    op.create_index(
        "ix_reviews_overrides_applied_gin",
        "reviews",
        ["overrides_applied"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_reviews_overrides_applied_gin", table_name="reviews")
    op.drop_column("reviews", "overrides_applied")
