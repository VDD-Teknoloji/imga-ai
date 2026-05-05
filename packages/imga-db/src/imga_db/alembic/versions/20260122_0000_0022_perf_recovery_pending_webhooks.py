"""Sprint 9.0 — pg_stat_statements + batch recovery + pending_webhook_events

Revision ID: 0022
Revises: 0021
Create Date: 2026-01-22 00:00:00

Sprint 9.0 (Performance + Demo Prep). Three concerns bundled because
they're all foundational for the rest of the sprint:

  1. ``pg_stat_statements`` — Postgres extension that records
     normalized query stats. Enables the slow-query review for the
     N+1 sweep (deferred to Sprint 9.1, but the data has to start
     accumulating now). Compose tuning carries the matching
     ``shared_preload_libraries`` setting.

  2. ``tenants.sla_webhook_dispatch_mode`` + ``pending_webhook_events``
     — manual / automatic toggle for SLA webhook dispatch. When a
     tenant flips to ``manual``, SLA webhook hits stop firing
     synchronously; the engine queues a row in ``pending_webhook_events``
     and the operator approves / dismisses it from the
     /pending-webhooks queue. Same RLS+FORCE convention as 0006 / 0019.

  3. ``analyze_batch_jobs`` recovery columns — ``last_checkpoint_row``
     advances every chunk so a worker restart can resume mid-file
     instead of replaying from row 0. ``retry_count`` + ``last_error``
     surface in the /batches detail UI so the user understands why a
     job rolled back.

Forward-only — Sprint 8.3.5.2 dersi.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision: str = "0022"
down_revision: str | Sequence[str] | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. pg_stat_statements extension --------------------------------------
    # Server-wide. The compose layer pre-loads the .so via
    # shared_preload_libraries; this DDL just registers the catalog
    # views. IF NOT EXISTS so re-running on an already-loaded cluster
    # (e.g. staging promoted to prod schema) is a no-op.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_stat_statements")

    # 2. tenants.sla_webhook_dispatch_mode ---------------------------------
    # Default 'automatic' so existing tenants keep firing SLA webhooks
    # synchronously. When flipped to 'manual', the engine routes hits
    # to pending_webhook_events instead of httpx.post.
    op.add_column(
        "tenants",
        sa.Column(
            "sla_webhook_dispatch_mode",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'automatic'"),
        ),
    )
    op.execute(
        "ALTER TABLE tenants ADD CONSTRAINT ck_tenants_sla_webhook_dispatch_mode "
        "CHECK (sla_webhook_dispatch_mode IN ('automatic', 'manual'))"
    )

    # 3. pending_webhook_events --------------------------------------------
    op.create_table(
        "pending_webhook_events",
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
            "sla_rule_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("sla_rules.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "review_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("reviews.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # 'slack' / 'teams' — mirrors sla_rules.action_type minus the
        # 'webhook' suffix.
        sa.Column("webhook_target", sa.String(length=16), nullable=False),
        sa.Column("webhook_url", sa.String(length=512), nullable=False),
        # Slack-only optional channel override. NULL for Teams.
        sa.Column("channel", sa.String(length=64), nullable=True),
        # Snapshot of the SlaWebhookPayload at the moment the rule
        # fired — preserved so the operator can review even if the
        # source review/rule has since changed.
        sa.Column(
            "payload",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "retry_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "dismissed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "dismissed_by_user_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.CheckConstraint(
            "webhook_target IN ('slack', 'teams')",
            name="ck_pending_webhook_target",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'failed', 'dismissed')",
            name="ck_pending_webhook_status",
        ),
    )
    op.create_index(
        "ix_pending_webhooks_tenant_status_created",
        "pending_webhook_events",
        ["tenant_id", "status", sa.text("created_at DESC")],
    )
    op.execute(
        "ALTER TABLE pending_webhook_events ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        "ALTER TABLE pending_webhook_events FORCE ROW LEVEL SECURITY"
    )
    op.execute(
        "CREATE POLICY tenant_isolation ON pending_webhook_events "
        "USING (tenant_id = current_setting('app.current_tenant_id')::uuid)"
    )

    # 4. analyze_batch_jobs recovery columns -------------------------------
    # last_checkpoint_row advances on every chunk commit so a worker
    # crash can resume from the next row. retry_count counts user-
    # initiated retries from /batches/{id}/retry. last_error is the
    # human-readable failure message (mirrors error_summary's textual
    # surface but at the job level).
    op.add_column(
        "analyze_batch_jobs",
        sa.Column(
            "last_checkpoint_row",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "analyze_batch_jobs",
        sa.Column(
            "retry_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "analyze_batch_jobs",
        sa.Column("last_error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("analyze_batch_jobs", "last_error")
    op.drop_column("analyze_batch_jobs", "retry_count")
    op.drop_column("analyze_batch_jobs", "last_checkpoint_row")

    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation ON pending_webhook_events"
    )
    op.execute(
        "ALTER TABLE pending_webhook_events DISABLE ROW LEVEL SECURITY"
    )
    op.drop_index(
        "ix_pending_webhooks_tenant_status_created",
        table_name="pending_webhook_events",
    )
    op.drop_table("pending_webhook_events")

    op.execute(
        "ALTER TABLE tenants DROP CONSTRAINT IF EXISTS "
        "ck_tenants_sla_webhook_dispatch_mode"
    )
    op.drop_column("tenants", "sla_webhook_dispatch_mode")

    # pg_stat_statements drop is left manual — extension might be
    # shared with other apps on the cluster.
