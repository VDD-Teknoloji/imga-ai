"""TicketService — ticket CRUD + transitions + auto-close primitives.

Reads + writes the ``tickets`` and ``ticket_state_transitions`` tables.
Every transition:

  1. State-machine validation (graph edge + role + window guard).
  2. Mutates the ticket row (state column + the relevant timestamp).
  3. Bumps ``last_state_change_at``.
  4. Inserts a ``ticket_state_transitions`` row.
  5. Writes an ``audit_logs`` entry.

Auto-close primitives (``find_due_resolved`` / ``find_due_pending`` +
``transition``) are pure-enough that a Sprint 8 worker can call them
on a schedule without further plumbing.

Comments / customer-facing replies are out of scope for Sprint 7.5;
``record_customer_inbound`` only sets the metadata flag.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from imga_db.models import (
    AutomationMode,
    CancellationReason,
    Tenant,
    Ticket,
    TicketPriority,
    TicketState,
    TicketStateTransition,
    UserTenantRole,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql import ColumnElement

from imga_api.services.audit_service import AuditService
from imga_api.services.ticket_state_machine import (
    assert_within_regression_window,
    assert_within_reopen_window,
    validate_transition,
)


class TicketServiceError(Exception):
    """Base for service-level errors not coming directly from the state machine."""


class TicketNotFoundError(TicketServiceError):
    """Ticket does not exist or RLS hides it."""


class DuplicateTicketError(TicketServiceError):
    """An auto-create attempt was suppressed because an open ticket
    already exists for the same review."""


class CancellationReasonRequiredError(TicketServiceError):
    """A transition into CANCELLED was attempted without a reason."""


class UnclaimByOthersError(TicketServiceError):
    """An ANALYST attempted to un-claim someone else's ticket. Allowed
    for TENANT_ADMIN; ANALYST can only un-claim tickets they own."""


@dataclass(frozen=True, slots=True)
class TransitionRequest:
    """Caller-supplied input for a transition.

    ``reason`` is freeform, surfaces in the timeline.
    ``cancellation_reason`` is required iff to_state == CANCELLED.
    """

    to_state: TicketState
    reason: str | None = None
    cancellation_reason: CancellationReason | None = None


@dataclass(frozen=True, slots=True)
class AutoCreateDecision:
    """Result of evaluating ``decide_auto_create_state`` against a tenant
    + classifier output."""

    should_create: bool
    reason: str  # for logging / audit


def decide_auto_create_state(
    *,
    automation_mode: AutomationMode,
    sentiment_score: float,
    confidence: float,
) -> AutoCreateDecision:
    """Pure decision function consumed by the review-ingestion path.

    Mode semantics:

    * ``manual``    — never auto-create; UI surfaces a suggestion.
    * ``semi_auto`` — auto-create iff confidence > 0.7 AND sentiment < -0.5.
    * ``full_auto`` — every classified-NEGATIF complaint becomes a ticket.
                      We treat sentiment < 0 as "negative" here.
    """
    if automation_mode == AutomationMode.MANUAL:
        return AutoCreateDecision(False, "manual_mode")
    if automation_mode == AutomationMode.SEMI_AUTO:
        if confidence > 0.7 and sentiment_score < -0.5:
            return AutoCreateDecision(True, "semi_auto_threshold_met")
        return AutoCreateDecision(False, "semi_auto_threshold_not_met")
    # full_auto
    if sentiment_score < 0:
        return AutoCreateDecision(True, "full_auto_negative")
    return AutoCreateDecision(False, "full_auto_non_negative")


class TicketService:
    """Lives on the imga_app session (RLS-bound) for tenant-scoped work.

    Auto-close worker code uses an admin session (BYPASSRLS) for
    cross-tenant queries — see ``find_due_resolved`` / ``find_due_pending``.
    """

    def __init__(self, session: AsyncSession, audit: AuditService) -> None:
        self._session = session
        self._audit = audit

    # --- create -----------------------------------------------------------

    async def create(
        self,
        *,
        tenant_id: UUID,
        category_id: UUID,
        title: str,
        summary: str | None = None,
        priority: TicketPriority = TicketPriority.NORMAL,
        review_id: UUID | None = None,
        created_by_user_id: UUID | None = None,
        opened_at: datetime | None = None,
    ) -> Ticket:
        """Insert a new ticket in OPEN. Caller is responsible for
        running ``find_open_for_review`` to prevent dedup-by-review
        before invoking auto-create paths.

        ``created_by_user_id=None`` marks the ticket as system-generated
        (auto-classifier path)."""
        now = opened_at or datetime.now(UTC)
        ticket = Ticket(
            tenant_id=tenant_id,
            category_id=category_id,
            review_id=review_id,
            title=title,
            summary=summary,
            priority=priority,
            state=TicketState.OPEN,
            created_by_user_id=created_by_user_id,
            opened_at=now,
            last_state_change_at=now,
        )
        self._session.add(ticket)
        await self._session.flush()

        self._session.add(
            TicketStateTransition(
                tenant_id=tenant_id,
                ticket_id=ticket.id,
                from_state=TicketState.OPEN,  # creation: from==to, marker row
                to_state=TicketState.OPEN,
                actor_user_id=created_by_user_id,
                reason="created",
                occurred_at=now,
                created_at=now,
            )
        )
        await self._audit.log(
            action="ticket.create",
            resource_type="ticket",
            resource_id=ticket.id,
            tenant_id=tenant_id,
            actor_user_id=created_by_user_id,
            details={
                "category_id": str(category_id),
                "system": created_by_user_id is None,
                "review_id": str(review_id) if review_id else None,
            },
        )
        return ticket

    async def find_open_for_review(
        self, *, tenant_id: UUID, review_id: UUID
    ) -> Ticket | None:
        """Dedup helper. Returns the ticket if one already exists for
        this review and is not in a terminal state (CLOSED / CANCELLED).
        Auto-create paths call this before insert."""
        result = await self._session.execute(
            select(Ticket)
            .where(Ticket.tenant_id == tenant_id)
            .where(Ticket.review_id == review_id)
            .where(Ticket.deleted_at.is_(None))
            .where(
                Ticket.state.in_(
                    (
                        TicketState.OPEN,
                        TicketState.IN_PROGRESS,
                        TicketState.PENDING_CUSTOMER,
                        TicketState.RESOLVED,
                    )
                )
            )
        )
        return result.scalar_one_or_none()

    # --- transition ------------------------------------------------------

    async def transition(
        self,
        *,
        ticket_id: UUID,
        request: TransitionRequest,
        actor_user_id: UUID | None,
        actor_role: UserTenantRole | None,
        actor_is_super_admin: bool = False,
        actor_is_system: bool = False,
        now: datetime | None = None,
    ) -> Ticket:
        """Run validation + persist the transition + write audit + write
        timeline row. Caller's session must already be RLS-bound for
        non-system actors."""
        moment = now or datetime.now(UTC)
        ticket = await self._session.get(Ticket, ticket_id)
        if ticket is None or ticket.deleted_at is not None:
            raise TicketNotFoundError(f"ticket {ticket_id} not found")

        from_state = ticket.state
        to_state = request.to_state

        # 1. State-machine validation
        validate_transition(
            from_state,
            to_state,
            role=actor_role,
            is_super_admin=actor_is_super_admin,
            actor_is_system=actor_is_system,
        )

        # 2. Self-only un-claim guard
        if (
            from_state == TicketState.IN_PROGRESS
            and to_state == TicketState.OPEN
            and actor_role == UserTenantRole.ANALYST
            and not actor_is_super_admin
            and ticket.assigned_to_user_id is not None
            and ticket.assigned_to_user_id != actor_user_id
        ):
            raise UnclaimByOthersError(
                "analyst can only un-claim a ticket they own"
            )

        # 3. Cancellation reason required iff entering CANCELLED
        if to_state == TicketState.CANCELLED and request.cancellation_reason is None:
            raise CancellationReasonRequiredError(
                "cancellation_reason is required for CANCELLED"
            )
        # Leaving CANCELLED clears the reason (uncancel → OPEN).

        # 4. Window guards (need ticket timestamps + tenant config)
        await self._enforce_window_guards(ticket, from_state, to_state, moment)

        # 5. Apply state + per-state timestamps
        self._apply_state_change(
            ticket,
            to_state,
            moment,
            actor_user_id=actor_user_id,
            cancellation_reason=request.cancellation_reason,
        )

        # 6. Write timeline + audit
        self._session.add(
            TicketStateTransition(
                tenant_id=ticket.tenant_id,
                ticket_id=ticket.id,
                from_state=from_state,
                to_state=to_state,
                actor_user_id=actor_user_id,
                reason=request.reason,
                occurred_at=moment,
                created_at=moment,
            )
        )
        await self._audit.log(
            action="ticket.transition",
            resource_type="ticket",
            resource_id=ticket.id,
            tenant_id=ticket.tenant_id,
            actor_user_id=actor_user_id,
            details={
                "from": str(from_state),
                "to": str(to_state),
                "reason": request.reason,
                "system": actor_is_system,
            },
        )
        await self._session.flush()
        return ticket

    async def _enforce_window_guards(
        self,
        ticket: Ticket,
        from_state: TicketState,
        to_state: TicketState,
        now: datetime,
    ) -> None:
        """Look up tenant windows and apply the regression / reopen guards."""
        # Only three transitions are time-bounded.
        is_regression = (
            from_state == TicketState.RESOLVED and to_state == TicketState.IN_PROGRESS
        )
        is_reopen_closed = (
            from_state == TicketState.CLOSED and to_state == TicketState.OPEN
        )
        is_uncancel = (
            from_state == TicketState.CANCELLED and to_state == TicketState.OPEN
        )
        if not (is_regression or is_reopen_closed or is_uncancel):
            return

        tenant = await self._session.get(Tenant, ticket.tenant_id)
        if tenant is None:
            # RLS hides the tenant from the app session normally; for the
            # admin-session callers we still error loudly here.
            raise TicketNotFoundError(
                f"tenant {ticket.tenant_id} unavailable for window check"
            )
        if is_regression:
            assert_within_regression_window(
                ticket.resolved_at,
                window_days=tenant.resolved_regression_window_days,
                now=now,
            )
        else:
            anchor = ticket.closed_at if is_reopen_closed else ticket.cancelled_at
            assert_within_reopen_window(
                anchor,
                window_days=tenant.ticket_reopen_window_days,
                now=now,
            )

    def _apply_state_change(
        self,
        ticket: Ticket,
        to_state: TicketState,
        now: datetime,
        *,
        actor_user_id: UUID | None,
        cancellation_reason: CancellationReason | None,
    ) -> None:
        """Mutate ticket columns for the target state. Idempotent on
        ``last_state_change_at`` (always set to ``now``)."""
        previous_state = ticket.state
        ticket.state = to_state
        ticket.last_state_change_at = now

        if to_state == TicketState.IN_PROGRESS:
            # First claim sets claimed_at; regression / customer-reply
            # bumps it too so SLA timers restart.
            ticket.claimed_at = now
            if actor_user_id is not None and ticket.assigned_to_user_id is None:
                ticket.assigned_to_user_id = actor_user_id

        if to_state == TicketState.OPEN and previous_state == TicketState.IN_PROGRESS:
            # Un-claim: drop assignment, leave claimed_at as historical.
            ticket.assigned_to_user_id = None

        if to_state == TicketState.PENDING_CUSTOMER:
            ticket.pending_since = now
        elif previous_state == TicketState.PENDING_CUSTOMER:
            # Leaving PENDING_CUSTOMER for any other state — stop the
            # pending timer.
            ticket.pending_since = None

        if to_state == TicketState.RESOLVED:
            ticket.resolved_at = now
        if to_state == TicketState.CLOSED:
            ticket.closed_at = now
        if to_state == TicketState.CANCELLED:
            ticket.cancelled_at = now
            ticket.cancellation_reason = cancellation_reason

        # Reopening / un-cancelling clears the terminal-state metadata
        # so the ticket genuinely re-enters the active pool.
        if to_state == TicketState.OPEN and previous_state in (
            TicketState.CLOSED,
            TicketState.CANCELLED,
        ):
            ticket.closed_at = None
            ticket.cancelled_at = None
            ticket.cancellation_reason = None
            # Don't clear resolved_at — keep it as historical evidence.

    # --- assign (metadata, no state change) ----------------------------

    async def assign(
        self,
        *,
        ticket_id: UUID,
        new_assignee_id: UUID | None,
        actor_user_id: UUID,
    ) -> Ticket:
        """Set / clear the ticket assignee. Does not change state.
        Allowed in any non-terminal state; routes enforce role.
        """
        ticket = await self._session.get(Ticket, ticket_id)
        if ticket is None or ticket.deleted_at is not None:
            raise TicketNotFoundError(f"ticket {ticket_id} not found")
        if ticket.state in (TicketState.CLOSED, TicketState.CANCELLED):
            raise TicketServiceError(
                f"cannot reassign a {ticket.state} ticket; reopen first"
            )
        previous = ticket.assigned_to_user_id
        ticket.assigned_to_user_id = new_assignee_id
        await self._audit.log(
            action="ticket.assign",
            resource_type="ticket",
            resource_id=ticket.id,
            tenant_id=ticket.tenant_id,
            actor_user_id=actor_user_id,
            details={
                "from": str(previous) if previous else None,
                "to": str(new_assignee_id) if new_assignee_id else None,
            },
        )
        await self._session.flush()
        return ticket

    # --- quick-resolve (claim + resolve) ------------------------------

    async def quick_resolve(
        self,
        *,
        ticket_id: UUID,
        actor_user_id: UUID,
        actor_role: UserTenantRole | None,
        actor_is_super_admin: bool = False,
        reason: str | None = None,
    ) -> Ticket:
        """Two transitions in one call: OPEN → IN_PROGRESS → RESOLVED.

        Each transition is logged separately in ticket_state_transitions
        and audit_logs — the timeline is unambiguous about what
        happened. Useful for trivially-answerable cases where the
        analyst doesn't need to "claim and walk away" first.

        If the ticket is not in OPEN we let validate_transition raise,
        keeping the surface area honest.
        """
        moment = datetime.now(UTC)
        await self.transition(
            ticket_id=ticket_id,
            request=TransitionRequest(
                to_state=TicketState.IN_PROGRESS, reason=reason
            ),
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            actor_is_super_admin=actor_is_super_admin,
            now=moment,
        )
        # Second step ~1ms later so the timeline ordering is stable.
        return await self.transition(
            ticket_id=ticket_id,
            request=TransitionRequest(
                to_state=TicketState.RESOLVED, reason=reason
            ),
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            actor_is_super_admin=actor_is_super_admin,
            now=moment + timedelta(milliseconds=1),
        )

    # --- customer inbound (no state change) ---------------------------

    async def record_customer_inbound(
        self,
        *,
        ticket_id: UUID,
        occurred_at: datetime | None = None,
    ) -> Ticket:
        """Stamp the ticket with ``customer_inbound_received_at``. Does
        NOT change state — see 7.5 design rev: spam / bounce / bot
        replies must not auto-resume PENDING_CUSTOMER tickets. The UI
        renders the field; the analyst decides."""
        ticket = await self._session.get(Ticket, ticket_id)
        if ticket is None or ticket.deleted_at is not None:
            raise TicketNotFoundError(f"ticket {ticket_id} not found")
        ticket.customer_inbound_received_at = occurred_at or datetime.now(UTC)
        await self._audit.log(
            action="ticket.customer_inbound",
            resource_type="ticket",
            resource_id=ticket.id,
            tenant_id=ticket.tenant_id,
            actor_user_id=None,  # system event
            details={"received_at": ticket.customer_inbound_received_at.isoformat()},
        )
        await self._session.flush()
        return ticket

    # --- auto-close primitives (Sprint 8 worker calls these) ----------

    async def find_due_resolved(
        self,
        *,
        now: datetime,
        tenant_id: UUID | None = None,
    ) -> Sequence[Ticket]:
        """Tickets in RESOLVED whose ``resolved_at + tenant.auto_close_resolved_days
        <= now``. Caller iterates and runs ``transition`` with
        ``actor_is_system=True`` to drive them to CLOSED.

        Pass ``tenant_id`` to scope to a single tenant; otherwise this
        is intended for an admin (BYPASSRLS) session.
        """
        stmt = (
            select(Ticket)
            .join(Tenant, Tenant.id == Ticket.tenant_id)
            .where(Ticket.state == TicketState.RESOLVED)
            .where(Ticket.deleted_at.is_(None))
            .where(
                Ticket.resolved_at
                <= now - _days_interval_clause(Tenant.auto_close_resolved_days)
            )
        )
        if tenant_id is not None:
            stmt = stmt.where(Ticket.tenant_id == tenant_id)
        result = await self._session.execute(stmt)
        return list(result.scalars())

    async def find_due_pending(
        self,
        *,
        now: datetime,
        tenant_id: UUID | None = None,
    ) -> Sequence[Ticket]:
        """Tickets in PENDING_CUSTOMER beyond their tenant's auto_close_pending_days."""
        stmt = (
            select(Ticket)
            .join(Tenant, Tenant.id == Ticket.tenant_id)
            .where(Ticket.state == TicketState.PENDING_CUSTOMER)
            .where(Ticket.deleted_at.is_(None))
            .where(
                Ticket.pending_since
                <= now - _days_interval_clause(Tenant.auto_close_pending_days)
            )
        )
        if tenant_id is not None:
            stmt = stmt.where(Ticket.tenant_id == tenant_id)
        result = await self._session.execute(stmt)
        return list(result.scalars())


def _days_interval_clause(
    days_column: InstrumentedAttribute[int],
) -> ColumnElement[timedelta]:
    """Build ``make_interval(years => 0, months => 0, weeks => 0, days => col)``
    so each row's threshold comes from its own tenant. Used to build
    ``Ticket.resolved_at <= now - interval-derived-from-tenant`` filters
    in find_due_*."""
    return func.make_interval(0, 0, 0, days_column)
