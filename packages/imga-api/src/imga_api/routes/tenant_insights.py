"""``/tenants/me/insights/*`` — Sprint 8.3.9 visualization endpoints.

Three GET endpoints, all RLS-bound (app session + bind_tenant), all
Redis-cached at the service layer:

  * ``/cohort``     — period × dimension aggregation (1h cache)
  * ``/word-cloud`` — token frequency + sentiment skew (6h cache)
  * ``/heatmap``    — 2D matrix over count / avg_sentiment / avg_nps
                      (1h cache)
  * ``/root-cause`` — GET okur (cache/DB), POST üretir (12h cache +
                      LLM). Sprint 13.1 drill-down 3. seviye.

The ``/insights`` prefix is deliberately separate from
``/analytics``: those are pre-existing review-centric aggregations
shipped in Sprint 8.3.3; the new namespace is for visualization
endpoints whose responses target specific chart components.

logger.exception() in every catch-block — Sprint 8.3.6.6 round-3
baseline note.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from imga_core.llm import AllKeysExhaustedError, LLMError
from imga_db.models import UserTenantRole
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import CurrentUser, bind_tenant, require_role
from imga_api.db_deps import get_app_session
from imga_api.services.cohort_analyzer import (
    ALLOWED_DIMENSIONS,
    ALLOWED_PERIODS,
    CohortAnalyzer,
)
from imga_api.services.heatmap_generator import (
    ALLOWED_METRICS,
    ALLOWED_X_AXES,
    ALLOWED_Y_AXES,
    HeatmapGenerator,
)
from imga_api.services.root_cause_service import (
    InvalidCategoryError,
    NoCredentialsError,
    NotEnoughReviewsError,
    RootCauseResponseInvalidError,
    RootCauseService,
)
from imga_api.services.word_cloud import WordCloudGenerator
from imga_api.services.word_cloud.generator import ALLOWED_SENTIMENTS

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tenants/me/insights", tags=["Insights"])

_AnyMember = Depends(require_role(
    UserTenantRole.TENANT_ADMIN,
    UserTenantRole.ANALYST,
    UserTenantRole.VIEWER,
))
# Kök neden ÜRETİMİ para harcayan bir LLM çağrısı — okuma her üyeye
# açık, tetikleme yönetici + analiste.
_AdminOrAnalyst = Depends(require_role(
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


# --- response models -------------------------------------------------


class CohortDataPoint(BaseModel):
    period_start: str
    count: int
    avg_sentiment: float | None
    avg_nps: float | None


class CohortSeries(BaseModel):
    key: str
    label: str
    data_points: list[CohortDataPoint]


class CohortResponse(BaseModel):
    period: str
    dimension: str
    cohorts: list[CohortSeries]


class WordCloudWord(BaseModel):
    text: str
    weight: int
    sentiment_skew: float
    is_bigram: bool


class WordCloudResponse(BaseModel):
    words: list[WordCloudWord]
    total_reviews_analyzed: int


class RootCauseItemResponse(BaseModel):
    title: str
    description: str
    evidence_quotes: list[str]
    affected_surface: str
    suggested_action: str
    share_estimate_pct: float | None


class RootCausePayloadResponse(BaseModel):
    summary: str
    root_causes: list[RootCauseItemResponse]


class RootCauseResponse(BaseModel):
    id: str
    primary_category_code: str
    perspective_code: str
    date_from: str | None
    date_to: str | None
    review_count: int
    model_provider: str
    model_name: str
    payload: RootCausePayloadResponse
    created_at: str


class RootCauseGenerateRequest(BaseModel):
    primary_category: str
    perspective_code: str
    date_from: date | None = None
    date_to: date | None = None
    force_refresh: bool = False


class HeatmapResponse(BaseModel):
    x_axis: str
    y_axis: str
    metric: str
    metric_label: str
    x_labels: list[str]
    y_labels: list[str]
    # Sprint 9.5.1 B1.1 — raw axis values aligned 1:1 with x_labels /
    # y_labels. HeatmapGenerator has been building these since the
    # 9.5 B1 commit but the Pydantic response model dropped them on
    # serialisation (extra=ignore by default), so the frontend's
    # drilldown handler always saw ``undefined`` and silently early-
    # returned. Production smoke (2026-05-12) found the symptom:
    # cells visually highlighted on hover but click never navigated
    # to /reviews. Time-based axes are integers (0-23, 0-6, 1-12,
    # 1-53); taxonomy_code carries the string code.
    x_keys: list[int | str]
    y_keys: list[int | str]
    values: list[list[float | int | None]]
    metric_min: float | int
    metric_max: float | int


# --- endpoints --------------------------------------------------------


@router.get(
    "/cohort",
    response_model=CohortResponse,
    summary="Period × dimension cohort aggregation.",
)
async def get_cohort(
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    period: Annotated[str, Query(description="week | month | quarter")] = "month",
    dimension: Annotated[
        str,
        Query(description="taxonomy | company_perspective | nps_bucket"),
    ] = "taxonomy",
    date_from: date | None = None,
    date_to: date | None = None,
    limit_cohorts: Annotated[int, Query(ge=1, le=50)] = 10,
    batch_id: UUID | None = None,
) -> CohortResponse:
    if period not in ALLOWED_PERIODS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"period must be one of {sorted(ALLOWED_PERIODS)}",
        )
    if dimension not in ALLOWED_DIMENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"dimension must be one of {sorted(ALLOWED_DIMENSIONS)}",
        )
    tenant_id = _require_active_tenant(current)
    try:
        async with app_session.begin():
            await bind_tenant(app_session, current)
            payload = await CohortAnalyzer(app_session).aggregate(
                tenant_id=tenant_id,
                period=period,  # type: ignore[arg-type]
                dimension=dimension,  # type: ignore[arg-type]
                date_from=date_from,
                date_to=date_to,
                limit_cohorts=limit_cohorts,
                batch_id=batch_id,
            )
        return CohortResponse(**_strip_for_response(payload))
    except HTTPException:
        raise
    except Exception:
        _logger.exception(
            "cohort endpoint failed",
            extra={"tenant_id": str(tenant_id)},
        )
        raise


@router.get(
    "/word-cloud",
    response_model=WordCloudResponse,
    summary="Token frequency + sentiment skew (Türkçe stop-word filtered).",
)
async def get_word_cloud(
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    sentiment: Annotated[
        str,
        Query(description="positive | negative | neutral | all"),
    ] = "all",
    taxonomy_code: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit_words: Annotated[int, Query(ge=5, le=500)] = 100,
    include_bigrams: bool = True,
    batch_id: UUID | None = None,
) -> WordCloudResponse:
    if sentiment not in ALLOWED_SENTIMENTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"sentiment must be one of {sorted(ALLOWED_SENTIMENTS)}",
        )
    tenant_id = _require_active_tenant(current)
    try:
        async with app_session.begin():
            await bind_tenant(app_session, current)
            payload = await WordCloudGenerator(app_session).generate(
                tenant_id=tenant_id,
                sentiment=sentiment,  # type: ignore[arg-type]
                taxonomy_code=taxonomy_code,
                date_from=date_from,
                date_to=date_to,
                limit_words=limit_words,
                include_bigrams=include_bigrams,
                batch_id=batch_id,
            )
        return WordCloudResponse(**_strip_for_response(payload))
    except HTTPException:
        raise
    except Exception:
        _logger.exception(
            "word_cloud endpoint failed",
            extra={"tenant_id": str(tenant_id)},
        )
        raise


@router.get(
    "/heatmap",
    response_model=HeatmapResponse,
    summary="2D heatmap over hour/day/week × day/month/taxonomy.",
)
async def get_heatmap(
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    x_axis: Annotated[
        str,
        Query(description="hour_of_day | day_of_week | week_of_year"),
    ] = "hour_of_day",
    y_axis: Annotated[
        str,
        Query(description="day_of_week | month | taxonomy_code"),
    ] = "day_of_week",
    metric: Annotated[
        str,
        Query(description="count | avg_sentiment | avg_nps"),
    ] = "count",
    date_from: date | None = None,
    date_to: date | None = None,
    taxonomy_top_n: Annotated[int, Query(ge=1, le=50)] = 12,
    batch_id: UUID | None = None,
) -> HeatmapResponse:
    if x_axis not in ALLOWED_X_AXES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"x_axis must be one of {sorted(ALLOWED_X_AXES)}",
        )
    if y_axis not in ALLOWED_Y_AXES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"y_axis must be one of {sorted(ALLOWED_Y_AXES)}",
        )
    if x_axis == y_axis:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="x_axis and y_axis must differ",
        )
    if metric not in ALLOWED_METRICS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"metric must be one of {sorted(ALLOWED_METRICS)}",
        )
    tenant_id = _require_active_tenant(current)
    try:
        async with app_session.begin():
            await bind_tenant(app_session, current)
            payload = await HeatmapGenerator(app_session).generate(
                tenant_id=tenant_id,
                x_axis=x_axis,  # type: ignore[arg-type]
                y_axis=y_axis,  # type: ignore[arg-type]
                metric=metric,  # type: ignore[arg-type]
                date_from=date_from,
                date_to=date_to,
                taxonomy_top_n=taxonomy_top_n,
                batch_id=batch_id,
            )
        return HeatmapResponse(**_strip_for_response(payload))
    except HTTPException:
        raise
    except Exception:
        _logger.exception(
            "heatmap endpoint failed",
            extra={"tenant_id": str(tenant_id)},
        )
        raise


# --- kök neden (Sprint 13.1) ------------------------------------------


@router.get(
    "/root-cause",
    response_model=RootCauseResponse,
    summary="Alt kategori için en son üretilmiş kök neden analizi.",
)
async def get_root_cause(
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    primary_category: Annotated[str, Query(description="Ana kategori kodu.")],
    perspective_code: Annotated[
        str,
        Query(
            description=(
                "Alt kategori kodu. '__unmatched__' alt kategorisi "
                "atanmamış yorumların kovası."
            )
        ),
    ],
    date_from: date | None = None,
    date_to: date | None = None,
) -> RootCauseResponse:
    """Cache -> DB sırasıyla okur. Hiç üretilmemişse 404 — frontend o
    durumda "Analiz Oluştur" CTA'sını gösterir."""
    tenant_id = _require_active_tenant(current)
    try:
        async with app_session.begin():
            await bind_tenant(app_session, current)
            result = await RootCauseService(
                app_session, tenant_id, current.user_id
            ).get_latest(
                primary_category=primary_category,
                perspective_code=perspective_code,
                date_from=date_from,
                date_to=date_to,
            )
    except HTTPException:
        raise
    except Exception:
        _logger.exception(
            "root-cause read failed", extra={"tenant_id": str(tenant_id)}
        )
        raise
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bu alt kategori için henüz kök neden analizi üretilmemiş.",
        )
    return RootCauseResponse(**result)


@router.post(
    "/root-cause",
    response_model=RootCauseResponse,
    summary="Alt kategori için kök neden analizi üret (LLM).",
)
async def generate_root_cause(
    body: RootCauseGenerateRequest,
    current: Annotated[CurrentUser, _AdminOrAnalyst],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> RootCauseResponse:
    """Kovadaki yorumları modele verip kök nedenleri üretir, kalıcı bir
    satır açar ve 12 saat cache'ler.

    Hata haritası:
      * 412 — kurumun aktif LLM anahtarı yok (frontend ayarlar CTA'sı)
      * 400 — kovada 10'dan az yorum var
      * 422 — geçersiz ana kategori kodu
      * 503 — tüm anahtarlar tükendi / sağlayıcı hatası
    """
    tenant_id = _require_active_tenant(current)
    # Deferred raise: denetim satırı kendi savepoint'inde flush
    # edilebilsin diye önce transaction kapanır, HTTP hatası sonra
    # yükselir (briefing servisiyle aynı desen).
    deferred: HTTPException | None = None
    result: dict[str, Any] | None = None
    try:
        async with app_session.begin():
            await bind_tenant(app_session, current)
            service = RootCauseService(app_session, tenant_id, current.user_id)
            try:
                result = await service.generate(
                    primary_category=body.primary_category,
                    perspective_code=body.perspective_code,
                    date_from=body.date_from,
                    date_to=body.date_to,
                    force_refresh=body.force_refresh,
                )
            except NoCredentialsError:
                deferred = HTTPException(
                    status_code=status.HTTP_412_PRECONDITION_FAILED,
                    detail=(
                        "LLM API anahtarı tanımlanmamış. Ayarlar > "
                        "Entegrasyonlar üzerinden ekleyin."
                    ),
                )
            except NotEnoughReviewsError as exc:
                deferred = HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=str(exc),
                )
            except InvalidCategoryError as exc:
                deferred = HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=str(exc),
                )
            except (AllKeysExhaustedError, LLMError) as exc:
                deferred = HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=f"LLM sağlayıcısına ulaşılamadı: {exc}",
                )
            except RootCauseResponseInvalidError as exc:
                deferred = HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"LLM yanıtı beklenen şekilde değil: {exc}",
                )
    except HTTPException:
        raise
    except Exception:
        _logger.exception(
            "root-cause generate failed", extra={"tenant_id": str(tenant_id)}
        )
        raise
    if deferred is not None:
        raise deferred
    assert result is not None  # deferred is None => generate() returned
    return RootCauseResponse(**result)


def _strip_for_response(payload: dict[str, Any]) -> dict[str, Any]:
    """Pydantic v2 ``response_model`` validates by name, but the
    cache layer round-trips through JSON which is already
    response-friendly. This pass-through helper exists so a future
    re-shape is one place — drop unknown keys instead of letting
    Pydantic's ``model_extra`` toggle leak."""
    return dict(payload)
