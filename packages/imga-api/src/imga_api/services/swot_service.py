"""SWOT generator orchestrator.

Sprint 8.3.6 / Alt-Faz 8.3.6.3.C. Wires the eight pieces that produce
a single SWOT row:

  1. Stats: ``StatsAggregator.collect`` builds the snapshot.
  2. Cache key: ``swot:{tenant}:{date_from}:{date_to}:{stats_hash}``.
  3. Cache lookup (Redis ``GET``). Hit → return the cached row,
     no LLM call.
  4. Credentials: load active ``tenant_llm_credentials`` rows,
     decrypt, build a ``GeminiKeyRotator``.
  5. Prompts: render the SWOT v1 user prompt from the snapshot.
  6. LLM call: ``rotator.call_with_rotation`` → ``GeminiProvider.
     generate_swot``. Returns parsed JSON dict + the key that won.
  7. Validate: defence-in-depth check against the response_schema's
     top-level required fields. The Gemini SDK already enforces, but
     a regression here is cheaper to catch than to debug from the
     dashboard.
  8. Persist: insert one ``strategic_reports`` row with input_stats +
     output_payload + duration + token_usage (when the SDK provides
     it). Cache the same payload for 24h. Return the row.

Failure modes:

  * ``NoCredentialsError`` — tenant has zero active rows in
    ``tenant_llm_credentials``. Frontend renders the "configure an API
    key" CTA, no LLM call attempted.
  * ``AllKeysExhaustedError`` (from ``imga_core.llm``) — every key in
    rotation hit RateLimit / InvalidKey. Service marks any
    ``InvalidKeyError``-flagged keys' ``last_failed_at`` so the
    /settings/integrations page can surface "needs attention". The
    error then re-raises so the route layer returns a 503.
  * Other ``LLMError`` (Malformed, generic provider) — the rotator
    propagates without retrying; service surfaces the same to the
    route layer.

Cache failures (Redis down, network blip) NEVER block generation —
each cache op is wrapped in a defensive try/except that logs and
falls through. Sprint 8.3.6.3 ships with the manual-only trigger so
the user-perceived cost of a cold cache is one extra LLM call, not a
broken page.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import date
from typing import Any
from uuid import UUID

from imga_core.llm import (
    AllKeysExhaustedError,
    GeminiKeyRotator,
    InvalidKeyError,
    LLMError,
)
from imga_core.llm.gemini import GeminiProvider
from imga_db.models import StrategicReport
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.cache.redis_client import get_redis_client
from imga_api.llm.prompts.swot_v1 import (
    SWOT_RESPONSE_SCHEMA,
    SWOT_SYSTEM_PROMPT,
    render_swot_user_prompt,
)
from imga_api.services.llm_credentials import (
    NoCredentialsError,
    load_active_gemini_keys,
    mark_keys_failed,
)
from imga_api.services.stats_aggregator import (
    StatsAggregator,
    StrategicStatsSnapshot,
)
from imga_api.services.strategic_constants import (
    company_size_label,
    industry_label,
)

_logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 86400
CACHE_KEY_PREFIX = "swot"
DEFAULT_MODEL_NAME = "gemini-2.5-pro"


class SwotServiceError(Exception):
    """Base for SWOT generator failures the route layer must map to
    HTTP responses."""


class SwotResponseInvalidError(SwotServiceError):
    """The LLM returned a 200 that's syntactically JSON but missing
    one of the SWOT_RESPONSE_SCHEMA's top-level required fields. The
    Gemini SDK should have caught this; the service double-checks
    because a regression there silently corrupts dashboards."""


class SwotService:
    """Orchestrate one SWOT generation against the tenant's keys."""

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
        # Provider injected for test isolation; production code path
        # builds one with no constructor key (every call passes its
        # own key via the rotator).
        self._provider = provider or _build_provider_without_key()

    async def generate(
        self,
        date_from: date | None = None,
        date_to: date | None = None,
        *,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """Generate (or fetch from cache) one SWOT report. Returns the
        persisted row as a serialisable dict (see ``_serialise_report``)
        — the caller maps it to the wire shape."""
        # 1. Stats
        stats = await StatsAggregator(self._session, self._tenant_id).collect(
            date_from=date_from, date_to=date_to
        )

        # 2/3. Cache key + lookup. Cache miss / Redis down both fall
        # through to the slow path; ``force_refresh`` skips the lookup
        # but still writes on the way out.
        cache_key = self._cache_key(stats, date_from, date_to)
        if not force_refresh:
            cached = await self._cache_get(cache_key)
            if cached is not None:
                _logger.info(
                    "SWOT cache hit tenant=%s key=%s",
                    self._tenant_id, cache_key,
                )
                return cached

        # 4. Credentials → rotator
        keys = await load_active_gemini_keys(self._session, self._tenant_id)
        if not keys:
            raise NoCredentialsError(
                "Tenant has no active LLM API keys configured"
            )
        rotator = GeminiKeyRotator(keys)

        # 5. Prompt rendering
        user_prompt = render_swot_user_prompt(self._render_context(stats))

        # 6. LLM call with rotation. ``failed_key_ids`` accumulates the
        # ids of any InvalidKey-flagged keys; we mark them
        # last_failed_at after the AllKeysExhausted branch (or after
        # success — only invalid keys we tried + failed deserve the
        # mark).
        failed_invalid_key_ids: list[UUID] = []

        async def _call(api_key: str) -> tuple[dict[str, Any], dict[str, int] | None]:
            try:
                return await self._provider.generate_swot(
                    api_key=api_key,
                    system_prompt=SWOT_SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                    response_schema=SWOT_RESPONSE_SCHEMA,
                )
            except InvalidKeyError:
                # Attribute the failure to the key the rotator passed
                # in (we look it up below by value).
                for k in keys:
                    if k.value == api_key:
                        failed_invalid_key_ids.append(UUID(k.id))
                        break
                raise

        start = time.monotonic()
        try:
            (response, token_usage), key_used = await rotator.call_with_rotation(_call)
        except AllKeysExhaustedError:
            # Mark every key we identified as InvalidKey before re-raising.
            await mark_keys_failed(self._session, failed_invalid_key_ids)
            raise
        except LLMError:
            # Other LLMError (Malformed, generic) — propagate without
            # marking keys; the keys themselves aren't the issue.
            raise

        duration_ms = int((time.monotonic() - start) * 1000)

        # If the winning attempt was preceded by an InvalidKey on a
        # higher-priority key, mark that one as failed so the UI can
        # surface "needs attention".
        if failed_invalid_key_ids:
            await mark_keys_failed(self._session, failed_invalid_key_ids)

        # 7. Validate
        self._validate_swot_response(response)

        # 8. Persist + cache + return
        report_dict = await self._persist_report(
            response=response,
            stats=stats,
            date_from=date_from,
            date_to=date_to,
            model_name=DEFAULT_MODEL_NAME,
            duration_ms=duration_ms,
            token_usage=token_usage,
        )
        await self._cache_set(cache_key, report_dict)

        _logger.info(
            "SWOT generated tenant=%s key_id=%s key_label=%s duration_ms=%d",
            self._tenant_id, key_used.id, key_used.label, duration_ms,
        )
        return report_dict

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _cache_key(
        self,
        stats: StrategicStatsSnapshot,
        date_from: date | None,
        date_to: date | None,
    ) -> str:
        df = date_from.isoformat() if date_from else "all"
        dt = date_to.isoformat() if date_to else "all"
        return f"{CACHE_KEY_PREFIX}:{self._tenant_id}:{df}:{dt}:{stats.stats_hash()}"

    async def _cache_get(self, key: str) -> dict[str, Any] | None:
        """Best-effort Redis lookup. Any exception → None (treat as
        cache miss). The defensive wrap is critical: if Redis is down
        we still want SWOT generation to work, just at slow-path cost.
        """
        try:
            client = get_redis_client()
            raw = await client.get(key)
        except Exception as exc:
            _logger.warning("SWOT cache get failed (%s); falling through", exc)
            return None
        if raw is None:
            return None
        try:
            return _from_json(raw)
        except (ValueError, TypeError) as exc:
            _logger.warning(
                "SWOT cache holds malformed payload at %s (%s); "
                "treating as miss",
                key, exc,
            )
            return None

    async def _cache_set(self, key: str, payload: dict[str, Any]) -> None:
        """Best-effort Redis write. Any exception is swallowed so a
        Redis blip doesn't fail the whole generation after the LLM
        call already succeeded."""
        try:
            client = get_redis_client()
            await client.set(key, _to_json(payload), ex=CACHE_TTL_SECONDS)
        except Exception as exc:
            _logger.warning("SWOT cache set failed (%s); continuing", exc)

    @staticmethod
    def _render_context(stats: StrategicStatsSnapshot) -> dict[str, Any]:
        """Adapt the snapshot to the Jinja template's expected key
        shape (mostly 1:1 plus the resolved Türkçe labels)."""
        return {
            "industry_label": industry_label(
                stats.industry, stats.industry_other_text
            ),
            "industry_other_text": stats.industry_other_text,
            "company_size_label": company_size_label(stats.company_size),
            "business_description": stats.business_description,
            "date_from": stats.date_from,
            "date_to": stats.date_to,
            "total_reviews": stats.total_reviews,
            "crisis_count": stats.crisis_count,
            "sensitive_topics_count": stats.sensitive_topics_count,
            "avg_sentiment_score": stats.avg_sentiment_score,
            "sentiment_distribution": stats.sentiment_distribution,
            "nps_score": stats.nps_score,
            "nps_coverage_percent": stats.nps_coverage_percent,
            "nps_distribution": stats.nps_distribution,
            "category_distribution": stats.category_distribution,
            "company_perspective_distribution": stats.company_perspective_distribution,
            "unmatched_perspective_count": stats.unmatched_perspective_count,
        }

    @staticmethod
    def _validate_swot_response(payload: dict[str, Any]) -> None:
        """Defence-in-depth validation. Two layers, each with a
        deliberately different posture:

          * **Required-field shape (strict):** missing top-level keys
            mean the LLM ignored the schema entirely; that's a hard
            error — the row would be unrenderable.
          * **Per-section counts (permissive):** the count window
            (2-6 SWOT items, 3-5 recommendations) used to live in the
            response_schema as ``minItems`` / ``maxItems`` until the
            Gemini SDK crashed on those keys (8.3.6.6 round-1
            production). It now lives in the system prompt + this
            soft check: out-of-range counts log a warning but the
            row still gets persisted. Worst case a user sees one
            section with a single item; that's strictly better than a
            500 with no row at all.
        """
        required = SWOT_RESPONSE_SCHEMA["required"]
        missing = [k for k in required if k not in payload]
        if missing:
            raise SwotResponseInvalidError(
                f"SWOT response missing required fields: {missing}"
            )

        for section in ("strengths", "weaknesses", "opportunities", "threats"):
            items = payload.get(section, [])
            if not (2 <= len(items) <= 6):
                _logger.warning(
                    "SWOT response %s has %d items, expected 2-6 — "
                    "persisting anyway",
                    section, len(items),
                )

        recs = payload.get("strategic_recommendations", [])
        if not (3 <= len(recs) <= 5):
            _logger.warning(
                "SWOT response strategic_recommendations has %d items, "
                "expected 3-5 — persisting anyway",
                len(recs),
            )

    async def _persist_report(
        self,
        *,
        response: dict[str, Any],
        stats: StrategicStatsSnapshot,
        date_from: date | None,
        date_to: date | None,
        model_name: str,
        duration_ms: int,
        token_usage: dict[str, Any] | None,
    ) -> dict[str, Any]:
        report = StrategicReport(
            tenant_id=self._tenant_id,
            report_type="swot",
            date_from=date_from,
            date_to=date_to,
            input_stats=_snapshot_to_input_stats(stats),
            output_payload=response,
            source_report_id=None,
            model_name=model_name,
            token_usage=token_usage,
            generation_duration_ms=duration_ms,
            created_by_user_id=self._user_id,
        )
        self._session.add(report)
        await self._session.flush()
        report_id = report.id
        return {
            "id": str(report_id),
            "tenant_id": str(self._tenant_id),
            "report_type": "swot",
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
            "input_stats": _snapshot_to_input_stats(stats),
            "output_payload": response,
            "model_name": model_name,
            "token_usage": token_usage,
            "generation_duration_ms": duration_ms,
            "created_by_user_id": (
                str(self._user_id) if self._user_id is not None else None
            ),
        }


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------


def _build_provider_without_key() -> GeminiProvider:
    """Construct a GeminiProvider with a placeholder key. The SWOT
    path always passes ``api_key`` per call (rotator-driven), so the
    constructor key is unused — but the provider's ``__init__`` still
    rejects empty keys + imports the SDK eagerly.

    We pass a single-character placeholder so the constructor's
    "non-empty" guard passes. genai.configure(api_key="x") is harmless
    because every actual generate_swot call reconfigures with the real
    key before the SDK reaches out.
    """
    return GeminiProvider(api_key="x", model_name=DEFAULT_MODEL_NAME)


def _snapshot_to_input_stats(stats: StrategicStatsSnapshot) -> dict[str, Any]:
    """Frozen JSON representation of the snapshot for ``input_stats``
    column. Date objects → ISO strings, everything else passes
    through. Used both by the persistence path and the test layer that
    asserts on the persisted shape."""
    return {
        "date_from": stats.date_from.isoformat() if stats.date_from else None,
        "date_to": stats.date_to.isoformat() if stats.date_to else None,
        "industry": stats.industry,
        "industry_other_text": stats.industry_other_text,
        "company_size": stats.company_size,
        "business_description": stats.business_description,
        "total_reviews": stats.total_reviews,
        "crisis_count": stats.crisis_count,
        "sensitive_topics_count": stats.sensitive_topics_count,
        "avg_sentiment_score": stats.avg_sentiment_score,
        "sentiment_distribution": stats.sentiment_distribution,
        "nps_score": stats.nps_score,
        "nps_coverage_percent": stats.nps_coverage_percent,
        "nps_distribution": stats.nps_distribution,
        "nps_monthly_trend": stats.nps_monthly_trend,
        "category_distribution": stats.category_distribution,
        "company_perspective_distribution": stats.company_perspective_distribution,
        "unmatched_perspective_count": stats.unmatched_perspective_count,
        "stats_hash": stats.stats_hash(),
    }


def _to_json(payload: dict[str, Any]) -> bytes:
    """Serialise a SWOT row dict to bytes for Redis storage. Defaults
    to UTF-8 JSON; ``ensure_ascii=False`` keeps Türkçe characters
    readable in Redis dumps."""
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _from_json(raw: bytes) -> dict[str, Any]:
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("SWOT cache payload is not a dict")
    return data


__all__ = [
    "CACHE_KEY_PREFIX",
    "CACHE_TTL_SECONDS",
    "DEFAULT_MODEL_NAME",
    "NoCredentialsError",
    "SwotResponseInvalidError",
    "SwotService",
    "SwotServiceError",
]
