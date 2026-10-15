"""Veri asistanı — kurum verisine dayalı soru-cevap (2026-10-15).

Akış: soru → kapsam (dönem + odak kategori/aşama/duygu) → SQL kanıt
paketi (sorulan dönem ve hemen önceki eşit dönem) → LLM (JSON şema) →
yanıt + kanıt. Rakamlar HER ZAMAN SQL'den gelir; model yalnız yorumlar.
LLM anahtarı yoksa ya da çağrı başarısızsa kural tabanlı özet üretilir
(``llm_used=False``), böylece asistan anahtarsız kurumda da çalışır.
Alıntılar KVKK maskesinden geçer ve kısaltılır.

Twitter kısıtı: gönderiler yazar kimliği taşımaz; kanıt paketi müşteri
değil yorum sayar. ``journey_stage`` (migration 0052) kanıt paketinde
"aşama" ekseni olarak yer alır.
"""

from __future__ import annotations

import logging
import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from imga_core.categories.taxonomy import DEFAULT_GLOBAL_CATEGORIES
from imga_core.config import LABEL_NEGATIVE, LABEL_POSITIVE
from imga_core.journey import JOURNEY_STAGES
from imga_core.llm import (
    AllKeysExhaustedError,
    GeminiKeyRotator,
    InvalidKeyError,
    LLMError,
)
from imga_core.text_utils import normalize_turkish
from imga_db.models import CategoryTaxonomy, Review, Tenant
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.llm.prompts.data_assistant_v1 import (
    DATA_ASSISTANT_RESPONSE_SCHEMA,
    DATA_ASSISTANT_SYSTEM_PROMPT,
    render_data_assistant_user_prompt,
)
from imga_api.services.category_codes import valid_primary_codes
from imga_api.services.company_intelligence import context_directive
from imga_api.services.llm_credentials import (
    load_active_llm_keys,
    mark_keys_failed,
    platform_fallback_selection,
)
from imga_api.services.llm_provider_factory import (
    StructuredProvider,
    build_structured_provider,
    resolve_model_name,
)
from imga_api.services.pii_mask import mask_pii
from imga_api.services.strategic_constants import language_directive, terminology_directive

_logger = logging.getLogger("imga-api.assistant")

MAX_QUESTION_LENGTH = 500
MAX_HISTORY_TURNS = 8
QUOTE_LIMIT = 8
QUOTE_MAX_CHARS = 240
DEFAULT_WINDOW_DAYS = 30
MAX_WINDOW_DAYS = 365
# Altındaki örneklemde model "neden" iddiası yerine "yetersiz veri" demeli.
MIN_FOCUS_SAMPLE = 5

_CATEGORY_LABELS: dict[str, str] = {c.code: c.name for c in DEFAULT_GLOBAL_CATEGORIES}

# Soru metnindeki eş anlamlılar → kategori kodu. Yalnız kurumun geçerli
# kod listesindeki kodlar uygulanır; özel kategoriler kod/etiket adıyla
# eşleşir (bkz. parse_question).
_CATEGORY_SYNONYMS: dict[str, tuple[str, ...]] = {
    "iade": ("iade", "geri odeme", "para iadesi", "iadeler"),
    "kargo": ("kargo", "teslimat", "kurye", "paket", "gonderi", "dagitim"),
    "faturalama": ("fatura", "odeme", "ucret", "fiyat", "tahsilat"),
    "teknik_destek": ("uygulama", "site", "giris", "cokuyor", "teknik", "hata veriyor"),
    "musteri_hizmetleri": ("cagri merkezi", "temsilci", "musteri hizmetleri", "destek hatti"),
    "urun_kalitesi": ("urun", "kalite", "bozuk", "hasarli", "kusurlu"),
    "siparis_sureci": ("siparis", "hazirlaniyor", "onay", "sepet"),
    "pazarlama": ("kampanya", "indirim", "reklam", "pazarlama"),
}

_STAGE_SYNONYMS: dict[str, tuple[str, ...]] = {
    "ayrilma": ("ayril", "rakibe", "birak", "vazgec", "iptal ed", "churn", "kayip"),
    "sadakat": ("sadakat", "tavsiye", "yenileme", "sadik"),
    "kesif": ("kesif", "yeni musteri", "ilk kez"),
    "degerlendirme": ("degerlendirme", "karsilastir", "satin alma oncesi"),
    "satin_alma": ("satin alma", "satin alirken", "odeme asamasi"),
    "teslimat": ("teslimat asamasi", "kurulum", "aktivasyon"),
    "kullanim": ("kullanim asamasi", "kullanirken"),
    "destek": ("destek asamasi", "destek surecinde"),
}

_NEGATIVE_HINTS = (
    "sikayet",
    "olumsuz",
    "sorun",
    "memnuniyetsiz",
    "kotu",
    "neden artti",
    "niye artti",
    "problem",
    "gecik",
)
_POSITIVE_HINTS = ("memnun", "olumlu", "tesekkur", "begen", "neden azaldi")

_STAGE_LABELS: dict[str, str] = {
    "kesif": "Keşif",
    "degerlendirme": "Değerlendirme",
    "satin_alma": "Satın alma",
    "teslimat": "Teslimat / Başlangıç",
    "kullanim": "Kullanım",
    "destek": "Destek",
    "sadakat": "Sadakat / Yenileme",
    "ayrilma": "Ayrılma riski",
}

_WORD_NUMBERS = {"bir": 1, "iki": 2, "uc": 3, "dort": 4, "alti": 6, "on iki": 12}


@dataclass(frozen=True, slots=True)
class QuestionScope:
    question: str
    date_from: date
    date_to: date
    prev_from: date
    prev_to: date
    window_days: int
    period_label: str
    focus_category: str | None = None
    focus_category_label: str | None = None
    focus_stage: str | None = None
    focus_sentiment: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "period_label": self.period_label,
            "current": {"from": self.date_from.isoformat(), "to": self.date_to.isoformat()},
            "previous": {"from": self.prev_from.isoformat(), "to": self.prev_to.isoformat()},
            "window_days": self.window_days,
            "focus_category": self.focus_category,
            "focus_category_label": self.focus_category_label,
            "focus_stage": self.focus_stage,
            "focus_stage_label": _STAGE_LABELS.get(self.focus_stage or ""),
            "focus_sentiment": self.focus_sentiment,
        }


@dataclass(slots=True)
class AssistantAnswer:
    answer: str
    highlights: list[str]
    follow_ups: list[str]
    data_gaps: list[str]
    scope: dict[str, Any]
    evidence: dict[str, Any]
    llm_used: bool
    model: str | None = None
    provider: str | None = None
    warnings: list[str] = field(default_factory=list)


_ASCII_FOLD = str.maketrans(
    {
        "ş": "s",
        "ı": "i",
        "ğ": "g",
        "ü": "u",
        "ö": "o",
        "ç": "c",
        "â": "a",
        "î": "i",
        "û": "u",
    }
)


def _fold(text: str) -> str:
    """Küçük harf + Türkçe harfleri ASCII'ye katlar; eş anlamlı listeleri
    bu biçimde yazıldı. ``normalize_turkish`` yalnız küçültür (İ→i, I→ı),
    katlamayı burada tamamlıyoruz; kalan birleşik işaretler (İ'nin
    noktası gibi) NFKD ile atılır."""
    lowered = normalize_turkish(text).translate(_ASCII_FOLD)
    stripped = "".join(
        ch for ch in unicodedata.normalize("NFKD", lowered) if not unicodedata.combining(ch)
    )
    return " ".join(stripped.split())


def _window_from_question(folded: str, today: date) -> tuple[int, str] | None:
    match = re.search(r"son (\d{1,3}|bir|iki|uc|dort|alti) (gun|hafta|ay)", folded)
    if match:
        raw, unit = match.group(1), match.group(2)
        count = int(raw) if raw.isdigit() else _WORD_NUMBERS.get(raw, 1)
        days = {"gun": 1, "hafta": 7, "ay": 30}[unit] * count
        label = f"Son {count} {'gün' if unit == 'gun' else 'hafta' if unit == 'hafta' else 'ay'}"
        return max(1, min(days, MAX_WINDOW_DAYS)), label
    if "son ay" in folded or "gecen ay" in folded or "gectigimiz ay" in folded:
        return 30, "Son 1 ay"
    if "son hafta" in folded or "gecen hafta" in folded or "bu hafta" in folded:
        return 7, "Son 1 hafta"
    if "son ceyrek" in folded or "bu ceyrek" in folded:
        return 90, "Son 3 ay"
    if "bu ay" in folded:
        days = max(1, today.day)
        return days, "Bu ay"
    if "bu yil" in folded or "son bir yil" in folded or "son yil" in folded:
        return MAX_WINDOW_DAYS, "Son 1 yıl"
    return None


def parse_question(
    question: str,
    *,
    today: date,
    valid_codes: set[str],
    custom_labels: dict[str, str] | None = None,
) -> QuestionScope:
    """Soru metninden dönem ve odak çıkarır. Saf fonksiyon, I/O yok."""
    folded = _fold(question)
    window = _window_from_question(folded, today)
    window_days, label = window if window else (DEFAULT_WINDOW_DAYS, "Son 30 gün")
    date_to = today
    date_from = today - timedelta(days=window_days - 1)
    prev_to = date_from - timedelta(days=1)
    prev_from = prev_to - timedelta(days=window_days - 1)

    labels = dict(_CATEGORY_LABELS)
    labels.update(custom_labels or {})
    focus_category: str | None = None
    for code in sorted(valid_codes):
        if code == "belirsiz":
            continue
        candidates = [code.replace("_", " "), labels.get(code, "")]
        candidates.extend(_CATEGORY_SYNONYMS.get(code, ()))
        if any(c and _fold(c) in folded for c in candidates):
            focus_category = code
            break

    focus_stage: str | None = None
    for stage in JOURNEY_STAGES:
        if any(_fold(s) in folded for s in _STAGE_SYNONYMS.get(stage, ())):
            focus_stage = stage
            break

    focus_sentiment: str | None = None
    if any(h in folded for h in _POSITIVE_HINTS):
        focus_sentiment = LABEL_POSITIVE
    if any(h in folded for h in _NEGATIVE_HINTS):
        focus_sentiment = LABEL_NEGATIVE

    return QuestionScope(
        question=question.strip(),
        date_from=date_from,
        date_to=date_to,
        prev_from=prev_from,
        prev_to=prev_to,
        window_days=window_days,
        period_label=label,
        focus_category=focus_category,
        focus_category_label=labels.get(focus_category, focus_category) if focus_category else None,
        focus_stage=focus_stage,
        focus_sentiment=focus_sentiment,
    )


def _pct_change(current: int, previous: int) -> float | None:
    if previous <= 0:
        return None
    return round((current - previous) / previous * 100, 1)


def _share(part: int, total: int) -> float:
    return round(part / total * 100, 1) if total else 0.0


def _bounds(day_from: date, day_to: date) -> tuple[datetime, datetime]:
    start = datetime(day_from.year, day_from.month, day_from.day, tzinfo=UTC)
    end = datetime(day_to.year, day_to.month, day_to.day, tzinfo=UTC) + timedelta(days=1)
    return start, end


class DataAssistantService:
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
        self._provider = provider

    # ------------------------------------------------------------ evidence

    def _base(self, day_from: date, day_to: date) -> list[Any]:
        start, end = _bounds(day_from, day_to)
        return [
            Review.tenant_id == self._tenant_id,
            Review.deleted_at.is_(None),
            Review.quality_flag.is_(None),
            Review.review_date >= start,
            Review.review_date < end,
        ]

    def _focus(self, scope: QuestionScope) -> list[Any]:
        conditions: list[Any] = []
        if scope.focus_category:
            conditions.append(Review.primary_category == scope.focus_category)
        if scope.focus_stage:
            conditions.append(Review.journey_stage == scope.focus_stage)
        return conditions

    async def _window_stats(
        self, scope: QuestionScope, day_from: date, day_to: date
    ) -> dict[str, Any]:
        base = self._base(day_from, day_to)
        negatif = func.count().filter(Review.sentiment_label == LABEL_NEGATIVE)
        sentiment_rows = (
            await self._session.execute(
                select(Review.sentiment_label, func.count())
                .where(*base)
                .group_by(Review.sentiment_label)
            )
        ).all()
        sentiment = {str(label): int(count) for label, count in sentiment_rows}
        total = sum(sentiment.values())

        category_rows = (
            await self._session.execute(
                select(Review.primary_category, func.count(), negatif)
                .where(*base)
                .group_by(Review.primary_category)
                .order_by(func.count().desc())
            )
        ).all()
        categories = {
            str(code): {
                "total": int(cnt),
                "negatif": int(neg),
                "label": _CATEGORY_LABELS.get(str(code), str(code)),
            }
            for code, cnt, neg in category_rows
        }

        stage_rows = (
            await self._session.execute(
                select(Review.journey_stage, func.count(), negatif)
                .where(*base)
                .group_by(Review.journey_stage)
            )
        ).all()
        stages = {
            (str(stage) if stage else "atanmamis"): {"total": int(cnt), "negatif": int(neg)}
            for stage, cnt, neg in stage_rows
        }

        content_rows = (
            await self._session.execute(
                select(Review.content_type, func.count())
                .where(*base, Review.content_type.is_not(None))
                .group_by(Review.content_type)
            )
        ).all()
        content_types = {str(ctype): int(cnt) for ctype, cnt in content_rows}

        focus: dict[str, Any] | None = None
        focus_conditions = self._focus(scope)
        if focus_conditions:
            focus_total, focus_neg, focus_tickets = (
                await self._session.execute(
                    select(
                        func.count(),
                        negatif,
                        func.count().filter(Review.ticket_id.is_not(None)),
                    ).where(*base, *focus_conditions)
                )
            ).one()
            perspective_rows = (
                await self._session.execute(
                    select(Review.company_perspective_code, func.count())
                    .where(*base, *focus_conditions, Review.company_perspective_code.is_not(None))
                    .group_by(Review.company_perspective_code)
                    .order_by(func.count().desc())
                    .limit(8)
                )
            ).all()
            dimension_rows: dict[str, list[dict[str, Any]]] = {}
            for name, column in (
                ("channel", Review.channel),
                ("business_segment", Review.business_segment),
                ("source", Review.source),
            ):
                rows = (
                    await self._session.execute(
                        select(func.lower(func.trim(column)), func.count())
                        .where(*base, *focus_conditions, column.is_not(None))
                        .group_by(func.lower(func.trim(column)))
                        .order_by(func.count().desc())
                        .limit(5)
                    )
                ).all()
                if rows:
                    dimension_rows[name] = [{"value": str(v), "total": int(c)} for v, c in rows]
            stage_in_focus = (
                await self._session.execute(
                    select(Review.journey_stage, func.count())
                    .where(*base, *focus_conditions)
                    .group_by(Review.journey_stage)
                )
            ).all()
            focus = {
                "total": int(focus_total or 0),
                "negatif": int(focus_neg or 0),
                "ticket_linked": int(focus_tickets or 0),
                "share_of_all": _share(int(focus_total or 0), total),
                "perspectives": [
                    {"code": str(code), "total": int(cnt)} for code, cnt in perspective_rows
                ],
                "dimensions": dimension_rows,
                "stages": {
                    (str(stage) if stage else "atanmamis"): int(cnt)
                    for stage, cnt in stage_in_focus
                },
            }

        return {
            "from": day_from.isoformat(),
            "to": day_to.isoformat(),
            "total": total,
            "sentiment": sentiment,
            "negative_share": _share(sentiment.get(LABEL_NEGATIVE, 0), total),
            "categories": categories,
            "stages": stages,
            "content_types": content_types,
            "focus": focus,
        }

    async def _quotes(
        self, scope: QuestionScope, day_from: date, day_to: date, limit: int
    ) -> list[dict[str, Any]]:
        conditions = self._base(day_from, day_to) + self._focus(scope)
        if scope.focus_sentiment == LABEL_POSITIVE:
            conditions.append(Review.sentiment_label == LABEL_POSITIVE)
        else:
            conditions.append(Review.sentiment_label == LABEL_NEGATIVE)
        rows = (
            await self._session.execute(
                select(
                    Review.id,
                    Review.text,
                    Review.review_date,
                    Review.source,
                    Review.primary_category,
                    Review.company_perspective_code,
                    Review.journey_stage,
                    Review.sentiment_label,
                )
                .where(*conditions)
                .order_by(Review.review_date.desc())
                .limit(limit)
            )
        ).all()
        quotes: list[dict[str, Any]] = []
        for row in rows:
            text = mask_pii(" ".join(str(row.text).split()))
            if len(text) > QUOTE_MAX_CHARS:
                text = text[: QUOTE_MAX_CHARS - 1] + "…"
            quotes.append(
                {
                    "review_id": str(row.id),
                    "text": text,
                    "date": row.review_date.date().isoformat(),
                    "source": row.source,
                    "category": _CATEGORY_LABELS.get(
                        str(row.primary_category), str(row.primary_category)
                    ),
                    "perspective_code": row.company_perspective_code,
                    "stage": row.journey_stage,
                    "sentiment": row.sentiment_label,
                }
            )
        return quotes

    async def _perspective_labels(self, codes: list[str]) -> dict[str, str]:
        if not codes:
            return {}
        rows = (
            await self._session.execute(
                select(CategoryTaxonomy.code, CategoryTaxonomy.label_tr).where(
                    CategoryTaxonomy.tenant_id == self._tenant_id,
                    CategoryTaxonomy.code.in_(codes),
                )
            )
        ).all()
        return {str(code): str(label) for code, label in rows}

    async def collect_evidence(self, scope: QuestionScope) -> dict[str, Any]:
        current = await self._window_stats(scope, scope.date_from, scope.date_to)
        previous = await self._window_stats(scope, scope.prev_from, scope.prev_to)
        quotes = await self._quotes(scope, scope.date_from, scope.date_to, QUOTE_LIMIT)
        for index, quote in enumerate(quotes, start=1):
            quote["ref"] = index

        codes: list[str] = []
        for window in (current, previous):
            if window["focus"]:
                codes.extend(p["code"] for p in window["focus"]["perspectives"])
        codes.extend(str(q["perspective_code"]) for q in quotes if q.get("perspective_code"))
        labels = await self._perspective_labels(sorted(set(codes)))
        for window in (current, previous):
            if window["focus"]:
                for item in window["focus"]["perspectives"]:
                    item["label"] = labels.get(item["code"], item["code"])
        for quote in quotes:
            code = quote.get("perspective_code")
            quote["perspective_label"] = labels.get(str(code), code) if code else None

        all_codes = set(current["categories"]) | set(previous["categories"])
        movers: list[dict[str, Any]] = []
        for code in all_codes:
            cur = current["categories"].get(code, {"total": 0, "negatif": 0})
            prev = previous["categories"].get(code, {"total": 0, "negatif": 0})
            movers.append(
                {
                    "code": code,
                    "label": _CATEGORY_LABELS.get(code, code),
                    "current": cur["total"],
                    "previous": prev["total"],
                    "diff": cur["total"] - prev["total"],
                    "pct_change": _pct_change(cur["total"], prev["total"]),
                    "current_negatif": cur["negatif"],
                    "previous_negatif": prev["negatif"],
                }
            )
        movers.sort(key=lambda m: (-m["diff"], m["code"]))

        focus_delta: dict[str, Any] | None = None
        if current["focus"] is not None and previous["focus"] is not None:
            focus_delta = {
                "total_diff": current["focus"]["total"] - previous["focus"]["total"],
                "total_pct_change": _pct_change(
                    current["focus"]["total"], previous["focus"]["total"]
                ),
                "negatif_diff": current["focus"]["negatif"] - previous["focus"]["negatif"],
                "negatif_pct_change": _pct_change(
                    current["focus"]["negatif"], previous["focus"]["negatif"]
                ),
                "share_diff_points": round(
                    current["focus"]["share_of_all"] - previous["focus"]["share_of_all"], 1
                ),
                "sample_status": "sufficient"
                if current["focus"]["total"] >= MIN_FOCUS_SAMPLE
                else "insufficient",
            }

        stage_delta = {
            stage: {
                "current": current["stages"].get(stage, {"total": 0})["total"],
                "previous": previous["stages"].get(stage, {"total": 0})["total"],
            }
            for stage in (*JOURNEY_STAGES, "atanmamis")
            if stage in current["stages"] or stage in previous["stages"]
        }

        return {
            "current": current,
            "previous": previous,
            "overall_delta": {
                "total_diff": current["total"] - previous["total"],
                "total_pct_change": _pct_change(current["total"], previous["total"]),
                "negative_share_diff_points": round(
                    current["negative_share"] - previous["negative_share"], 1
                ),
            },
            "focus_delta": focus_delta,
            "category_movers": movers[:6],
            "category_fallers": sorted(movers, key=lambda m: (m["diff"], m["code"]))[:3],
            "stage_delta": stage_delta,
            "quotes": quotes,
            "data_quality": {
                "excludes_flagged_rows": True,
                "stage_unassigned_current": current["stages"].get("atanmamis", {"total": 0})[
                    "total"
                ],
            },
        }

    # ---------------------------------------------------------- fallback

    @staticmethod
    def rule_based_answer(scope: QuestionScope, evidence: dict[str, Any]) -> AssistantAnswer:
        cur = evidence["current"]
        prev = evidence["previous"]
        parts: list[str] = []
        highlights: list[str] = []
        gaps: list[str] = []
        if cur["total"] == 0:
            parts.append(
                f"{scope.period_label} içinde değerlendirilebilir yorum yok "
                f"({scope.date_from.isoformat()} – {scope.date_to.isoformat()})."
            )
            gaps.append("Sorulan dönemde veri yok.")
            return AssistantAnswer(
                answer=" ".join(parts),
                highlights=highlights,
                follow_ups=["Son 3 ayda hangi konular öne çıktı?"],
                data_gaps=gaps,
                scope=scope.as_dict(),
                evidence=evidence,
                llm_used=False,
            )
        focus_label = scope.focus_category_label or (
            _STAGE_LABELS.get(scope.focus_stage or "") if scope.focus_stage else None
        )
        if cur["focus"] is not None and focus_label:
            f_cur, f_prev = cur["focus"], prev["focus"]
            pct = evidence["focus_delta"]["total_pct_change"] if evidence["focus_delta"] else None
            trend = (
                "değişmedi"
                if f_cur["total"] == f_prev["total"]
                else ("arttı" if f_cur["total"] > f_prev["total"] else "azaldı")
            )
            pct_text = f" (%{abs(pct):.0f})" if pct is not None else ""
            parts.append(
                f"{scope.period_label}: {focus_label} konusunda {f_cur['total']} yorum var; "
                f"önceki dönemde {f_prev['total']} idi, yani {trend}{pct_text}. "
                f"Bu yorumların {f_cur['negatif']} tanesi olumsuz ve toplam yorumların %{f_cur['share_of_all']}'i."
            )
            if f_cur["perspectives"]:
                top = ", ".join(
                    f"{p.get('label', p['code'])} ({p['total']})" for p in f_cur["perspectives"][:3]
                )
                parts.append(f"En sık alt konular: {top}.")
                highlights.append(f"Alt konular: {top}")
            if f_cur["total"] < MIN_FOCUS_SAMPLE:
                gaps.append(
                    f"Odak konuda yalnız {f_cur['total']} yorum var; neden çıkarımı için örneklem küçük."
                )
        else:
            delta = evidence["overall_delta"]
            pct = delta["total_pct_change"]
            pct_text = f" (%{abs(pct):.0f})" if pct is not None else ""
            parts.append(
                f"{scope.period_label}: {cur['total']} yorum, önceki dönemde {prev['total']}"
                f"{pct_text}. Olumsuz payı %{cur['negative_share']} "
                f"(önceki dönem %{prev['negative_share']})."
            )
        movers = [m for m in evidence["category_movers"] if m["diff"] > 0][:3]
        if movers:
            text = ", ".join(f"{m['label']} (+{m['diff']})" for m in movers)
            parts.append(f"En çok artan konular: {text}.")
            highlights.append(f"Artan konular: {text}")
        risky = evidence["stage_delta"].get("ayrilma")
        if risky and risky["current"] > 0:
            highlights.append(
                f"Ayrılma riski aşamasında {risky['current']} yorum (önceki dönem {risky['previous']})."
            )
        quotes = evidence["quotes"][:3]
        if quotes:
            parts.append(
                "Örnek ifadeler: " + " ".join(f'[#{q["ref"]}] "{q["text"][:120]}"' for q in quotes)
            )
        if evidence["data_quality"]["stage_unassigned_current"] > 0:
            gaps.append(
                f"{evidence['data_quality']['stage_unassigned_current']} yorumda yolculuk aşaması atanmamış."
            )
        gaps.append(
            "Yapay zekâ yorumu yok: kurum için LLM anahtarı tanımlı değil ya da çağrı başarısız oldu."
        )
        follow_ups = [
            f"{focus_label or 'Bu konu'} için en sık alt konular neler?"
            if focus_label
            else "Son 30 günde en çok artan konu hangisi?",
            "Ayrılma riski ifade eden yorumlar hangi kanaldan geliyor?",
            "Önceki döneme göre olumsuz payı neden değişti?",
        ]
        return AssistantAnswer(
            answer=" ".join(parts),
            highlights=highlights[:4],
            follow_ups=follow_ups[:3],
            data_gaps=gaps,
            scope=scope.as_dict(),
            evidence=evidence,
            llm_used=False,
        )

    # --------------------------------------------------------------- ask

    async def ask(
        self,
        question: str,
        *,
        history: list[dict[str, str]] | None = None,
    ) -> AssistantAnswer:
        question = question.strip()
        if not question:
            raise ValueError("Soru boş olamaz.")
        if len(question) > MAX_QUESTION_LENGTH:
            raise ValueError(f"Soru en çok {MAX_QUESTION_LENGTH} karakter olabilir.")
        valid_codes = await valid_primary_codes(self._session, self._tenant_id)
        scope = parse_question(question, today=datetime.now(UTC).date(), valid_codes=valid_codes)
        evidence = await self.collect_evidence(scope)
        fallback = self.rule_based_answer(scope, evidence)

        key_selection = await load_active_llm_keys(self._session, self._tenant_id)
        if key_selection is None:
            key_selection = platform_fallback_selection()
        if key_selection is None or not key_selection.keys:
            return fallback

        provider_name = key_selection.provider
        model_name = resolve_model_name(provider_name, key_selection.model)
        provider = self._provider or build_structured_provider(provider_name)
        keys = key_selection.keys
        rotator = GeminiKeyRotator(keys)

        tenant = await self._session.get(Tenant, self._tenant_id)
        settings = tenant.settings if tenant else None
        language = str(
            (settings or {}).get("language") or getattr(tenant, "language", "tr") or "tr"
        )
        terminology = getattr(tenant, "terminology", None)
        from imga_api.services.prompt_override import select_prompt

        ctx: dict[str, Any] = {
            "question": question,
            "history": (history or [])[-MAX_HISTORY_TURNS:],
            "scope": scope.as_dict(),
            "evidence": evidence,
        }
        selection = await select_prompt(
            self._session,
            tenant_id=self._tenant_id,
            template_key="data_assistant",
            variables=ctx,
            default_system_prompt=DATA_ASSISTANT_SYSTEM_PROMPT,
            default_user_prompt=lambda: render_data_assistant_user_prompt(ctx),
        )
        system_prompt = (
            selection.system_prompt
            + language_directive(language)
            + terminology_directive(terminology if isinstance(terminology, list) else None)
            + context_directive(settings)
        )
        user_prompt = selection.user_prompt
        failed_invalid_key_ids: list[UUID] = []

        async def _call(api_key: str) -> tuple[dict[str, Any], dict[str, int] | None]:
            try:
                return await provider.generate_assistant_answer(
                    api_key=api_key,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    response_schema=DATA_ASSISTANT_RESPONSE_SCHEMA,
                    model_name=model_name,
                )
            except InvalidKeyError:
                for k in keys:
                    if k.value == api_key:
                        failed_invalid_key_ids.append(UUID(k.id))
                        break
                raise

        from imga_api.services.llm_audit_service import (
            CALL_TYPE_ASSISTANT,
            LLMCallAuditor,
            LLMCallContext,
        )

        audit_ctx = LLMCallContext(
            tenant_id=self._tenant_id,
            call_type=CALL_TYPE_ASSISTANT,
            model_name=model_name,
            model_provider=provider_name,
            prompt_template_key="data_assistant",
            prompt_template_version=selection.version,
            actor_user_id=self._user_id,
            related_entity_type="data_assistant",
        )
        started = time.monotonic()
        auditor = LLMCallAuditor(self._session, audit_ctx, prompt=user_prompt)
        try:
            async with auditor:
                try:
                    (response, usage), _key_used = await rotator.call_with_rotation(_call)
                except AllKeysExhaustedError as exc:
                    auditor.record_failure(
                        error_type="all_keys_exhausted",
                        error_message=str(exc.__cause__ or exc)[:1024],
                    )
                    raise
                except LLMError as exc:
                    auditor.record_failure(error_type="api_error", error_message=str(exc)[:1024])
                    raise
                except Exception as exc:
                    auditor.record_failure(
                        error_type="other", error_message=f"{type(exc).__name__}: {exc}"[:1024]
                    )
                    raise
                auditor.record_success(
                    input_tokens=(usage.get("input") if usage else None),
                    output_tokens=(usage.get("output") if usage else None),
                )
        except AllKeysExhaustedError:
            await mark_keys_failed(self._session, failed_invalid_key_ids)
            _logger.warning("assistant: all keys exhausted tenant=%s", self._tenant_id)
            fallback.warnings.append("llm_unavailable")
            return fallback
        except Exception as exc:
            _logger.warning("assistant: llm call failed tenant=%s: %s", self._tenant_id, exc)
            fallback.warnings.append("llm_failed")
            return fallback

        _logger.info(
            "assistant: answered tenant=%s model=%s in %dms",
            self._tenant_id,
            model_name,
            int((time.monotonic() - started) * 1000),
        )
        answer_text = str(response.get("answer") or "").strip()
        if not answer_text:
            fallback.warnings.append("llm_empty")
            return fallback

        def _strings(key: str, limit: int) -> list[str]:
            raw = response.get(key)
            if not isinstance(raw, list):
                return []
            return [str(item).strip() for item in raw if str(item).strip()][:limit]

        return AssistantAnswer(
            answer=answer_text,
            highlights=_strings("highlights", 4),
            follow_ups=_strings("follow_ups", 3),
            data_gaps=_strings("data_gaps", 4),
            scope=scope.as_dict(),
            evidence=evidence,
            llm_used=True,
            model=model_name,
            provider=provider_name,
        )

    async def suggestions(self) -> list[str]:
        """Veriye göre önerilen sorular: en çok artan konu + sabit kalıplar."""
        valid_codes = await valid_primary_codes(self._session, self._tenant_id)
        scope = parse_question(
            "son 30 gün", today=datetime.now(UTC).date(), valid_codes=valid_codes
        )
        evidence = await self.collect_evidence(scope)
        items: list[str] = []
        movers = [m for m in evidence["category_movers"] if m["diff"] > 0]
        if movers:
            label = movers[0]["label"].replace("İ", "i").replace("I", "ı").lower()
            items.append(f"Son 1 ayda {label} şikayetleri neden arttı?")
        risky = evidence["stage_delta"].get("ayrilma")
        if risky and risky["current"] > 0:
            items.append("Ayrılma riski ifade eden müşteriler ne söylüyor?")
        items.extend(
            [
                "Son 1 ayda iadeler neden arttı?",
                "Son 3 ayda olumsuz yorumların payı nasıl değişti?",
                "Kargo şikayetlerinde en sık alt konu ne?",
                "Hangi kanaldan gelen yorumlar daha olumsuz?",
            ]
        )
        seen: set[str] = set()
        unique: list[str] = []
        for item in items:
            if item not in seen:
                seen.add(item)
                unique.append(item)
        return unique[:6]


__all__ = [
    "AssistantAnswer",
    "DataAssistantService",
    "QuestionScope",
    "parse_question",
]
