"""Sprint 9.0.5-B — action extraction log + briefing top_action_ids + trend_alert dedupe

Revision ID: 0024
Revises: 0023
Create Date: 2026-01-24 00:00:00

Sprint 9.0.5-B foundation. Three additions tied to two
code-review (P1+P2) bugs + one demo-feature linkage:

  1. ``action_items_extraction_log`` (G) — UNIQUE index keyed on
     (tenant_id, source_type, source_id, fingerprint) so re-running
     extraction over the same source content is a no-op. The
     fingerprint is ``sha256(source_content + extraction_version)``
     so a content edit (source_id stays the same) re-extracts; a
     re-render with the same content does not. RLS+FORCE; same
     convention as 0006 / 0019 / 0021.

  2. ``executive_briefings.top_action_item_ids`` (G) — UUID array
     linking the briefing to the ActionItem rows extracted from
     its top_actions field. Frontend joins this for clickable
     "follow up" cards on the briefing detail page.

  3. ``trend_alerts.fingerprint`` + ``trend_alerts.evaluated_at``
     (I) — daily UNIQUE index on (tenant_id, fingerprint,
     DATE(evaluated_at)) so re-running ``/evaluate`` on an
     unchanged condition (same NPS drop band, same week, etc.)
     doesn't spam duplicate alert rows. Calendar-day granularity
     keeps the condition fresh on rolling windows that span
     midnight.

Forward-only — Sprint 8.3.5.2 dersi.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision: str = "0024"
down_revision: str | Sequence[str] | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. action_items_extraction_log -------------------------------------
    op.create_table(
        "action_items_extraction_log",
        sa.Column(
            "id",
            PG_UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column(
            "source_id", PG_UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "extraction_fingerprint", sa.String(length=64), nullable=False
        ),
        sa.Column(
            "action_item_ids",
            ARRAY(PG_UUID(as_uuid=True)),
            nullable=False,
            server_default=sa.text("ARRAY[]::uuid[]"),
        ),
        sa.Column(
            "extracted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "source_type IN ('strategic_report', 'executive_briefing')",
            name="ck_action_extraction_log_source_type",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "source_type",
            "source_id",
            "extraction_fingerprint",
            name="uq_action_extraction_log_fingerprint",
        ),
    )
    op.execute(
        "ALTER TABLE action_items_extraction_log "
        "ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        "ALTER TABLE action_items_extraction_log "
        "FORCE ROW LEVEL SECURITY"
    )
    op.execute(
        "CREATE POLICY tenant_isolation ON action_items_extraction_log "
        "USING (tenant_id = current_setting('app.current_tenant_id')::uuid)"
    )

    # 2. executive_briefings.top_action_item_ids -------------------------
    op.add_column(
        "executive_briefings",
        sa.Column(
            "top_action_item_ids",
            ARRAY(PG_UUID(as_uuid=True)),
            nullable=False,
            server_default=sa.text("ARRAY[]::uuid[]"),
        ),
    )
    # GIN index so the JOIN-by-membership query
    #   SELECT * FROM action_items WHERE id = ANY(top_action_item_ids)
    # plus reverse lookups stay fast as the array grows.
    op.execute(
        "CREATE INDEX ix_executive_briefings_top_action_items "
        "ON executive_briefings USING GIN (top_action_item_ids)"
    )

    # 3. trend_alerts dedupe columns + per-day UNIQUE index --------------
    op.add_column(
        "trend_alerts",
        sa.Column(
            "fingerprint",
            sa.String(length=64),
            nullable=False,
            server_default=sa.text("''"),
        ),
    )
    op.add_column(
        "trend_alerts",
        sa.Column(
            "evaluated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    # Calendar-day grain so the same condition doesn't fire twice
    # per day, but a true day-over-day repeat still flows through
    # to a fresh alert. Postgres treats ``timestamptz::date`` as
    # mutable (the result depends on the session timezone), so the
    # index expression has to anchor the timezone explicitly —
    # ``(timestamptz AT TIME ZONE 'UTC')::date`` is IMMUTABLE per
    # the docs. The day boundary is therefore UTC-anchored, which
    # is what the service's _filter_already_emitted_today already
    # assumes.
    op.execute(
        "CREATE UNIQUE INDEX uq_trend_alerts_fingerprint_per_day "
        "ON trend_alerts ("
        "tenant_id, fingerprint, "
        "((evaluated_at AT TIME ZONE 'UTC')::date)"
        ") "
        "WHERE fingerprint <> ''"
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS uq_trend_alerts_fingerprint_per_day"
    )
    op.drop_column("trend_alerts", "evaluated_at")
    op.drop_column("trend_alerts", "fingerprint")

    op.execute(
        "DROP INDEX IF EXISTS ix_executive_briefings_top_action_items"
    )
    op.drop_column("executive_briefings", "top_action_item_ids")

    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation ON action_items_extraction_log"
    )
    op.execute(
        "ALTER TABLE action_items_extraction_log "
        "DISABLE ROW LEVEL SECURITY"
    )
    op.drop_table("action_items_extraction_log")
