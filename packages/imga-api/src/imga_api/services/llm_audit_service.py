"""Sprint 9.3 A — LLM call governance audit.

Every LLM call that goes through the platform writes one
``llm_call_audit`` row capturing the prompt template + version,
model meta, token usage, duration, success / error metadata, and
the request_id from Sprint 9.1 C so an operator can correlate a UI
failure to the underlying provider call.

``LLMCallAuditor`` is an async context manager — wrap the call
site, ``record_success(...)`` after the call returns, or
``record_failure(...)`` in the except branch. The context manager
auto-records on exit if neither was called explicitly.

Wire-shape for the audit row:
  * call_type — 'classification' | 'briefing' |
    'strategic_report' | 'action_extraction' | 'okr' |
    'root_cause'
  * related_entity_type / related_entity_id — points at the
    review / briefing / report row this call produced.
  * prompt_template_key / version — None when the call uses the
    hard-coded fallback (e.g. classifier with no DB row yet).
  * prompt_hash — sha256(rendered_user_prompt). Same prompt twice
    yields the same hash; dedup analytics can use this to find
    redundant work.
  * model_provider — 'gemini' today; future providers fill in.
  * fallback_used — true when the keyword classifier ran instead
    of the LLM (HybridClassifier circuit-open path).

The auditor does NOT manage transactions: callers wrap each call
in their own ``async with session.begin():`` so the audit row
commits with the rest of the request's work. If the caller's
transaction rolls back, the audit row goes with it — that's
intentional, an audit row for a transaction that was discarded is
worse than no row.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from imga_db.models import LlmCallAudit
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.services.llm_pricing import cost_usd as _price_call

_logger = logging.getLogger(__name__)


CALL_TYPE_CLASSIFICATION = "classification"
CALL_TYPE_BRIEFING = "briefing"
CALL_TYPE_STRATEGIC_REPORT = "strategic_report"
CALL_TYPE_ACTION_EXTRACTION = "action_extraction"
CALL_TYPE_OKR = "okr"
# Sprint 13.1 — alt kategori kök neden analizi. ck_llm_call_audit_call_type
# kısıtı migration 0040 ile genişletildi; yeni bir tip eklemeden önce
# aynı kısıtı da güncelle.
CALL_TYPE_ROOT_CAUSE = "root_cause"
# Dalga 2 — toplu yükleme veri kalitesi raporu özeti (kısıt: 0043).
CALL_TYPE_QUALITY_REPORT = "quality_report"
# 2026-08-20 (süper-admin envanteri, migration 0045) — onboarding
# sihirbazının AI kategori önerisi çağrısı. SA2 kullanacak.
CALL_TYPE_ONBOARDING_SUGGEST = "onboarding_suggest"
# 2026-08-26 (migration 0048) — Twitter'dan Çek: marka anahtar kelime
# planı + gönderi başına alaka hakemi (services/twitter_brand_service).
CALL_TYPE_TWITTER_KEYWORDS = "twitter_keywords"
CALL_TYPE_TWITTER_RELEVANCE = "twitter_relevance"

ERROR_TIMEOUT = "timeout"
ERROR_RATE_LIMIT = "rate_limit"
ERROR_API = "api_error"
ERROR_PARSE = "parse_error"
ERROR_INVALID_KEY = "invalid_key"
ERROR_ALL_KEYS_EXHAUSTED = "all_keys_exhausted"
ERROR_BLOCKED = "blocked"
ERROR_TOKEN_LIMIT = "token_limit"
ERROR_OTHER = "other"


@dataclass(frozen=True, slots=True)
class LLMCallContext:
    """All-in-one input bag for the auditor. Built once per call
    and immutable so a peer task can't mutate it mid-flight."""

    tenant_id: UUID
    call_type: str
    model_name: str
    model_provider: str = "gemini"
    related_entity_type: str | None = None
    related_entity_id: UUID | None = None
    prompt_template_key: str | None = None
    prompt_template_version: str | None = None
    actor_user_id: UUID | None = None
    request_id: str | None = None
    model_temperature: float | None = None
    model_max_tokens: int | None = None


class LLMCallAuditor:
    """Async context manager around a single LLM call. Usage::

        ctx = LLMCallContext(tenant_id=..., call_type='briefing', ...)
        auditor = LLMCallAuditor(session, ctx, prompt=rendered_prompt)
        async with auditor:
            response = await provider.generate_executive_briefing(...)
            auditor.record_success(
                input_tokens=response.usage_metadata.prompt_token_count,
                output_tokens=response.usage_metadata.candidates_token_count,
            )

    The ``__aexit__`` path records a failure with whatever exception
    raised inside the ``with`` body; an explicit ``record_success``
    short-circuits that. Bare ``__aexit__`` without either call
    is treated as a no-op success (the body returned but the caller
    didn't bother to report token usage)."""

    def __init__(
        self,
        session: AsyncSession,
        ctx: LLMCallContext,
        *,
        prompt: str,
        fallback_used: bool = False,
    ) -> None:
        self._session = session
        self._ctx = ctx
        self._prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        self._fallback_used = fallback_used
        self._started_at: float | None = None
        self._recorded = False
        self._success = True
        self._error_type: str | None = None
        self._error_message: str | None = None
        self._input_tokens: int | None = None
        self._output_tokens: int | None = None
        # Sprint 9.5.5 A — optional duration override. The batch path
        # wraps a window AFTER the real LLM call has already returned
        # (the chunk_auditor's async-with body just flips flags), so
        # ``_started_at -> now`` measures ~1ms instead of the actual
        # Gemini latency. Callers that know the real duration (e.g.
        # batch_analyzer.py reading HybridClassifier's
        # BatchClassificationResult.llm_duration_ms) can ship it
        # through ``record_success(duration_ms=...)`` and the audit
        # row uses that instead of the in-window elapsed.
        self._duration_ms_override: int | None = None

    async def __aenter__(self) -> LLMCallAuditor:
        self._started_at = time.monotonic()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        if self._recorded:
            return
        if exc_val is not None:
            self._success = False
            self._error_type = self._error_type or _classify_exception(exc_val)
            self._error_message = self._error_message or str(exc_val)[:1024]
        await self._insert_row()
        # Don't swallow the exception — the caller still sees it.

    def record_success(
        self,
        *,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        duration_ms: int | None = None,
    ) -> None:
        """Caller's chance to report token usage when the SDK
        surfaces it. ``input_tokens`` / ``output_tokens`` are
        ``None`` when the response didn't carry usage_metadata
        (rare, but the row stays consistent with the provider's
        actual response shape).

        Sprint 9.5.5 A — ``duration_ms`` overrides the auditor's
        in-window elapsed measurement. Required by the batch chunk
        path where the ``async with`` body runs AFTER the LLM call
        has already returned (the auditor would otherwise log ~1ms,
        not the real ~80s Gemini latency). The override is None when
        the caller wraps the actual call inside the ``async with``
        block (briefing / OKR / SWOT paths), in which case the
        auditor's own timer is the right source.
        """
        self._success = True
        self._input_tokens = input_tokens
        self._output_tokens = output_tokens
        if duration_ms is not None:
            self._duration_ms_override = duration_ms

    def record_failure(
        self,
        *,
        error_type: str,
        error_message: str,
    ) -> None:
        """Pre-empt the __aexit__ classifier when the caller has a
        better signal (e.g. a ``RateLimitError`` exception that
        the rotator caught + handled before we'd see it)."""
        self._success = False
        self._error_type = error_type
        self._error_message = error_message[:1024]

    def mark_fallback_used(self, used: bool) -> None:
        """Sprint 9.4.3 A — callers that can only learn whether the
        LLM was actually invoked AFTER the call returns (HybridClassifier
        is the canonical case: it falls back to the keyword classifier
        on rotator exhaustion or breaker-open without raising) flip
        the flag here. The auditor reads it on __aexit__."""
        self._fallback_used = used

    async def _insert_row(self) -> None:
        """Write the audit row. Best-effort: a failed insert logs
        but doesn't propagate.

        Sprint 9.4 F — wraps the INSERT in ``begin_nested()``
        (SAVEPOINT). Pre-9.4 a failed audit flush left the outer
        SQLAlchemy transaction in a failed state — the request's
        primary work (briefing INSERT, decision row, etc.) couldn't
        commit afterward and the whole call surfaced as 500. The
        savepoint isolates the failure so the auditor stays the
        observability tier it's meant to be."""
        if self._recorded:
            return
        self._recorded = True
        # Sprint 9.5.5 A — duration override beats the in-window
        # timer. See record_success for the batch-path rationale.
        if self._duration_ms_override is not None:
            elapsed: int | None = self._duration_ms_override
        elif self._started_at is not None:
            elapsed = int((time.monotonic() - self._started_at) * 1000)
        else:
            elapsed = None
        try:
            async with self._session.begin_nested():
                row = LlmCallAudit(
                    tenant_id=self._ctx.tenant_id,
                    call_type=self._ctx.call_type,
                    related_entity_type=self._ctx.related_entity_type,
                    related_entity_id=self._ctx.related_entity_id,
                    prompt_template_key=self._ctx.prompt_template_key,
                    prompt_template_version=self._ctx.prompt_template_version,
                    prompt_hash=self._prompt_hash,
                    model_name=self._ctx.model_name,
                    model_provider=self._ctx.model_provider,
                    model_temperature=(
                        Decimal(str(self._ctx.model_temperature))
                        if self._ctx.model_temperature is not None
                        else None
                    ),
                    model_max_tokens=self._ctx.model_max_tokens,
                    input_tokens=self._input_tokens,
                    output_tokens=self._output_tokens,
                    cost_usd=_price_call(
                        self._ctx.model_provider,
                        self._ctx.model_name,
                        self._input_tokens,
                        self._output_tokens,
                    ),
                    duration_ms=elapsed,
                    success=self._success,
                    error_type=self._error_type,
                    error_message=self._error_message,
                    fallback_used=self._fallback_used,
                    actor_user_id=self._ctx.actor_user_id,
                    request_id=self._ctx.request_id,
                    created_at=datetime.now(UTC),
                )
                self._session.add(row)
                await self._session.flush()
        except Exception:
            _logger.warning(
                "llm audit insert failed (non-fatal — savepoint rolled back)",
                exc_info=True,
                extra={
                    "tenant_id": str(self._ctx.tenant_id),
                    "call_type": self._ctx.call_type,
                    "request_id": self._ctx.request_id,
                },
            )


def _classify_exception(exc: BaseException) -> str:
    """Map a raw exception to one of the registry's error_type
    values. Best-effort — unknown exceptions fall through to
    ``other``."""
    name = type(exc).__name__
    msg = str(exc).lower()
    if (
        "rate" in name.lower()
        or "rate_limit" in msg
        or "ratelimit" in msg
        or "429" in msg
        or "quota" in msg
        or "resource_exhausted" in msg
    ):
        return ERROR_RATE_LIMIT
    if "invalidkey" in name.lower() or "invalid api key" in msg or "api key not valid" in msg:
        return ERROR_INVALID_KEY
    if "allkeysexhausted" in name.lower():
        return ERROR_ALL_KEYS_EXHAUSTED
    if "timeout" in name.lower() or "timed out" in msg or "deadline" in msg:
        return ERROR_TIMEOUT
    if "blocked" in name.lower() or "safety" in msg or "recitation" in msg:
        return ERROR_BLOCKED
    if "tokenlimit" in name.lower() or "max_tokens" in msg:
        return ERROR_TOKEN_LIMIT
    if "malformed" in name.lower() or "json" in msg or "parse" in msg:
        return ERROR_PARSE
    if "504" in msg or "503" in msg or "500" in msg:
        return ERROR_API
    return ERROR_OTHER


__all__ = [
    "CALL_TYPE_ACTION_EXTRACTION",
    "CALL_TYPE_BRIEFING",
    "CALL_TYPE_CLASSIFICATION",
    "CALL_TYPE_OKR",
    "CALL_TYPE_ONBOARDING_SUGGEST",
    "CALL_TYPE_QUALITY_REPORT",
    "CALL_TYPE_ROOT_CAUSE",
    "CALL_TYPE_STRATEGIC_REPORT",
    "ERROR_ALL_KEYS_EXHAUSTED",
    "ERROR_API",
    "ERROR_BLOCKED",
    "ERROR_INVALID_KEY",
    "ERROR_OTHER",
    "ERROR_PARSE",
    "ERROR_RATE_LIMIT",
    "ERROR_TIMEOUT",
    "ERROR_TOKEN_LIMIT",
    "LLMCallAuditor",
    "LLMCallContext",
]
