"""Sprint 9.2 — metric registry, KPI goals, executive snapshots, scheduled briefings

Revision ID: 0026
Revises: 0025
Create Date: 2026-05-14 00:00:00

Four tables drop together because they share the same C-Level
contract: a metric registry that the rest of the platform agrees
on, goals expressed in the registry's units, snapshots that cache
the goal-bearing computation, and a scheduler that emits briefings
referencing both.

  1. ``metric_definitions`` — tenant-agnostic registry of every
     KPI the platform reports. ``canonical_implementation`` is a
     ``module:attr`` pointer (imga_core.metrics.nps:score) that the
     services agree to call so a future "what is NPS exactly" Slack
     thread has one answer. Seeded at upgrade time with the six
     metrics already in active use.

  2. ``tenant_kpi_goals`` — per-tenant target/period/value with
     RLS+FORCE. Active goals (``period_end >= CURRENT_DATE``) are
     surfaced on the dashboard via a partial index hot path.

  3. ``executive_snapshots`` — cached metric bundle keyed on
     (tenant_id, period, snapshot_date). The cursor column
     ``last_review_id_at_snapshot`` lets the snapshot service tell
     when the cache is stale (any review id newer than the cursor
     means the upstream changed).

  4. ``briefing_schedules`` — recurring weekly/monthly briefing
     trigger. ``next_run_at`` is the column the arq cron worker
     scans every 5 minutes for due rows.

Forward-only — Sprint 8.3.5.2 dersi.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision: str = "0026"
down_revision: str | Sequence[str] | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_PERIOD_GOAL = ("weekly", "monthly", "quarterly", "yearly")
_PERIOD_SNAPSHOT = ("daily", "weekly", "monthly")
_PERIOD_SCHEDULE = ("weekly", "monthly")
_AGGREGATIONS = (
    "aggregate",
    "average",
    "count",
    "distinct_count",
    "percentage",
    "distribution",
    "ratio",
    "sum",
)


def upgrade() -> None:
    # 1. metric_definitions ----------------------------------------------
    op.create_table(
        "metric_definitions",
        sa.Column(
            "id",
            PG_UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("metric_key", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("formula", sa.Text(), nullable=False),
        sa.Column("unit", sa.Text(), nullable=False),
        sa.Column("range_min", sa.Numeric(), nullable=True),
        sa.Column("range_max", sa.Numeric(), nullable=True),
        sa.Column(
            "higher_is_better",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("TRUE"),
        ),
        sa.Column("aggregation", sa.Text(), nullable=False),
        sa.Column("canonical_implementation", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint("metric_key", name="uq_metric_definitions_key"),
        sa.CheckConstraint(
            "aggregation IN (" + ", ".join(f"'{a}'" for a in _AGGREGATIONS) + ")",
            name="ck_metric_definitions_aggregation",
        ),
    )
    # Tenant-agnostic — no RLS. Read by every tenant's UI.

    # Seed the six metrics already in production use. Keeping the
    # insert in the migration (rather than a separate data-migration
    # helper) means a fresh DB has the registry from row zero.
    op.execute(
        """
        INSERT INTO metric_definitions
            (metric_key, display_name, description, formula, unit,
             range_min, range_max, higher_is_better, aggregation,
             canonical_implementation)
        VALUES
            ('nps',
             'Net Promoter Score',
             'Promoter % minus Detractor % over the NPS-bearing review pool.',
             '((promoter_count - detractor_count) / nps_bearing_count) * 100',
             'score', -100, 100, TRUE, 'aggregate',
             'imga_core.metrics.nps:score_from_buckets'),
            ('csat',
             'Customer Satisfaction Score',
             'Average satisfaction rating scaled to 0-100.',
             'mean(rating) * 20',
             'percentage', 0, 100, TRUE, 'average',
             'imga_core.metrics.csat:score_from_ratings'),
            ('review_volume',
             'Review Volume',
             'Total review rows in scope.',
             'count(*)',
             'count', 0, NULL, TRUE, 'count',
             'imga_core.metrics.volume:count_reviews'),
            ('category_concentration',
             'Category Concentration (Herfindahl)',
             'Sum of squared category share — 0=spread evenly, 1=one category dominates.',
             'sum(category_share^2)',
             'ratio', 0, 1, FALSE, 'aggregate',
             'imga_core.metrics.concentration:herfindahl_index'),
            ('sentiment_distribution',
             'Sentiment Distribution',
             'Percent breakdown across positive / neutral / negative.',
             'pct_breakdown(sentiment_label)',
             'percentage', 0, 100, TRUE, 'distribution',
             'imga_core.metrics.sentiment:distribution_from_labels'),
            ('manual_review_rate',
             'Manual Review Rate',
             'Share of reviews routed to manual operator review.',
             '(manual_review_count / total) * 100',
             'percentage', 0, 100, FALSE, 'percentage',
             'imga_core.metrics.manual_review:rate_from_flags');
        """
    )

    # 2. tenant_kpi_goals ------------------------------------------------
    op.create_table(
        "tenant_kpi_goals",
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
        sa.Column(
            "metric_key",
            sa.Text(),
            sa.ForeignKey(
                "metric_definitions.metric_key",
                ondelete="RESTRICT",
                onupdate="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("target_value", sa.Numeric(), nullable=False),
        sa.Column("target_period", sa.Text(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column(
            "set_by_user_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "set_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.UniqueConstraint(
            "tenant_id",
            "metric_key",
            "target_period",
            "period_start",
            name="uq_tenant_kpi_goals_period",
        ),
        sa.CheckConstraint(
            "target_period IN ("
            + ", ".join(f"'{p}'" for p in _PERIOD_GOAL)
            + ")",
            name="ck_tenant_kpi_goals_period",
        ),
        sa.CheckConstraint(
            "period_end >= period_start",
            name="ck_tenant_kpi_goals_period_order",
        ),
    )
    # Sprint 9.2 B — composite index on (tenant_id, period_end). The
    # partial-index variant (``WHERE period_end >= CURRENT_DATE``) is
    # what the dashboard hot path wants, but ``CURRENT_DATE`` is not
    # IMMUTABLE in Postgres index predicates (same trap migration
    # 0024 hit with ``evaluated_at::date``). The full B-tree is fine
    # — the dashboard's ``period_end >= CURRENT_DATE`` filter at
    # query time still uses this index for the prefix scan, and
    # archived-goal accumulation grows linearly with tenant size,
    # not with active-goal count.
    op.create_index(
        "idx_tenant_kpi_goals_active",
        "tenant_kpi_goals",
        ["tenant_id", "period_end"],
    )
    op.execute("ALTER TABLE tenant_kpi_goals ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenant_kpi_goals FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON tenant_kpi_goals "
        "USING (tenant_id = current_setting('app.current_tenant_id')::uuid)"
    )

    # 3. executive_snapshots --------------------------------------------
    op.create_table(
        "executive_snapshots",
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
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("period", sa.Text(), nullable=False),
        sa.Column(
            "metrics",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "review_count_at_snapshot",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "last_review_id_at_snapshot",
            PG_UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "computation_duration_ms",
            sa.Integer(),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "snapshot_date",
            "period",
            name="uq_executive_snapshots_period",
        ),
        sa.CheckConstraint(
            "period IN ("
            + ", ".join(f"'{p}'" for p in _PERIOD_SNAPSHOT)
            + ")",
            name="ck_executive_snapshots_period",
        ),
    )
    op.create_index(
        "idx_executive_snapshots_lookup",
        "executive_snapshots",
        ["tenant_id", "period", sa.text("snapshot_date DESC")],
    )
    op.execute("ALTER TABLE executive_snapshots ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE executive_snapshots FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON executive_snapshots "
        "USING (tenant_id = current_setting('app.current_tenant_id')::uuid)"
    )

    # 4. briefing_schedules ---------------------------------------------
    op.create_table(
        "briefing_schedules",
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
        sa.Column("period", sa.Text(), nullable=False),
        sa.Column("schedule_day", sa.Integer(), nullable=False),
        sa.Column(
            "schedule_hour",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("9"),
        ),
        sa.Column(
            "timezone",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'Europe/Istanbul'"),
        ),
        sa.Column(
            "recipients",
            ARRAY(PG_UUID(as_uuid=True)),
            nullable=False,
            server_default=sa.text("ARRAY[]::uuid[]"),
        ),
        sa.Column(
            "email_recipients",
            ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("ARRAY[]::text[]"),
        ),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("TRUE"),
        ),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_run_briefing_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey(
                "executive_briefings.id", ondelete="SET NULL"
            ),
            nullable=True,
        ),
        sa.Column("last_run_status", sa.Text(), nullable=True),
        sa.Column("last_run_error", sa.Text(), nullable=True),
        sa.Column(
            "next_run_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "period IN ("
            + ", ".join(f"'{p}'" for p in _PERIOD_SCHEDULE)
            + ")",
            name="ck_briefing_schedules_period",
        ),
        sa.CheckConstraint(
            "schedule_hour BETWEEN 0 AND 23",
            name="ck_briefing_schedules_hour",
        ),
        sa.CheckConstraint(
            "(period = 'weekly' AND schedule_day BETWEEN 0 AND 6) OR "
            "(period = 'monthly' AND schedule_day BETWEEN 1 AND 28)",
            name="ck_briefing_schedules_day",
        ),
        sa.CheckConstraint(
            "last_run_status IS NULL OR last_run_status IN ('success', 'failed')",
            name="ck_briefing_schedules_status",
        ),
    )
    op.create_index(
        "idx_briefing_schedules_next_run",
        "briefing_schedules",
        ["enabled", "next_run_at"],
        postgresql_where=sa.text("enabled = TRUE"),
    )
    op.execute("ALTER TABLE briefing_schedules ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE briefing_schedules FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON briefing_schedules "
        "USING (tenant_id = current_setting('app.current_tenant_id')::uuid)"
    )


def downgrade() -> None:
    raise NotImplementedError("Sprint 9.2 is forward-only")
