"""Pure-function tests for the ticket state machine.

No DB, no fixtures, no async — just enums and datetimes. The integration
tests in test_tickets.py exercise the service layer that consumes
these primitives.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from imga_db.models import TicketState, UserTenantRole

from imga_api.services.ticket_state_machine import (
    ROLE_MATRIX,
    TRANSITIONS,
    ForbiddenTransitionError,
    InvalidTransitionError,
    WindowExpiredError,
    assert_within_regression_window,
    assert_within_reopen_window,
    is_authorized,
    is_valid_transition,
    is_within_window,
    validate_transition,
)

# --- transition graph ---------------------------------------------------


@pytest.mark.parametrize(
    "from_state,to_state,expected",
    [
        # OPEN exits
        (TicketState.OPEN, TicketState.IN_PROGRESS, True),
        (TicketState.OPEN, TicketState.CANCELLED, True),
        # OPEN -> RESOLVED was deliberately removed in 7.5 revision 4.
        (TicketState.OPEN, TicketState.RESOLVED, False),
        (TicketState.OPEN, TicketState.CLOSED, False),

        # IN_PROGRESS exits
        (TicketState.IN_PROGRESS, TicketState.OPEN, True),
        (TicketState.IN_PROGRESS, TicketState.PENDING_CUSTOMER, True),
        (TicketState.IN_PROGRESS, TicketState.RESOLVED, True),
        (TicketState.IN_PROGRESS, TicketState.CANCELLED, True),
        (TicketState.IN_PROGRESS, TicketState.CLOSED, False),

        # PENDING_CUSTOMER exits
        (TicketState.PENDING_CUSTOMER, TicketState.IN_PROGRESS, True),
        (TicketState.PENDING_CUSTOMER, TicketState.RESOLVED, True),
        (TicketState.PENDING_CUSTOMER, TicketState.CLOSED, True),
        (TicketState.PENDING_CUSTOMER, TicketState.CANCELLED, False),

        # RESOLVED exits
        (TicketState.RESOLVED, TicketState.CLOSED, True),
        (TicketState.RESOLVED, TicketState.IN_PROGRESS, True),
        (TicketState.RESOLVED, TicketState.PENDING_CUSTOMER, False),

        # CLOSED exits — only reopen
        (TicketState.CLOSED, TicketState.OPEN, True),
        (TicketState.CLOSED, TicketState.IN_PROGRESS, False),

        # CANCELLED exits — only uncancel
        (TicketState.CANCELLED, TicketState.OPEN, True),
        (TicketState.CANCELLED, TicketState.CLOSED, False),
    ],
)
def test_is_valid_transition(
    from_state: TicketState, to_state: TicketState, expected: bool
) -> None:
    assert is_valid_transition(from_state, to_state) is expected


def test_no_self_loop_transitions() -> None:
    for state in TicketState:
        assert state not in TRANSITIONS.get(state, frozenset()), (
            f"self-loop {state} -> {state} must not be in the graph"
        )


def test_role_matrix_only_covers_valid_transitions() -> None:
    """Every entry in ROLE_MATRIX must reference a valid graph edge."""
    for (from_state, to_state) in ROLE_MATRIX:
        assert is_valid_transition(from_state, to_state), (
            f"ROLE_MATRIX has stale entry {from_state} -> {to_state}"
        )


def test_role_matrix_covers_every_user_facing_edge() -> None:
    """Every graph edge must have a ROLE_MATRIX entry (even if it's
    an empty set for system-only transitions)."""
    for from_state, tos in TRANSITIONS.items():
        for to in tos:
            assert (from_state, to) in ROLE_MATRIX, (
                f"missing ROLE_MATRIX entry for {from_state} -> {to}"
            )


# --- authorization rules -----------------------------------------------


def test_super_admin_passes_every_user_facing_transition() -> None:
    for from_state, tos in TRANSITIONS.items():
        for to in tos:
            assert is_authorized(
                from_state, to, role=None, is_super_admin=True
            ) is True


def test_system_actor_passes_every_transition() -> None:
    for from_state, tos in TRANSITIONS.items():
        for to in tos:
            assert is_authorized(
                from_state, to, role=None, actor_is_system=True
            ) is True


def test_viewer_cannot_perform_any_state_transition() -> None:
    for from_state, tos in TRANSITIONS.items():
        for to in tos:
            assert is_authorized(
                from_state, to, role=UserTenantRole.VIEWER
            ) is False


def test_analyst_cannot_reopen_closed() -> None:
    assert is_authorized(
        TicketState.CLOSED, TicketState.OPEN, role=UserTenantRole.ANALYST
    ) is False


def test_analyst_cannot_uncancel() -> None:
    assert is_authorized(
        TicketState.CANCELLED, TicketState.OPEN, role=UserTenantRole.ANALYST
    ) is False


def test_analyst_cannot_cancel_in_progress() -> None:
    """7.5 revision 5: analyst must un-claim first, then admin cancels."""
    assert is_authorized(
        TicketState.IN_PROGRESS,
        TicketState.CANCELLED,
        role=UserTenantRole.ANALYST,
    ) is False


def test_analyst_can_cancel_open() -> None:
    assert is_authorized(
        TicketState.OPEN, TicketState.CANCELLED, role=UserTenantRole.ANALYST
    ) is True


def test_admin_can_reopen_and_uncancel() -> None:
    assert is_authorized(
        TicketState.CLOSED,
        TicketState.OPEN,
        role=UserTenantRole.TENANT_ADMIN,
    ) is True
    assert is_authorized(
        TicketState.CANCELLED,
        TicketState.OPEN,
        role=UserTenantRole.TENANT_ADMIN,
    ) is True


def test_pending_customer_to_closed_is_system_only() -> None:
    """Auto-close path; no human role should be authorized."""
    for role in UserTenantRole:
        assert is_authorized(
            TicketState.PENDING_CUSTOMER,
            TicketState.CLOSED,
            role=role,
        ) is False
    assert is_authorized(
        TicketState.PENDING_CUSTOMER,
        TicketState.CLOSED,
        role=None,
        actor_is_system=True,
    ) is True


# --- validate_transition raises the right exception type ---------------


def test_validate_raises_invalid_for_graph_violation() -> None:
    with pytest.raises(InvalidTransitionError):
        validate_transition(
            TicketState.OPEN,
            TicketState.RESOLVED,  # removed in revision 4
            role=UserTenantRole.TENANT_ADMIN,
        )


def test_validate_raises_forbidden_for_role_violation() -> None:
    with pytest.raises(ForbiddenTransitionError):
        validate_transition(
            TicketState.CLOSED,
            TicketState.OPEN,
            role=UserTenantRole.ANALYST,
        )


def test_validate_passes_for_admin_reopen() -> None:
    # No raise.
    validate_transition(
        TicketState.CLOSED,
        TicketState.OPEN,
        role=UserTenantRole.TENANT_ADMIN,
    )


# --- window guards ------------------------------------------------------


def test_within_window_anchor_none_returns_false() -> None:
    assert is_within_window(None, window_days=7) is False


def test_within_window_at_exact_boundary_passes() -> None:
    now = datetime(2026, 1, 10, tzinfo=UTC)
    anchor = now - timedelta(days=7)  # exactly at the boundary
    assert is_within_window(anchor, window_days=7, now=now) is True


def test_within_window_past_boundary_fails() -> None:
    now = datetime(2026, 1, 10, tzinfo=UTC)
    anchor = now - timedelta(days=7, seconds=1)
    assert is_within_window(anchor, window_days=7, now=now) is False


def test_assert_regression_window_raises_when_lapsed() -> None:
    now = datetime(2026, 1, 10, tzinfo=UTC)
    resolved = now - timedelta(days=8)
    with pytest.raises(WindowExpiredError):
        assert_within_regression_window(resolved, window_days=7, now=now)


def test_assert_regression_window_passes_when_within() -> None:
    now = datetime(2026, 1, 10, tzinfo=UTC)
    resolved = now - timedelta(days=3)
    # Should not raise.
    assert_within_regression_window(resolved, window_days=7, now=now)


def test_assert_reopen_window_handles_none_anchor() -> None:
    """A row with closed_at IS NULL but state='closed' shouldn't happen
    (timestamps are set on transition), but defensively the guard still
    raises rather than allowing the transition."""
    with pytest.raises(WindowExpiredError):
        assert_within_reopen_window(None, window_days=30)
