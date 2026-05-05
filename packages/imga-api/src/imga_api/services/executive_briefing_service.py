"""Executive briefing generator.

Sprint 8.3.10. Produces a 1-page LLM-authored summary by:
  1. Computing window stats (current period + same-length prior period)
  2. Calling Gemini Flash with the executive_briefing_v1 prompt
  3. Persisting an ``executive_briefings`` row + caching for 12h

Failure surface mirrors SwotService:
  * NoCredentialsError — no active rows in tenant_llm_credentials
  * AllKeysExhaustedError — every key hit RateLimit / InvalidKey
  * BriefingResponseInvalidError — defence-in-depth schema check
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any
from uuid import UUID

from imga_core.llm import (
    AllKeysExhaustedError,
    GeminiKeyRotator,
    InvalidKeyError,
    LLMError,
)
from imga_core.llm.gemini import GeminiProvider
from imga_db.models import ExecutiveBriefing, Review, Tenant
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.cache.redis_client import get_redis_client
from imga_api.llm.prompts.executive_briefing_v1 import (
    EXECUTIVE_BRIEFING_RESPONSE_SCHEMA,
    EXECUTIVE_BRIEFING_SYSTEM_PROMPT,
    render_executive_briefing_user_prompt,
)
from imga_api.services.llm_credentials import (
    NoCredentialsError,
    load_active_gemini_keys,
    mark_keys_failed,
)
from imga_api.services.strategic_constants import (
    company_size_label,
    industry_label,
)

_logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 12 * 3600
DEFAULT_MODEL_NAME = "gemini-2.5-flash"


class BriefingServiceError(Exception):
    """Base for executive briefing failures."""


class BriefingResponseInvalidError(BriefingServiceError):
    """Defence-in-depth — the LLM response missed a required field."""


@dataclass(frozen=True)
class _PeriodStats:
    total_reviews: int
    nps_score: float | None
    avg_sentiment: float | None
    negative_share: float
    top_categories: list[dict[str, Any]]


_PERIOD_DAYS = {"week": 7, "month": 30, "quarter": 90}
_PERIOD_LABELS = {
    "week": "Hafta",
    "month": "Ay",
    "quarter": "Çeyrek",
}


class ExecutiveBriefingService:
    def __init__(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        user_id: UUID | None,
        *,
        provider: GeminiProvider | None = None,
    ) -> None:
        self._session = session
        self._tenant_id = tenant_id
        self._user_id = user_id
        self._provider = provider or _build_provider_without_key()

    async def generate(
        self,
        *,
        period: str,
        date_from: date | None = None,
        date_to: date | None = None,
        batch_id: UUID | None = None,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        if period not in _PERIOD_DAYS:
            raise ValueError(
                f"period must be one of {sorted(_PERIOD_DAYS)}"
            )

        # Resolve the date window. If the caller didn't pin one,
        # use the trailing N days ending today.
        if date_to is None:
            date_to = date.today()
        if date_from is None:
            date_from = date_to - timedelta(days=_PERIOD_DAYS[period])

        cache_key = self._cache_key(period, date_from, date_to, batch_id)
        if not force_refresh:
            cached = await self._cache_get(cache_key)
            if cached is not None:
                return cached

        # Stats — current + prior window (same length).
        window_days = (date_to - date_from).days or 1
        prior_to = date_from
        prior_from = prior_to - timedelta(days=window_days)
        current = await self._compute_stats(date_from, date_to, batch_id)
        previous = await self._compute_stats(prior_from, prior_to, batch_id)

        # Tenant context.
        tenant = await self._session.get(Tenant, self._tenant_id)
        industry = tenant.industry if tenant else None
        industry_other = tenant.industry_other_text if tenant else None
        company_size = tenant.company_size if tenant else None

        prompt_ctx: dict[str, Any] = {
            "industry_label": industry_label(industry, industry_other),
            "company_size_label": company_size_label(company_size),
            "period_label": _PERIOD_LABELS[period],
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "batch_label": str(batch_id) if batch_id else None,
            "current": {
                "total_reviews": current.total_reviews,
                "nps_score": current.nps_score,
                "avg_sentiment": current.avg_sentiment,
                "negative_share": current.negative_share,
                "top_categories": current.top_categories,
            },
            "previous": {
                "total_reviews": previous.total_reviews,
                "nps_score": previous.nps_score,
                "avg_sentiment": previous.avg_sentiment,
                "negative_share": previous.negative_share,
            },
        }

        # Credentials → rotator.
        keys = await load_active_gemini_keys(self._session, self._tenant_id)
        if not keys:
            raise NoCredentialsError(
                "Tenant has no active LLM API keys configured"
            )
        rotator = GeminiKeyRotator(keys)

        user_prompt = render_executive_briefing_user_prompt(prompt_ctx)
        failed_invalid_key_ids: list[UUID] = []

        async def _call(api_key: str) -> tuple[dict[str, Any], dict[str, int] | None]:
            try:
                return await self._provider.generate_executive_briefing(
                    api_key=api_key,
                    system_prompt=EXECUTIVE_BRIEFING_SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                    response_schema=EXECUTIVE_BRIEFING_RESPONSE_SCHEMA,
                )
            except InvalidKeyError:
                for k in keys:
                    if k.value == api_key:
                        failed_invalid_key_ids.append(UUID(k.id))
                        break
                raise

        start = time.monotonic()
        try:
            (response, token_usage), key_used = await rotator.call_with_rotation(_call)
        except AllKeysExhaustedError:
            await mark_keys_failed(self._session, failed_invalid_key_ids)
            raise
        except LLMError:
            raise

        duration_ms = int((time.monotonic() - start) * 1000)
        if failed_invalid_key_ids:
            await mark_keys_failed(self._session, failed_invalid_key_ids)

        self._validate_response(response)

        # Sprint 8.3.11 R2 — replace the LLM's kpi_changes with the
        # server-computed list. The LLM occasionally hallucinated
        # change_pct on previous=0 rows (Inf% / NaN); computing
        # locally + overriding gives us deterministic numbers and a
        # "yeni başlangıç" label for the new-period case the LLM
        # otherwise mishandled. Headline / insights / top_actions
        # from the LLM still pass through unchanged.
        response = dict(response)
        response["kpi_changes"] = _compute_kpi_changes(current, previous)

        report_dict = await self._persist(
            response=response,
            period=period,
            date_from=date_from,
            date_to=date_to,
            batch_id=batch_id,
            input_stats=prompt_ctx,
            duration_ms=duration_ms,
            token_usage=token_usage,
        )
        await self._cache_set(cache_key, report_dict)
        _logger.info(
            "executive briefing generated tenant=%s key_id=%s duration_ms=%d",
            self._tenant_id, key_used.id, duration_ms,
        )
        return report_dict

    async def _compute_stats(
        self,
        date_from: date,
        date_to: date,
        batch_id: UUID | None,
    ) -> _PeriodStats:
        # Aggregate stats over the window. Single SQL hit.
        stmt = select(
            func.count().label("cnt"),
            func.avg(Review.nps_score).label("nps_avg"),
            func.avg(Review.sentiment_score).label("sent_avg"),
            func.sum(
                case(
                    (Review.sentiment_label == "NEGATIF", 1),
                    else_=0,
                )
            ).label("neg_cnt"),
        ).where(
            Review.tenant_id == self._tenant_id,
            Review.deleted_at.is_(None),
            Review.created_at >= date_from,
            Review.created_at <= date_to,
        )
        if batch_id is not None:
            stmt = stmt.where(Review.batch_job_id == batch_id)
        agg = (await self._session.execute(stmt)).one()
        cnt = int(agg.cnt or 0)
        neg = int(agg.neg_cnt or 0)
        share = (neg / cnt) if cnt > 0 else 0.0

        # Top categories (limit 5).
        cat_stmt = (
            select(Review.primary_category, func.count().label("cnt"))
            .where(
                Review.tenant_id == self._tenant_id,
                Review.deleted_at.is_(None),
                Review.created_at >= date_from,
                Review.created_at <= date_to,
            )
            .group_by(Review.primary_category)
            .order_by(func.count().desc())
            .limit(5)
        )
        if batch_id is not None:
            cat_stmt = cat_stmt.where(Review.batch_job_id == batch_id)
        cat_rows = (await self._session.execute(cat_stmt)).all()
        top_categories = [
            {"label": r.primary_category, "count": int(r.cnt)}
            for r in cat_rows
        ]

        return _PeriodStats(
            total_reviews=cnt,
            nps_score=float(agg.nps_avg) if agg.nps_avg is not None else None,
            avg_sentiment=(
                float(agg.sent_avg) if agg.sent_avg is not None else None
            ),
            negative_share=share,
            top_categories=top_categories,
        )

    @staticmethod
    def _validate_response(payload: dict[str, Any]) -> None:
        required = EXECUTIVE_BRIEFING_RESPONSE_SCHEMA["required"]
        missing = [k for k in required if k not in payload]
        if missing:
            raise BriefingResponseInvalidError(
                f"executive briefing response missing required fields: {missing}"
            )

    async def _persist(
        self,
        *,
        response: dict[str, Any],
        period: str,
        date_from: date,
        date_to: date,
        batch_id: UUID | None,
        input_stats: dict[str, Any],
        duration_ms: int,
        token_usage: dict[str, int] | None,
    ) -> dict[str, Any]:
        row = ExecutiveBriefing(
            tenant_id=self._tenant_id,
            period=period,
            date_from=date_from,
            date_to=date_to,
            batch_id=batch_id,
            headline=str(response.get("headline", "")),
            kpi_changes=list(response.get("kpi_changes") or []),
            critical_insights=list(response.get("critical_insights") or []),
            top_actions=list(response.get("top_actions") or []),
            input_stats=input_stats,
            model_name=DEFAULT_MODEL_NAME,
            token_usage=token_usage,
            generation_duration_ms=duration_ms,
            created_by_user_id=self._user_id,
        )
        self._session.add(row)
        await self._session.flush()
        return {
            "id": str(row.id),
            "tenant_id": str(self._tenant_id),
            "period": period,
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "batch_id": str(batch_id) if batch_id else None,
            "headline": row.headline,
            "kpi_changes": list(row.kpi_changes),
            "critical_insights": list(row.critical_insights),
            "top_actions": list(row.top_actions),
            "model_name": row.model_name,
            "token_usage": dict(row.token_usage) if row.token_usage else None,
            "generation_duration_ms": duration_ms,
            "generated_at": row.created_at.isoformat(),
        }

    def _cache_key(
        self,
        period: str,
        date_from: date,
        date_to: date,
        batch_id: UUID | None,
    ) -> str:
        bid = str(batch_id) if batch_id else "none"
        return (
            f"briefing:{self._tenant_id}:{period}:"
            f"{date_from.isoformat()}:{date_to.isoformat()}:{bid}"
        )

    async def _cache_get(self, key: str) -> dict[str, Any] | None:
        try:
            client = get_redis_client()
            raw = await client.get(key)
        except Exception as exc:
            _logger.warning("briefing cache get failed (%s)", exc)
            return None
        if raw is None:
            return None
        try:
            data = json.loads(
                raw.decode("utf-8") if isinstance(raw, bytes) else raw
            )
            return data if isinstance(data, dict) else None
        except (ValueError, TypeError):
            return None

    async def _cache_set(self, key: str, payload: dict[str, Any]) -> None:
        try:
            client = get_redis_client()
            await client.set(
                key,
                json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                ex=CACHE_TTL_SECONDS,
            )
        except Exception as exc:
            _logger.warning("briefing cache set failed (%s)", exc)


def _build_provider_without_key() -> GeminiProvider:
    return GeminiProvider(api_key="x", model_name=DEFAULT_MODEL_NAME)


# Sprint 8.3.11 R2 — server-computed KPI deltas. The LLM occasionally
# hallucinated values for the previous=0 case (Inf% / NaN / fabricated
# numbers); computing here gives us deterministic numbers + a clear
# "yeni başlangıç" label that the response model + frontend can
# render without additional logic. The LLM's kpi_changes output is
# discarded in favour of this list.
_KPI_METRICS: tuple[tuple[str, str], ...] = (
    ("total_reviews", "Toplam Yorum"),
    ("nps_score", "NPS"),
    ("avg_sentiment", "Ortalama Duygu"),
    ("negative_share", "Negatif Yorum Oranı"),
)


def _compute_kpi_changes(
    current: _PeriodStats,
    previous: _PeriodStats,
) -> list[dict[str, Any]]:
    """Build the kpi_changes payload from raw period stats.

    For each metric in ``_KPI_METRICS``:
      * If both values are present and previous != 0 →
        ``change_pct = round((current - previous) / previous * 100, 1)``
        with direction inferred from the sign.
      * If previous is missing OR zero → ``change_pct = None`` plus a
        ``change_label = "yeni başlangıç"`` so the UI renders the
        no-comparison state correctly.
      * If both values are missing (None for nps_score on a no-NPS
        tenant) → omit the metric entirely.
    """
    out: list[dict[str, Any]] = []
    for key, label in _KPI_METRICS:
        cur_val = _attr(current, key)
        prev_val = _attr(previous, key)
        if cur_val is None and prev_val is None:
            continue
        # Coerce to float for the arithmetic; keep None for "no data".
        cur_f = float(cur_val) if cur_val is not None else None
        prev_f = float(prev_val) if prev_val is not None else None

        if prev_f is None or prev_f == 0:
            change_pct: float | None = None
            change_label: str | None = "yeni başlangıç"
            direction = "flat"
        else:
            current_anchored = cur_f if cur_f is not None else 0.0
            change_pct = round((current_anchored - prev_f) / prev_f * 100, 1)
            change_label = None
            if change_pct > 0:
                direction = "up"
            elif change_pct < 0:
                direction = "down"
            else:
                direction = "flat"

        out.append(
            {
                "metric": label,
                "current": _round_for_wire(cur_f) if cur_f is not None else 0.0,
                "previous": _round_for_wire(prev_f) if prev_f is not None else 0.0,
                "change_pct": change_pct,
                "change_label": change_label,
                "direction": direction,
            }
        )
    return out


def _attr(stats: _PeriodStats, key: str) -> Any:
    """Field accessor that maps wire keys (``total_reviews``,
    ``nps_score`` …) to the dataclass attribute."""
    return getattr(stats, key, None)


def _round_for_wire(value: float) -> float:
    """Round to 2 decimals so the JSON payload stays tidy in
    cache dumps and DB rows."""
    return round(value, 2)


__all__ = [
    "CACHE_TTL_SECONDS",
    "DEFAULT_MODEL_NAME",
    "BriefingResponseInvalidError",
    "BriefingServiceError",
    "ExecutiveBriefingService",
    "NoCredentialsError",
]
