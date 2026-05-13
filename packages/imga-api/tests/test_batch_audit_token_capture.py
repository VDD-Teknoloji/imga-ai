"""Sprint 9.5.5 A — batch chunk audit captures real token usage + duration.

Pre-9.5.5 the batch-path ``llm_call_audit`` row landed with
``input_tokens = NULL``, ``output_tokens = NULL`` (so total_tokens = 0
via the GENERATED column), and ``duration_ms`` ~= 0. The briefing
auditor was working correctly; the gap was specific to
``batch_analyzer.py`` because:

  * ``HybridClassifier.classify_batch_async`` used to return a bare
    ``list[CategoryClassification]`` so the worker had no aggregate
    to pass on to ``record_success``.
  * The chunk's ``async with chunk_auditor`` wrapped only the ~1ms
    flag-setting region AFTER the real LLM call had already
    returned, so the auditor's in-window elapsed measured ~1ms
    instead of the actual ~80s Gemini latency.

The fix has three load-bearing pieces and this module pins each:

  1. ``LLMClassificationResult.token_usage`` is the carrier — set
     by GeminiProvider from the SDK's ``usage_metadata``, propagated
     unchanged through ``_merge_with_llm`` so each successful row
     in a HybridClassifier batch carries its per-call usage.

  2. ``HybridClassifier.classify_batch_async`` now returns
     ``BatchClassificationResult`` with the per-batch aggregates
     (sum of inputs, sum of outputs, real LLM wall-clock).

  3. ``LLMCallAuditor.record_success`` accepts a ``duration_ms``
     override so the batch path can ship the classifier's
     wall-clock instead of the auditor's 1ms in-window measurement.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import pytest
from imga_core.classifiers.hybrid import (
    BatchClassificationResult,
    HybridClassifier,
)
from imga_core.classifiers.keyword import KeywordCategoryClassifier
from imga_core.llm.base import LLMProvider
from imga_core.models import LLMClassificationResult
from imga_db.models import LlmCallAudit
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.services.llm_audit_service import (
    CALL_TYPE_CLASSIFICATION,
    LLMCallAuditor,
    LLMCallContext,
)


class _StubLLMProvider(LLMProvider):
    """LLM provider that emits a known token_usage on every call.

    Mirrors the Gemini shape: ``token_usage = {'input': N, 'output': M,
    'total': N+M}``. ``call_count`` lets the test assert the number
    of LLM calls actually dispatched (matches the LLM-fallback
    candidate count for the batch).
    """

    PROVIDER_NAME = "stub-gemini"

    def __init__(
        self,
        *,
        input_tokens: int = 120,
        output_tokens: int = 45,
        sleep_seconds: float = 0.0,
    ) -> None:
        self._input = input_tokens
        self._output = output_tokens
        self._sleep = sleep_seconds
        self.call_count = 0

    def classify(
        self, text: str, available_categories: list[str]
    ) -> LLMClassificationResult:
        self.call_count += 1
        return LLMClassificationResult(
            primary="kargo",
            confidence=0.88,
            reasoning="stub reasoning",
            provider=self.PROVIDER_NAME,
            model="stub-model",
            token_usage={
                "input": self._input,
                "output": self._output,
                "total": self._input + self._output,
            },
        )

    async def classify_async(
        self, text: str, available_categories: list[str]
    ) -> LLMClassificationResult:
        if self._sleep > 0:
            await asyncio.sleep(self._sleep)
        return self.classify(text, available_categories)

    def health_check(self) -> bool:
        return True


# --- 1. token_usage propagation through merge -----------------------------


@pytest.mark.asyncio
async def test_classify_batch_async_aggregates_token_usage() -> None:
    """Two low-confidence texts both trigger LLM fallback. The
    BatchClassificationResult should sum input + output tokens
    across every successful call."""
    provider = _StubLLMProvider(input_tokens=100, output_tokens=40)
    classifier = HybridClassifier(
        keyword_classifier=KeywordCategoryClassifier(),
        llm_provider=provider,
        confidence_threshold=0.99,  # force every row to LLM fallback
    )

    texts = ["belirsiz girdi 1", "belirsiz girdi 2"]
    result = await classifier.classify_batch_async(texts)

    assert isinstance(result, BatchClassificationResult)
    assert len(result.classifications) == 2
    assert provider.call_count == 2, (
        "both texts had keyword confidence below threshold so each "
        "should have hit the LLM fallback"
    )
    assert result.llm_total_input_tokens == 200
    assert result.llm_total_output_tokens == 80


@pytest.mark.asyncio
async def test_classify_batch_async_keyword_only_yields_zero_aggregates() -> None:
    """No LLM dispatch means no tokens + no LLM duration. The
    envelope still wraps the classifications so the caller's
    unpacking is uniform across paths."""
    classifier = HybridClassifier(
        keyword_classifier=KeywordCategoryClassifier(),
        llm_provider=None,  # LLM disabled entirely
    )
    result = await classifier.classify_batch_async(["kargo gecikmesi"])
    assert isinstance(result, BatchClassificationResult)
    assert result.llm_total_input_tokens == 0
    assert result.llm_total_output_tokens == 0
    assert result.llm_duration_ms == 0


@pytest.mark.asyncio
async def test_classify_batch_async_clocks_real_llm_wallclock() -> None:
    """The LLM duration is wall-clock spent on the fan-out, not on
    keyword/BERT/etc. Single LLM call with a 50ms sleep should
    register at least ~50ms (loose bound — CI clock fuzz)."""
    provider = _StubLLMProvider(sleep_seconds=0.05)
    classifier = HybridClassifier(
        keyword_classifier=KeywordCategoryClassifier(),
        llm_provider=provider,
        confidence_threshold=0.99,
    )
    result = await classifier.classify_batch_async(["belirsiz"])
    assert result.llm_duration_ms >= 40, (
        f"expected ~50ms LLM duration; got {result.llm_duration_ms}ms — "
        "the wall-clock measurement may have regressed to the "
        "auditor's old in-window window"
    )


# --- 2. record_success duration_ms override writes to the audit row ------


@pytest.mark.asyncio
async def test_record_success_duration_ms_override_persists(
    semi_auto_tenant: tuple[Any, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """Sprint 9.5.5 A — the batch chunk path wraps the auditor's
    ``async with`` AFTER the real LLM call has returned, so the
    auditor's in-window timer measures ~1ms. ``record_success`` now
    accepts a ``duration_ms`` override; the row should reflect it,
    NOT the in-window 1ms."""
    _user, tenant_id, _pw = semi_auto_tenant
    ctx = LLMCallContext(
        tenant_id=tenant_id,
        call_type=CALL_TYPE_CLASSIFICATION,
        model_name="stub-model",
        model_provider="stub-gemini",
    )

    async with admin_session.begin():
        # Set tenant context — llm_call_audit is RLS-bound; the admin
        # session bypasses RLS for read but the INSERT still has to
        # match the FK to a real tenant.
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tenant_id)},
        )
        auditor = LLMCallAuditor(
            admin_session, ctx, prompt="stub chunk anchor",
        )
        async with auditor:
            # Simulate the batch path: the real LLM took ~80s,
            # returned 50k input + 30k output tokens. The async-with
            # body is basically instant — just flips flags.
            auditor.record_success(
                input_tokens=50_000,
                output_tokens=30_000,
                duration_ms=80_000,
            )

    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tenant_id)},
        )
        rows = (
            await admin_session.execute(
                select(LlmCallAudit).where(
                    LlmCallAudit.tenant_id == tenant_id
                )
            )
        ).scalars().all()

    assert len(rows) == 1
    row = rows[0]
    assert row.input_tokens == 50_000
    assert row.output_tokens == 30_000
    # total_tokens is a GENERATED column on the table.
    assert row.total_tokens == 80_000
    assert row.duration_ms == 80_000, (
        f"expected duration_ms=80000 (override); got {row.duration_ms} — "
        "if ~0, _duration_ms_override isn't being consulted in "
        "_insert_row's elapsed calculation"
    )
    assert row.success is True


@pytest.mark.asyncio
async def test_record_success_without_override_keeps_in_window_timer(
    semi_auto_tenant: tuple[Any, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """No override means the auditor's own ``time.monotonic`` window
    is the source — the briefing / OKR / SWOT paths rely on this
    behaviour and must NOT regress to a forced zero."""
    _user, tenant_id, _pw = semi_auto_tenant
    ctx = LLMCallContext(
        tenant_id=tenant_id,
        call_type=CALL_TYPE_CLASSIFICATION,
        model_name="stub-model",
        model_provider="stub-gemini",
    )

    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tenant_id)},
        )
        auditor = LLMCallAuditor(
            admin_session, ctx, prompt="stub anchor",
        )
        async with auditor:
            await asyncio.sleep(0.03)  # ~30ms in-window work
            auditor.record_success(input_tokens=10, output_tokens=5)

    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tenant_id)},
        )
        rows = (
            await admin_session.execute(
                select(LlmCallAudit).where(
                    LlmCallAudit.tenant_id == tenant_id
                )
            )
        ).scalars().all()
    assert len(rows) == 1
    # Loose bound — CI clock fuzz; just assert it's NOT zero (which
    # would mean the timer regressed).
    assert rows[0].duration_ms is not None and rows[0].duration_ms >= 20
