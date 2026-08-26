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

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from imga_core.llm.key_rotation import GeminiKey
from imga_db.models import Review, ReviewFact, UserTenantRole
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import CurrentUser, bind_tenant, require_role
from imga_api.db_deps import get_app_session
from imga_api.dependencies import get_review_service
from imga_api.routes.tenant_batch import BatchJobResponse, dispatch_reanalysis
from imga_api.services import (
    AuditService,
    CategoryNotConfiguredError,
    ReviewAlreadyTicketedError,
    ReviewNotFoundError,
    ReviewService,
)
from imga_api.services.correction_service import (
    CorrectionError,
    CorrectionService,
)
from imga_api.services.dimension_service import UnknownDimension
from imga_api.services.embedding_service import embed_text
from imga_api.services.llm_credentials import load_active_gemini_keys
from imga_api.services.review_list_service import (
    ReviewListFilters,
    ReviewListItem,
    ReviewListService,
)
from imga_api.workers.reanalyzer import (
    NoReanalysisCandidatesError,
    create_reanalysis_job,
)

router = APIRouter(prefix="/tenants/me/reviews", tags=["Analyze"])

_AnyMember = Depends(
    require_role(
        UserTenantRole.TENANT_ADMIN,
        UserTenantRole.ANALYST,
        UserTenantRole.VIEWER,
    )
)
_WriteMember = Depends(
    require_role(
        UserTenantRole.TENANT_ADMIN,
        UserTenantRole.ANALYST,
    )
)
_TenantAdmin = Depends(require_role(UserTenantRole.TENANT_ADMIN))


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
    # Yorumun kendi tarihi (yüklemedeki ``tarih`` kolonu; yoksa ingest
    # anı). Liste bu tarihi gösterir, analyzed_at ikincil kalır.
    review_date: datetime
    submitted_by_user_id: UUID | None
    override_count: int
    company_perspective_code: str | None = None
    company_perspective_label_tr: str | None = None
    # 2026-08-10 — LLM'in temas noktası kararı ("dijital" |
    # "operasyonel"). NULL = birleşik yol koşmamış eski satır; UI
    # kategori eşlemesine düşer.
    experience_type: str | None = None
    # 2026-08-26 (migration 0047) — kaynaktaki kalıcı bağlantı (tweet
    # URL'si vb.). NULL = kaynakta bağlantı yok.
    source_url: str | None = None


class ReviewListResponse(BaseModel):
    items: list[ReviewItemResponse]
    total: int
    limit: int
    offset: int


class DimensionValueItem(BaseModel):
    value: str
    count: int


class DimensionValuesResponse(BaseModel):
    values: list[DimensionValueItem]


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


class ReviewFactsBlock(BaseModel):
    """Migration 0046 — operasyonel facts (SLA/CSAT/efor/tazmin/
    teslimat), ``review_facts`` satırı varsa. ``review_id``/
    ``tenant_id``/``created_at``/``updated_at`` hariç tüm kolonlar."""

    sla_resolution_status: str | None
    sla_first_response_status: str | None
    resolution_time_minutes: int | None
    first_response_time_minutes: int | None
    csat_score: int | None
    csat_raw: str | None
    agent_interactions: int | None
    customer_interactions: int | None
    compensation_status: str | None
    # float: Decimal pydantic json modunda string'e serilesir, frontend
    # number bekler (operations/summary ile ayni tel-tipi).
    freight_cost: float | None
    goods_cost: float | None
    refund_reason: str | None
    delivery_status: str | None
    delivery_detail: str | None


class ReviewDetailResponse(BaseModel):
    id: UUID
    text: str
    text_hash: str
    analyzed_at: datetime
    review_date: datetime
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
    experience_type: str | None = None
    facts: ReviewFactsBlock | None = None
    source_url: str | None = None


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
    channels: str | None = Query(
        default=None,
        description=(
            "CSV of Review.channel raw values (taşıyıcı). "
            "Case/whitespace-insensitive — matched via lower(trim(...))."
        ),
    ),
    business_segments: str | None = Query(
        default=None,
        description="CSV of Review.business_segment raw values (departman).",
    ),
    product_lines: str | None = Query(
        default=None,
        description="CSV of Review.product_line raw values (talep tipi).",
    ),
    customer_tiers: str | None = Query(
        default=None,
        description="CSV of Review.customer_tier raw values (ticket kategori).",
    ),
    entered_bys: str | None = Query(
        default=None,
        description="CSV of Review.entered_by raw values (temsilci).",
    ),
    sources: str | None = Query(
        default=None,
        description="CSV of Review.source raw values (Email/Portal/Phone...).",
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
    quality_flags: str | None = Query(
        default=None,
        description=(
            "CSV: duplicate,empty,informational,meaningless. Verilirse "
            "yalnız bu bayraklara sahip satırlar döner (ör. 'sadece "
            "bilgilendirmeleri göster')."
        ),
    ),
    include_flagged: bool = Query(
        default=True,
        description=(
            "Düşük kaliteli (bayraklı) yorumları listeye dahil et. "
            "Liste bir arşivdir; varsayılan HEPSİ (analitik "
            "varsayılanından farklı). quality_flags verilmişse bu "
            "alan devre dışı kalır."
        ),
    ),
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
        channels=_split_csv(channels),
        business_segments=_split_csv(business_segments),
        product_lines=_split_csv(product_lines),
        customer_tiers=_split_csv(customer_tiers),
        entered_bys=_split_csv(entered_bys),
        sources=_split_csv(sources),
        hour_of_day=hour_of_day,
        day_of_week=day_of_week,
        week_of_year=week_of_year,
        month=month,
        search=search,
        quality_flags=_split_csv(quality_flags),
        include_flagged=include_flagged,
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
    "/dimension-values",
    response_model=DimensionValuesResponse,
    summary="Distinct raw values for one business-dimension column.",
    description=(
        "Filter-chip source for the review list's business-dimension "
        "filters (channels / business_segments / product_lines / "
        "customer_tiers / entered_bys / sources). Folds on "
        "lower(trim(...)) like the dimension breakdown and the list "
        "filters themselves — 'FEDEX' and 'fedex' collapse into one "
        "entry whose value is the most-frequent raw spelling. Ordered "
        "by count desc, capped at 100."
    ),
    responses={400: {"description": "Unknown field."}},
)
async def list_dimension_values(
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    field: str = Query(
        ...,
        description=(
            "channel | business_segment | product_line | " "customer_tier | entered_by | source"
        ),
    ),
    include_flagged: bool = Query(
        default=True,
        description=(
            "Düşük kaliteli (bayraklı) yorumları da say. Varsayılan: "
            "dahil — bu uç bir filtre kaynağıdır, liste gibi arşive "
            "bakar (analitiğin False varsayılanından farklı)."
        ),
    ),
) -> DimensionValuesResponse:
    # NOTE: this route MUST stay registered before GET /{review_id} —
    # Starlette matches path patterns in registration order and
    # "dimension-values" would otherwise be swallowed by {review_id}
    # (a str-typed path segment) and 422 on UUID coercion instead of
    # reaching this handler.
    tenant_id = _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        service = ReviewListService(app_session)
        try:
            rows = await service.dimension_values(
                tenant_id=tenant_id,
                field=field,
                include_flagged=include_flagged,
            )
        except UnknownDimension as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return DimensionValuesResponse(
        values=[DimensionValueItem(value=r.value, count=r.count) for r in rows]
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
        result = await service.get_review(tenant_id=tenant_id, review_id=review_id)
        if result is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="review not found")
        review, perspective_label_tr = result
        # Sprint 8.3.4 — overrides_applied JSONB now populated by the
        # bridge (and the batch worker on the dedup/opt-out paths). Rows
        # analyzed before migration 0014 carry NULL; surface as []. The
        # raw/final score split still surfaces the same value on both
        # sides; once override math reshapes the score this row already
        # has the trace ready to drive the divergence.
        score = float(review.sentiment_score)
        overrides_list: list[dict[str, object]] = list(review.overrides_applied or [])
        # Migration 0046 — nullable facts enrichment (review_facts is
        # 1:1 with reviews; most rows have none).
        fact_row = (
            await app_session.execute(select(ReviewFact).where(ReviewFact.review_id == review_id))
        ).scalar_one_or_none()
        facts_block = (
            ReviewFactsBlock(
                sla_resolution_status=fact_row.sla_resolution_status,
                sla_first_response_status=fact_row.sla_first_response_status,
                resolution_time_minutes=fact_row.resolution_time_minutes,
                first_response_time_minutes=fact_row.first_response_time_minutes,
                csat_score=fact_row.csat_score,
                csat_raw=fact_row.csat_raw,
                agent_interactions=fact_row.agent_interactions,
                customer_interactions=fact_row.customer_interactions,
                compensation_status=fact_row.compensation_status,
                freight_cost=(
                    float(fact_row.freight_cost) if fact_row.freight_cost is not None else None
                ),
                goods_cost=(
                    float(fact_row.goods_cost) if fact_row.goods_cost is not None else None
                ),
                refund_reason=fact_row.refund_reason,
                delivery_status=fact_row.delivery_status,
                delivery_detail=fact_row.delivery_detail,
            )
            if fact_row is not None
            else None
        )
        return ReviewDetailResponse(
            id=review.id,
            text=review.text,
            text_hash=review.text_hash,
            analyzed_at=review.analyzed_at,
            review_date=review.review_date,
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
            experience_type=review.experience_type,
            facts=facts_block,
            source_url=review.source_url,
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
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        except CategoryNotConfiguredError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        return ManualPromotionResponse(
            review_id=review_id,
            ticket_id=ticket.id,
            ticket_state=str(ticket.state),
        )


# --- Sprint 11.0 — kullanıcı düzeltmesi (düzeltme-geri-besleme) -----


class CorrectReviewRequest(BaseModel):
    """En az bir alan zorunlu; verilmeyen alan mevcut kararda kalır.

    2026-08-18 (migration 0042) — sentiment_score/experience_type/
    perspective_code duygu ve kategoriden BAĞIMSIZ düzeltilebilir
    (yalnız skor ya da yalnız perspektif düzeltmesi de geçerli)."""

    sentiment_label: Literal["POZITIF", "NEGATIF", "NÖTR"] | None = None
    primary_category: str | None = None
    sentiment_score: float | None = Field(default=None, ge=-1.0, le=1.0)
    experience_type: Literal["dijital", "operasyonel"] | None = None
    # tenant'ın aktif CategoryTaxonomy kodlarından biri olmalı;
    # servis katmanı doğrular (bilinmeyen kod -> 400).
    perspective_code: str | None = None
    reason: str | None = None


class CorrectReviewResponse(BaseModel):
    review_id: UUID
    sentiment_label: str
    sentiment_score: float
    primary_category: str
    experience_type: str | None
    perspective_code: str | None
    correction_id: UUID
    # Frontend "düzeltme kaydedildi + benzer yorumlara genellenecek"
    # mesajını embedding başarısına göre tonlayabilir.
    embedding_stored: bool


@router.post(
    "/{review_id}/correct",
    response_model=CorrectReviewResponse,
    summary="Yanlış model kararını düzelt (düzeltme-geri-besleme).",
    description=(
        "Analiz kararını insan kararıyla değiştirir: reviews satırı "
        "anında güncellenir, düzeltme review_corrections'a yazılır. "
        "Düzeltme üç katmanda 'öğrenir': aynı metin bir daha gelirse "
        "birebir override; Gemini sınıflandırma prompt'una few-shot "
        "örneği; embedding (best-effort) ile anlamsal komşu araması. "
        "Viewer rolü düzeltemez."
    ),
    responses={
        400: {"description": "Geçersiz alanlar / değişiklik yok."},
        403: {"description": "Viewer rolü düzeltme yapamaz."},
        404: {"description": "Yorum bulunamadı / RLS gizledi."},
    },
)
async def correct_review(
    review_id: UUID,
    body: CorrectReviewRequest,
    current: Annotated[CurrentUser, _WriteMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> CorrectReviewResponse:
    tenant_id = _require_active_tenant(current)

    # Embedding, düzeltme transaction'ı AÇILMADAN önce best-effort
    # hesaplanır — dış API beklerken satır kilidi tutulmaz. Metin +
    # tenant key'leri kısa bir ön-transaction'da okunur.
    embedding: list[float] | None = None
    text_value: str | None = None
    keys: list[GeminiKey] = []
    async with app_session.begin():
        await bind_tenant(app_session, current)
        text_value = (
            await app_session.execute(
                select(Review.text)
                .where(Review.id == review_id)
                .where(Review.tenant_id == tenant_id)
                .where(Review.deleted_at.is_(None))
            )
        ).scalar_one_or_none()
        if text_value is not None:
            try:
                keys = await load_active_gemini_keys(app_session, tenant_id)
            except Exception:
                keys = []
    # 2026-08-18 — embed_text artık boş `keys` + IMGA_EMBEDDING_
    # FALLBACK_KEY varsa platform anahtarına düşer (embedding_service.
    # py); `and keys` kapısı bu yolu bloklardı, kaldırıldı.
    if text_value is not None:
        embedding = await embed_text(text_value, keys)

    async with app_session.begin():
        await bind_tenant(app_session, current)
        service = CorrectionService(app_session)
        try:
            correction, effective_score = await service.correct_review(
                tenant_id=tenant_id,
                review_id=review_id,
                new_sentiment_label=body.sentiment_label,
                new_category=(body.primary_category or "").strip() or None,
                new_score=body.sentiment_score,
                new_experience=body.experience_type,
                new_perspective=(body.perspective_code or "").strip() or None,
                reason=body.reason,
                corrected_by_user_id=current.user_id,
                embedding=embedding,
            )
        except CorrectionError as exc:
            detail = str(exc)
            code = (
                status.HTTP_404_NOT_FOUND if "bulunamadı" in detail else status.HTTP_400_BAD_REQUEST
            )
            raise HTTPException(status_code=code, detail=detail) from exc
        # 2026-08-18 (bulgu düzeltmesi) — ``correction.new_score`` ham
        # alan (yalnız skor GÖNDERİLDİYSE dolu); yalnız kategori/deneyim/
        # perspektif düzeltmesinde skor KORUNUR (SCORE_FOR_LABEL'e
        # sıfırlanmaz) — SCORE_FOR_LABEL fallback'i burada tekrarlarsak
        # yanıt DB'deki gerçek review.sentiment_score'dan sapar; servis
        # bu yüzden gerçekten yazılan skoru da döner.
        return CorrectReviewResponse(
            review_id=review_id,
            sentiment_label=correction.new_sentiment_label,
            sentiment_score=effective_score,
            primary_category=correction.new_category,
            experience_type=correction.new_experience,
            perspective_code=correction.new_perspective,
            correction_id=correction.id,
            embedding_stored=embedding is not None,
        )


# --- 2026-08-10 — kurum geneli yeniden analiz -----------------------


@router.post(
    "/reanalyze-all",
    response_model=BatchJobResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Kurumdaki TÜM yorumları güncel modelden yeniden geçir.",
    description=(
        "Yeni bir yeniden analiz işi açar (``analyze_batch_jobs`` "
        "satırı) ve kuyruğa verir; ilerleme normal bir yükleme işi "
        "gibi ``/tenants/me/analyze/batch/{job_id}`` üzerinden "
        "izlenir. Yorumlar YERİNDE güncellenir: duygu, kategori, alt "
        "kategori ve deneyim tipi tazelenir; ``review_date``, NPS, "
        "ticket bağlantısı ve otomasyon kararı korunur. İnsan "
        "düzeltmesi yapılmış yorumlara DOKUNULMAZ. Yalnız kurum "
        "yöneticisi çalıştırabilir."
    ),
    responses={
        400: {"description": "Yeniden analiz edilecek yorum yok."},
        403: {"description": "Kurum yöneticisi olmayan rol."},
    },
)
async def reanalyze_all_reviews(
    request: Request,
    current: Annotated[CurrentUser, _TenantAdmin],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> BatchJobResponse:
    tenant_id = _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        audit = AuditService(app_session)
        try:
            job = await create_reanalysis_job(
                app_session,
                audit,
                tenant_id=tenant_id,
                triggered_by_user_id=current.user_id,
                source_batch_job_id=None,
                ip_address=(request.client.host if request.client is not None else None),
            )
        except NoReanalysisCandidatesError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        job_id = job.id
        # ORM attribute'ları transaction KAPANMADAN (aşağıdaki commit'ten
        # önce) okunur — flush sonrası expire olabilirler, blok dışında
        # erişim MissingGreenlet'e çarpar (root_cause_service.py'deki
        # aynı gerekçeyle).
        candidate_row_count = job.total_rows

        # B3b — süper-admin denetim raporu: Karar Geçmişi'ne 'reanalysis
        # started' eylemi. tenant_kpi_goals.py:195'teki DecisionAudit
        # Service çağrı deseniyle aynı; ``create_reanalysis_job``'ın
        # AuditService.log çağrısı genel audit_logs izini bırakır, bu
        # ayrı bir kayıttır. ``source_batch_job_id=None`` her zaman
        # geçildiği için kapsam sabit "all" (tüm kurum) — bu route'ta
        # tek-batch kapsamlı yeniden analiz yok. ``DECISION_REANALYSIS_
        # STARTED`` migration 0045 ile decision_audit_service.py'ye
        # ekleniyor (SA1); henüz diskte yoksa bu import başarısız olur.
        from imga_api.services.decision_audit_service import (
            DECISION_REANALYSIS_STARTED,
            DecisionAuditService,
        )

        await DecisionAuditService(app_session).record_decision(
            tenant_id=tenant_id,
            decision_type=DECISION_REANALYSIS_STARTED,
            related_entity_type="batch_job",
            related_entity_id=job_id,
            actor_user_id=current.user_id,
            payload={"scope": "all", "row_count": candidate_row_count},
            request_id=getattr(request.state, "request_id", None),
        )

    return await dispatch_reanalysis(
        request, current, app_session, job_id=job_id, tenant_id=tenant_id
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
        review_date=item.review_date,
        submitted_by_user_id=item.submitted_by_user_id,
        override_count=item.override_count,
        company_perspective_code=item.company_perspective_code,
        company_perspective_label_tr=item.company_perspective_label_tr,
        experience_type=item.experience_type,
        source_url=item.source_url,
    )
