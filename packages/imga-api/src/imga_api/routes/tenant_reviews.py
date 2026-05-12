"""``/tenants/me/reviews`` — list + detail over the analyzed-text archive.

Sprint 8.3.1 (originally 8.3.4 in the spec; pulled forward so batch
upload users can immediately see results). Filters mirror the ticket
list pattern. The detail endpoint includes ``raw_score`` /
``final_score`` (synonyms today; once override math becomes visible
they diverge) plus the override layer trace.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from imga_db.models import UserTenantRole
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import CurrentUser, bind_tenant, require_role
from imga_api.db_deps import get_app_session
from imga_api.dependencies import get_review_service
from imga_api.services import (
    CategoryNotConfiguredError,
    ReviewAlreadyTicketedError,
    ReviewNotFoundError,
    ReviewService,
)
from imga_api.services.review_list_service import (
    ReviewListFilters,
    ReviewListItem,
    ReviewListService,
)

router = APIRouter(prefix="/tenants/me/reviews", tags=["Analyze"])

_AnyMember = Depends(require_role(
    UserTenantRole.TENANT_ADMIN,
    UserTenantRole.ANALYST,
    UserTenantRole.VIEWER,
))
_WriteMember = Depends(require_role(
    UserTenantRole.TENANT_ADMIN,
    UserTenantRole.ANALYST,
))


def _require_active_tenant(current: CurrentUser) -> UUID:
    if current.active_tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="active tenant context required for this endpoint",
        )
    return current.active_tenant_id


def _split_csv(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    return tuple(part.strip() for part in raw.split(",") if part.strip())


# --- response models -----------------------------------------------


class ReviewItemResponse(BaseModel):
    id: UUID
    text: str
    sentiment_label: str
    sentiment_score: float
    primary_category: str
    primary_confidence: float
    decision: str
    decision_reason: str | None
    ticket_id: UUID | None
    batch_job_id: UUID | None
    source_type: str
    analyzed_at: datetime
    submitted_by_user_id: UUID | None
    override_count: int
    company_perspective_code: str | None = None
    company_perspective_label_tr: str | None = None


class ReviewListResponse(BaseModel):
    items: list[ReviewItemResponse]
    total: int
    limit: int
    offset: int


class SentimentBlock(BaseModel):
    label: str
    score: float
    raw_score: float
    final_score: float


class CategorizationBlock(BaseModel):
    primary: str
    primary_confidence: float


class CompanyPerspectiveBlock(BaseModel):
    """Heuristic match block, Sprint 8.3.5.6.

    Both fields can be None: ``code`` is None when the heuristic didn't
    fire, ``label_tr`` is None additionally when the taxonomy row has
    been pruned since analyze (Sprint 8.3.7 edit UI). Frontend renders
    "removed category" for code != None / label_tr None.
    """

    code: str | None
    label_tr: str | None


class ReviewDetailResponse(BaseModel):
    id: UUID
    text: str
    text_hash: str
    analyzed_at: datetime
    source_type: str
    batch_job_id: UUID | None
    sentiment: SentimentBlock
    categorization: CategorizationBlock
    company_perspective: CompanyPerspectiveBlock
    overrides_applied: list[dict[str, object]]
    ticket_id: UUID | None
    auto_ticket_decision: str
    auto_ticket_decision_reason: str | None
    nps_score: int | None = None
    nps_category: str | None = None


# --- endpoints -----------------------------------------------------


@router.get(
    "",
    response_model=ReviewListResponse,
    summary="Filtered list over the tenant's analyzed-text archive.",
)
async def list_reviews(
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    sentiment_labels: str | None = Query(
        default=None,
        description="CSV: NEGATIF,POZITIF,NÖTR",
    ),
    has_ticket: bool | None = None,
    batch_job_id: UUID | None = None,
    source_types: str | None = Query(default=None, description="CSV: manual,batch"),
    decisions: str | None = Query(
        default=None,
        description="CSV: create,skipped_belirsiz,skipped_mode,skipped_threshold,skipped_dedup",
    ),
    perspective_codes: str | None = Query(
        default=None,
        description=(
            "CSV of CategoryTaxonomy.code values. The literal "
            "'__unmatched__' filters to rows where the heuristic didn't "
            "match any code (NULL company_perspective_code)."
        ),
    ),
    primary_categories: str | None = Query(
        default=None,
        description=(
            "Sprint 8.3.10 — CSV of BERT primary_category codes. The "
            "/insights cross-analysis heatmap drill-down passes this "
            "to scope the listing to the clicked cell's category."
        ),
    ),
    hour_of_day: int | None = Query(
        default=None,
        ge=0,
        le=23,
        description=(
            "Sprint 9.5 B1 — heatmap drilldown filter. EXTRACT(HOUR "
            "FROM created_at) match. Frontend passes the cell's "
            "x_keys/y_keys value when xAxis or yAxis = hour_of_day."
        ),
    ),
    day_of_week: int | None = Query(
        default=None,
        ge=0,
        le=6,
        description=(
            "Sprint 9.5 B1 — EXTRACT(DOW FROM created_at) match. "
            "Postgres DOW: 0=Sunday..6=Saturday."
        ),
    ),
    week_of_year: int | None = Query(
        default=None,
        ge=1,
        le=53,
        description="Sprint 9.5 B1 — EXTRACT(WEEK FROM created_at) match.",
    ),
    month: int | None = Query(
        default=None,
        ge=1,
        le=12,
        description="Sprint 9.5 B1 — EXTRACT(MONTH FROM created_at) match.",
    ),
    search: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    order_by: Literal["created_at", "sentiment_score"] = "created_at",
    order: Literal["asc", "desc"] = "desc",
) -> ReviewListResponse:
    tenant_id = _require_active_tenant(current)
    filters = ReviewListFilters(
        date_from=date_from,
        date_to=date_to,
        sentiment_labels=_split_csv(sentiment_labels),
        has_ticket=has_ticket,
        batch_job_id=batch_job_id,
        source_types=_split_csv(source_types),
        decisions=_split_csv(decisions),
        perspective_codes=_split_csv(perspective_codes),
        primary_categories=_split_csv(primary_categories),
        hour_of_day=hour_of_day,
        day_of_week=day_of_week,
        week_of_year=week_of_year,
        month=month,
        search=search,
        order_by=order_by,
        order=order,
    )
    async with app_session.begin():
        await bind_tenant(app_session, current)
        service = ReviewListService(app_session)
        items, total = await service.list_reviews(
            tenant_id=tenant_id,
            filters=filters,
            limit=limit,
            offset=offset,
        )
    return ReviewListResponse(
        items=[_to_item_response(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{review_id}",
    response_model=ReviewDetailResponse,
    summary="Single-review detail with override trace.",
    responses={404: {"description": "Review not found or hidden by RLS."}},
)
async def get_review(
    review_id: UUID,
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> ReviewDetailResponse:
    tenant_id = _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        service = ReviewListService(app_session)
        result = await service.get_review(
            tenant_id=tenant_id, review_id=review_id
        )
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="review not found"
            )
        review, perspective_label_tr = result
        # Sprint 8.3.4 — overrides_applied JSONB now populated by the
        # bridge (and the batch worker on the dedup/opt-out paths). Rows
        # analyzed before migration 0014 carry NULL; surface as []. The
        # raw/final score split still surfaces the same value on both
        # sides; once override math reshapes the score this row already
        # has the trace ready to drive the divergence.
        score = float(review.sentiment_score)
        overrides_list: list[dict[str, object]] = list(review.overrides_applied or [])
        return ReviewDetailResponse(
            id=review.id,
            text=review.text,
            text_hash=review.text_hash,
            analyzed_at=review.analyzed_at,
            source_type="batch" if review.batch_job_id else "manual",
            batch_job_id=review.batch_job_id,
            sentiment=SentimentBlock(
                label=review.sentiment_label,
                score=score,
                raw_score=score,
                final_score=score,
            ),
            categorization=CategorizationBlock(
                primary=review.primary_category,
                primary_confidence=float(review.primary_confidence),
            ),
            company_perspective=CompanyPerspectiveBlock(
                code=review.company_perspective_code,
                label_tr=perspective_label_tr,
            ),
            overrides_applied=overrides_list,
            ticket_id=review.ticket_id,
            auto_ticket_decision=str(review.decision),
            auto_ticket_decision_reason=review.decision_reason,
            nps_score=review.nps_score,
            nps_category=review.nps_category,
        )


class ManualPromotionResponse(BaseModel):
    review_id: UUID
    ticket_id: UUID
    ticket_state: str


@router.post(
    "/{review_id}/create-ticket",
    response_model=ManualPromotionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Manually open a ticket for a review the bridge skipped.",
    description=(
        "Used when an analyst's domain expertise overrides the bridge's "
        "no-op decision (skipped_mode / skipped_threshold / skipped_belirsiz). "
        "Idempotent on the review side: the second call against a review "
        "that already has a ticket returns 409. Viewer role is denied."
    ),
    responses={
        403: {"description": "Viewer role can not promote reviews."},
        404: {"description": "Review not found / hidden by RLS."},
        409: {"description": "Review already linked to a ticket."},
    },
)
async def manually_create_ticket(
    review_id: UUID,
    current: Annotated[CurrentUser, _WriteMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    reviews: Annotated[ReviewService, Depends(get_review_service)],
) -> ManualPromotionResponse:
    tenant_id = _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        try:
            ticket = await reviews.promote_to_ticket(
                tenant_id=tenant_id,
                review_id=review_id,
                actor_user_id=current.user_id,
            )
        except ReviewNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="review not found"
            ) from exc
        except ReviewAlreadyTicketedError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=str(exc)
            ) from exc
        except CategoryNotConfiguredError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=str(exc)
            ) from exc
        return ManualPromotionResponse(
            review_id=review_id,
            ticket_id=ticket.id,
            ticket_state=str(ticket.state),
        )


def _to_item_response(item: ReviewListItem) -> ReviewItemResponse:
    return ReviewItemResponse(
        id=item.id,
        text=item.text,
        sentiment_label=item.sentiment_label,
        sentiment_score=item.sentiment_score,
        primary_category=item.primary_category,
        primary_confidence=item.primary_confidence,
        decision=item.decision,
        decision_reason=item.decision_reason,
        ticket_id=item.ticket_id,
        batch_job_id=item.batch_job_id,
        source_type=item.source_type,
        analyzed_at=item.analyzed_at,
        submitted_by_user_id=item.submitted_by_user_id,
        override_count=item.override_count,
        company_perspective_code=item.company_perspective_code,
        company_perspective_label_tr=item.company_perspective_label_tr,
    )
