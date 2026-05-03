"""reviews.company_perspective_code — heuristic taxonomy match per row

Revision ID: 0018
Revises: 0017
Create Date: 2026-01-18 00:00:00

Sprint 8.3.5 / Alt-Faz 8.3.5.6. Persists the company-perspective code
the heuristic reranker (8.3.5.5) picked at analyze time. Stored as a
plain VARCHAR — *not* an FK to category_taxonomies — because the
taxonomy is per-tenant and editable in 8.3.7. A taxonomy edit must not
break historical reviews; if a code disappears the row simply renders
as the raw code in the UI (or the frontend resolves to a "removed
category" badge).

Partial index ``ix_reviews_tenant_perspective`` covers the dominant
analytics query "give me reviews of perspective X for tenant Y", and
the partial WHERE keeps the index small for tenants that haven't
analyzed any reviews yet (NULL is the absent state).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "0018"
down_revision: str | Sequence[str] | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "reviews",
        sa.Column("company_perspective_code", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_reviews_tenant_perspective",
        "reviews",
        ["tenant_id", "company_perspective_code"],
        postgresql_where=sa.text("company_perspective_code IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_reviews_tenant_perspective", table_name="reviews")
    op.drop_column("reviews", "company_perspective_code")
