"""Ticket + TicketStateTransition models + enums.

The ticket lifecycle has six states; their semantics are documented
in the Sprint 7.5 design (auth_service.py-style preamble below).
``TicketStateTransition`` is an append-only timeline that records
every transition (manual or system-driven). Both tables are RLS+FORCE
tenant-scoped — see migration 0006 for the policies.

State legend:

    OPEN              — created, untriaged. Auto-create lands here.
    IN_PROGRESS       — assigned analyst is working on it.
    PENDING_CUSTOMER  — waiting for customer info; optional.
    RESOLVED          — analyst marked done; auto-closes after N days.
    CLOSED            — terminal-ish (reopen-able for a bounded window).
    CANCELLED         — invalid (false-positive, duplicate, spam, off-topic).

CANCELLED uses ``cancellation_reason``; the DB enforces this with a
biconditional CHECK (state='cancelled' iff cancellation_reason IS NOT
NULL).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from imga_db.base import Base
from imga_db.models.mixins import SoftDeleteMixin, TimestampMixin


class TicketState(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    PENDING_CUSTOMER = "pending_customer"
    RESOLVED = "resolved"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class TicketPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class CancellationReason(StrEnum):
    """Why a ticket should never have existed (or should be removed
    from outcome metrics). Required when state='cancelled', forbidden
    otherwise — enforced by a DB CHECK constraint."""

    FALSE_POSITIVE = "false_positive"
    DUPLICATE = "duplicate"
    SPAM = "spam"
    OFF_TOPIC = "off_topic"
    OTHER = "other"


class Ticket(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "tickets"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # No FK on review_id — review model lands post-Sprint-7.
    review_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    category_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("categories.id", ondelete="RESTRICT"),
        nullable=False,
    )

    state: Mapped[TicketState] = mapped_column(
        String(24), default=TicketState.OPEN, nullable=False, index=True
    )
    priority: Mapped[TicketPriority] = mapped_column(
        String(8), default=TicketPriority.NORMAL, nullable=False
    )
    title: Mapped[str] = mapped_column(Text(), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text(), nullable=True)

    assigned_to_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    cancellation_reason: Mapped[CancellationReason | None] = mapped_column(
        String(24), nullable=True
    )
    # Reserved for Sprint 8: out-of-window reopen creates a NEW ticket
    # that points back here. No CASCADE — historic ticket survives.
    parent_ticket_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tickets.id"), nullable=True
    )

    # Timeline columns. opened_at is the canonical creation moment;
    # last_state_change_at is the SLA timer's reference point and is
    # bumped on every transition by TicketService.
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    pending_since: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    customer_inbound_received_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_state_change_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


class TicketStateTransition(Base):
    """Append-only timeline of ticket state changes.

    Captures every transition — including system-driven auto-closes
    (actor_user_id IS NULL). This is duplicated, not replaced, by
    audit_logs: audit_logs covers the wider security audit, while
    this table is optimized for fast per-ticket timeline rendering.
    No updated_at / deleted_at — rows are immutable.
    """

    __tablename__ = "ticket_state_transitions"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    # Denormalized so RLS works without joining tickets.
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ticket_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    from_state: Mapped[TicketState] = mapped_column(String(24), nullable=False)
    to_state: Mapped[TicketState] = mapped_column(String(24), nullable=False)
    actor_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reason: Mapped[str | None] = mapped_column(Text(), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
