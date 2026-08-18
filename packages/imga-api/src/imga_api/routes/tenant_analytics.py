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
    PeriodStats,
)
from imga_api.services.category_codes import valid_primary_codes

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


class CategoryDrilldownRowResponse(BaseModel):
    code: str
    label_tr: str
    total: int
    negative_count: int
    negative_share: float
    share: float


class CategoryDrilldownResponse(BaseModel):
    primary_category: str
    total: int
    negative_total: int
    data: list[CategoryDrilldownRowResponse]


class ExperienceBucketResponse(BaseModel):
    total: int
    negatif: int


class ExperienceDistributionResponse(BaseModel):
    """2026-08-10 — temas noktası kovaları. ``atanmamis`` = ne modelin
    kararı ne kategori yedeği bir kova üretebildi."""

    dijital: ExperienceBucketResponse
    operasyonel: ExperienceBucketResponse
    atanmamis: ExperienceBucketResponse


# --- WS4 — dönem karşılaştırma (2026-08-18) ------------------------------


class PeriodStatsResponse(BaseModel):
    date_from: date
    date_to: date
    total_reviews: int
    sentiment_counts: dict[str, int]
    category_counts: dict[str, int]
    nps: NPSSummaryResponse
    experience: ExperienceDistributionResponse
    avg_sentiment_score: float | None


class PeriodComparisonDeltaResponse(BaseModel):
    """Her alan ``period_b - period_a`` yönündedir. ``*_direction``
    "up" | "down" | "flat" değeri taşır; ilgili fark None ise (bir
    pencerede veri yoksa) "flat" döner."""

    total_reviews_diff: int
    total_reviews_direction: str
    sentiment_pct_point_diff: dict[str, float]
    category_pct_point_diff: dict[str, float]
    nps_score_diff: float | None
    nps_direction: str
    avg_sentiment_score_diff: float | None
    avg_sentiment_direction: str


class PeriodComparisonResponse(BaseModel):
    period_a: PeriodStatsResponse
    period_b: PeriodStatsResponse
    delta: PeriodComparisonDeltaResponse


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
    include_flagged: bool = False,
) -> AnalyticsFilters:
    return AnalyticsFilters(
        date_from=date_from,
        date_to=date_to,
        sentiment_labels=_split_csv(sentiment_labels),
        category_ids=_split_uuid_csv(category_ids),
        source_types=_split_csv(source_types),
        batch_job_id=batch_job_id,
        include_flagged=include_flagged,
    )


_INCLUDE_FLAGGED_DESC = (
    "Düşük kaliteli (bayraklı: duplicate/empty/informational/"
    "meaningless) yorumları da dahil et. Varsayılan: hariç."
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
    include_flagged: bool = Query(default=False, description=_INCLUDE_FLAGGED_DESC),
) -> SentimentDistResponse:
    tenant_id = _require_active_tenant(current)
    filters = _build_filters(
        date_from, date_to, sentiment_labels, category_ids, source_types, batch_job_id,
        include_flagged=include_flagged,
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
    "/experience-distribution",
    response_model=ExperienceDistributionResponse,
    summary="Dijital / operasyonel temas noktası dağılımı.",
    description=(
        "2026-08-10 — deneyim tipi artık yorum başına LLM kararı "
        "(``reviews.experience_type``). Kolonu NULL olan eski satırlar "
        "SQL tarafında eski kategori eşlemesine düşer "
        "(teknik_destek/faturalama → dijital, belirsiz → atanmamış, "
        "geri kalan → operasyonel), böylece yeniden analiz tamamlanana "
        "kadar sayımlar bozulmaz. Tüm kurum üyelerine açık. Tarih "
        "filtreleri ``review_date`` üzerinde ve diğer /analytics "
        "uçlarıyla aynı ISO datetime zarfını kullanır."
    ),
)
async def experience_distribution(
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    source_types: str | None = None,
    batch_job_id: UUID | None = None,
    include_flagged: bool = Query(default=False, description=_INCLUDE_FLAGGED_DESC),
) -> ExperienceDistributionResponse:
    tenant_id = _require_active_tenant(current)
    filters = _build_filters(
        date_from, date_to, source_types=source_types, batch_job_id=batch_job_id,
        include_flagged=include_flagged,
    )
    async with app_session.begin():
        await bind_tenant(app_session, current)
        result = await AnalyticsService(app_session).experience_distribution(
            tenant_id=tenant_id, filters=filters
        )
    return ExperienceDistributionResponse(
        dijital=ExperienceBucketResponse(**asdict(result.dijital)),
        operasyonel=ExperienceBucketResponse(**asdict(result.operasyonel)),
        atanmamis=ExperienceBucketResponse(**asdict(result.atanmamis)),
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
    include_flagged: bool = Query(default=False, description=_INCLUDE_FLAGGED_DESC),
) -> CategoryDistResponse:
    tenant_id = _require_active_tenant(current)
    filters = _build_filters(
        date_from, date_to, sentiment_labels=sentiment_labels,
        source_types=source_types, batch_job_id=batch_job_id,
        include_flagged=include_flagged,
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
    include_flagged: bool = Query(default=False, description=_INCLUDE_FLAGGED_DESC),
) -> SentimentByCategoryResponse:
    tenant_id = _require_active_tenant(current)
    filters = _build_filters(
        date_from, date_to, source_types=source_types, batch_job_id=batch_job_id,
        include_flagged=include_flagged,
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
    include_flagged: bool = Query(default=False, description=_INCLUDE_FLAGGED_DESC),
) -> OverrideStatsResponse:
    tenant_id = _require_active_tenant(current)
    filters = _build_filters(
        date_from, date_to, source_types=source_types, include_flagged=include_flagged,
    )
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
    include_flagged: bool = Query(default=False, description=_INCLUDE_FLAGGED_DESC),
) -> TimelineResponse:
    tenant_id = _require_active_tenant(current)
    filters = _build_filters(
        date_from, date_to, source_types=source_types, include_flagged=include_flagged,
    )
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
    include_flagged: bool = Query(default=False, description=_INCLUDE_FLAGGED_DESC),
) -> SensitivityDistResponse:
    tenant_id = _require_active_tenant(current)
    filters = _build_filters(
        date_from, date_to, source_types=source_types, include_flagged=include_flagged,
    )
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
    include_flagged: bool = Query(default=False, description=_INCLUDE_FLAGGED_DESC),
) -> NPSSummaryResponse:
    """Aggregate NPS for the tenant + filter window. Every analytics
    endpoint — NPS included — now keys on Review.review_date (yorumun
    kendi tarihi; ``tarih`` kolonu yoksa ingest anı). ``created_at`` /
    ``analyzed_at`` yalnızca ingest anlamı taşıyan yerlerde kaldı:
    dedup penceresi, "son veri girişi" ve heatmap'in SAAT ekseni
    (yüklenen tarihler gün hassasiyetinde, saat bilgisi yok)."""
    tenant_id = _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        result = await AnalyticsService(app_session).compute_nps_summary(
            tenant_id=tenant_id,
            date_from=date_from,
            date_to=date_to,
            batch_job_id=batch_job_id,
            include_flagged=include_flagged,
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
    include_flagged: bool = Query(default=False, description=_INCLUDE_FLAGGED_DESC),
) -> list[NPSMonthlyPointResponse]:
    """Trailing months_back calendar months of NPS. Months without any
    NPS-bearing review surface with score=null so a connectNulls=false
    chart renders a real gap."""
    tenant_id = _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        result = await AnalyticsService(app_session).compute_monthly_nps_trend(
            tenant_id=tenant_id, months_back=months_back,
            include_flagged=include_flagged,
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
    include_flagged: bool = Query(default=False, description=_INCLUDE_FLAGGED_DESC),
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
            include_flagged=include_flagged,
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
    include_flagged: bool = Query(default=False, description=_INCLUDE_FLAGGED_DESC),
) -> CompanyPerspectiveDistResponse:
    """Top-N matched company-perspective codes for the tenant, joined
    to the taxonomy for label_tr. ``unmatched_count`` is the share of
    reviews where the heuristic didn't match anything; reported
    separately so the dashboard can show it as its own signal."""
    tenant_id = _require_active_tenant(current)
    filters = _build_filters(
        date_from, date_to, sentiment_labels=sentiment_labels,
        source_types=source_types, batch_job_id=batch_job_id,
        include_flagged=include_flagged,
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


@router.get(
    "/category-drilldown",
    response_model=CategoryDrilldownResponse,
    summary="Alt kategori kirilimi (tek ana kategori altinda).",
)
async def category_drilldown(
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    primary_category: str = Query(
        description="Ana kategori kodu (reviews.primary_category)."
    ),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    sentiment_labels: str | None = None,
    source_types: str | None = None,
    batch_job_id: UUID | None = None,
    limit: int = Query(default=25, ge=1, le=50),
    include_flagged: bool = Query(default=False, description=_INCLUDE_FLAGGED_DESC),
) -> CategoryDrilldownResponse:
    """Hiyerarsik drill-down'in ikinci seviyesi: secili ana kategori
    altindaki alt kategoriler, her biri icin toplam + olumsuz sayisi.

    Kovalar YALNIZ review kolonlarindan kurulur (primary_category
    filtresi + company_perspective_code grubu). Taksonominin ana
    kategori eslemesi burada kullanilmaz — bkz. AnalyticsService.
    compute_category_drilldown. Bu sayede her satir dogrudan
    /reviews?primary_categories=X&perspective_codes=Y baglantisina
    cevrilebilir ve sayilar birebir tutar.

    NULL perspektifli yorumlar ``__unmatched__`` kovasinda doner.
    """
    tenant_id = _require_active_tenant(current)
    filters = _build_filters(
        date_from, date_to, sentiment_labels=sentiment_labels,
        source_types=source_types, batch_job_id=batch_job_id,
        include_flagged=include_flagged,
    )
    async with app_session.begin():
        await bind_tenant(app_session, current)
        # 2026-08-18 WS2 — global kod uzayi + kurumun aktif custom
        # kategori kodlari; sabit GLOBAL_CATEGORY_CODES kurumun kendi
        # actigi custom kategoriyi hep reddediyordu.
        valid_codes = await valid_primary_codes(app_session, tenant_id)
        if primary_category not in valid_codes:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "primary_category gecersiz; gecerli kodlar: "
                    + ", ".join(sorted(valid_codes))
                ),
            )
        result = await AnalyticsService(app_session).compute_category_drilldown(
            tenant_id=tenant_id,
            primary_category=primary_category,
            filters=filters,
            limit=limit,
        )
    return CategoryDrilldownResponse(
        primary_category=result.primary_category,
        total=result.total,
        negative_total=result.negative_total,
        data=[CategoryDrilldownRowResponse(**asdict(r)) for r in result.data],
    )


@router.get(
    "/period-comparison",
    response_model=PeriodComparisonResponse,
    summary="İki bağımsız tarih penceresini karşılaştır.",
    description=(
        "İki pencere ([a_from,a_to] ve [b_from,b_to]) için toplam, "
        "duygu/kategori dağılımı, NPS özeti, deneyim dağılımı ve "
        "ortalama skor hesaplanır; ``delta`` alanı period_b - period_a "
        "farkını + yönünü (up/down/flat) taşır. Pencereler kullanıcı "
        "seçimidir; çakışma/bitişiklik kontrolü yapılmaz."
    ),
)
async def period_comparison(
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    a_from: Annotated[
        date, Query(description="A penceresi başlangıcı (YYYY-MM-DD).")
    ],
    a_to: Annotated[date, Query(description="A penceresi bitişi (YYYY-MM-DD).")],
    b_from: Annotated[
        date, Query(description="B penceresi başlangıcı (YYYY-MM-DD).")
    ],
    b_to: Annotated[date, Query(description="B penceresi bitişi (YYYY-MM-DD).")],
    include_flagged: bool = Query(default=False, description=_INCLUDE_FLAGGED_DESC),
) -> PeriodComparisonResponse:
    if a_to < a_from:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="a_to, a_from'dan önce olamaz.",
        )
    if b_to < b_from:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="b_to, b_from'dan önce olamaz.",
        )
    tenant_id = _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        result = await AnalyticsService(app_session).period_comparison(
            tenant_id=tenant_id,
            a_from=a_from,
            a_to=a_to,
            b_from=b_from,
            b_to=b_to,
            include_flagged=include_flagged,
        )
    return PeriodComparisonResponse(
        period_a=_period_stats_response(result.period_a),
        period_b=_period_stats_response(result.period_b),
        delta=PeriodComparisonDeltaResponse(**asdict(result.delta)),
    )


def _period_stats_response(stats: PeriodStats) -> PeriodStatsResponse:
    return PeriodStatsResponse(
        date_from=stats.date_from,
        date_to=stats.date_to,
        total_reviews=stats.total_reviews,
        sentiment_counts=stats.sentiment_counts,
        category_counts=stats.category_counts,
        nps=NPSSummaryResponse(**asdict(stats.nps)),
        experience=ExperienceDistributionResponse(
            dijital=ExperienceBucketResponse(**asdict(stats.experience.dijital)),
            operasyonel=ExperienceBucketResponse(**asdict(stats.experience.operasyonel)),
            atanmamis=ExperienceBucketResponse(**asdict(stats.experience.atanmamis)),
        ),
        avg_sentiment_score=stats.avg_sentiment_score,
    )

