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


class ReviewDetailResponse(BaseModel):
    id: UUID
    text: str
    text_hash: str
    analyzed_at: datetime
    source_type: str
    batch_job_id: UUID | None
    sentiment: SentimentBlock
    categorization: CategorizationBlock
    overrides_applied: list[dict[str, object]]
    ticket_id: UUID | None
    auto_ticket_decision: str
    auto_ticket_decision_reason: str | None


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
        review = await service.get_review(
            tenant_id=tenant_id, review_id=review_id
        )
        if review is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="review not found"
            )
        # Sprint 8.3.4 will populate overrides_applied + raw vs final
        # split. Today the review row only stores the final score; we
        # surface it as both raw and final so the frontend has a stable
        # shape and the divergence appears later without a contract
        # break.
        score = float(review.sentiment_score)
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
            overrides_applied=[],
            ticket_id=review.ticket_id,
            auto_ticket_decision=str(review.decision),
            auto_ticket_decision_reason=review.decision_reason,
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
    )
