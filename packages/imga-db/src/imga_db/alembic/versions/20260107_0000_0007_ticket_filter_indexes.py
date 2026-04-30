"""composite indexes for /tickets filter + sort hot paths

Revision ID: 0007
Revises: 0006
Create Date: 2026-01-07 00:00:00

Sprint 7.5.5 / Alt-Faz 2: ``GET /tickets`` now accepts multi-value
state, priority, category, assignee, and date-range filters server
side, plus an aggregation endpoint at ``/tickets/stats``. The
existing single-column indexes on tickets cover only the trivial
``state``, ``priority``, etc. lookups in isolation; combined queries
(``WHERE tenant_id = X AND state IN (...) AND priority IN (...)``)
fall back to a sequential scan or a less-optimal single-column scan.

Three new B-tree indexes:

  * (tenant_id, state, priority) — composite filter; covers the
    dashboard "open + high priority" combination.
  * (tenant_id, opened_at DESC) — date-range filter + opened_at
    ordering. Index direction matters for ORDER BY ... DESC LIMIT N.
  * (tenant_id, assigned_to_user_id) WHERE assigned_to_user_id
    IS NOT NULL — partial index for "assignee = X" queries; saves
    the ~30% of unassigned rows that the lookup will never touch.

Validated post-migration with EXPLAIN ANALYZE on the three filter
shapes; all show "Index Scan using ix_tickets_..." rather than the
earlier "Seq Scan on tickets".
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_tickets_tenant_state_priority",
        "tickets",
        ["tenant_id", "state", "priority"],
    )
    op.create_index(
        "ix_tickets_tenant_opened_at",
        "tickets",
        ["tenant_id", sa.text("opened_at DESC")],
    )
    op.create_index(
        "ix_tickets_tenant_assignee",
        "tickets",
        ["tenant_id", "assigned_to_user_id"],
        postgresql_where=sa.text("assigned_to_user_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_tickets_tenant_assignee", table_name="tickets")
    op.drop_index("ix_tickets_tenant_opened_at", table_name="tickets")
    op.drop_index("ix_tickets_tenant_state_priority", table_name="tickets")
