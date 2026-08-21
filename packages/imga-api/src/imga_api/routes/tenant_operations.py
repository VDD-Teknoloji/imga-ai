"""``/tenants/me/operations`` + ``/tenants/me/fact-mappings`` —
operasyonel "facts" modülü (migration 0046): SLA gerçekleşmeleri,
CSAT, efor (temsilci/müşteri etkileşimi), tazmin ve teslimat verisi
üzerine analitik + tenant'ın CSV eşleme konfigürasyonu.

``review_facts`` ``reviews`` ile 1:1 — her endpoint ``reviews`` üzerine
LEFT/INNER JOIN ile çalışır (tarih penceresi ve ``quality_flag`` filtresi
her zaman ``Review`` kolonları üzerinden uygulanır, boyut analitiğiyle
aynı ``day_floor``/``day_ceil`` + ``include_flagged`` konvansiyonu).

Beş endpoint:
  * GET  /tenants/me/operations/summary
  * GET  /tenants/me/operations/breakdown
  * GET  /tenants/me/operations/sentiment-correlation
  * GET  /tenants/me/fact-mappings
  * PUT  /tenants/me/fact-mappings
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from imga_db.models import Review, ReviewFact, TenantFactMapping, UserTenantRole
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from imga_api.auth_deps import CurrentUser, bind_tenant, require_role
from imga_api.db_deps import get_app_session
from imga_api.services.date_bounds import day_ceil, day_floor
from imga_api.services.dimension_service import (
    DIMENSION_COLUMNS,
    dimension_value_present,
    fold_dimension_key,
)
from imga_api.services.fact_parsing import FACT_FIELDS

router = APIRouter(tags=["Operations"])

_AnyMember = Depends(require_role(
    UserTenantRole.TENANT_ADMIN,
    UserTenantRole.ANALYST,
    UserTenantRole.VIEWER,
))
_TenantAdmin = Depends(require_role(UserTenantRole.TENANT_ADMIN))

#: Pydantic ``Literal`` must be statically known — kept in sync with
#: ``fact_parsing.FACT_FIELDS`` by hand; a test asserts the two match
#: (test_operations_routes.py).
FactFieldName = Literal[
    "sla_resolution_status",
    "sla_first_response_status",
    "resolution_time",
    "first_response_time",
    "csat",
    "agent_interactions",
    "customer_interactions",
    "compensation_status",
    "freight_cost",
    "goods_cost",
    "refund_reason",
    "delivery_status",
    "delivery_detail",
]

_BREAKDOWN_METRIC_KEYS = (
    "violation_rate",
    "first_response_violation_rate",
    "avg_resolution_minutes",
    "avg_first_response_minutes",
    "avg_agent_interactions",
    "avg_customer_interactions",
    "csat_avg",
)

_SENTIMENT_LABELS = ("NEGATIF", "NOTR", "POZITIF")


def _require_active_tenant(current: CurrentUser) -> UUID:
    if current.active_tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="active tenant context required",
        )
    return current.active_tenant_id


def _sentiment_key(raw_label: str) -> str:
    """``Review.sentiment_label`` ham değerleri ('NÖTR' dahil) bu uç
    sözleşmesinin ASCII anahtarına (``"NOTR"``) eşlenir; POZITIF/
    NEGATIF zaten ASCII, değişmeden geçer."""
    return "NOTR" if raw_label == "NÖTR" else raw_label


def _base_conditions(
    tenant_id: UUID,
    *,
    date_from: datetime | None,
    date_to: datetime | None,
    include_flagged: bool,
) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = [
        Review.tenant_id == tenant_id,
        Review.deleted_at.is_(None),
    ]
    if date_from is not None:
        conditions.append(Review.review_date >= day_floor(date_from))
    if date_to is not None:
        conditions.append(Review.review_date <= day_ceil(date_to))
    if not include_flagged:
        conditions.append(Review.quality_flag.is_(None))
    return conditions


def _f(value: Any) -> float | None:
    """Postgres NUMERIC/percentile_cont sonuçları asyncpg üzerinden
    ``Decimal`` gelebilir — JSON'a yazılmadan önce ``float``'a
    normalize edilir. ``None`` aynen geçer."""
    return None if value is None else round(float(value), 2)


# --- response models -------------------------------------------------


class SlaBucket(BaseModel):
    within: int
    violated: int
    violation_rate_pct: float


class FactsCoverage(BaseModel):
    sla_resolution: int
    sla_first_response: int
    csat: int
    effort: int
    delivery: int
    compensation: int


class SlaSummary(BaseModel):
    resolution: SlaBucket
    first_response: SlaBucket
    avg_resolution_minutes: float | None
    median_resolution_minutes: float | None
    avg_first_response_minutes: float | None


class EffortSummary(BaseModel):
    avg_agent_interactions: float | None
    avg_customer_interactions: float | None


class CsatSummary(BaseModel):
    count: int
    avg_score: float | None
    distribution: dict[str, int]


class CompensationSummary(BaseModel):
    statuses: dict[str, int]
    freight_cost_sum: float
    goods_cost_sum: float


class DeliverySummary(BaseModel):
    statuses: dict[str, int]


class OperationsSummaryResponse(BaseModel):
    total_reviews: int
    facts_coverage: FactsCoverage
    sla: SlaSummary
    effort: EffortSummary
    csat: CsatSummary
    compensation: CompensationSummary
    delivery: DeliverySummary


class OperationsBreakdownResponse(BaseModel):
    dimension: str
    metric_key: str
    buckets: list[dict[str, Any]]
    total_count: int
    coverage_count: int


class SentimentCounts(BaseModel):
    NEGATIF: int
    NOTR: int
    POZITIF: int


class SlaCorrelationBlock(BaseModel):
    violated: SentimentCounts
    within: SentimentCounts


class CsatMatrixRow(BaseModel):
    csat_score: int
    NEGATIF: int
    NOTR: int
    POZITIF: int


class AgreementBlock(BaseModel):
    csat_high_model_positive_pct: float | None
    csat_low_model_negative_pct: float | None
    n_csat: int


class SentimentCorrelationResponse(BaseModel):
    sla: SlaCorrelationBlock
    csat_matrix: list[CsatMatrixRow]
    agreement: AgreementBlock


class FactMappingResponse(BaseModel):
    fact_field: str
    csv_column_mapping: str
    enabled: bool


class FactMappingUpsertItem(BaseModel):
    fact_field: FactFieldName
    csv_column_mapping: str = Field(..., min_length=1, max_length=256)
    enabled: bool = True


# --- GET /tenants/me/operations/summary -------------------------------


@router.get(
    "/tenants/me/operations/summary",
    response_model=OperationsSummaryResponse,
    summary="Operasyonel facts özeti — SLA, CSAT, efor, tazmin, teslimat.",
)
async def operations_summary(
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    include_flagged: bool = False,
) -> OperationsSummaryResponse:
    tenant_id = _require_active_tenant(current)
    conditions = _base_conditions(
        tenant_id,
        date_from=date_from,
        date_to=date_to,
        include_flagged=include_flagged,
    )

    async with app_session.begin():
        await bind_tenant(app_session, current)

        base = (
            select(Review)
            .select_from(Review)
            .outerjoin(ReviewFact, ReviewFact.review_id == Review.id)
            .where(*conditions)
        )

        resolution_filter = ReviewFact.sla_resolution_status.is_not(None)
        first_response_filter = ReviewFact.sla_first_response_status.is_not(None)

        agg_stmt = base.with_only_columns(
            func.count(Review.id).label("total_reviews"),
            func.count(ReviewFact.sla_resolution_status).label("cov_sla_resolution"),
            func.count(ReviewFact.sla_first_response_status).label(
                "cov_sla_first_response"
            ),
            func.count(ReviewFact.csat_score).label("cov_csat"),
            func.sum(
                case(
                    (
                        ReviewFact.agent_interactions.is_not(None)
                        | ReviewFact.customer_interactions.is_not(None),
                        1,
                    ),
                    else_=0,
                )
            ).label("cov_effort"),
            func.count(ReviewFact.delivery_status).label("cov_delivery"),
            func.count(ReviewFact.compensation_status).label("cov_compensation"),
            func.sum(
                case((ReviewFact.sla_resolution_status == "within", 1), else_=0)
            ).label("resolution_within"),
            func.sum(
                case((ReviewFact.sla_resolution_status == "violated", 1), else_=0)
            ).label("resolution_violated"),
            func.sum(
                case((ReviewFact.sla_first_response_status == "within", 1), else_=0)
            ).label("first_response_within"),
            func.sum(
                case((ReviewFact.sla_first_response_status == "violated", 1), else_=0)
            ).label("first_response_violated"),
            func.avg(
                case((resolution_filter, ReviewFact.resolution_time_minutes))
            ).label("avg_resolution_minutes"),
            func.percentile_cont(0.5)
            .within_group(
                case((resolution_filter, ReviewFact.resolution_time_minutes))
            )
            .label("median_resolution_minutes"),
            func.avg(
                case(
                    (first_response_filter, ReviewFact.first_response_time_minutes)
                )
            ).label("avg_first_response_minutes"),
            func.avg(ReviewFact.agent_interactions).label("avg_agent_interactions"),
            func.avg(ReviewFact.customer_interactions).label(
                "avg_customer_interactions"
            ),
            func.avg(ReviewFact.csat_score).label("avg_csat_score"),
            func.coalesce(func.sum(ReviewFact.freight_cost), 0).label(
                "freight_cost_sum"
            ),
            func.coalesce(func.sum(ReviewFact.goods_cost), 0).label("goods_cost_sum"),
        )
        row = (await app_session.execute(agg_stmt)).one()

        csat_dist_stmt = (
            base.with_only_columns(
                ReviewFact.csat_score, func.count().label("cnt")
            )
            .where(ReviewFact.csat_score.is_not(None))
            .group_by(ReviewFact.csat_score)
        )
        csat_rows = (await app_session.execute(csat_dist_stmt)).all()
        distribution = {str(n): 0 for n in range(1, 6)}
        for score, cnt in csat_rows:
            distribution[str(score)] = int(cnt)

        # CSV kaynakli yazim tutarsizligina karsi ayni fold konvansiyonu
        # (dimension_service.fold_dimension_key): lower(trim) anahtari,
        # mode() ile en sik ham yazim etiket olur.
        comp_stmt = (
            base.with_only_columns(
                func.mode()
                .within_group(func.trim(ReviewFact.compensation_status))
                .label("bucket"),
                func.count().label("cnt"),
            )
            .where(ReviewFact.compensation_status.is_not(None))
            .group_by(func.lower(func.trim(ReviewFact.compensation_status)))
        )
        comp_rows = (await app_session.execute(comp_stmt)).all()

        delivery_stmt = (
            base.with_only_columns(
                func.mode()
                .within_group(func.trim(ReviewFact.delivery_status))
                .label("bucket"),
                func.count().label("cnt"),
            )
            .where(ReviewFact.delivery_status.is_not(None))
            .group_by(func.lower(func.trim(ReviewFact.delivery_status)))
        )
        delivery_rows = (await app_session.execute(delivery_stmt)).all()

    within_res = int(row.resolution_within or 0)
    violated_res = int(row.resolution_violated or 0)
    res_denom = within_res + violated_res
    within_fr = int(row.first_response_within or 0)
    violated_fr = int(row.first_response_violated or 0)
    fr_denom = within_fr + violated_fr

    return OperationsSummaryResponse(
        total_reviews=int(row.total_reviews or 0),
        facts_coverage=FactsCoverage(
            sla_resolution=int(row.cov_sla_resolution or 0),
            sla_first_response=int(row.cov_sla_first_response or 0),
            csat=int(row.cov_csat or 0),
            effort=int(row.cov_effort or 0),
            delivery=int(row.cov_delivery or 0),
            compensation=int(row.cov_compensation or 0),
        ),
        sla=SlaSummary(
            resolution=SlaBucket(
                within=within_res,
                violated=violated_res,
                violation_rate_pct=(
                    round((violated_res / res_denom) * 100.0, 2) if res_denom else 0.0
                ),
            ),
            first_response=SlaBucket(
                within=within_fr,
                violated=violated_fr,
                violation_rate_pct=(
                    round((violated_fr / fr_denom) * 100.0, 2) if fr_denom else 0.0
                ),
            ),
            avg_resolution_minutes=_f(row.avg_resolution_minutes),
            median_resolution_minutes=_f(row.median_resolution_minutes),
            avg_first_response_minutes=_f(row.avg_first_response_minutes),
        ),
        effort=EffortSummary(
            avg_agent_interactions=_f(row.avg_agent_interactions),
            avg_customer_interactions=_f(row.avg_customer_interactions),
        ),
        csat=CsatSummary(
            count=int(row.cov_csat or 0),
            avg_score=_f(row.avg_csat_score),
            distribution=distribution,
        ),
        compensation=CompensationSummary(
            statuses={str(label): int(cnt) for label, cnt in comp_rows},
            freight_cost_sum=_f(row.freight_cost_sum) or 0.0,
            goods_cost_sum=_f(row.goods_cost_sum) or 0.0,
        ),
        delivery=DeliverySummary(
            statuses={str(label): int(cnt) for label, cnt in delivery_rows},
        ),
    )


# --- GET /tenants/me/operations/breakdown ------------------------------


@router.get(
    "/tenants/me/operations/breakdown",
    response_model=OperationsBreakdownResponse,
    summary="Bir facts metriğini iş boyutuna göre kırar.",
    responses={400: {"description": "Bilinmeyen dimension/metric_key."}},
)
async def operations_breakdown(
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    dimension: str,
    metric_key: str,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    include_flagged: bool = False,
) -> OperationsBreakdownResponse:
    tenant_id = _require_active_tenant(current)
    if dimension not in DIMENSION_COLUMNS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unknown dimension {dimension!r}; valid={list(DIMENSION_COLUMNS)}",
        )
    if metric_key not in _BREAKDOWN_METRIC_KEYS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"unknown metric_key {metric_key!r}; "
                f"valid={list(_BREAKDOWN_METRIC_KEYS)}"
            ),
        )
    column = DIMENSION_COLUMNS[dimension]
    folded = fold_dimension_key(column)
    value_label = func.mode().within_group(func.trim(column)).label("bucket")

    conditions = _base_conditions(
        tenant_id,
        date_from=date_from,
        date_to=date_to,
        include_flagged=include_flagged,
    )

    async with app_session.begin():
        await bind_tenant(app_session, current)

        total_stmt = (
            select(func.count()).select_from(Review).where(*conditions)
        )
        total_count = (await app_session.execute(total_stmt)).scalar_one() or 0

        coverage_stmt = (
            select(func.count())
            .select_from(Review)
            .where(*conditions, dimension_value_present(column))
        )
        coverage_count = (
            await app_session.execute(coverage_stmt)
        ).scalar_one() or 0

        # Her metric_key'in kendi payda filtresi — coverage_count'tan
        # BAĞIMSIZ: bir bucket'ta boyut değeri dolu olabilir ama bu
        # metriğe ait facts hiç işlenmemiş olabilir (bkz. modül
        # docstring'i + spec'in "count = ilgili metrik için payda satır
        # sayısı" notu).
        metric_filter: ColumnElement[bool]
        agg_col: Any
        is_rate: bool
        if metric_key == "violation_rate":
            metric_filter = ReviewFact.sla_resolution_status.is_not(None)
            numerator = case(
                (ReviewFact.sla_resolution_status == "violated", 1), else_=0
            )
            agg_col = func.sum(numerator)
            is_rate = True
        elif metric_key == "first_response_violation_rate":
            metric_filter = ReviewFact.sla_first_response_status.is_not(None)
            numerator = case(
                (ReviewFact.sla_first_response_status == "violated", 1), else_=0
            )
            agg_col = func.sum(numerator)
            is_rate = True
        elif metric_key == "avg_resolution_minutes":
            metric_filter = ReviewFact.sla_resolution_status.is_not(None)
            agg_col = func.avg(ReviewFact.resolution_time_minutes)
            is_rate = False
        elif metric_key == "avg_first_response_minutes":
            metric_filter = ReviewFact.sla_first_response_status.is_not(None)
            agg_col = func.avg(ReviewFact.first_response_time_minutes)
            is_rate = False
        elif metric_key == "avg_agent_interactions":
            metric_filter = ReviewFact.agent_interactions.is_not(None)
            agg_col = func.avg(ReviewFact.agent_interactions)
            is_rate = False
        elif metric_key == "avg_customer_interactions":
            metric_filter = ReviewFact.customer_interactions.is_not(None)
            agg_col = func.avg(ReviewFact.customer_interactions)
            is_rate = False
        else:  # csat_avg
            metric_filter = ReviewFact.csat_score.is_not(None)
            agg_col = func.avg(ReviewFact.csat_score)
            is_rate = False

        stmt = (
            select(value_label, func.count().label("cnt"), agg_col.label("agg"))
            .select_from(Review)
            .join(ReviewFact, ReviewFact.review_id == Review.id)
            .where(*conditions, dimension_value_present(column), metric_filter)
            .group_by(folded)
            .order_by(func.count().desc())
        )
        rows = (await app_session.execute(stmt)).all()

    buckets: list[dict[str, Any]] = []
    for r in rows:
        cnt = int(r.cnt or 0)
        if is_rate:
            metric_value = round((float(r.agg or 0) / cnt) * 100.0, 2) if cnt else 0.0
        else:
            metric_value = _f(r.agg) or 0.0
        buckets.append({"value": r.bucket, "count": cnt, "metric_value": metric_value})

    return OperationsBreakdownResponse(
        dimension=dimension,
        metric_key=metric_key,
        buckets=buckets,
        total_count=int(total_count),
        coverage_count=int(coverage_count),
    )


# --- GET /tenants/me/operations/sentiment-correlation -------------------


@router.get(
    "/tenants/me/operations/sentiment-correlation",
    response_model=SentimentCorrelationResponse,
    summary="SLA/CSAT gerçekleşmesi ile model duygu kararının çapraz analizi.",
)
async def operations_sentiment_correlation(
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    include_flagged: bool = False,
) -> SentimentCorrelationResponse:
    tenant_id = _require_active_tenant(current)
    conditions = _base_conditions(
        tenant_id,
        date_from=date_from,
        date_to=date_to,
        include_flagged=include_flagged,
    )

    async with app_session.begin():
        await bind_tenant(app_session, current)

        sla_stmt = (
            select(
                ReviewFact.sla_resolution_status,
                Review.sentiment_label,
                func.count().label("cnt"),
            )
            .select_from(Review)
            .join(ReviewFact, ReviewFact.review_id == Review.id)
            .where(*conditions, ReviewFact.sla_resolution_status.is_not(None))
            .group_by(ReviewFact.sla_resolution_status, Review.sentiment_label)
        )
        sla_rows = (await app_session.execute(sla_stmt)).all()

        csat_matrix_stmt = (
            select(
                ReviewFact.csat_score,
                Review.sentiment_label,
                func.count().label("cnt"),
            )
            .select_from(Review)
            .join(ReviewFact, ReviewFact.review_id == Review.id)
            .where(*conditions, ReviewFact.csat_score.is_not(None))
            .group_by(ReviewFact.csat_score, Review.sentiment_label)
        )
        csat_rows = (await app_session.execute(csat_matrix_stmt)).all()

        n_csat_stmt = (
            select(func.count())
            .select_from(Review)
            .join(ReviewFact, ReviewFact.review_id == Review.id)
            .where(*conditions, ReviewFact.csat_score.is_not(None))
        )
        n_csat = (await app_session.execute(n_csat_stmt)).scalar_one() or 0

        high_stmt = (
            select(
                func.count().label("cnt"),
                func.sum(
                    case((Review.sentiment_label == "POZITIF", 1), else_=0)
                ).label("match_cnt"),
            )
            .select_from(Review)
            .join(ReviewFact, ReviewFact.review_id == Review.id)
            .where(*conditions, ReviewFact.csat_score >= 4)
        )
        high_row = (await app_session.execute(high_stmt)).one()

        low_stmt = (
            select(
                func.count().label("cnt"),
                func.sum(
                    case((Review.sentiment_label == "NEGATIF", 1), else_=0)
                ).label("match_cnt"),
            )
            .select_from(Review)
            .join(ReviewFact, ReviewFact.review_id == Review.id)
            .where(*conditions, ReviewFact.csat_score <= 2)
        )
        low_row = (await app_session.execute(low_stmt)).one()

    sla: dict[str, dict[str, int]] = {
        "violated": dict.fromkeys(_SENTIMENT_LABELS, 0),
        "within": dict.fromkeys(_SENTIMENT_LABELS, 0),
    }
    for status_value, label, cnt in sla_rows:
        if status_value not in sla:
            continue
        sla[status_value][_sentiment_key(label)] = int(cnt)

    csat_matrix_acc: dict[int, dict[str, int]] = {
        score: dict.fromkeys(_SENTIMENT_LABELS, 0) for score in range(1, 6)
    }
    for score, label, cnt in csat_rows:
        if score not in csat_matrix_acc:
            continue
        csat_matrix_acc[score][_sentiment_key(label)] = int(cnt)

    high_cnt = int(high_row.cnt or 0)
    high_match = int(high_row.match_cnt or 0)
    low_cnt = int(low_row.cnt or 0)
    low_match = int(low_row.match_cnt or 0)

    return SentimentCorrelationResponse(
        sla=SlaCorrelationBlock(
            violated=SentimentCounts(**sla["violated"]),
            within=SentimentCounts(**sla["within"]),
        ),
        csat_matrix=[
            CsatMatrixRow(csat_score=score, **counts)
            for score, counts in sorted(csat_matrix_acc.items())
        ],
        agreement=AgreementBlock(
            csat_high_model_positive_pct=(
                round((high_match / high_cnt) * 100.0, 2) if high_cnt else None
            ),
            csat_low_model_negative_pct=(
                round((low_match / low_cnt) * 100.0, 2) if low_cnt else None
            ),
            n_csat=int(n_csat),
        ),
    )


# --- fact-mappings CRUD -------------------------------------------------


@router.get(
    "/tenants/me/fact-mappings",
    response_model=list[FactMappingResponse],
    summary="Kurumun operasyonel facts CSV eşlemelerini listeler.",
)
async def list_fact_mappings(
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> list[FactMappingResponse]:
    tenant_id = _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        rows = (
            await app_session.execute(
                select(TenantFactMapping).where(
                    TenantFactMapping.tenant_id == tenant_id
                )
            )
        ).scalars().all()
    rank = {name: i for i, name in enumerate(FACT_FIELDS)}
    ordered = sorted(rows, key=lambda r: rank.get(r.fact_field, len(rank)))
    return [
        FactMappingResponse(
            fact_field=r.fact_field,
            csv_column_mapping=r.csv_column_mapping,
            enabled=r.enabled,
        )
        for r in ordered
    ]


@router.put(
    "/tenants/me/fact-mappings",
    response_model=list[FactMappingResponse],
    summary="Facts CSV eşlemelerini tam-replace şeklinde günceller.",
    description=(
        "Gövdedeki listede olmayan mevcut eşleme satırları SİLİNİR "
        "(tam-replace, kısmi PATCH değil). ``fact_field`` beyaz "
        "listesi dışı bir değer FastAPI/pydantic tarafından 422 ile "
        "reddedilir."
    ),
)
async def replace_fact_mappings(
    body: list[FactMappingUpsertItem],
    current: Annotated[CurrentUser, _TenantAdmin],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> list[FactMappingResponse]:
    tenant_id = _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        existing = {
            row.fact_field: row
            for row in (
                await app_session.execute(
                    select(TenantFactMapping).where(
                        TenantFactMapping.tenant_id == tenant_id
                    )
                )
            )
            .scalars()
            .all()
        }
        # Aynı fact_field birden çok kez gelirse son değer kazanır — tekilleştirme
        # olmadan iki INSERT aynı (tenant_id, fact_field) unique constraint'ine
        # çarpıp flush'ta IntegrityError/500 üretir.
        deduped_body = {item.fact_field: item for item in body}.values()
        incoming_fields = {item.fact_field for item in deduped_body}
        for fact_field, row in existing.items():
            if fact_field not in incoming_fields:
                await app_session.delete(row)
        for item in deduped_body:
            existing_row = existing.get(item.fact_field)
            if existing_row is not None:
                existing_row.csv_column_mapping = item.csv_column_mapping
                existing_row.enabled = item.enabled
            else:
                app_session.add(
                    TenantFactMapping(
                        tenant_id=tenant_id,
                        fact_field=item.fact_field,
                        csv_column_mapping=item.csv_column_mapping,
                        enabled=item.enabled,
                    )
                )
        await app_session.flush()
        rows = (
            await app_session.execute(
                select(TenantFactMapping).where(
                    TenantFactMapping.tenant_id == tenant_id
                )
            )
        ).scalars().all()
    rank = {name: i for i, name in enumerate(FACT_FIELDS)}
    ordered = sorted(rows, key=lambda r: rank.get(r.fact_field, len(rank)))
    return [
        FactMappingResponse(
            fact_field=r.fact_field,
            csv_column_mapping=r.csv_column_mapping,
            enabled=r.enabled,
        )
        for r in ordered
    ]
