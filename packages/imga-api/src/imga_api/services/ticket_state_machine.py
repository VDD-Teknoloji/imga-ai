"""Ticket lifecycle state machine — pure validation, no I/O.

Three concerns live here, all as pure functions over enums and
datetimes so they're trivially unit-testable without a database:

  1. The transition graph: which (from_state, to_state) pairs are
     even meaningful (independent of who's asking).
  2. The role matrix: which UserTenantRole values may invoke each
     transition. System-driven transitions (auto-close worker) bypass
     the role matrix via the ``actor_is_system`` flag, and super-admin
     bypasses via ``actor_is_super_admin``.
  3. Time-window guards: the regression and reopen windows that turn
     a logically-allowed transition into a "create linked ticket
     instead" 409.

The service layer wraps these with DB I/O — see TicketService.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from imga_db.models import TicketState, UserTenantRole

# --- transition graph ----------------------------------------------------

# from_state -> set of to_states the system *could* allow (subject to
# role matrix + window guards).  OPEN -> RESOLVED is intentionally
# absent: the design rejected the skip-ahead in favour of a
# /tickets/{id}/quick-resolve endpoint that performs OPEN ->
# IN_PROGRESS -> RESOLVED as two logged transitions.
TRANSITIONS: dict[TicketState, frozenset[TicketState]] = {
    TicketState.OPEN: frozenset({
        TicketState.IN_PROGRESS,
        TicketState.CANCELLED,
    }),
    TicketState.IN_PROGRESS: frozenset({
        TicketState.OPEN,                 # un-claim
        TicketState.PENDING_CUSTOMER,
        TicketState.RESOLVED,
        TicketState.CANCELLED,
    }),
    TicketState.PENDING_CUSTOMER: frozenset({
        TicketState.IN_PROGRESS,
        TicketState.RESOLVED,
        TicketState.CLOSED,               # auto-close worker only
    }),
    TicketState.RESOLVED: frozenset({
        TicketState.CLOSED,
        TicketState.IN_PROGRESS,          # regression — bounded by window
    }),
    TicketState.CLOSED: frozenset({
        TicketState.OPEN,                 # reopen — bounded by window
    }),
    TicketState.CANCELLED: frozenset({
        TicketState.OPEN,                 # uncancel — bounded by window
    }),
}

# --- role matrix --------------------------------------------------------

# (from_state, to_state) -> roles that may invoke this transition.
# Empty frozenset() means "system only" — only the auto-close worker
# (actor_is_system=True) may perform this transition.
_ANALYST_OR_ADMIN: frozenset[UserTenantRole] = frozenset({
    UserTenantRole.ANALYST,
    UserTenantRole.TENANT_ADMIN,
})
_ADMIN_ONLY: frozenset[UserTenantRole] = frozenset({UserTenantRole.TENANT_ADMIN})

ROLE_MATRIX: dict[tuple[TicketState, TicketState], frozenset[UserTenantRole]] = {
    (TicketState.OPEN, TicketState.IN_PROGRESS): _ANALYST_OR_ADMIN,
    (TicketState.OPEN, TicketState.CANCELLED): _ANALYST_OR_ADMIN,
    (TicketState.IN_PROGRESS, TicketState.OPEN): _ANALYST_OR_ADMIN,        # un-claim (self-only check applied at service)
    (TicketState.IN_PROGRESS, TicketState.PENDING_CUSTOMER): _ANALYST_OR_ADMIN,
    (TicketState.IN_PROGRESS, TicketState.RESOLVED): _ANALYST_OR_ADMIN,
    (TicketState.IN_PROGRESS, TicketState.CANCELLED): _ADMIN_ONLY,         # 7.5 revision 5
    (TicketState.PENDING_CUSTOMER, TicketState.IN_PROGRESS): _ANALYST_OR_ADMIN,
    (TicketState.PENDING_CUSTOMER, TicketState.RESOLVED): _ANALYST_OR_ADMIN,
    (TicketState.PENDING_CUSTOMER, TicketState.CLOSED): frozenset(),       # system only
    (TicketState.RESOLVED, TicketState.CLOSED): _ANALYST_OR_ADMIN,
    (TicketState.RESOLVED, TicketState.IN_PROGRESS): _ANALYST_OR_ADMIN,
    (TicketState.CLOSED, TicketState.OPEN): _ADMIN_ONLY,                   # reopen
    (TicketState.CANCELLED, TicketState.OPEN): _ADMIN_ONLY,                # uncancel
}


# --- exceptions ---------------------------------------------------------


class TicketTransitionError(Exception):
    """Base class for state-machine validation failures."""


class InvalidTransitionError(TicketTransitionError):
    """The (from_state, to_state) pair is not in the transition graph."""


class ForbiddenTransitionError(TicketTransitionError):
    """The transition exists but the actor's role is not authorized."""


class WindowExpiredError(TicketTransitionError):
    """The transition would be allowed except that the per-tenant time
    window (regression / reopen) has elapsed. Callers typically translate
    this to 409 with a hint to create a linked ticket instead."""


# --- pure validators ----------------------------------------------------


def is_valid_transition(from_state: TicketState, to_state: TicketState) -> bool:
    """Whether the graph permits this transition at all."""
    return to_state in TRANSITIONS.get(from_state, frozenset())


def is_authorized(
    from_state: TicketState,
    to_state: TicketState,
    *,
    role: UserTenantRole | None,
    is_super_admin: bool = False,
    actor_is_system: bool = False,
) -> bool:
    """Authorization check independent of the graph check.

    * ``actor_is_system=True`` always passes — auto-close worker.
    * ``is_super_admin=True`` always passes.
    * Otherwise the actor must have an active tenant role that appears
      in ``ROLE_MATRIX[(from, to)]``.
    """
    if actor_is_system:
        return True
    if is_super_admin:
        return True
    if role is None:
        return False
    allowed = ROLE_MATRIX.get((from_state, to_state), frozenset())
    return role in allowed


def validate_transition(
    from_state: TicketState,
    to_state: TicketState,
    *,
    role: UserTenantRole | None,
    is_super_admin: bool = False,
    actor_is_system: bool = False,
) -> None:
    """Raise InvalidTransitionError if the graph forbids the move,
    ForbiddenTransitionError if the role matrix forbids the actor.

    Window checks (regression, reopen) are NOT applied here — caller
    must invoke the dedicated window guards because they need the
    ticket's timestamps + the tenant's per-tenant window settings.
    """
    if not is_valid_transition(from_state, to_state):
        raise InvalidTransitionError(
            f"transition {from_state} -> {to_state} is not allowed"
        )
    if not is_authorized(
        from_state,
        to_state,
        role=role,
        is_super_admin=is_super_admin,
        actor_is_system=actor_is_system,
    ):
        raise ForbiddenTransitionError(
            f"role {role} cannot perform {from_state} -> {to_state}"
        )


# --- time-window guards -------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


def is_within_window(
    anchor: datetime | None,
    *,
    window_days: int,
    now: datetime | None = None,
) -> bool:
    """``True`` iff (now - anchor) <= window_days, with anchor required.

    Returns ``False`` when ``anchor`` is None (defensive — a row without
    the relevant timestamp shouldn't be eligible for the bounded
    transition).
    """
    if anchor is None:
        return False
    current = now if now is not None else _now()
    return (current - anchor) <= timedelta(days=window_days)


def assert_within_regression_window(
    resolved_at: datetime | None,
    *,
    window_days: int,
    now: datetime | None = None,
) -> None:
    """For RESOLVED -> IN_PROGRESS transitions. Raise if the regression
    window has lapsed; the route handler then maps that to 409 + the
    "create linked ticket" hint."""
    if not is_within_window(resolved_at, window_days=window_days, now=now):
        raise WindowExpiredError(
            f"regression window of {window_days}d has elapsed; "
            "create a linked ticket instead"
        )


def assert_within_reopen_window(
    anchor: datetime | None,
    *,
    window_days: int,
    now: datetime | None = None,
) -> None:
    """For CLOSED -> OPEN (anchor=closed_at) and CANCELLED -> OPEN
    (anchor=cancelled_at). Same semantic; same error mapping."""
    if not is_within_window(anchor, window_days=window_days, now=now):
        raise WindowExpiredError(
            f"reopen window of {window_days}d has elapsed; "
            "create a linked ticket instead"
        )
