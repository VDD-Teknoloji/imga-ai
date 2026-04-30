"""tickets + ticket_state_transitions + per-tenant timer windows

Revision ID: 0006
Revises: 0005
Create Date: 2026-01-06 00:00:00

Sprint 7.5: ticket lifecycle. The ``tickets`` table holds the live
state of every customer-complaint ticket; ``ticket_state_transitions``
is an append-only timeline of every transition (including
system-driven auto-closes). Both are tenant-scoped and protected by
RLS+FORCE.

Per-tenant timer windows live as dedicated INTEGER columns on
``tenants``, not in the JSON ``settings`` blob:

  * auto_close_resolved_days        — RESOLVED → CLOSED auto-close (default 7)
  * auto_close_pending_days         — PENDING_CUSTOMER → CLOSED auto-close (default 14)
  * resolved_regression_window_days — RESOLVED → IN_PROGRESS regression cutoff (default 7)
  * ticket_reopen_window_days       — CLOSED/CANCELLED → OPEN reopen cutoff (default 30)

A ``parent_ticket_id`` self-reference is added now so that Sprint 8 can
implement "create linked ticket" when the reopen window has lapsed,
without another migration.

State enum is enforced at the DB layer with a CHECK constraint rather
than a Postgres ENUM type — same convention as ``automation_mode`` and
``plan_tier``. The ``cancellation_reason`` column is non-NULL iff the
state is ``cancelled``; that XOR rule is enforced with a single
biconditional CHECK.

The ``last_state_change_at`` column drives SLA-timer queries; it is
seeded to ``opened_at`` on insert and bumped by TicketService on every
transition. ``total_active_seconds`` (cumulative non-closed time) is
deferred to Sprint 8.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers
revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- per-tenant timer windows ---------------------------------------
    op.add_column(
        "tenants",
        sa.Column(
            "auto_close_resolved_days",
            sa.Integer(),
            nullable=False,
            server_default="7",
        ),
    )
    op.add_column(
        "tenants",
        sa.Column(
            "auto_close_pending_days",
            sa.Integer(),
            nullable=False,
            server_default="14",
        ),
    )
    op.add_column(
        "tenants",
        sa.Column(
            "resolved_regression_window_days",
            sa.Integer(),
            nullable=False,
            server_default="7",
        ),
    )
    op.add_column(
        "tenants",
        sa.Column(
            "ticket_reopen_window_days",
            sa.Integer(),
            nullable=False,
            server_default="30",
        ),
    )

    # --- tickets table --------------------------------------------------
    op.create_table(
        "tickets",
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
        # No FK on review_id yet — review model is post-Sprint-7.
        sa.Column("review_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "category_id",
            UUID(as_uuid=True),
            sa.ForeignKey("categories.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("state", sa.String(24), nullable=False, server_default="open"),
        sa.Column("priority", sa.String(8), nullable=False, server_default="normal"),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "assigned_to_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_by_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("cancellation_reason", sa.String(24), nullable=True),
        # Self-reference so the row can later say "this is a linked
        # successor of an out-of-window CLOSED ticket". No CASCADE because
        # we want the historical ticket preserved.
        sa.Column(
            "parent_ticket_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tickets.id"),
            nullable=True,
        ),
        # Timeline columns. opened_at is set by TicketService on creation
        # (claimed_at etc. are updated as transitions occur).
        sa.Column(
            "opened_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pending_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("customer_inbound_received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_state_change_at",
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
        # State must be one of the six known values.
        sa.CheckConstraint(
            "state IN ('open','in_progress','pending_customer','resolved','closed','cancelled')",
            name="ck_tickets_state",
        ),
        sa.CheckConstraint(
            "priority IN ('low','normal','high','urgent')",
            name="ck_tickets_priority",
        ),
        # Biconditional: cancellation_reason is set iff state='cancelled'.
        # ((a) = (b)) is true exactly when a and b have the same boolean value.
        sa.CheckConstraint(
            "(state = 'cancelled') = (cancellation_reason IS NOT NULL)",
            name="ck_tickets_cancellation_reason_xor",
        ),
        sa.CheckConstraint(
            "cancellation_reason IS NULL OR "
            "cancellation_reason IN ('false_positive','duplicate','spam','off_topic','other')",
            name="ck_tickets_cancellation_reason_value",
        ),
    )
    op.create_index("ix_tickets_tenant_id", "tickets", ["tenant_id"])
    op.create_index("ix_tickets_state", "tickets", ["state"])
    op.create_index("ix_tickets_assigned_to_user_id", "tickets", ["assigned_to_user_id"])
    op.create_index(
        "ix_tickets_last_state_change_at", "tickets", ["last_state_change_at"]
    )
    op.create_index(
        "ix_tickets_review_id",
        "tickets",
        ["review_id"],
        postgresql_where=sa.text("review_id IS NOT NULL"),
    )
    op.create_index("ix_tickets_deleted_at", "tickets", ["deleted_at"])

    op.execute("ALTER TABLE tickets ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tickets FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON tickets
            FOR ALL
            USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
        """
    )

    # --- ticket_state_transitions (append-only timeline) ----------------
    # tenant_id is denormalized so RLS can apply without a JOIN.
    op.create_table(
        "ticket_state_transitions",
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
        sa.Column(
            "ticket_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tickets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("from_state", sa.String(24), nullable=False),
        sa.Column("to_state", sa.String(24), nullable=False),
        # actor_user_id NULL = system-driven (auto-close worker).
        sa.Column(
            "actor_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "occurred_at",
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
    )
    op.create_index("ix_tst_ticket_id", "ticket_state_transitions", ["ticket_id"])
    op.create_index("ix_tst_tenant_id", "ticket_state_transitions", ["tenant_id"])
    op.create_index("ix_tst_occurred_at", "ticket_state_transitions", ["occurred_at"])

    op.execute("ALTER TABLE ticket_state_transitions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ticket_state_transitions FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON ticket_state_transitions
            FOR ALL
            USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON ticket_state_transitions")
    op.execute("ALTER TABLE ticket_state_transitions DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_tst_occurred_at", table_name="ticket_state_transitions")
    op.drop_index("ix_tst_tenant_id", table_name="ticket_state_transitions")
    op.drop_index("ix_tst_ticket_id", table_name="ticket_state_transitions")
    op.drop_table("ticket_state_transitions")

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON tickets")
    op.execute("ALTER TABLE tickets DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_tickets_deleted_at", table_name="tickets")
    op.drop_index("ix_tickets_review_id", table_name="tickets")
    op.drop_index("ix_tickets_last_state_change_at", table_name="tickets")
    op.drop_index("ix_tickets_assigned_to_user_id", table_name="tickets")
    op.drop_index("ix_tickets_state", table_name="tickets")
    op.drop_index("ix_tickets_tenant_id", table_name="tickets")
    op.drop_table("tickets")

    op.drop_column("tenants", "ticket_reopen_window_days")
    op.drop_column("tenants", "resolved_regression_window_days")
    op.drop_column("tenants", "auto_close_pending_days")
    op.drop_column("tenants", "auto_close_resolved_days")
