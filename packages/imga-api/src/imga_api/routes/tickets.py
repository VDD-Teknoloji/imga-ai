"""/tickets endpoints — CRUD + transitions + quick-resolve + assign + customer-inbound.

All endpoints are tenant-scoped (require ``active_tenant_id``) and
RLS-bound inside their own ``session.begin()`` block.

State-changing endpoints map service errors to HTTP codes:

  * InvalidTransitionError      → 409 (graph rejection)
  * ForbiddenTransitionError    → 403 (role rejection)
  * WindowExpiredError          → 409 (regression / reopen window lapsed)
  * CancellationReasonRequiredError → 422
  * UnclaimByOthersError        → 403
  * TicketNotFoundError         → 404

Read endpoints are open to ANALYST / TENANT_ADMIN / VIEWER. Mutations
are open to ANALYST / TENANT_ADMIN; some specific transitions
(IN_PROGRESS → CANCELLED, reopen, uncancel) are TENANT_ADMIN-only and
the state machine returns 403 for ANALYST callers.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from imga_db.models import (
    CancellationReason,
    Ticket,
    TicketPriority,
    TicketState,
    TicketStateTransition,
    UserTenantRole,
)
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import CurrentUser, bind_tenant, require_role
from imga_api.db_deps import get_app_session
from imga_api.dependencies import get_ticket_service
from imga_api.services import (
    CancellationReasonRequiredError,
    ForbiddenTransitionError,
    InvalidTransitionError,
    TicketNotFoundError,
    TicketService,
    TicketServiceError,
    TransitionRequest,
    UnclaimByOthersError,
    WindowExpiredError,
)

router = APIRouter(prefix="/tickets", tags=["Tickets"])


# --- request/response models -------------------------------------------


class TicketCreateRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "category_id": "9c45a2f1-bd5c-4c81-9f1b-7b1a04d1e0c0",
                "title": "Kargom 5 gündür gelmedi",
                "summary": "Sipariş #A123, takip numarası yanıt vermiyor.",
                "priority": "high",
            }
        },
    )
    category_id: UUID
    title: str = Field(..., min_length=1, max_length=4000)
    summary: str | None = None
    priority: TicketPriority = TicketPriority.NORMAL
    review_id: UUID | None = None


class TicketTransitionBody(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {"to_state": "in_progress", "reason": "claiming for triage"},
                {"to_state": "cancelled", "cancellation_reason": "spam"},
                {"to_state": "open", "reason": "regression — customer not happy"},
            ]
        },
    )
    to_state: TicketState
    reason: str | None = Field(default=None, max_length=2000)
    cancellation_reason: CancellationReason | None = None


class TicketAssignBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assignee_user_id: UUID | None = None  # null clears the assignment


class TicketResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    review_id: UUID | None
    category_id: UUID
    state: str
    priority: str
    title: str
    summary: str | None
    assigned_to_user_id: UUID | None
    created_by_user_id: UUID | None
    cancellation_reason: str | None
    parent_ticket_id: UUID | None
    opened_at: datetime
    claimed_at: datetime | None
    pending_since: datetime | None
    resolved_at: datetime | None
    closed_at: datetime | None
    cancelled_at: datetime | None
    customer_inbound_received_at: datetime | None
    last_state_change_at: datetime


class TicketListResponse(BaseModel):
    tickets: list[TicketResponse]


class TransitionView(BaseModel):
    id: UUID
    from_state: str
    to_state: str
    actor_user_id: UUID | None
    reason: str | None
    occurred_at: datetime


class TransitionsResponse(BaseModel):
    transitions: list[TransitionView]


# --- helpers ------------------------------------------------------------


def _require_active_tenant(current: CurrentUser) -> UUID:
    if current.active_tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="active tenant context required for this endpoint",
        )
    return current.active_tenant_id


def _ticket_view(t: Ticket) -> TicketResponse:
    return TicketResponse(
        id=t.id,
        tenant_id=t.tenant_id,
        review_id=t.review_id,
        category_id=t.category_id,
        state=str(t.state),
        priority=str(t.priority),
        title=t.title,
        summary=t.summary,
        assigned_to_user_id=t.assigned_to_user_id,
        created_by_user_id=t.created_by_user_id,
        cancellation_reason=str(t.cancellation_reason) if t.cancellation_reason else None,
        parent_ticket_id=t.parent_ticket_id,
        opened_at=t.opened_at,
        claimed_at=t.claimed_at,
        pending_since=t.pending_since,
        resolved_at=t.resolved_at,
        closed_at=t.closed_at,
        cancelled_at=t.cancelled_at,
        customer_inbound_received_at=t.customer_inbound_received_at,
        last_state_change_at=t.last_state_change_at,
    )


def _map_transition_error(exc: Exception) -> HTTPException:
    """Translate state-machine / service errors to HTTP responses.
    Centralized so each endpoint stays a thin wrapper."""
    if isinstance(exc, TicketNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, ForbiddenTransitionError | UnclaimByOthersError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, InvalidTransitionError | WindowExpiredError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, CancellationReasonRequiredError):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        )
    if isinstance(exc, TicketServiceError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    raise exc  # unexpected — let the framework's 500 path handle it.


_AnyMember = Depends(require_role(
    UserTenantRole.TENANT_ADMIN,
    UserTenantRole.ANALYST,
    UserTenantRole.VIEWER,
))
_AnalystOrAdmin = Depends(require_role(
    UserTenantRole.TENANT_ADMIN,
    UserTenantRole.ANALYST,
))


# --- endpoints ---------------------------------------------------------


@router.post(
    "",
    response_model=TicketResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a ticket manually.",
    description=(
        "Creates a ticket in OPEN. The auto-create path from /analyze "
        "(Sprint 7.5.5 / 8) will use the same service entry point with "
        "created_by_user_id=None to flag the ticket as system-generated."
    ),
)
async def create_ticket(
    body: TicketCreateRequest,
    current: Annotated[CurrentUser, _AnalystOrAdmin],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    tickets: Annotated[TicketService, Depends(get_ticket_service)],
) -> TicketResponse:
    """Manual ticket creation. Auto-create from review pipeline lives
    in the ingestion path (Sprint 8) and uses TicketService.create
    directly with ``created_by_user_id=None``."""
    tenant_id = _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        ticket = await tickets.create(
            tenant_id=tenant_id,
            category_id=body.category_id,
            title=body.title,
            summary=body.summary,
            priority=body.priority,
            review_id=body.review_id,
            created_by_user_id=current.user_id,
        )
        view = _ticket_view(ticket)
    return view


@router.get(
    "",
    response_model=TicketListResponse,
    summary="List tickets in the active tenant; default sort by latest state change.",
)
async def list_tickets(
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    state: TicketState | None = None,
) -> TicketListResponse:
    """List tickets in the active tenant. Filtered by state when given.
    Default sort: most-recent state change first (matches the UI's
    default queue ordering)."""
    _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        stmt = (
            select(Ticket)
            .where(Ticket.deleted_at.is_(None))
            .order_by(Ticket.last_state_change_at.desc())
        )
        if state is not None:
            stmt = stmt.where(Ticket.state == state)
        result = await app_session.execute(stmt)
        rows = list(result.scalars())
    return TicketListResponse(tickets=[_ticket_view(t) for t in rows])


@router.get(
    "/{ticket_id}",
    response_model=TicketResponse,
    summary="Fetch a single ticket by id.",
    responses={404: {"description": "Ticket not found or hidden by RLS."}},
)
async def get_ticket(
    ticket_id: UUID,
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> TicketResponse:
    _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        ticket = await app_session.get(Ticket, ticket_id)
        if ticket is None or ticket.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="ticket not found"
            )
        view = _ticket_view(ticket)
    return view


@router.get(
    "/{ticket_id}/transitions",
    response_model=TransitionsResponse,
    summary="Append-only timeline of every state change for the ticket.",
)
async def list_transitions(
    ticket_id: UUID,
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> TransitionsResponse:
    _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        stmt = (
            select(TicketStateTransition)
            .where(TicketStateTransition.ticket_id == ticket_id)
            .order_by(TicketStateTransition.occurred_at.asc())
        )
        rows = list((await app_session.execute(stmt)).scalars())
    return TransitionsResponse(
        transitions=[
            TransitionView(
                id=r.id,
                from_state=str(r.from_state),
                to_state=str(r.to_state),
                actor_user_id=r.actor_user_id,
                reason=r.reason,
                occurred_at=r.occurred_at,
            )
            for r in rows
        ]
    )


@router.post(
    "/{ticket_id}/transition",
    response_model=TicketResponse,
    summary="Move the ticket to a new state.",
    description=(
        "State machine: OPEN ↔ IN_PROGRESS ↔ PENDING_CUSTOMER → "
        "RESOLVED → CLOSED, plus CANCELLED branch and admin-only reopen "
        "/ uncancel back to OPEN. Reopen and uncancel are bounded by "
        "per-tenant windows (default 30d). RESOLVED → IN_PROGRESS is "
        "bounded by resolved_regression_window_days (default 7d). "
        "Past either window, callers get 409 with a hint to create a "
        "linked ticket (Sprint 8 feature)."
    ),
    responses={
        403: {"description": "Role not authorized for this transition."},
        404: {"description": "Ticket not found."},
        409: {"description": "Graph rejection or per-tenant window expired."},
        422: {"description": "cancellation_reason missing for to_state=cancelled."},
    },
)
async def transition_ticket(
    ticket_id: UUID,
    body: TicketTransitionBody,
    current: Annotated[CurrentUser, _AnalystOrAdmin],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    tickets: Annotated[TicketService, Depends(get_ticket_service)],
) -> TicketResponse:
    """Generic transition endpoint. The state machine + service decides
    whether the move is permitted; specific state pairs (reopen,
    uncancel, regression) carry per-tenant time-window guards."""
    _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        try:
            ticket = await tickets.transition(
                ticket_id=ticket_id,
                request=TransitionRequest(
                    to_state=body.to_state,
                    reason=body.reason,
                    cancellation_reason=body.cancellation_reason,
                ),
                actor_user_id=current.user_id,
                actor_role=_role_for_state_machine(current),
                actor_is_super_admin=current.is_super_admin,
            )
        except Exception as exc:
            raise _map_transition_error(exc) from exc
        view = _ticket_view(ticket)
    return view


@router.post(
    "/{ticket_id}/quick-resolve",
    response_model=TicketResponse,
    summary="OPEN → IN_PROGRESS → RESOLVED in one call (two timeline rows).",
    description=(
        "Convenience for trivially-answerable tickets where the analyst "
        "doesn't need to claim and walk away first. Two transitions are "
        "recorded in the timeline + audit log so the history is "
        "unambiguous about what happened."
    ),
)
async def quick_resolve(
    ticket_id: UUID,
    current: Annotated[CurrentUser, _AnalystOrAdmin],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    tickets: Annotated[TicketService, Depends(get_ticket_service)],
    body: TicketTransitionBody | None = None,
) -> TicketResponse:
    """Two transitions in one call (claim + resolve). Ticket must be in
    OPEN. Two timeline rows + two audit entries are written so the
    history is unambiguous."""
    _require_active_tenant(current)
    reason = body.reason if body else None
    async with app_session.begin():
        await bind_tenant(app_session, current)
        try:
            ticket = await tickets.quick_resolve(
                ticket_id=ticket_id,
                actor_user_id=current.user_id,
                actor_role=_role_for_state_machine(current),
                actor_is_super_admin=current.is_super_admin,
                reason=reason,
            )
        except Exception as exc:
            raise _map_transition_error(exc) from exc
        view = _ticket_view(ticket)
    return view


@router.post(
    "/{ticket_id}/assign",
    response_model=TicketResponse,
    summary="Reassign or unassign a ticket. Metadata-only, no state change.",
)
async def assign_ticket(
    ticket_id: UUID,
    body: TicketAssignBody,
    current: Annotated[CurrentUser, _AnalystOrAdmin],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    tickets: Annotated[TicketService, Depends(get_ticket_service)],
) -> TicketResponse:
    """Set or clear the ticket assignee. Metadata-only — no state change."""
    _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        try:
            ticket = await tickets.assign(
                ticket_id=ticket_id,
                new_assignee_id=body.assignee_user_id,
                actor_user_id=current.user_id,
            )
        except Exception as exc:
            raise _map_transition_error(exc) from exc
        view = _ticket_view(ticket)
    return view


@router.post(
    "/{ticket_id}/customer-inbound",
    response_model=TicketResponse,
    summary="Stamp customer-inbound metadata. Does not change state.",
    description=(
        "Records that the customer replied. State stays the same so "
        "spam / bounce / bot replies cannot auto-resume "
        "PENDING_CUSTOMER tickets. The analyst decides whether to call "
        "/transition with to_state=in_progress next."
    ),
)
async def record_customer_inbound(
    ticket_id: UUID,
    current: Annotated[CurrentUser, _AnalystOrAdmin],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    tickets: Annotated[TicketService, Depends(get_ticket_service)],
) -> TicketResponse:
    """Stamp ``customer_inbound_received_at``. Does NOT change state —
    the analyst decides whether to resume PENDING_CUSTOMER tickets;
    spam / bounce / bot replies must not auto-resume.

    Public-facing endpoint accepts the call from a future webhook
    bridge (Sprint 8). For now the role gate keeps it internal."""
    _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        try:
            ticket = await tickets.record_customer_inbound(ticket_id=ticket_id)
        except Exception as exc:
            raise _map_transition_error(exc) from exc
        view = _ticket_view(ticket)
    return view


def _role_for_state_machine(current: CurrentUser) -> UserTenantRole | None:
    """Map the JWT role string back to the enum the state machine wants.

    Super-admin without a chosen tenant role still falls through; the
    state machine handles is_super_admin separately."""
    if current.active_role is None:
        return None
    try:
        return UserTenantRole(current.active_role)
    except ValueError:
        return None
