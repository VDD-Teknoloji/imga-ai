"""reviews table — analyzed-text archive + auto-ticket bridge log

Revision ID: 0008
Revises: 0007
Create Date: 2026-01-08 00:00:00

Sprint 7.5.5 / Alt-Faz 3: ``POST /tenants/me/analyze`` archives every
analyzed review and the bridge decision (create / skipped_*) made at
ingestion time. This gives us:

  1. **Audit trail** — every decision branch is captured per row
     (``decision`` column) so we can reconstruct *why* a complaint did
     or didn't become a ticket.
  2. **Dedup** — a 24-hour text_hash window collapses duplicate
     submissions of the same review to a single ticket; the second
     submission lands a row with ``decision='skipped_dedup'`` and a
     pointer to the original ticket.
  3. **Future analytics** — Sprint 8 SHI / category distribution
     dashboards read from here rather than re-running classification.

``text_hash`` is sha256 hex over ``normalize_turkish(text).strip()``.
The Turkish normalization lives in ``imga_core.text_utils`` (Sprint
6.10) — same function the keyword classifier uses, so identical
substring matches collapse to identical hashes.

Schema notes:

  * ``automation_mode`` is **snapshotted** at decision time (not
    a foreign key into the live tenant config). If the tenant flips
    manual ↔ full_auto two minutes later, the historical decision
    still shows the mode that produced it.
  * ``ticket_id`` is set both on ``decision='create'`` (newly minted
    ticket) and on ``decision='skipped_dedup'`` (pointer to the
    existing ticket that absorbed this submission). Other branches
    leave it NULL.
  * Composite index ``(tenant_id, text_hash, analyzed_at DESC)``
    backs the dedup-window lookup; partial filter on
    ``ticket_id IS NOT NULL`` keeps it lean — only "rows that
    successfully reached or shared a ticket" need to be scanned.

RLS+FORCE on ``tenant_id``, same policy convention as the rest of
the schema.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers
revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reviews",
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
        sa.Column("text", sa.Text(), nullable=False),
        # SHA-256 hex over normalize_turkish(text).strip(); fixed length
        # 64 hex chars. CHAR(64) keeps the column physically narrow.
        sa.Column("text_hash", sa.CHAR(64), nullable=False),
        sa.Column("sentiment_label", sa.String(8), nullable=False),
        sa.Column("sentiment_score", sa.Float(), nullable=False),
        sa.Column("primary_category", sa.String(64), nullable=False),
        sa.Column("primary_confidence", sa.Float(), nullable=False),
        # Snapshot of the tenant's automation_mode at decision time —
        # NOT a live foreign key (see module docstring).
        sa.Column("automation_mode", sa.String(16), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        # ticket_id is set on 'create' (new ticket) AND 'skipped_dedup'
        # (pointer to the existing ticket). Other decisions leave NULL.
        sa.Column(
            "ticket_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tickets.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "submitted_by_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "analyzed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "decision IN ("
            "'create','skipped_belirsiz','skipped_mode',"
            "'skipped_threshold','skipped_dedup')",
            name="ck_reviews_decision",
        ),
        sa.CheckConstraint(
            "automation_mode IN ('manual','semi_auto','full_auto')",
            name="ck_reviews_automation_mode",
        ),
        sa.CheckConstraint(
            "sentiment_label IN ('NEGATIF','NÖTR','POZITIF')",
            name="ck_reviews_sentiment_label",
        ),
        sa.CheckConstraint(
            "char_length(text_hash) = 64",
            name="ck_reviews_text_hash_length",
        ),
    )

    # Indexes:
    # - tenant_id alone for tenant-scoped scans.
    # - (tenant_id, text_hash, analyzed_at DESC) WHERE ticket_id IS NOT NULL
    #   backs the dedup lookup ("did this same text already get a ticket
    #   in the last 24h?"); partial filter keeps the index small.
    # - (tenant_id, analyzed_at DESC) for review history pagination.
    op.create_index("ix_reviews_tenant_id", "reviews", ["tenant_id"])
    op.create_index(
        "ix_reviews_tenant_dedup",
        "reviews",
        ["tenant_id", "text_hash", sa.text("analyzed_at DESC")],
        postgresql_where=sa.text("ticket_id IS NOT NULL"),
    )
    op.create_index(
        "ix_reviews_tenant_analyzed_at",
        "reviews",
        ["tenant_id", sa.text("analyzed_at DESC")],
    )
    op.create_index("ix_reviews_ticket_id", "reviews", ["ticket_id"])
    op.create_index("ix_reviews_deleted_at", "reviews", ["deleted_at"])

    op.execute("ALTER TABLE reviews ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE reviews FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON reviews
            FOR ALL
            USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON reviews")
    op.execute("ALTER TABLE reviews DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_reviews_deleted_at", table_name="reviews")
    op.drop_index("ix_reviews_ticket_id", table_name="reviews")
    op.drop_index("ix_reviews_tenant_analyzed_at", table_name="reviews")
    op.drop_index("ix_reviews_tenant_dedup", table_name="reviews")
    op.drop_index("ix_reviews_tenant_id", table_name="reviews")
    op.drop_table("reviews")
