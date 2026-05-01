"""ticket_assignment_history — append-only assignment audit, fed into /timeline

Revision ID: 0010
Revises: 0009
Create Date: 2026-01-10 00:00:00

Sprint 7.7.2 backend mini-patch closes Gap 2 from the Alt-Faz 7.7.2
report. Before this migration, ``TicketService.assign`` only wrote
to ``audit_logs``; the polymorphic ``GET /tickets/{id}/timeline``
endpoint had no way to surface "Alice atadı → Bob" rows because
audit_logs is wide-grained (every API mutation lands there) and
not joined into the per-ticket timeline.

Adding a dedicated table — same shape pattern as
``ticket_state_transitions`` (append-only, denormalised
``tenant_id`` for RLS, no soft-delete) — gives the timeline a
clean event source. ``audit_logs`` continues to write the
``ticket.assign`` row exactly as before; this is additive, not a
replacement.

Schema:

  * ``from_user_id`` NULL means "was unassigned"; ``to_user_id``
    NULL means "becoming unassigned". They cannot both be NULL —
    the service refuses to log a no-op.
  * ``actor_user_id`` is the user who initiated the change. NULL
    is reserved for system-driven assigns (none exist today; kept
    consistent with TicketStateTransition.actor_user_id semantics).
  * ``occurred_at`` is the canonical sort key for the timeline
    merge — populated by the service so a single transaction's
    rows order naturally with state transitions and comments.

Index strategy mirrors 0006:

  * (tenant_id, ticket_id, occurred_at) — primary timeline render
    join key. ASC ordering matches the ``ticket_state_transitions``
    + ``ticket_comments`` indexes; the route's Python merge sort
    is stable so the final stream is stable too.

RLS+FORCE on tenant_id, same policy convention.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers
revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ticket_assignment_history",
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
        sa.Column(
            "from_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "to_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "actor_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # Defence in depth — the service refuses no-ops, but the DB
        # also rejects them so a buggy caller can't pollute the
        # timeline with "Alice → Alice" rows.
        sa.CheckConstraint(
            "from_user_id IS DISTINCT FROM to_user_id",
            name="ck_assignment_history_change",
        ),
    )
    op.create_index(
        "ix_assignment_history_tenant_ticket_occurred",
        "ticket_assignment_history",
        ["tenant_id", "ticket_id", "occurred_at"],
    )
    op.create_index(
        "ix_assignment_history_tenant_id",
        "ticket_assignment_history",
        ["tenant_id"],
    )

    op.execute(
        "ALTER TABLE ticket_assignment_history ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        "ALTER TABLE ticket_assignment_history FORCE ROW LEVEL SECURITY"
    )
    op.execute(
        """
        CREATE POLICY tenant_isolation ON ticket_assignment_history
            FOR ALL
            USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation ON ticket_assignment_history"
    )
    op.execute(
        "ALTER TABLE ticket_assignment_history DISABLE ROW LEVEL SECURITY"
    )
    op.drop_index(
        "ix_assignment_history_tenant_id",
        table_name="ticket_assignment_history",
    )
    op.drop_index(
        "ix_assignment_history_tenant_ticket_occurred",
        table_name="ticket_assignment_history",
    )
    op.drop_table("ticket_assignment_history")
