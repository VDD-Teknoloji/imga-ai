"""``/tenants/me/executive/overview`` — C-level tek-bakış endpoint'i.

Sprint 10.0 — dashboard redesign'ın veri katmanı. Yönetici ana
sayfası tek round-trip ile boyanmalı; bu endpoint beş ayrı
sorgunun cevabını tek payload'da toplar:

  1. Duygu dağılımı (tüm zamanlar) — dev hero'nun üç büyük sayısı.
  2. En çok şikayet alan kategori — hero'nun tek-cümle Türkçe
     anlatısına girer ("En büyük şikayet konusu: Kargo").
  3. Müşterinin Sesi — gerçek yorum alıntıları (2 en negatif +
     1 en pozitif). "Veri değil bilgi" ilkesinin taşıyıcısı:
     yönetici sayı değil, müşterisinin cümlesini görür.
  4. Son yönetici özeti (executive briefing) — headline + kritik
     içgörüler. Yapay Zeka Özeti şeridini besler.
  5. Son SWOT + son OKR — strateji kartlarının kaynağı.

Boş tenant'ta her blok null/sıfır döner; frontend her blok için
"1 dakikada oluşturun" CTA'sını gösterir — demo akışında satış
anlatısının parçası.

Performans notu: beş sorgu tek transaction içinde sırayla koşar.
Hepsi indexli okumalar (sentiment dist GROUP BY + LIMIT 1'ler +
LIMIT 10 review taraması); 10K-yorum tenant'ta toplam <100ms
hedefi. Dashboard'un eski hali 6+ ayrı HTTP çağrısı yapıyordu;
tek çağrı hem hızlı hem atomik bir görüntü verir.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from imga_db.models import (
    Category,
    ExecutiveBriefing,
    Review,
    StrategicReport,
    UserTenantRole,
)
from pydantic import BaseModel
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import CurrentUser, bind_tenant, require_role
from imga_api.db_deps import get_app_session
from imga_api.services.analytics_service import AnalyticsService

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tenants/me/executive", tags=["Executive"])

_AnyMember = Depends(require_role(
    UserTenantRole.TENANT_ADMIN,
    UserTenantRole.ANALYST,
    UserTenantRole.VIEWER,
))

# Müşterinin Sesi alıntı seçimi: bu uzunluğun altındaki yorumlar
# ("kötü", "süper" gibi) yönetici ekranında anlam taşımaz — eler.
_QUOTE_MIN_CHARS = 40
# Alıntı metni bu uzunlukta kırpılır (kart taşmasın).
_QUOTE_MAX_CHARS = 280


# --- response models ----------------------------------------------------


class TopProblem(BaseModel):
    """Ana Sorunlar bloğunun bir satırı. ``share_pct`` tüm NEGATIF
    yorumlar içindeki pay; ``sample_text`` o kategorinin en sert,
    anlamlı (≥40 karakter) şikayet cümlesi — yönetici satırda
    rakamla birlikte müşterisinin sesini de duyar."""

    code: str
    label: str
    count: int
    share_pct: float
    sample_text: str | None


class CustomerQuote(BaseModel):
    id: UUID
    text: str
    sentiment_label: str
    category_code: str
    category_label: str
    analyzed_at: datetime


class BriefingSnapshot(BaseModel):
    id: UUID
    headline: str
    critical_insights: list[str]
    period: str
    created_at: datetime


class SwotSnapshotItem(BaseModel):
    title: str
    description: str


class SwotRecommendation(BaseModel):
    title: str
    description: str
    priority: str


class SwotSnapshot(BaseModel):
    id: UUID
    created_at: datetime
    strengths: list[SwotSnapshotItem]
    weaknesses: list[SwotSnapshotItem]
    top_recommendation: SwotRecommendation | None


class OkrKeyResult(BaseModel):
    text: str
    metric: str
    baseline: str
    target: str


class OkrObjective(BaseModel):
    objective: str
    key_results: list[OkrKeyResult]


class OkrSnapshot(BaseModel):
    id: UUID
    created_at: datetime
    objectives: list[OkrObjective]


class SentimentTrend(BaseModel):
    """Son 30 gün vs önceki 30 gün pozitif-oran karşılaştırması.
    C-level'ın "hareket ediyor muyuz?" sorusunun cevabı — statik
    fotoğraf değil, yön. Önceki pencerede hiç yorum yoksa endpoint
    null döner (yeni tenant'ta uydurma trend gösterme)."""

    current_positive_pct: float
    previous_positive_pct: float
    delta_points: float


class ExecutiveOverviewResponse(BaseModel):
    sentiment: dict[str, int]  # {"POZITIF": n, "NEGATIF": n, "NÖTR": n, "total": n}
    trend: SentimentTrend | None
    top_problems: list[TopProblem]
    nps_score: float | None
    voice_of_customer: list[CustomerQuote]
    latest_briefing: BriefingSnapshot | None
    latest_swot: SwotSnapshot | None
    latest_okr: OkrSnapshot | None


# --- helpers ------------------------------------------------------------


def _require_active_tenant(current: CurrentUser) -> UUID:
    if current.active_tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="active tenant context required for this endpoint",
        )
    return current.active_tenant_id


async def _sentiment_totals(
    session: AsyncSession, tenant_id: UUID
) -> dict[str, int]:
    """Üç duygu etiketinin toplam sayıları + genel toplam. Anahtarlar
    frontend'in beklediği literal set: POZITIF / NEGATIF / NÖTR."""
    rows = (
        await session.execute(
            select(Review.sentiment_label, func.count())
            .where(Review.tenant_id == tenant_id)
            .where(Review.deleted_at.is_(None))
            .group_by(Review.sentiment_label)
        )
    ).all()
    counts: dict[str, int] = {"POZITIF": 0, "NEGATIF": 0, "NÖTR": 0}
    for label, count in rows:
        if label in counts:
            counts[label] = int(count)
    counts["total"] = sum(
        counts[k] for k in ("POZITIF", "NEGATIF", "NÖTR")
    )
    return counts


async def _sentiment_trend(
    session: AsyncSession, tenant_id: UUID
) -> SentimentTrend | None:
    """Son 30 gün vs önceki 30 gün pozitif oranı. İki pencere de
    ``created_at`` üzerinden; önceki pencere boşsa None (trend
    iddia etme)."""
    now = datetime.now(UTC)
    cur_start = now - timedelta(days=30)
    prev_start = now - timedelta(days=60)

    async def _window(start: datetime, end: datetime | None) -> tuple[int, int]:
        stmt = (
            select(
                func.count().label("total"),
                func.sum(
                    case((Review.sentiment_label == "POZITIF", 1), else_=0)
                ).label("pos"),
            )
            .where(Review.tenant_id == tenant_id)
            .where(Review.deleted_at.is_(None))
            .where(Review.created_at >= start)
        )
        if end is not None:
            stmt = stmt.where(Review.created_at < end)
        row = (await session.execute(stmt)).first()
        if row is None:
            return 0, 0
        total, pos = row
        return int(total or 0), int(pos or 0)

    cur_total, cur_pos = await _window(cur_start, None)
    prev_total, prev_pos = await _window(prev_start, cur_start)

    if prev_total == 0 or cur_total == 0:
        return None
    cur_pct = round((cur_pos / cur_total) * 100, 1)
    prev_pct = round((prev_pos / prev_total) * 100, 1)
    return SentimentTrend(
        current_positive_pct=cur_pct,
        previous_positive_pct=prev_pct,
        delta_points=round(cur_pct - prev_pct, 1),
    )


async def _top_problems(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    total_negative: int,
    take: int = 3,
) -> list[TopProblem]:
    """Ana Sorunlar: en çok negatif yorum alan ``take`` kategori.
    'belirsiz' hariç — sınıflandırılamayan yorumlar yönetici
    anlatısına girmemeli ("En büyük sorun: Belirsiz" güven kaybı).

    ``share_pct`` paydası TÜM negatif yorumlar (belirsiz dahil) —
    "olumsuzların %30'u İade/Değişim hakkında" cümlesi dürüst kalır.
    Her kategori için en sert (en düşük sentiment_score) anlamlı
    şikayet cümlesi de döner; satırda rakam + müşteri sesi yan yana.
    """
    rows = (
        await session.execute(
            select(
                Review.primary_category,
                Category.label_tr,
                func.count().label("cnt"),
            )
            .select_from(Review)
            .outerjoin(
                Category,
                (Category.code == Review.primary_category)
                & Category.tenant_id.is_(None),
            )
            .where(Review.tenant_id == tenant_id)
            .where(Review.deleted_at.is_(None))
            .where(Review.sentiment_label == "NEGATIF")
            .where(Review.primary_category != "belirsiz")
            .group_by(Review.primary_category, Category.label_tr)
            .order_by(func.count().desc())
            .limit(take)
        )
    ).all()

    problems: list[TopProblem] = []
    for code, label_tr, count in rows:
        sample = (
            await session.execute(
                select(Review.text)
                .where(Review.tenant_id == tenant_id)
                .where(Review.deleted_at.is_(None))
                .where(Review.sentiment_label == "NEGATIF")
                .where(Review.primary_category == code)
                .where(func.length(Review.text) >= _QUOTE_MIN_CHARS)
                .order_by(Review.sentiment_score.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
        share = (
            round((int(count) / total_negative) * 100, 1)
            if total_negative > 0
            else 0.0
        )
        problems.append(
            TopProblem(
                code=code,
                label=label_tr or code,
                count=int(count),
                share_pct=share,
                sample_text=(
                    sample.strip()[:_QUOTE_MAX_CHARS] if sample else None
                ),
            )
        )
    return problems


async def _voice_of_customer(
    session: AsyncSession, tenant_id: UUID
) -> list[CustomerQuote]:
    """Gerçek müşteri alıntıları: 2 en negatif + 1 en pozitif.

    Uzunluk filtresi SQL'de (length(text) >= 40) — anlamlı cümleler.
    Her duygudan LIMIT 5 çekip Python'da slice: aynı müşterinin
    near-duplicate yorumları üst üste binmesin diye ilk farklı
    metinleri alıyoruz.
    """
    label_map = dict(
        (
            await session.execute(
                select(Category.code, Category.label_tr).where(
                    Category.tenant_id.is_(None),
                    Category.deleted_at.is_(None),
                )
            )
        ).all()
    )

    async def _pick(label: str, order_desc: bool, take: int) -> list[CustomerQuote]:
        order_col = (
            Review.sentiment_score.desc()
            if order_desc
            else Review.sentiment_score.asc()
        )
        rows = (
            await session.execute(
                select(
                    Review.id,
                    Review.text,
                    Review.sentiment_label,
                    Review.primary_category,
                    Review.analyzed_at,
                )
                .where(Review.tenant_id == tenant_id)
                .where(Review.deleted_at.is_(None))
                .where(Review.sentiment_label == label)
                .where(func.length(Review.text) >= _QUOTE_MIN_CHARS)
                .order_by(order_col, Review.analyzed_at.desc())
                .limit(5)
            )
        ).all()
        picked: list[CustomerQuote] = []
        seen_texts: set[str] = set()
        for rid, text, slabel, category, analyzed_at in rows:
            normalized = text.strip()[:80].lower()
            if normalized in seen_texts:
                continue
            seen_texts.add(normalized)
            picked.append(
                CustomerQuote(
                    id=rid,
                    text=text.strip()[:_QUOTE_MAX_CHARS],
                    sentiment_label=slabel,
                    category_code=category,
                    category_label=label_map.get(category, category),
                    analyzed_at=analyzed_at,
                )
            )
            if len(picked) >= take:
                break
        return picked

    negatives = await _pick("NEGATIF", order_desc=False, take=2)
    positives = await _pick("POZITIF", order_desc=True, take=1)
    return negatives + positives


async def _latest_briefing(
    session: AsyncSession, tenant_id: UUID
) -> BriefingSnapshot | None:
    row = (
        await session.execute(
            select(ExecutiveBriefing)
            .where(ExecutiveBriefing.tenant_id == tenant_id)
            .order_by(ExecutiveBriefing.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    insights = [str(i) for i in (row.critical_insights or [])][:3]
    return BriefingSnapshot(
        id=row.id,
        headline=row.headline,
        critical_insights=insights,
        period=row.period,
        created_at=row.created_at,
    )


def _swot_items(raw: Any, take: int) -> list[SwotSnapshotItem]:
    items: list[SwotSnapshotItem] = []
    if not isinstance(raw, list):
        return items
    for entry in raw[:take]:
        if not isinstance(entry, dict):
            continue
        items.append(
            SwotSnapshotItem(
                title=str(entry.get("title", "")),
                description=str(entry.get("description", "")),
            )
        )
    return items


async def _latest_swot(
    session: AsyncSession, tenant_id: UUID
) -> SwotSnapshot | None:
    row = (
        await session.execute(
            select(StrategicReport)
            .where(StrategicReport.tenant_id == tenant_id)
            .where(StrategicReport.report_type == "swot")
            .order_by(StrategicReport.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    payload = row.output_payload or {}
    recs = payload.get("strategic_recommendations")
    top_rec: SwotRecommendation | None = None
    if isinstance(recs, list) and recs:
        # "yüksek" öncelikli ilk tavsiye; yoksa listenin ilki.
        chosen = next(
            (
                r
                for r in recs
                if isinstance(r, dict)
                and str(r.get("priority", "")).lower() == "yüksek"
            ),
            recs[0] if isinstance(recs[0], dict) else None,
        )
        if isinstance(chosen, dict):
            top_rec = SwotRecommendation(
                title=str(chosen.get("title", "")),
                description=str(chosen.get("description", "")),
                priority=str(chosen.get("priority", "orta")),
            )
    return SwotSnapshot(
        id=row.id,
        created_at=row.created_at,
        strengths=_swot_items(payload.get("strengths"), 2),
        weaknesses=_swot_items(payload.get("weaknesses"), 2),
        top_recommendation=top_rec,
    )


async def _latest_okr(
    session: AsyncSession, tenant_id: UUID
) -> OkrSnapshot | None:
    row = (
        await session.execute(
            select(StrategicReport)
            .where(StrategicReport.tenant_id == tenant_id)
            .where(StrategicReport.report_type == "okr")
            .order_by(StrategicReport.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    payload = row.output_payload or {}
    objectives: list[OkrObjective] = []
    raw_objectives = payload.get("objectives")
    if isinstance(raw_objectives, list):
        for obj in raw_objectives[:2]:
            if not isinstance(obj, dict):
                continue
            krs: list[OkrKeyResult] = []
            raw_krs = obj.get("key_results")
            if isinstance(raw_krs, list):
                for kr in raw_krs[:3]:
                    if not isinstance(kr, dict):
                        continue
                    krs.append(
                        OkrKeyResult(
                            text=str(kr.get("text", "")),
                            metric=str(kr.get("metric", "")),
                            baseline=str(kr.get("baseline", "")),
                            target=str(kr.get("target", "")),
                        )
                    )
            objectives.append(
                OkrObjective(
                    objective=str(obj.get("objective", "")),
                    key_results=krs,
                )
            )
    return OkrSnapshot(id=row.id, created_at=row.created_at, objectives=objectives)


# --- endpoint -----------------------------------------------------------


@router.get(
    "/overview",
    response_model=ExecutiveOverviewResponse,
    summary="C-level tek-bakış: duygu + müşterinin sesi + son SWOT/OKR/özet.",
    description=(
        "Yönetici ana sayfasını tek round-trip'te boyayan aggregate "
        "endpoint. Duygu dağılımı tüm zamanları kapsar; Müşterinin "
        "Sesi en etkili 2 negatif + 1 pozitif gerçek yorumu döner; "
        "son SWOT / OKR / yönetici özeti snapshot olarak gelir. Boş "
        "tenant'ta bloklar null/sıfır döner — frontend her blok için "
        "oluşturma CTA'sı gösterir."
    ),
)
async def executive_overview(
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> ExecutiveOverviewResponse:
    tenant_id = _require_active_tenant(current)
    try:
        async with app_session.begin():
            await bind_tenant(app_session, current)

            sentiment = await _sentiment_totals(app_session, tenant_id)
            trend = await _sentiment_trend(app_session, tenant_id)
            top_problems = await _top_problems(
                app_session, tenant_id,
                total_negative=sentiment["NEGATIF"],
            )
            voice = await _voice_of_customer(app_session, tenant_id)
            briefing = await _latest_briefing(app_session, tenant_id)
            swot = await _latest_swot(app_session, tenant_id)
            okr = await _latest_okr(app_session, tenant_id)

            # NPS: canonical formül — AnalyticsService.compute_nps_summary.
            nps = await AnalyticsService(app_session).compute_nps_summary(
                tenant_id=tenant_id,
            )

        return ExecutiveOverviewResponse(
            sentiment=sentiment,
            trend=trend,
            top_problems=top_problems,
            nps_score=nps.score,
            voice_of_customer=voice,
            latest_briefing=briefing,
            latest_swot=swot,
            latest_okr=okr,
        )
    except HTTPException:
        raise
    except Exception:
        _logger.exception(
            "executive overview failed",
            extra={"tenant_id": str(tenant_id)},
        )
        raise
