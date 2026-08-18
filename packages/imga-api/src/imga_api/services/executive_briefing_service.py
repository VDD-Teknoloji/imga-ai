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
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from imga_core.categories.taxonomy import DEFAULT_GLOBAL_CATEGORIES
from imga_core.llm import (
    AllKeysExhaustedError,
    GeminiKeyRotator,
    InvalidKeyError,
    LLMError,
)
from imga_db.models import ExecutiveBriefing, Review, Tenant
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.cache.redis_client import get_redis_client
from imga_api.llm.prompts.executive_briefing_v1 import (
    EXECUTIVE_BRIEFING_RESPONSE_SCHEMA,
    EXECUTIVE_BRIEFING_SYSTEM_PROMPT,
    render_executive_briefing_user_prompt,
)
from imga_api.services.date_bounds import day_ceil, day_floor
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
    terminology_directive,
)

_logger = logging.getLogger(__name__)

# root_cause_service ile ayni eslem — ham kategori kodu ("belirsiz",
# eski BERT kodlari) LLM prompt'una sizip brifingde kod adiyla
# alintilaniyordu.
_CATEGORY_LABELS: dict[str, str] = {
    c.code: c.name for c in DEFAULT_GLOBAL_CATEGORIES
}

CACHE_TTL_SECONDS = 12 * 3600
# Sprint 9.5.4 — Gemini 3 ailesine cutover. Recent history:
#
#   * 9.5 A3 + 9.5.1 A3.1: tried gemini-2.5-pro end-to-end. Hit 6/6
#     504 DEADLINE_EXCEEDED on briefing payloads in prod (2026-05-12).
#     Server-agent logs showed gemini-2.5-flash also ~22% 504 on
#     the same payload — the 2.5 family doesn't fit briefing's
#     payload size inside Google's 30s infra SLA. Tier 2 wouldn't
#     help; this is a compute-pool latency issue, not a quota issue.
#
#   * 9.5.2: fell back to gemini-2.0-flash. Failed differently —
#     404 NOT_FOUND with the message "no longer available to new
#     users". Google docs confirm 2.0-flash is closed to new
#     accounts and sunsets entirely 2026-06-01. We're a new-tier
#     account so the rollout doesn't apply to us yet but the API
#     surface already blocks us.
#
# 9.5.4 hypothesis: gemini-3-flash-preview lives on a different
# compute pool with a different SLA pattern. Experimental. If it
# also 504s, Sprint 9.5.5 swaps to gemini-3.1-flash-lite. If it
# 404s, the model-name string needs verification against current
# Google docs (the "-preview" suffix is moving target territory).
DEFAULT_MODEL_NAME = "gemini-3-flash-preview"


class BriefingServiceError(Exception):
    """Base for executive briefing failures."""


class BriefingResponseInvalidError(BriefingServiceError):
    """Defence-in-depth — the LLM response missed a required field."""


@dataclass(frozen=True)
class _PeriodStats:
    total_reviews: int
    # Sprint 9.0.5-B E — ``nps_score`` is now the canonical NPS in
    # the -100..100 range (AnalyticsService.compute_nps_summary
    # output), NOT the raw 0-10 average that the previous
    # implementation produced. The new ``nps_coverage_percent`` +
    # ``nps_bearing_count`` fields surface the denominator so the
    # prompt can say "%82 of reviews carried an NPS this period"
    # instead of pretending every row had a score. Both default to
    # 0.0 / 0 so the kpi_compute unit tests (and any other in-
    # process construction site) don't have to thread the new
    # fields through — production callers always set them via
    # ``_compute_stats``.
    nps_score: float | None
    avg_sentiment: float | None
    negative_share: float
    top_categories: list[dict[str, Any]]
    nps_coverage_percent: float = 0.0
    nps_bearing_count: int = 0


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
        provider: StructuredProvider | None = None,
    ) -> None:
        self._session = session
        self._tenant_id = tenant_id
        self._user_id = user_id
        # None -> generate() kurar (saglayici tenant kimligine bagli).
        self._provider = provider

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
            date_to = datetime.now(UTC).date()
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

        # Sprint 9.2 B — pull active KPI goals into the prompt context
        # so the LLM can frame the headline as "NPS 65 (aylık hedef
        # 70, %92.8 achievement)" instead of just "NPS 65". Best-
        # effort: the executive briefing path is the goal data's
        # *consumer*, not its source — if the goal table query fails
        # or the tenant has no goals, the briefing still ships, just
        # without the comparison framing.
        kpi_goal_context = await self._collect_kpi_goal_context(
            current_nps=current.nps_score,
            current_total=current.total_reviews,
        )

        # Sprint 9.2 C — pull (or compute) today's executive snapshot
        # so the prompt can reference it ("Aylık snapshot 2026-05-14:
        # NPS 65, ..."). The snapshot service handles the cache hit
        # vs cold-compute; we fall through silently if it errors so a
        # cache infra hiccup doesn't block the briefing.
        snapshot_payload = await self._collect_snapshot_context(period)

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
            "kpi_goals": kpi_goal_context,
            "executive_snapshot": snapshot_payload,
        }

        # Credentials → rotator. Kazanan saglayici + model kurum
        # kimlik kayitlarindan gelir (OpenRouter entegrasyonu).
        key_selection = await load_active_llm_keys(
            self._session, self._tenant_id
        )
        if key_selection is None:
            raise NoCredentialsError(
                "Tenant has no active LLM API keys configured"
            )
        keys = key_selection.keys
        rotator = GeminiKeyRotator(keys)
        provider_name = key_selection.provider
        model_name = resolve_model_name(provider_name, key_selection.model)
        provider = self._provider or build_structured_provider(provider_name)

        from imga_api.services.prompt_override import select_prompt

        selection = await select_prompt(
            self._session,
            tenant_id=self._tenant_id,
            template_key="briefing",
            variables=prompt_ctx,
            default_system_prompt=EXECUTIVE_BRIEFING_SYSTEM_PROMPT,
            default_user_prompt=lambda: render_executive_briefing_user_prompt(
                prompt_ctx
            ),
        )
        user_prompt = selection.user_prompt
        # Sprint 12 i18n — kurum dili 'en' ise İngilizce çıktı yönergesi.
        # 2026-08-18 (WS1) — terim sözlüğü yönergesi aynı sona eklenir.
        system_prompt = (
            selection.system_prompt
            + language_directive(getattr(tenant, "language", "tr"))
            + terminology_directive(getattr(tenant, "terminology", None))
        )
        failed_invalid_key_ids: list[UUID] = []

        async def _call(api_key: str) -> tuple[dict[str, Any], dict[str, int] | None]:
            try:
                return await provider.generate_executive_briefing(
                    api_key=api_key,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    response_schema=EXECUTIVE_BRIEFING_RESPONSE_SCHEMA,
                    model_name=model_name,
                )
            except InvalidKeyError:
                for k in keys:
                    if k.value == api_key:
                        failed_invalid_key_ids.append(UUID(k.id))
                        break
                raise

        # Sprint 9.3 A — wrap the rotator call in the LLM call
        # auditor so every executive briefing generation lands one
        # ``llm_call_audit`` row with prompt hash, model meta, token
        # usage, success / error metadata. Best-effort: a failed
        # audit insert logs but doesn't propagate (governance is
        # observability, not the request's primary contract).
        from imga_api.services.llm_audit_service import (
            CALL_TYPE_BRIEFING,
            LLMCallAuditor,
            LLMCallContext,
        )

        audit_ctx = LLMCallContext(
            tenant_id=self._tenant_id,
            call_type=CALL_TYPE_BRIEFING,
            model_name=model_name,
            model_provider=provider_name,
            prompt_template_key="executive_briefing",
            prompt_template_version="v1",
            actor_user_id=self._user_id,
            related_entity_type="executive_briefing",
        )
        auditor = LLMCallAuditor(
            self._session, audit_ctx, prompt=user_prompt
        )
        start = time.monotonic()
        try:
            async with auditor:
                # Sprint 9.4.4 — explicit record_failure on the rotator
                # raise path. The auditor's __aexit__ does auto-record
                # on exception, but Sprint 9.4.3 B's empirical
                # all-keys-exhausted run (12.05.2026 12:07:13) didn't
                # land an audit row even with that auto-path in place.
                # The most defensible interpretation: classify the
                # error at the call site where we know it's a rotator
                # exhaustion, not let the generic _classify_exception
                # have to infer it from a wrapped LLMProviderError
                # message. record_failure populates the error fields
                # ahead of __aexit__, which then reads ``_error_type
                # or _classify_exception(exc_val)`` and keeps our
                # explicit value.
                try:
                    (response, token_usage), key_used = (
                        await rotator.call_with_rotation(_call)
                    )
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
                    # LLMProviderError lives in imga_core.llm.base, not
                    # in the LLMError hierarchy, so the typed handlers
                    # above don't catch it. Sprint 9.4.3 B's rotator
                    # broadened to catch LLMProviderError + rotate,
                    # which means an all-504 storm now ends with
                    # AllKeysExhaustedError (handled above) — but we
                    # still record a generic failure for any other
                    # unexpected raise so the audit table doesn't
                    # quietly drop rows.
                    auditor.record_failure(
                        error_type="other",
                        error_message=f"{type(exc).__name__}: {exc}"[:1024],
                    )
                    raise
                input_tokens = (
                    token_usage.get("input") if token_usage else None
                )
                output_tokens = (
                    token_usage.get("output") if token_usage else None
                )
                auditor.record_success(
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )
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
            model_name=model_name,
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
        # Sprint 9.0.5-B E — NPS is computed via the canonical
        # ``AnalyticsService.compute_nps_summary`` rather than
        # ``func.avg(nps_score)``. The earlier raw-average produced a
        # 0-10 number that callers misread as canonical NPS (which is
        # promoter% - detractor% on the -100..100 scale). The
        # dashboard, executive briefing, and trend alerts now share
        # the same definition.
        from imga_api.services.analytics_service import AnalyticsService

        analytics = AnalyticsService(self._session)
        nps_summary = await analytics.compute_nps_summary(
            tenant_id=self._tenant_id,
            date_from=date_from,
            date_to=date_to,
            batch_job_id=batch_id,
        )

        # Volume + sentiment + negative share remain a single SQL hit;
        # NPS already came back from compute_nps_summary above.
        stmt = select(
            func.count().label("cnt"),
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
            # Gun-sinirli datetime bound'lar (date_bounds docstring'i):
            # ciplak `<= date` geceyarisina cozulup bitis gununu (bugunu)
            # pencereden dusuruyordu — bugun analiz edilen veriyle brifing
            # "hic yorum yok" uretiyordu.
            Review.review_date >= day_floor(date_from),
            Review.review_date <= day_ceil(date_to),
            # 2026-08-18 — brifing metrikleri de temiz veriden; toggle
            # yok (yönetici özeti her zaman bayraklı satırları dışlar).
            Review.quality_flag.is_(None),
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
                Review.review_date >= day_floor(date_from),
                Review.review_date <= day_ceil(date_to),
                # Bkz. yukarıdaki agg stmt yorumu — top-categories de
                # temiz veriden.
                Review.quality_flag.is_(None),
            )
            .group_by(Review.primary_category)
            .order_by(func.count().desc())
            .limit(5)
        )
        if batch_id is not None:
            cat_stmt = cat_stmt.where(Review.batch_job_id == batch_id)
        cat_rows = (await self._session.execute(cat_stmt)).all()
        top_categories = [
            {
                "label": _CATEGORY_LABELS.get(
                    r.primary_category, r.primary_category
                ),
                "count": int(r.cnt),
            }
            for r in cat_rows
        ]

        return _PeriodStats(
            total_reviews=cnt,
            nps_score=nps_summary.score,
            nps_coverage_percent=nps_summary.coverage_percent,
            nps_bearing_count=nps_summary.total_count,
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

    async def _collect_snapshot_context(
        self, period: str,
    ) -> dict[str, Any] | None:
        """Sprint 9.2 C — read today's snapshot or compute it cold.

        ``period`` maps directly to the snapshot table's period
        column. Daily / weekly / monthly all share the same row shape;
        the caller picks based on briefing cadence.
        """
        try:
            from imga_api.services.snapshot_service import SnapshotService

            service = SnapshotService(self._session)
            payload = await service.get_or_compute(
                tenant_id=self._tenant_id,
                period=period if period in ("daily", "weekly", "monthly") else "monthly",
            )
            return {
                "snapshot_date": payload.snapshot_date.isoformat(),
                "period": payload.period,
                "metrics": payload.metrics,
                "review_count": payload.review_count,
                "computed_at": payload.computed_at.isoformat(),
                "computation_duration_ms": payload.computation_duration_ms,
            }
        except Exception:
            _logger.exception(
                "executive briefing: snapshot collection failed (non-fatal)",
                extra={"tenant_id": str(self._tenant_id)},
            )
            return None

    async def _collect_kpi_goal_context(
        self,
        *,
        current_nps: float | None,
        current_total: int,
    ) -> list[dict[str, Any]]:
        """Sprint 9.2 B — fold every active KPI goal into the prompt
        context. Returns a list of ``{metric_key, target, current,
        achievement_pct, on_track}`` dicts the LLM can quote in the
        headline; an empty list is fine (the prompt template only
        renders the section when the array is non-empty).

        Best-effort: any failure (RLS hiccup, missing tenant) logs +
        falls through to ``[]`` so the briefing still ships."""
        try:
            from imga_api.services.kpi_goal_service import KpiGoalService

            service = KpiGoalService(self._session)
            goals = await service.list_active(tenant_id=self._tenant_id)
            if not goals:
                return []
            current_by_key: dict[str, float] = {}
            if current_nps is not None:
                current_by_key["nps"] = float(current_nps)
            current_by_key["review_volume"] = float(current_total)
            payload: list[dict[str, Any]] = []
            for goal in goals:
                progress = KpiGoalService.compute_progress(
                    goal, current_by_key.get(goal.metric_key)
                )
                payload.append(
                    {
                        "metric_key": progress.metric_key,
                        "target": progress.target_value,
                        "current": progress.current_value,
                        "achievement_pct": progress.achievement_pct,
                        "on_track": progress.on_track,
                        "period": progress.target_period,
                        "higher_is_better": progress.higher_is_better,
                    }
                )
            return payload
        except Exception:
            _logger.exception(
                "executive briefing: KPI goal context collection failed",
                extra={"tenant_id": str(self._tenant_id)},
            )
            return []

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
        model_name: str,
    ) -> dict[str, Any]:
        top_actions = list(response.get("top_actions") or [])
        row = ExecutiveBriefing(
            tenant_id=self._tenant_id,
            period=period,
            date_from=date_from,
            date_to=date_to,
            batch_id=batch_id,
            headline=str(response.get("headline", "")),
            kpi_changes=list(response.get("kpi_changes") or []),
            critical_insights=list(response.get("critical_insights") or []),
            top_actions=top_actions,
            input_stats=input_stats,
            model_name=model_name,
            token_usage=token_usage,
            generation_duration_ms=duration_ms,
            created_by_user_id=self._user_id,
        )
        self._session.add(row)
        await self._session.flush()

        # Sprint 9.0.5-B G — extract ActionItem rows from the LLM's
        # top_actions prose + persist the linkage on the briefing.
        # Idempotent on the action-extraction side: a re-render of
        # the same briefing returns the existing action_item_ids
        # via the unique fingerprint constraint, so the
        # top_action_item_ids column can be re-written safely.
        action_item_ids: list[UUID] = []
        if top_actions:
            try:
                from imga_api.services.action_extraction_service import (
                    ActionExtractionService,
                )

                content_text = json.dumps(
                    top_actions, sort_keys=True, ensure_ascii=False,
                )
                extractor = ActionExtractionService(self._session)
                action_item_ids = await extractor.extract(
                    tenant_id=self._tenant_id,
                    source_type="executive_briefing",
                    source_id=row.id,
                    content_text=content_text,
                    action_payloads=top_actions,
                )
                if action_item_ids:
                    row.top_action_item_ids = list(action_item_ids)
                    await self._session.flush()
            except Exception:
                _logger.exception(
                    "executive briefing: action extraction failed; "
                    "briefing row persisted without top_action_item_ids",
                    extra={
                        "tenant_id": str(self._tenant_id),
                        "briefing_id": str(row.id),
                    },
                )

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
            "top_action_item_ids": [str(i) for i in action_item_ids],
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
