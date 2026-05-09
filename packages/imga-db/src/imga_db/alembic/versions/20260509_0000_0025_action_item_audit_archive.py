"""Sprint 9.1 A — action item audit trail + archive (soft delete)

Revision ID: 0025
Revises: 0024
Create Date: 2026-05-09 00:00:00

The hard-delete path on action_items shipped in Sprint 8.3.10 leaves
no audit trail — a tenant_admin who removed a high-priority follow-up
left no record of who decided what or why. Sprint 9.1 A swaps the
hard delete for a reversible archive plus a per-event log:

  1. ``action_item_events`` — every state-changing operation (create,
     update, archive, unarchive, status_changed, priority_changed,
     assigned, unassigned, commented) writes one row keyed on
     (action_item_id, created_at). RLS+FORCE on ``tenant_id`` per the
     0006 / 0019 / 0021 / 0024 convention. ``actor_type`` distinguishes
     a human update from an LLM extraction or briefing-pipeline insert
     so the timeline UI can render different icons. ``payload`` is a
     JSONB blob the service fills with the diff (``{"from":"open",
     "to":"in_progress"}`` for status changes).

  2. ``action_items.archived_at`` + ``archived_by`` — a non-null
     ``archived_at`` means the row is hidden from the default
     dashboard list; the operator can restore it. Existing rows
     keep ``NULL`` so the migration is online-safe (no rewrite, no
     default fill).

  3. Partial index on (tenant_id, status) WHERE archived_at IS NULL
     so the dashboard query (the hot path — every authenticated
     refresh) doesn't widen its scan as archived rows accumulate.

Forward-only — Sprint 8.3.5.2 dersi.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision: str = "0025"
down_revision: str | Sequence[str] | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_EVENT_TYPES = (
    "created",
    "updated",
    "archived",
    "unarchived",
    "status_changed",
    "priority_changed",
    "assigned",
    "unassigned",
    "commented",
)
_ACTOR_TYPES = ("user", "system", "llm_extraction", "briefing_pipeline")


def upgrade() -> None:
    # 1. action_item_events ------------------------------------------------
    op.create_table(
        "action_item_events",
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
            "action_item_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("action_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column(
            "actor_user_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column(
            "payload",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "event_type IN ("
            + ", ".join(f"'{e}'" for e in _EVENT_TYPES)
            + ")",
            name="ck_action_item_events_event_type",
        ),
        sa.CheckConstraint(
            "actor_type IN ("
            + ", ".join(f"'{a}'" for a in _ACTOR_TYPES)
            + ")",
            name="ck_action_item_events_actor_type",
        ),
    )
    # Hot read: the timeline UI reads every event for one item ordered
    # newest first. Partial-by-tenant via the FK; the action_id +
    # created_at composite index serves both single-item paging and
    # tenant-wide audit pulls.
    op.create_index(
        "idx_action_item_events_action_id_created_at",
        "action_item_events",
        ["action_item_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "idx_action_item_events_tenant_actor",
        "action_item_events",
        ["tenant_id", "actor_user_id", sa.text("created_at DESC")],
    )

    op.execute(
        "ALTER TABLE action_item_events ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        "ALTER TABLE action_item_events FORCE ROW LEVEL SECURITY"
    )
    op.execute(
        "CREATE POLICY tenant_isolation ON action_item_events "
        "USING (tenant_id = current_setting('app.current_tenant_id')::uuid)"
    )

    # 2. action_items archive columns -------------------------------------
    op.add_column(
        "action_items",
        sa.Column(
            "archived_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "action_items",
        sa.Column(
            "archived_by",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # 3. Hot-path partial index — dashboard list filters out archived
    # rows by default. The existing (tenant_id, created_at) order is
    # served by the implicit index on the FK; adding a partial on
    # (tenant_id, status) WHERE archived_at IS NULL keeps the
    # status-filtered query path narrow even after months of
    # archive accumulation.
    op.create_index(
        "idx_action_items_active_status",
        "action_items",
        ["tenant_id", "status"],
        postgresql_where=sa.text("archived_at IS NULL"),
    )


def downgrade() -> None:
    # Forward-only — left as a stub so alembic's history is clean.
    raise NotImplementedError("Sprint 9.1 A is forward-only")
