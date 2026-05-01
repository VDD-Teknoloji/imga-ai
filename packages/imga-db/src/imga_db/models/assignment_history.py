"""TicketAssignmentEvent model — append-only assignment audit trail.

Sprint 7.7.2 backend mini-patch. Lives next to ``TicketStateTransition``
in spirit: append-only, denormalised ``tenant_id`` so RLS works
without a join, no ``updated_at`` / ``deleted_at``.

The ``GET /tickets/{id}/timeline`` endpoint reads this table and
merges it with ``ticket_state_transitions`` and ``ticket_comments``
into one polymorphic stream.

A row is written by ``TicketService.assign`` exactly when the
assignee actually changes — no-op assigns (same → same) are dropped
service-side and rejected DB-side via the ``ck_assignment_history_change``
biconditional CHECK on (from_user_id, to_user_id).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from imga_db.base import Base


class TicketAssignmentEvent(Base):
    """One row per actual assignment change (skips no-ops).

    ``from_user_id`` NULL = was unassigned; ``to_user_id`` NULL =
    becoming unassigned. They cannot both be NULL — DB CHECK enforces.
    """

    __tablename__ = "ticket_assignment_history"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    ticket_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False,
    )
    from_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    to_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
