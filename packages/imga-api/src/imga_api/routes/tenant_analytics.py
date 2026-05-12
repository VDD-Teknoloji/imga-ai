"""``/tenants/me/analytics/*`` — read-only aggregations for /insights.

Sprint 8.3.3. Seven endpoints, all GET, all RLS-bound (app session +
bind_tenant). The ticket-only ``/tickets/stats`` from Sprint 7 is left
intact; the analytics namespace is review-centric (with one ticket
endpoint for resolution time).

Filters share a CSV-encoded querystring shape, mirroring the
``/tickets/stats`` and ``/reviews`` patterns.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from imga_db.models import UserTenantRole
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import CurrentUser, bind_tenant, require_role
from imga_api.db_deps import get_app_session
from imga_api.services.analytics_service import (
    AnalyticsFilters,
    AnalyticsService,
    Granularity,
)

router = APIRouter(prefix="/tenants/me/analytics", tags=["Analyze"])

_AnyMember = Depends(require_role(
    UserTenantRole.TENANT_ADMIN,
    UserTenantRole.ANALYST,
    UserTenantRole.VIEWER,
))


# --- response shapes ----------------------------------------------------


class SentimentDistRowResponse(BaseModel):
    label: str
    count: int
    percentage: float
    avg_score: float


class SentimentDistResponse(BaseModel):
    total: int
    data: list[SentimentDistRowResponse]


class CategoryDistRowResponse(BaseModel):
    category: str
    category_label_tr: str
    count: int
    percentage: float


class CategoryDistResponse(BaseModel):
    total: int
    data: list[CategoryDistRowResponse]


class SentimentByCategoryResponse(BaseModel):
    categories: list[str]
    category_labels_tr: list[str]
    sentiments: list[str]
    matrix: list[list[int]]
    totals_by_category: list[int]
    totals_by_sentiment: list[int]


class OverrideStatsRowResponse(BaseModel):
    layer: str
    layer_label_tr: str
    trigger_count: int
    trigger_percentage: float
    direction: str
    avg_impact: float
    max_impact: float


class OverrideStatsResponse(BaseModel):
    total_reviews: int
    data: list[OverrideStatsRowResponse]


class TimelinePointResponse(BaseModel):
    date: str
    negatif: int = Field(alias="negatif")
    nötr: int = Field(alias="nötr")
    pozitif: int = Field(alias="pozitif")
    total: int
    avg_score: float

    model_config = {"populate_by_name": True}


class TimelineResponse(BaseModel):
    granularity: str
    data: list[TimelinePointResponse]


class ResolutionBucketResponse(BaseModel):
    bucket: str
    count: int


class ResolutionByCategoryResponse(BaseModel):
    category: str
    avg_hours: float
    count: int


class TicketResolutionResponse(BaseModel):
    total_resolved_tickets: int
    avg_resolution_hours: float
    median_resolution_hours: float
    p95_resolution_hours: float
    distribution: list[ResolutionBucketResponse]
    by_category: list[ResolutionByCategoryResponse]


class SensitivityBucketResponse(BaseModel):
    range_start: float
    range_end: float
    count: int


class SensitivityStatsResponse(BaseModel):
    mean: float
    median: float
    std_dev: float


class SensitivityDistResponse(BaseModel):
    total: int
    buckets: list[SensitivityBucketResponse]
    stats: SensitivityStatsResponse


class NPSSummaryResponse(BaseModel):
    score: float | None
    detractor_count: int
    passive_count: int
    promoter_count: int
    total_count: int
    coverage_percent: float


class NPSMonthlyPointResponse(BaseModel):
    month: date
    score: float | None
    detractor_count: int
    passive_count: int
    promoter_count: int
    total_count: int


class HeadlineMetricsResponse(BaseModel):
    total_reviews: int
    open_tickets: int
    today_new_tickets: int
    crisis_count: int
    nps_score: float | None
    nps_coverage_percent: float
    avg_sentiment_score: float | None
    sensitive_topics_count: int


class CompanyPerspectiveDistRowResponse(BaseModel):
    code: str
    label_tr: str
    count: int
    percentage: float


class CompanyPerspectiveDistResponse(BaseModel):
    total: int
    unmatched_count: int
    data: list[CompanyPerspectiveDistRowResponse]


# --- helpers ------------------------------------------------------------


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


def _split_uuid_csv(raw: str | None) -> tuple[UUID, ...]:
    return tuple(UUID(p) for p in _split_csv(raw))


def _build_filters(
    date_from: datetime | None,
    date_to: datetime | None,
    sentiment_labels: str | None = None,
    category_ids: str | None = None,
    source_types: str | None = None,
    batch_job_id: UUID | None = None,
) -> AnalyticsFilters:
    return AnalyticsFilters(
        date_from=date_from,
        date_to=date_to,
        sentiment_labels=_split_csv(sentiment_labels),
        category_ids=_split_uuid_csv(category_ids),
        source_types=_split_csv(source_types),
        batch_job_id=batch_job_id,
    )


# --- endpoints ----------------------------------------------------------


@router.get(
    "/sentiment-distribution",
    response_model=SentimentDistResponse,
    summary="Sentiment label counts + average score per label.",
)
async def sentiment_distribution(
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    sentiment_labels: str | None = None,
    category_ids: str | None = None,
    source_types: str | None = None,
    batch_job_id: UUID | None = None,
) -> SentimentDistResponse:
    tenant_id = _require_active_tenant(current)
    filters = _build_filters(
        date_from, date_to, sentiment_labels, category_ids, source_types, batch_job_id,
    )
    async with app_session.begin():
        await bind_tenant(app_session, current)
        result = await AnalyticsService(app_session).sentiment_distribution(
            tenant_id=tenant_id, filters=filters,
        )
    return SentimentDistResponse(
        total=result.total,
        data=[SentimentDistRowResponse(**asdict(row)) for row in result.data],
    )


@router.get(
    "/category-distribution",
    response_model=CategoryDistResponse,
    summary="Top-N categories by review count.",
)
async def category_distribution(
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    sentiment_labels: str | None = None,
    source_types: str | None = None,
    batch_job_id: UUID | None = None,
    limit: int = Query(default=10, ge=1, le=50),
) -> CategoryDistResponse:
    tenant_id = _require_active_tenant(current)
    filters = _build_filters(
        date_from, date_to, sentiment_labels=sentiment_labels,
        source_types=source_types, batch_job_id=batch_job_id,
    )
    async with app_session.begin():
        await bind_tenant(app_session, current)
        result = await AnalyticsService(app_session).category_distribution(
            tenant_id=tenant_id, filters=filters, limit=limit,
        )
    return CategoryDistResponse(
        total=result.total,
        data=[CategoryDistRowResponse(**asdict(row)) for row in result.data],
    )


@router.get(
    "/sentiment-by-category",
    response_model=SentimentByCategoryResponse,
    summary="Heatmap matrix: top N categories × sentiment labels.",
)
async def sentiment_by_category(
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    source_types: str | None = None,
    batch_job_id: UUID | None = None,
    top_n_categories: int = Query(default=10, ge=1, le=20),
) -> SentimentByCategoryResponse:
    tenant_id = _require_active_tenant(current)
    filters = _build_filters(
        date_from, date_to, source_types=source_types, batch_job_id=batch_job_id,
    )
    async with app_session.begin():
        await bind_tenant(app_session, current)
        result = await AnalyticsService(app_session).sentiment_by_category(
            tenant_id=tenant_id, filters=filters,
            top_n_categories=top_n_categories,
        )
    return SentimentByCategoryResponse(**asdict(result))


@router.get(
    "/override-stats",
    response_model=OverrideStatsResponse,
    summary="Override layer trigger counts + impact direction.",
)
async def override_stats(
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    source_types: str | None = None,
) -> OverrideStatsResponse:
    tenant_id = _require_active_tenant(current)
    filters = _build_filters(date_from, date_to, source_types=source_types)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        result = await AnalyticsService(app_session).override_stats(
            tenant_id=tenant_id, filters=filters,
        )
    return OverrideStatsResponse(
        total_reviews=result.total_reviews,
        data=[OverrideStatsRowResponse(**asdict(row)) for row in result.data],
    )


@router.get(
    "/sentiment-timeline",
    response_model=TimelineResponse,
    summary="Time-series sentiment counts at day / week / month granularity.",
)
async def sentiment_timeline(
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    granularity: Annotated[Granularity, Query()] = "day",
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    source_types: str | None = None,
) -> TimelineResponse:
    tenant_id = _require_active_tenant(current)
    filters = _build_filters(date_from, date_to, source_types=source_types)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        result = await AnalyticsService(app_session).sentiment_timeline(
            tenant_id=tenant_id, filters=filters, granularity=granularity,
        )
    return TimelineResponse(
        granularity=result.granularity,
        data=[TimelinePointResponse(**asdict(point)) for point in result.data],
    )


@router.get(
    "/ticket-resolution-time",
    response_model=TicketResolutionResponse,
    summary="Resolution-time distribution + per-category averages.",
)
async def ticket_resolution_time(
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    category_ids: str | None = None,
) -> TicketResolutionResponse:
    tenant_id = _require_active_tenant(current)
    filters = _build_filters(date_from, date_to, category_ids=category_ids)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        result = await AnalyticsService(app_session).ticket_resolution_time(
            tenant_id=tenant_id, filters=filters,
        )
    return TicketResolutionResponse(
        total_resolved_tickets=result.total_resolved_tickets,
        avg_resolution_hours=result.avg_resolution_hours,
        median_resolution_hours=result.median_resolution_hours,
        p95_resolution_hours=result.p95_resolution_hours,
        distribution=[ResolutionBucketResponse(**asdict(b)) for b in result.distribution],
        by_category=[ResolutionByCategoryResponse(**asdict(c)) for c in result.by_category],
    )


@router.get(
    "/sensitivity-distribution",
    response_model=SensitivityDistResponse,
    summary="Sentiment-score histogram: 20 buckets between -1.0 and 1.0.",
)
async def sensitivity_distribution(
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    source_types: str | None = None,
) -> SensitivityDistResponse:
    tenant_id = _require_active_tenant(current)
    filters = _build_filters(date_from, date_to, source_types=source_types)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        result = await AnalyticsService(app_session).sensitivity_distribution(
            tenant_id=tenant_id, filters=filters,
        )
    return SensitivityDistResponse(
        total=result.total,
        buckets=[SensitivityBucketResponse(**asdict(b)) for b in result.buckets],
        stats=SensitivityStatsResponse(**asdict(result.stats)),
    )


@router.get(
    "/nps-summary",
    response_model=NPSSummaryResponse,
    summary="NPS score + bucket counts (Sprint 8.3.5).",
)
async def nps_summary(
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    date_from: date | None = None,
    date_to: date | None = None,
    batch_job_id: UUID | None = None,
) -> NPSSummaryResponse:
    """Aggregate NPS for the tenant + filter window. The pipeline date
    filter for NPS keys on Review.created_at (when ingested), distinct
    from the sentiment endpoints which key on analyzed_at — see
    AnalyticsService.compute_nps_summary docstring."""
    tenant_id = _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        result = await AnalyticsService(app_session).compute_nps_summary(
            tenant_id=tenant_id,
            date_from=date_from,
            date_to=date_to,
            batch_job_id=batch_job_id,
        )
    return NPSSummaryResponse(**asdict(result))


@router.get(
    "/nps-monthly-trend",
    response_model=list[NPSMonthlyPointResponse],
    summary="Last N months of NPS, oldest first; empty months keep score=null.",
)
async def nps_monthly_trend(
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    months_back: int = Query(default=12, ge=1, le=24),
) -> list[NPSMonthlyPointResponse]:
    """Trailing months_back calendar months of NPS. Months without any
    NPS-bearing review surface with score=null so a connectNulls=false
    chart renders a real gap."""
    tenant_id = _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        result = await AnalyticsService(app_session).compute_monthly_nps_trend(
            tenant_id=tenant_id, months_back=months_back,
        )
    return [NPSMonthlyPointResponse(**asdict(p)) for p in result]


@router.get(
    "/headline-metrics",
    response_model=HeadlineMetricsResponse,
    summary="Eight dashboard headline values in one call (Sprint 8.3.5).",
)
async def headline_metrics(
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    date_from: date | None = None,
    date_to: date | None = None,
    batch_id: UUID | None = None,
) -> HeadlineMetricsResponse:
    """Eight values for the dashboard top row, served from a single
    round-trip. Date filter applies to the review-side metrics only;
    open_tickets + today_new_tickets always reflect live state.

    Sprint 9.5 B4 — ``batch_id`` was already plumbed through
    ``AnalyticsService.compute_headline_metrics`` (added Sprint
    9.0.5-B H) but the route signature dropped it, so the strategy
    page couldn't ask for batch-scoped headline numbers even though
    the service supported it. The query param now flows end-to-end;
    the dashboard stays tenant-wide because it doesn't pass the key.
    """
    tenant_id = _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        result = await AnalyticsService(app_session).compute_headline_metrics(
            tenant_id=tenant_id,
            date_from=date_from,
            date_to=date_to,
            batch_id=batch_id,
        )
    return HeadlineMetricsResponse(**asdict(result))


@router.get(
    "/company-perspective-distribution",
    response_model=CompanyPerspectiveDistResponse,
    summary="Top-N company-perspective codes + unmatched count (Sprint 8.3.5.6).",
)
async def company_perspective_distribution(
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    sentiment_labels: str | None = None,
    source_types: str | None = None,
    batch_job_id: UUID | None = None,
    limit: int = Query(default=10, ge=1, le=50),
) -> CompanyPerspectiveDistResponse:
    """Top-N matched company-perspective codes for the tenant, joined
    to the taxonomy for label_tr. ``unmatched_count`` is the share of
    reviews where the heuristic didn't match anything; reported
    separately so the dashboard can show it as its own signal."""
    tenant_id = _require_active_tenant(current)
    filters = _build_filters(
        date_from, date_to, sentiment_labels=sentiment_labels,
        source_types=source_types, batch_job_id=batch_job_id,
    )
    async with app_session.begin():
        await bind_tenant(app_session, current)
        result = await AnalyticsService(
            app_session
        ).compute_company_perspective_distribution(
            tenant_id=tenant_id, filters=filters, limit=limit,
        )
    return CompanyPerspectiveDistResponse(
        total=result.total,
        unmatched_count=result.unmatched_count,
        data=[CompanyPerspectiveDistRowResponse(**asdict(r)) for r in result.data],
    )
