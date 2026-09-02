"""Kök neden analizi orkestratörü (Sprint 13.1).

Hiyerarşik kategori drill-down'ın üçüncü seviyesi: "Kargo kategorisinde
2500 olumsuz yorum var → 1200'ü kargo statüsüyle ilgili → tıkla → nokta
atışı kök neden". Bu servis o son adımı üretir.

Akış (executive briefing / SWOT idiomunun birebir aynısı):

  1. Kova sayımı + örneklem: (kurum, ana kategori, alt kategori,
     tarih penceresi) için en fazla 300 yorum metni — önce NEGATİF,
     sonra en yeniler.
  2. Redis cache lookup (12s TTL). Hit → LLM çağrısı yok.
  3. Kimlik bilgileri: ``load_active_llm_keys`` → yoksa
     ``NoCredentialsError`` (route 412'ye çevirir).
  4. Prompt: root_cause_v1 + kurum bağlamı (sektör/büyüklük/iş tanımı) +
     kurum diline göre ``language_directive`` + ``terminology_directive``
     + kategori bazlı ``playbook_directive`` (uzman CX notu, TASK B2).
  5. Sağlayıcı: ``build_structured_provider`` + ``resolve_model_name``,
     çağrı ``GeminiKeyRotator`` üzerinden.
  6. Denetim: ``LLMCallAuditor`` / ``CALL_TYPE_ROOT_CAUSE``.
  7. Kalıcılık: ``root_cause_analyses`` satırı + aynı payload cache'e.

Cache hataları ASLA üretimi bloklamaz — her cache işlemi savunmacı
try/except içinde (SWOT servisiyle aynı sözleşme).

SAYIM NOTU: örneklem sorgusu da drill-down endpoint'i gibi yalnız
``reviews`` kolonlarını filtreler (``primary_category`` +
``company_perspective_code``). Taksonominin ana kategori eşlemesi
buraya girmez; girseydi grafikte gördüğü 1200 yorum ile analizin
okuduğu küme farklı olurdu.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from imga_core.categories.taxonomy import DEFAULT_GLOBAL_CATEGORIES
from imga_core.config import LABEL_NEGATIVE
from imga_core.llm import (
    AllKeysExhaustedError,
    GeminiKeyRotator,
    InvalidKeyError,
    LLMError,
)
from imga_db.models import CategoryTaxonomy, Review, RootCauseAnalysis, Tenant
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.cache.redis_client import get_redis_client
from imga_api.llm.prompts.root_cause_v1 import (
    ROOT_CAUSE_RESPONSE_SCHEMA,
    ROOT_CAUSE_SYSTEM_PROMPT,
    render_root_cause_user_prompt,
)
from imga_api.services.analytics_service import UNMATCHED_PERSPECTIVE_SENTINEL
from imga_api.services.category_codes import valid_primary_codes
from imga_api.services.llm_credentials import (
    NoCredentialsError,
    load_active_llm_keys,
    mark_keys_failed,
)
from imga_api.services.llm_provider_factory import (
    StructuredProvider,
    build_structured_provider,
    resolve_model_name,
)
from imga_api.services.strategic_constants import (
    company_size_label,
    industry_label,
    language_directive,
    playbook_directive,
    terminology_directive,
)

_logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 12 * 3600
CACHE_KEY_PREFIX = "root_cause"
#: Modele gönderilen en fazla yorum sayısı.
MAX_SAMPLE_REVIEWS = 300
#: Bu eşiğin altında anlamlı bir kök neden çıkmıyor; 400 döndürülür.
MIN_REVIEWS = 10
#: Tek yorumun prompt'a giren en fazla karakteri (uzun kuyruğu kırp).
_MAX_REVIEW_CHARS = 600
# 2026-09-01 — yer tutucu ('...') iskelet yanıt için yeniden deneme sayısı.
_PLACEHOLDER_RETRIES = 2

_CATEGORY_LABELS: dict[str, str] = {c.code: c.name for c in DEFAULT_GLOBAL_CATEGORIES}


class RootCauseServiceError(Exception):
    """Route katmanının HTTP'ye çevirdiği taban hata."""


class NotEnoughReviewsError(RootCauseServiceError):
    """Kovada ``MIN_REVIEWS``'ten az yorum var — 400."""


class RootCauseResponseInvalidError(RootCauseServiceError):
    """LLM 200 döndü ama şemanın zorunlu alanları eksik."""


class RootCausePlaceholderError(RootCauseResponseInvalidError):
    """Model muhakemesiz bir şema iskeleti döndürdü (tüm metin alanları
    "..." / boş). Kaydedilmez; ``generate`` sınırlı sayıda yeniden dener."""


class InvalidCategoryError(RootCauseServiceError):
    """``primary_category`` global kod listesinde yok — 422."""


@dataclass(frozen=True, slots=True)
class _BucketSample:
    total: int
    negative: int
    reviews: list[dict[str, str]]


# ---------------------------------------------------------------------------
# Overview picker — shared by GET /root-cause/overview (tenant_insights.py)
# and the post-batch auto-generation task (workers/arq_worker.py). One
# query set, two callers with different windows (rolling "now" vs.
# day-rounded), so a fix to the SQL lands in both places at once.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CategoryPerspectivePick:
    """One drill-down candidate: the category's negative count in the
    window, its worst perspective (None if every negative row in the
    category is perspective-NULL), and whether that (category,
    perspective) bucket clears ``MIN_REVIEWS`` — the same gate
    ``RootCauseService.generate`` enforces, so ``can_generate`` never
    promises a generation the service would then reject."""

    primary_category_code: str
    negative_count: int
    perspective_code: str | None
    bucket_total: int
    can_generate: bool


async def pick_top_categories(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    date_from: datetime | None,
    date_to: datetime | None,
    limit: int,
) -> list[CategoryPerspectivePick]:
    """Top-``limit`` negative categories in the window, each paired
    with its worst company-perspective bucket.

    'belirsiz' is excluded from the candidates for the same reason
    ``tenant_executive._top_problems`` excludes it: a card titled "En
    büyük sorun: Belirsiz" is a trust-losing narrative, not a root
    cause to drill into.
    """

    def _scoped(stmt: Any) -> Any:
        stmt = (
            stmt.where(Review.tenant_id == tenant_id)
            .where(Review.deleted_at.is_(None))
            .where(Review.quality_flag.is_(None))
        )
        if date_from is not None:
            stmt = stmt.where(Review.review_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(Review.review_date <= date_to)
        return stmt

    top_rows = (
        await session.execute(
            _scoped(select(Review.primary_category, func.count().label("cnt")).select_from(Review))
            .where(Review.sentiment_label == LABEL_NEGATIVE)
            .where(Review.primary_category != "belirsiz")
            .group_by(Review.primary_category)
            .order_by(func.count().desc())
            .limit(limit)
        )
    ).all()

    picks: list[CategoryPerspectivePick] = []
    for category_code, negative_count in top_rows:
        persp_row = (
            await session.execute(
                _scoped(
                    select(
                        Review.company_perspective_code,
                        func.count().label("neg_cnt"),
                    ).select_from(Review)
                )
                .where(Review.primary_category == category_code)
                .where(Review.company_perspective_code.is_not(None))
                .where(Review.sentiment_label == LABEL_NEGATIVE)
                .group_by(Review.company_perspective_code)
                .order_by(func.count().desc())
                .limit(1)
            )
        ).first()
        if persp_row is None:
            picks.append(
                CategoryPerspectivePick(
                    primary_category_code=str(category_code),
                    negative_count=int(negative_count),
                    perspective_code=None,
                    bucket_total=0,
                    can_generate=False,
                )
            )
            continue
        perspective_code = str(persp_row[0])
        bucket_total = (
            await session.execute(
                _scoped(select(func.count()).select_from(Review))
                .where(Review.primary_category == category_code)
                .where(Review.company_perspective_code == perspective_code)
            )
        ).scalar_one()
        picks.append(
            CategoryPerspectivePick(
                primary_category_code=str(category_code),
                negative_count=int(negative_count),
                perspective_code=perspective_code,
                bucket_total=int(bucket_total),
                can_generate=int(bucket_total) >= MIN_REVIEWS,
            )
        )
    return picks


async def total_negative_count(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    date_from: datetime | None,
    date_to: datetime | None,
) -> int:
    """Denominator for card ``share_pct`` — ALL negatives in the
    window, 'belirsiz' included (mirrors ``_top_problems``: the
    numerator narrative excludes it, the honest denominator doesn't)."""
    stmt = (
        select(func.count())
        .select_from(Review)
        .where(Review.tenant_id == tenant_id)
        .where(Review.deleted_at.is_(None))
        .where(Review.quality_flag.is_(None))
        .where(Review.sentiment_label == LABEL_NEGATIVE)
    )
    if date_from is not None:
        stmt = stmt.where(Review.review_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(Review.review_date <= date_to)
    return int((await session.execute(stmt)).scalar_one() or 0)


async def latest_analysis_any_window(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    primary_category_code: str,
    perspective_code: str,
) -> RootCauseAnalysis | None:
    """Newest analysis for (tenant, category, perspective) regardless
    of the analysis's OWN date_from/date_to — the overview shows the
    freshest thinking; its window rides along in the response block
    rather than gating the lookup (a ranking window that shrank since
    the analysis was generated shouldn't hide it)."""
    stmt = (
        select(RootCauseAnalysis)
        .where(RootCauseAnalysis.tenant_id == tenant_id)
        .where(RootCauseAnalysis.primary_category_code == primary_category_code)
        .where(RootCauseAnalysis.perspective_code == perspective_code)
        .order_by(RootCauseAnalysis.created_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


def day_rounded_window(now: datetime | None = None) -> tuple[date, date]:
    """90-day window, rounded to whole UTC days: ``date_to`` = today,
    ``date_from`` = today - 90.

    Used ONLY by the post-batch auto-generation task. Day-rounding is
    the whole point: several batches can land for the same tenant on
    the same day, and each would otherwise compute a (date_from,
    date_to) pair a few seconds apart — different cache keys, so the
    12h ``RootCauseService`` cache would never dedup them and every
    batch would re-spend an LLM call. Rounding to the day means every
    call site on the same UTC day produces the identical tuple.
    """
    reference = (now or datetime.now(UTC)).astimezone(UTC)
    today = reference.date()
    return today - timedelta(days=90), today


class RootCauseService:
    """Tek bir (kurum, ana kategori, alt kategori, pencere) dörtlüsü
    için kök neden analizi üretir / okur."""

    def __init__(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        user_id: UUID | None,
        *,
        provider: StructuredProvider | None = None,
    ) -> None:
        self._session = session
        self._tenant_id = tenant_id
        self._user_id = user_id
        # Test izolasyonu için enjekte edilir; üretimde sağlayıcı
        # kurumun kazanan kimlik kaydına bağlı olduğundan generate()
        # içinde kurulur (SWOT servisiyle aynı gerekçe).
        self._provider = provider

    # ------------------------------------------------------------------
    # Read path
    # ------------------------------------------------------------------

    async def get_latest(
        self,
        *,
        primary_category: str,
        perspective_code: str,
        date_from: date | None,
        date_to: date | None,
    ) -> dict[str, Any] | None:
        """Cache → DB sırasıyla en son üretilmiş analizi döndür.
        Hiç üretilmemişse None (route 404'e çevirir)."""
        cache_key = self._cache_key(primary_category, perspective_code, date_from, date_to)
        cached = await self._cache_get(cache_key)
        if cached is not None:
            return cached

        stmt = (
            select(RootCauseAnalysis)
            .where(RootCauseAnalysis.tenant_id == self._tenant_id)
            .where(RootCauseAnalysis.primary_category_code == primary_category)
            .where(RootCauseAnalysis.perspective_code == perspective_code)
        )
        # NULL pencere ("tüm zaman") ile dolu pencere farklı kayıtlar;
        # ``== None`` SQL'de hiçbir satıra uymaz, IS NULL şart.
        stmt = stmt.where(
            RootCauseAnalysis.date_from.is_(None)
            if date_from is None
            else RootCauseAnalysis.date_from == date_from
        )
        stmt = stmt.where(
            RootCauseAnalysis.date_to.is_(None)
            if date_to is None
            else RootCauseAnalysis.date_to == date_to
        )
        stmt = stmt.order_by(RootCauseAnalysis.created_at.desc()).limit(1)
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return None
        return _serialise(row)

    # ------------------------------------------------------------------
    # Write path
    # ------------------------------------------------------------------

    async def generate(
        self,
        *,
        primary_category: str,
        perspective_code: str,
        date_from: date | None = None,
        date_to: date | None = None,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        # 2026-08-18 WS2 — global kod uzayi + kurumun aktif custom
        # kategori kodlari; sabit GLOBAL_CATEGORY_CODES kurumun kendi
        # actigi custom kategoriyi hep reddediyordu.
        valid_codes = await valid_primary_codes(self._session, self._tenant_id)
        if primary_category not in valid_codes:
            raise InvalidCategoryError(
                f"primary_category {primary_category!r} gecerli kod listesinde "
                f"yok: {', '.join(sorted(valid_codes))}"
            )

        cache_key = self._cache_key(primary_category, perspective_code, date_from, date_to)
        if not force_refresh:
            cached = await self._cache_get(cache_key)
            if cached is not None:
                _logger.info(
                    "root-cause cache hit tenant=%s key=%s",
                    self._tenant_id,
                    cache_key,
                )
                return cached

        sample = await self._collect_bucket(
            primary_category=primary_category,
            perspective_code=perspective_code,
            date_from=date_from,
            date_to=date_to,
        )
        if sample.total < MIN_REVIEWS:
            raise NotEnoughReviewsError(
                f"Bu alt kategoride kök neden analizi için yeterli yorum yok "
                f"(en az {MIN_REVIEWS} gerekiyor, bulunan {sample.total})."
            )

        key_selection = await load_active_llm_keys(self._session, self._tenant_id)
        if key_selection is None:
            raise NoCredentialsError("Tenant has no active LLM API keys configured")
        keys = key_selection.keys
        rotator = GeminiKeyRotator(keys)
        provider_name = key_selection.provider
        model_name = resolve_model_name(provider_name, key_selection.model)
        provider = self._provider or build_structured_provider(provider_name)

        perspective_label = await self._perspective_label(perspective_code)

        # B1a — DB override (tenant > global) varsa onu kullan, yoksa
        # kod sabitleri (swot_service.py:181-194 ile aynı desen; bu
        # servisin kendi Jinja2 user-prompt render mekanizması zaten
        # var — root_cause_v1.render_root_cause_user_prompt — bu yüzden
        # select_prompt hem system hem user prompt'u kapsar, SWOT'takiyle
        # birebir aynı şekilde).
        from imga_api.services.prompt_override import select_prompt

        tenant_context = await self._tenant_context()
        _ctx: dict[str, Any] = {
            "primary_category_label": _CATEGORY_LABELS.get(primary_category, primary_category),
            "perspective_label": perspective_label,
            "date_from": date_from,
            "date_to": date_to,
            "bucket_total": sample.total,
            "bucket_negative": sample.negative,
            "sample_count": len(sample.reviews),
            "reviews": sample.reviews,
            **tenant_context,
        }
        selection = await select_prompt(
            self._session,
            tenant_id=self._tenant_id,
            template_key="root_cause",
            variables=_ctx,
            default_system_prompt=ROOT_CAUSE_SYSTEM_PROMPT,
            default_user_prompt=lambda: render_root_cause_user_prompt(_ctx),
        )
        user_prompt = selection.user_prompt
        language = await self._tenant_language()
        terminology = await self._tenant_terminology()
        system_prompt = (
            selection.system_prompt
            + language_directive(language)
            + terminology_directive(terminology)
            + playbook_directive(primary_category)
        )

        failed_invalid_key_ids: list[UUID] = []

        async def _call(api_key: str) -> tuple[dict[str, Any], dict[str, int] | None]:
            try:
                return await provider.generate_root_cause(
                    api_key=api_key,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    response_schema=ROOT_CAUSE_RESPONSE_SCHEMA,
                    model_name=model_name,
                )
            except InvalidKeyError:
                for k in keys:
                    if k.value == api_key:
                        failed_invalid_key_ids.append(UUID(k.id))
                        break
                raise

        from imga_api.services.llm_audit_service import (
            CALL_TYPE_ROOT_CAUSE,
            LLMCallAuditor,
            LLMCallContext,
        )

        audit_ctx = LLMCallContext(
            tenant_id=self._tenant_id,
            call_type=CALL_TYPE_ROOT_CAUSE,
            model_name=model_name,
            model_provider=provider_name,
            prompt_template_key="root_cause",
            prompt_template_version=selection.version,
            actor_user_id=self._user_id,
            related_entity_type="root_cause_analysis",
        )
        start = time.monotonic()
        token_usage: dict[str, int] | None = None

        async def _attempt() -> tuple[dict[str, Any], Any]:
            nonlocal token_usage
            auditor = LLMCallAuditor(self._session, audit_ctx, prompt=user_prompt)
            try:
                async with auditor:
                    try:
                        (response, usage), key_used = await rotator.call_with_rotation(_call)
                    except AllKeysExhaustedError as exc:
                        auditor.record_failure(
                            error_type="all_keys_exhausted",
                            error_message=str(exc.__cause__ or exc)[:1024],
                        )
                        raise
                    except LLMError as exc:
                        auditor.record_failure(
                            error_type="api_error",
                            error_message=str(exc)[:1024],
                        )
                        raise
                    except Exception as exc:
                        auditor.record_failure(
                            error_type="other",
                            error_message=f"{type(exc).__name__}: {exc}"[:1024],
                        )
                        raise
                    token_usage = usage
                    auditor.record_success(
                        input_tokens=(usage.get("input") if usage else None),
                        output_tokens=(usage.get("output") if usage else None),
                    )
            except AllKeysExhaustedError:
                await mark_keys_failed(self._session, failed_invalid_key_ids)
                raise
            except LLMError:
                raise
            return response, key_used

        # 2026-09-01 — GLM ara sıra muhakemesiz bir şema iskeleti döndürüyor
        # (63 çıktı token'ı, 0 muhakeme; tüm alanlar "..."). Kaydedilirse
        # kart ekranda "..." gösterir. Yer tutucu yanıt doğrulamada
        # reddedilir ve sınırlı sayıda yeniden denenir; her deneme kendi
        # denetim satırını yazar.
        for attempt in range(_PLACEHOLDER_RETRIES + 1):
            response, key_used = await _attempt()
            try:
                payload = _validate_and_normalise(response)
                break
            except RootCausePlaceholderError as exc:
                if attempt >= _PLACEHOLDER_RETRIES:
                    raise
                _logger.warning(
                    "root-cause placeholder response tenant=%s main=%s sub=%s attempt=%d (%s); retrying",
                    self._tenant_id,
                    primary_category,
                    perspective_code,
                    attempt + 1,
                    exc,
                )

        duration_ms = int((time.monotonic() - start) * 1000)
        if failed_invalid_key_ids:
            await mark_keys_failed(self._session, failed_invalid_key_ids)

        row = RootCauseAnalysis(
            tenant_id=self._tenant_id,
            primary_category_code=primary_category,
            perspective_code=perspective_code,
            date_from=date_from,
            date_to=date_to,
            review_count=sample.total,
            model_provider=provider_name,
            model_name=model_name,
            payload=payload,
            generated_by_user_id=self._user_id,
        )
        self._session.add(row)
        await self._session.flush()
        # Sunucu tarafı default'lar (created_at/updated_at) flush'tan
        # sonra expire olur; senkron erişim MissingGreenlet atar.
        await self._session.refresh(row, ["created_at", "updated_at"])
        result = _serialise(row)
        await self._cache_set(cache_key, result)

        _logger.info(
            "root-cause generated tenant=%s main=%s sub=%s reviews=%d key_id=%s duration_ms=%d",
            self._tenant_id,
            primary_category,
            perspective_code,
            sample.total,
            key_used.id,
            duration_ms,
        )
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _collect_bucket(
        self,
        *,
        primary_category: str,
        perspective_code: str,
        date_from: date | None,
        date_to: date | None,
    ) -> _BucketSample:
        """Kova sayımı + örneklem. Yalnız review kolonları filtrelenir."""

        def _scoped(stmt: Any) -> Any:
            stmt = (
                stmt.where(Review.tenant_id == self._tenant_id)
                .where(Review.deleted_at.is_(None))
                .where(Review.quality_flag.is_(None))
                .where(Review.primary_category == primary_category)
            )
            if perspective_code == UNMATCHED_PERSPECTIVE_SENTINEL:
                stmt = stmt.where(Review.company_perspective_code.is_(None))
            else:
                stmt = stmt.where(Review.company_perspective_code == perspective_code)
            # Drill-down endpoint'iyle aynı pencere kuralı: kapsayıcı
            # UTC gün sınırları, üst sınır gün SONU (2026-03-31 o günün
            # 23:59:59'unu da kapsar).
            if date_from is not None:
                stmt = stmt.where(
                    Review.review_date
                    >= datetime.combine(date_from, datetime.min.time(), tzinfo=UTC)
                )
            if date_to is not None:
                stmt = stmt.where(
                    Review.review_date <= datetime.combine(date_to, datetime.max.time(), tzinfo=UTC)
                )
            return stmt

        totals = (
            await self._session.execute(
                _scoped(
                    select(
                        func.count().label("cnt"),
                        func.count().filter(Review.sentiment_label == LABEL_NEGATIVE).label("neg"),
                    ).select_from(Review)
                )
            )
        ).one()
        total = int(totals.cnt or 0)
        negative = int(totals.neg or 0)
        if total == 0:
            return _BucketSample(total=0, negative=0, reviews=[])

        rows = (
            await self._session.execute(
                _scoped(
                    select(
                        Review.text,
                        Review.sentiment_label,
                    ).select_from(Review)
                )
                .order_by(
                    case((Review.sentiment_label == LABEL_NEGATIVE, 0), else_=1),
                    Review.review_date.desc(),
                )
                .limit(MAX_SAMPLE_REVIEWS)
            )
        ).all()
        reviews = [
            {
                "text": " ".join(r.text.split())[:_MAX_REVIEW_CHARS],
                "sentiment": r.sentiment_label,
            }
            for r in rows
        ]
        return _BucketSample(total=total, negative=negative, reviews=reviews)

    async def _perspective_label(self, perspective_code: str) -> str:
        if perspective_code == UNMATCHED_PERSPECTIVE_SENTINEL:
            return "Eşleşmeyen (alt kategori atanmamış)"
        label = (
            await self._session.execute(
                select(CategoryTaxonomy.label_tr)
                .where(CategoryTaxonomy.tenant_id == self._tenant_id)
                .where(CategoryTaxonomy.code == perspective_code)
                .limit(1)
            )
        ).scalar_one_or_none()
        return label or perspective_code

    async def _tenant_language(self) -> str:
        language = (
            await self._session.execute(select(Tenant.language).where(Tenant.id == self._tenant_id))
        ).scalar_one_or_none()
        return language or "tr"

    async def _tenant_terminology(self) -> list[dict[str, Any]] | None:
        return (
            await self._session.execute(
                select(Tenant.terminology).where(Tenant.id == self._tenant_id)
            )
        ).scalar_one_or_none()

    async def _tenant_context(self) -> dict[str, str | None]:
        """Kurum profili (sektör / büyüklük / iş tanımı) — user prompt'a
        KURUM BAĞLAMI bloğu olarak girer (2026-09-02, TASK B2:
        swot_service._render_context ile aynı industry_label/
        company_size_label deseni). Kurgu doldurulmamışsa (None) ilgili
        satır template'te hiç basılmaz — "Sektör: belirsiz" gibi boş
        gürültü yerine sessizce atlanır."""
        row = (
            await self._session.execute(
                select(
                    Tenant.industry,
                    Tenant.industry_other_text,
                    Tenant.company_size,
                    Tenant.business_description,
                ).where(Tenant.id == self._tenant_id)
            )
        ).one_or_none()
        if row is None:
            return {
                "industry_label": None,
                "company_size_label": None,
                "business_description": None,
            }
        industry, industry_other_text, company_size, business_description = row
        return {
            "industry_label": industry_label(industry, industry_other_text) if industry else None,
            "company_size_label": company_size_label(company_size) if company_size else None,
            "business_description": (business_description or "").strip() or None,
        }

    def _cache_key(
        self,
        primary_category: str,
        perspective_code: str,
        date_from: date | None,
        date_to: date | None,
    ) -> str:
        df = date_from.isoformat() if date_from else "all"
        dt = date_to.isoformat() if date_to else "all"
        return (
            f"{CACHE_KEY_PREFIX}:{self._tenant_id}:{primary_category}:{perspective_code}:{df}:{dt}"
        )

    async def _cache_get(self, key: str) -> dict[str, Any] | None:
        try:
            client = get_redis_client()
            raw = await client.get(key)
        except Exception as exc:
            _logger.warning("root-cause cache get failed (%s); falling through", exc)
            return None
        if raw is None:
            return None
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, TypeError, AttributeError) as exc:
            _logger.warning(
                "root-cause cache holds malformed payload at %s (%s); treating as miss",
                key,
                exc,
            )
            return None
        if not isinstance(data, dict):
            return None
        return data

    async def _cache_set(self, key: str, payload: dict[str, Any]) -> None:
        try:
            client = get_redis_client()
            await client.set(
                key,
                json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                ex=CACHE_TTL_SECONDS,
            )
        except Exception as exc:
            _logger.warning("root-cause cache set failed (%s); continuing", exc)


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------


def _validate_and_normalise(payload: dict[str, Any]) -> dict[str, Any]:
    """Savunma amaçlı doğrulama + normalizasyon.

    Zorunlu üst-düzey alanlar SERT: eksikse satır render edilemez.
    Madde sayısı / alıntı sayısı YUMUŞAK: sistem prompt'u sınırı
    söylüyor, burada sadece kırpıp uyarı logluyoruz — model bir kez
    fazla madde yazdı diye kullanıcıya 500 dönmek daha kötü
    (swot_service'teki aynı ayrım).
    """
    missing = [k for k in ROOT_CAUSE_RESPONSE_SCHEMA["required"] if k not in payload]
    if missing:
        raise RootCauseResponseInvalidError(
            f"root cause response missing required fields: {missing}"
        )
    raw_causes = payload.get("root_causes")
    if not isinstance(raw_causes, list) or not raw_causes:
        raise RootCauseResponseInvalidError("root cause response has no root_causes items")
    if len(raw_causes) > 5:
        _logger.warning("root cause response has %d items, trimming to 5", len(raw_causes))
        raw_causes = raw_causes[:5]

    causes: list[dict[str, Any]] = []
    placeholder_items = 0
    for item in raw_causes:
        if not isinstance(item, dict):
            continue
        if _is_placeholder(item.get("title")) or _is_placeholder(item.get("description")):
            placeholder_items += 1
            continue
        quotes = item.get("evidence_quotes")
        quotes = [str(q) for q in quotes][:3] if isinstance(quotes, list) else []
        share = item.get("share_estimate_pct")
        try:
            share_value = float(share) if share is not None else None
        except (TypeError, ValueError):
            share_value = None
        cause: dict[str, Any] = {
            "title": str(item.get("title", "")),
            "description": str(item.get("description", "")),
            "evidence_quotes": quotes,
            "affected_surface": str(item.get("affected_surface", "")),
            "suggested_action": str(item.get("suggested_action", "")),
            "share_estimate_pct": share_value,
            # Vitrin alanları (kapalı kart): model yazmadıysa title /
            # suggested_action'dan türetilir — kart asla uzun paragrafa
            # düşmesin.
            "headline": showcase_headline(item.get("headline"), item.get("title")),
            "action_short": showcase_action(item.get("action_short"), item.get("suggested_action")),
        }
        # 2026-09-02 (TASK B2) — expert_note opsiyonel: model uzman notunu
        # bu kök nedene uygulamadıysa (ya da uzman notu hiç verilmediyse)
        # alanı yazmaz; yer tutucu/boş gelirse anahtar tamamen DÜŞÜRÜLÜR
        # (None ile doldurmuyoruz — routes/tenant_insights.py yokluğunu
        # ``"expert_note" in cause`` ile ayırt eder).
        expert_note = item.get("expert_note")
        if isinstance(expert_note, str) and not _is_placeholder(expert_note):
            cause["expert_note"] = _shorten(expert_note, _EXPERT_NOTE_MAX)
        causes.append(cause)
    if not causes:
        if placeholder_items:
            raise RootCausePlaceholderError(
                f"root cause response is a placeholder skeleton ({placeholder_items} items)"
            )
        raise RootCauseResponseInvalidError("root cause response items were all unusable")
    summary = payload.get("summary", "")
    return {"summary": "" if _is_placeholder(summary) else str(summary), "root_causes": causes}


_SHOWCASE_HEADLINE_MAX = 60
_SHOWCASE_ACTION_MAX = 90
_EXPERT_NOTE_MAX = 200
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.;!?])\s+")


def _shorten(text: str, limit: int) -> str:
    """Kelime sınırında kırp; kırpıldıysa "…" ekle (kart tek satır)."""
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    cut = compact[:limit]
    space = cut.rfind(" ")
    if space > limit // 2:
        cut = cut[:space]
    return cut.rstrip(" ,;:-") + "…"


def showcase_headline(headline: object, title: object) -> str | None:
    """Kapalı kartın başlığı: modelin headline'ı, yoksa title'ın kısaltılmışı."""
    for candidate in (headline, title):
        if isinstance(candidate, str) and not _is_placeholder(candidate):
            return _shorten(candidate, _SHOWCASE_HEADLINE_MAX)
    return None


def showcase_action(action_short: object, suggested_action: object) -> str | None:
    """Kapalı kartın tek satır aksiyonu: modelin action_short'u, yoksa
    suggested_action'ın İLK cümlesi (GLM bu alanı çoğu zaman boş bırakıyor)."""
    if isinstance(action_short, str) and not _is_placeholder(action_short):
        return _shorten(action_short, _SHOWCASE_ACTION_MAX)
    if isinstance(suggested_action, str) and not _is_placeholder(suggested_action):
        first = _SENTENCE_SPLIT_RE.split(" ".join(suggested_action.split()), maxsplit=1)[0]
        return _shorten(first, _SHOWCASE_ACTION_MAX)
    return None


def _is_placeholder(value: object) -> bool:
    """ "..."/"…"/boş ya da <8 karakterlik metin: model içeriği yazmamış."""
    if not isinstance(value, str):
        return True
    stripped = value.strip().strip(".…").strip()
    return len(stripped) < 8


def _serialise(row: RootCauseAnalysis) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "primary_category_code": row.primary_category_code,
        "perspective_code": row.perspective_code,
        "date_from": row.date_from.isoformat() if row.date_from else None,
        "date_to": row.date_to.isoformat() if row.date_to else None,
        "review_count": row.review_count,
        "model_provider": row.model_provider,
        "model_name": row.model_name,
        "payload": row.payload,
        "created_at": row.created_at.isoformat(),
    }


__all__ = [
    "CACHE_KEY_PREFIX",
    "CACHE_TTL_SECONDS",
    "MAX_SAMPLE_REVIEWS",
    "MIN_REVIEWS",
    "CategoryPerspectivePick",
    "InvalidCategoryError",
    "NoCredentialsError",
    "NotEnoughReviewsError",
    "RootCauseResponseInvalidError",
    "RootCauseService",
    "RootCauseServiceError",
    "day_rounded_window",
    "latest_analysis_any_window",
    "pick_top_categories",
    "total_negative_count",
]
