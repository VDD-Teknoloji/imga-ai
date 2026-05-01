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

from fastapi import APIRouter, Depends, HTTPException, Query, status
from imga_db.models import (
    CancellationReason,
    Ticket,
    TicketAssignmentEvent,
    TicketComment,
    TicketCommentKind,
    TicketPriority,
    TicketState,
    TicketStateTransition,
    UserTenantRole,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import CurrentUser, bind_tenant, require_role
from imga_api.db_deps import get_app_session
from imga_api.dependencies import get_comment_service, get_ticket_service
from imga_api.services import (
    COMMENT_MAX_BODY_LENGTH,
    CancellationReasonRequiredError,
    CommentForbiddenError,
    CommentNotFoundError,
    CommentService,
    CommentServiceError,
    ForbiddenTransitionError,
    GroupBy,
    InvalidTransitionError,
    OrderBy,
    OrderDirection,
    TicketFilters,
    TicketNotFoundError,
    TicketNotFoundForCommentError,
    TicketService,
    TicketServiceError,
    TicketStatsResult,
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
    """Response for GET /tickets. ``total`` ignores limit/offset so the
    UI can render "X / Y" counters without a second request."""

    tickets: list[TicketResponse]
    total: int
    limit: int
    offset: int


class StatsBucketView(BaseModel):
    key: str
    label: str
    count: int


class StatsResponse(BaseModel):
    """Response for GET /tickets/stats. ``total`` is the count over the
    filtered set before grouping; ``results`` are the per-group buckets
    sorted by count desc."""

    group_by: str
    total: int
    results: list[StatsBucketView]


class TransitionView(BaseModel):
    id: UUID
    from_state: str
    to_state: str
    actor_user_id: UUID | None
    reason: str | None
    occurred_at: datetime


class TransitionsResponse(BaseModel):
    transitions: list[TransitionView]


class CommentCreateRequest(BaseModel):
    """Body for POST /tickets/{id}/comments."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {"body": "Müşteri kargo adresini değiştirdi.", "kind": "internal_note"},
                {"body": "Sayın müşterimiz, talebiniz alınmıştır...", "kind": "customer_reply"},
            ]
        },
    )
    body: str = Field(..., min_length=1, max_length=COMMENT_MAX_BODY_LENGTH)
    kind: TicketCommentKind


class CommentView(BaseModel):
    id: UUID
    ticket_id: UUID
    author_user_id: UUID | None
    body: str
    kind: str
    created_at: datetime
    is_archived: bool
    archived_at: datetime | None
    archived_by_user_id: UUID | None


class CommentsResponse(BaseModel):
    """List response. ``include_archived=false`` filters live-only."""

    comments: list[CommentView]


# --- timeline (transitions + comments merged chronologically) -----------


class TimelineEvent(BaseModel):
    """Polymorphic timeline row. ``type`` discriminates the payload —
    'state_transition' carries from_state/to_state/reason; 'comment'
    carries body/kind/is_archived; 'assignment_changed' (Sprint 7.7.2
    patch) carries from_user_id/to_user_id. The merged ordering is
    ascending by ``occurred_at`` so the UI can render top-down without
    sorting client-side."""

    type: str  # "state_transition" | "comment" | "assignment_changed"
    id: UUID
    occurred_at: datetime
    actor_user_id: UUID | None

    # state_transition fields
    from_state: str | None = None
    to_state: str | None = None
    reason: str | None = None

    # comment fields
    body: str | None = None
    kind: str | None = None
    is_archived: bool | None = None
    archived_at: datetime | None = None
    archived_by_user_id: UUID | None = None

    # assignment_changed fields. Either side may be NULL (was/became
    # unassigned), but never both — service enforces "no-op skip" and
    # the DB CHECK biconditional rejects same-user rows.
    from_user_id: UUID | None = None
    to_user_id: UUID | None = None


class TimelineResponse(BaseModel):
    events: list[TimelineEvent]


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


def _filters_validation_error(exc: ValidationError) -> HTTPException:
    """Surface Pydantic 422 errors with the same shape FastAPI uses for
    request-body validation. Keeps the wire contract consistent with the
    rest of the API (single ``detail`` list of field errors)."""
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=exc.errors(include_url=False, include_input=False),
    )


def get_ticket_filters(
    state: Annotated[str | None, Query(description="CSV of state codes; empty allowed")] = None,
    priority: Annotated[str | None, Query(description="CSV of priority codes")] = None,
    category_id: Annotated[str | None, Query(description="CSV of category UUIDs")] = None,
    opened_after: Annotated[datetime | None, Query()] = None,
    opened_before: Annotated[datetime | None, Query()] = None,
    assignee: Annotated[
        str | None,
        Query(description='"me" / "unassigned" / a user UUID', max_length=64),
    ] = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    order_by: Annotated[OrderBy, Query()] = "last_state_change_at",
    order: Annotated[OrderDirection, Query()] = "desc",
) -> TicketFilters:
    """Depends factory that runs raw query params through TicketFilters.

    The CSV-string params (``state``, ``priority``, ``category_id``)
    are parsed by the model's field_validator(mode="before"), so an
    empty string yields ``[]`` rather than a 422. Unknown enum values
    still raise — the validator just splits, the enum coercion still
    happens after."""
    try:
        return TicketFilters(
            state=state,  # type: ignore[arg-type]
            priority=priority,  # type: ignore[arg-type]
            category_id=category_id,  # type: ignore[arg-type]
            opened_after=opened_after,
            opened_before=opened_before,
            assignee=assignee,
            search=search,
            limit=limit,
            offset=offset,
            order_by=order_by,
            order=order,
        )
    except ValidationError as exc:
        raise _filters_validation_error(exc) from exc


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
    summary="List tickets with multi-value filter, search, sort, and offset paging.",
    description=(
        "Multi-value filters (``state``, ``priority``, ``category_id``) "
        "accept comma-separated values: ``?state=open,in_progress``. "
        "Empty strings are treated as 'no filter' rather than an error. "
        "Sort: ``order_by`` is a fixed Literal (opened_at / "
        "last_state_change_at / priority) so SQL injection / unknown-"
        "column errors are impossible at the route layer. Offset paging "
        "is capped at ``limit=500``; cursor pagination lands in Sprint 8."
    ),
    responses={
        422: {"description": "Filter validation failed (unknown enum value etc.)."},
    },
)
async def list_tickets(
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    tickets: Annotated[TicketService, Depends(get_ticket_service)],
    filters: Annotated[TicketFilters, Depends(get_ticket_filters)],
) -> TicketListResponse:
    """Filtered + paginated list. Tenant scoping is enforced by RLS on
    the bound app session, so the service stays oblivious to the active
    tenant beyond the explicit ``tenant_id`` filter (defence in depth)."""
    tenant_id = _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        rows, total = await tickets.list_filtered(
            tenant_id=tenant_id,
            filters=filters,
            actor_user_id=current.user_id,
        )
    return TicketListResponse(
        tickets=[_ticket_view(t) for t in rows],
        total=total,
        limit=filters.limit,
        offset=filters.offset,
    )


@router.get(
    "/stats",
    response_model=StatsResponse,
    summary="Aggregate ticket counts by state / priority / category / assignee.",
    description=(
        "Same filter surface as GET /tickets, plus ``group_by`` "
        "(state / priority / category / assignee). Categories are "
        "resolved to their ``label_tr`` via LEFT JOIN; assignee buckets "
        "show the user UUID until the tenant directory endpoint lands "
        "in Alt-Faz 4 (frontend currently maps me / unassigned only). "
        "Unassigned tickets surface as a single ``unassigned`` bucket."
    ),
)
async def get_ticket_stats(
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    tickets: Annotated[TicketService, Depends(get_ticket_service)],
    filters: Annotated[TicketFilters, Depends(get_ticket_filters)],
    group_by: Annotated[GroupBy, Query()] = "state",
) -> StatsResponse:
    """RLS-bound aggregation. The /stats path runs inside the same
    ``app_session.begin()`` + ``bind_tenant`` block as /tickets so
    cross-tenant counts cannot leak even with a malformed filter."""
    tenant_id = _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        result: TicketStatsResult = await tickets.stats(
            tenant_id=tenant_id,
            group_by=group_by,
            filters=filters,
            actor_user_id=current.user_id,
        )
    return StatsResponse(
        group_by=result.group_by,
        total=result.total,
        results=[
            StatsBucketView(key=b.key, label=b.label, count=b.count)
            for b in result.results
        ],
    )


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


# --- comments + timeline (Sprint 7.5.5 / Alt-Faz 4) -------------------


def _comment_view(c: TicketComment) -> CommentView:
    return CommentView(
        id=c.id,
        ticket_id=c.ticket_id,
        author_user_id=c.author_user_id,
        body=c.body,
        kind=str(c.kind),
        created_at=c.created_at,
        is_archived=c.is_archived,
        archived_at=c.archived_at,
        archived_by_user_id=c.archived_by_user_id,
    )


def _map_comment_error(exc: Exception) -> HTTPException:
    if isinstance(exc, CommentNotFoundError | TicketNotFoundForCommentError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, CommentForbiddenError):
        # "already archived" is the only 409 path; everything else is 403.
        if "already archived" in str(exc):
            return HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=str(exc)
            )
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, CommentServiceError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    raise exc


@router.post(
    "/{ticket_id}/comments",
    response_model=CommentView,
    status_code=status.HTTP_201_CREATED,
    summary="Append a comment to the ticket (internal note or customer reply).",
    description=(
        "Role matrix: VIEWER can only post ``internal_note``; ANALYST "
        "and TENANT_ADMIN can post both kinds. State guard: "
        "``customer_reply`` is forbidden when the ticket is CLOSED or "
        "CANCELLED — internal notes remain allowed in every state so "
        "post-mortem notes survive."
    ),
    responses={
        403: {"description": "Role / state matrix rejected the kind."},
        404: {"description": "Ticket not found."},
        422: {"description": "Body empty or exceeds 8000-char cap."},
    },
)
async def create_comment(
    ticket_id: UUID,
    body: CommentCreateRequest,
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    comments: Annotated[CommentService, Depends(get_comment_service)],
) -> CommentView:
    _require_active_tenant(current)
    role = _role_for_state_machine(current)
    # Super-admin without a chosen tenant role still posts as the
    # most-privileged tenant role so the matrix reads consistently.
    effective_role = role if role is not None else UserTenantRole.TENANT_ADMIN
    tenant_id = current.active_tenant_id
    assert tenant_id is not None  # guarded by _require_active_tenant
    async with app_session.begin():
        await bind_tenant(app_session, current)
        try:
            comment = await comments.create(
                tenant_id=tenant_id,
                ticket_id=ticket_id,
                author_user_id=current.user_id,
                author_role=effective_role,
                body=body.body,
                kind=body.kind,
            )
        except Exception as exc:
            raise _map_comment_error(exc) from exc
        view = _comment_view(comment)
    return view


@router.get(
    "/{ticket_id}/comments",
    response_model=CommentsResponse,
    summary="List comments on a ticket; archived rows included by default.",
    description=(
        "Returns comments in chronological order (oldest first). "
        "``include_archived`` defaults to true so the UI can show the "
        "whole history with archived rows greyed out; pass ``false`` "
        "for a live-only list."
    ),
)
async def list_comments(
    ticket_id: UUID,
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    comments: Annotated[CommentService, Depends(get_comment_service)],
    include_archived: Annotated[bool, Query()] = True,
) -> CommentsResponse:
    _require_active_tenant(current)
    tenant_id = current.active_tenant_id
    assert tenant_id is not None
    async with app_session.begin():
        await bind_tenant(app_session, current)
        rows = await comments.list_for_ticket(
            tenant_id=tenant_id,
            ticket_id=ticket_id,
            include_archived=include_archived,
        )
    return CommentsResponse(comments=[_comment_view(c) for c in rows])


@router.post(
    "/{ticket_id}/comments/{comment_id}/archive",
    response_model=CommentView,
    summary="Soft-delete (archive) a comment. Author or admin only.",
    description=(
        "Archives the comment by setting ``deleted_at`` + "
        "``archived_by_user_id``. The row remains in the timeline with "
        "``is_archived=true`` so the historical record stays intact. "
        "Hard delete is intentionally absent."
    ),
    responses={
        403: {"description": "Not the author and not a tenant admin."},
        404: {"description": "Comment not found."},
        409: {"description": "Comment is already archived."},
    },
)
async def archive_comment(
    ticket_id: UUID,
    comment_id: UUID,
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    comments: Annotated[CommentService, Depends(get_comment_service)],
) -> CommentView:
    _require_active_tenant(current)
    role = _role_for_state_machine(current)
    effective_role = role if role is not None else UserTenantRole.TENANT_ADMIN
    async with app_session.begin():
        await bind_tenant(app_session, current)
        try:
            archived = await comments.archive(
                comment_id=comment_id,
                actor_user_id=current.user_id,
                actor_role=effective_role,
                actor_is_super_admin=current.is_super_admin,
            )
        except Exception as exc:
            raise _map_comment_error(exc) from exc
        view = _comment_view(archived)
    return view


@router.get(
    "/{ticket_id}/timeline",
    response_model=TimelineResponse,
    summary="Merged chronological timeline (transitions + comments + assignments).",
    description=(
        "Polymorphic event stream: state transitions, comments (archived "
        "rows included with is_archived=true), and assignment changes "
        "(Sprint 7.7.2). ``type`` discriminates the payload shape per "
        "row. Sorted ascending by occurred_at so the UI can render "
        "top-down without sorting client-side. The legacy /transitions "
        "endpoint remains for backwards compatibility."
    ),
)
async def get_timeline(
    ticket_id: UUID,
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    comments: Annotated[CommentService, Depends(get_comment_service)],
) -> TimelineResponse:
    _require_active_tenant(current)
    tenant_id = current.active_tenant_id
    assert tenant_id is not None
    async with app_session.begin():
        await bind_tenant(app_session, current)
        # Three independent queries (transitions, comments, assignments)
        # are simpler than a UNION here — the row counts are bounded
        # (one ticket's worth) and PostgreSQL's planner can't easily
        # merge three unrelated tables on a polymorphic timestamp
        # without losing per-table column types. We merge in Python,
        # where the polymorphic shape is also built.
        trans_stmt = (
            select(TicketStateTransition)
            .where(TicketStateTransition.ticket_id == ticket_id)
            .order_by(TicketStateTransition.occurred_at.asc())
        )
        trans_rows = list((await app_session.execute(trans_stmt)).scalars())

        assignment_stmt = (
            select(TicketAssignmentEvent)
            .where(TicketAssignmentEvent.ticket_id == ticket_id)
            .order_by(TicketAssignmentEvent.occurred_at.asc())
        )
        assignment_rows = list(
            (await app_session.execute(assignment_stmt)).scalars()
        )

        comment_rows = await comments.list_for_ticket(
            tenant_id=tenant_id,
            ticket_id=ticket_id,
            include_archived=True,
        )

    events: list[TimelineEvent] = []
    for r in trans_rows:
        events.append(
            TimelineEvent(
                type="state_transition",
                id=r.id,
                occurred_at=r.occurred_at,
                actor_user_id=r.actor_user_id,
                from_state=str(r.from_state),
                to_state=str(r.to_state),
                reason=r.reason,
            )
        )
    for a in assignment_rows:
        events.append(
            TimelineEvent(
                type="assignment_changed",
                id=a.id,
                occurred_at=a.occurred_at,
                actor_user_id=a.actor_user_id,
                from_user_id=a.from_user_id,
                to_user_id=a.to_user_id,
            )
        )
    for c in comment_rows:
        events.append(
            TimelineEvent(
                type="comment",
                id=c.id,
                occurred_at=c.created_at,
                actor_user_id=c.author_user_id,
                body=c.body,
                kind=str(c.kind),
                is_archived=c.is_archived,
                archived_at=c.archived_at,
                archived_by_user_id=c.archived_by_user_id,
            )
        )
    events.sort(key=lambda e: e.occurred_at)
    return TimelineResponse(events=events)


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
