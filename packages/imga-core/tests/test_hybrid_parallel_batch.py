"""Sprint 9.0.5-A R4 — HybridClassifier parallel LLM batch coverage.

Demo incident: a 98-row LLM-bound batch took 161 seconds because
``HybridClassifier`` had no batch-aware async path — the default
``classify_batch`` ran 98 sequential ``self.llm.classify(...)`` calls
inside a single ``asyncio.to_thread`` worker.

The R4 fix adds ``classify_batch_async`` with bounded parallelism
(``LLM_CONCURRENCY=8``), a circuit breaker on consecutive failures,
and per-batch telemetry. These tests pin the load-bearing properties:

  1. Speedup — N parallel calls finish in ≈ wall-clock / concurrency.
  2. Circuit breaker — opens after 5 consecutive failures, skips the
     LLM hop until cooldown ends.
  3. Keyword-only short-circuit — high-confidence keyword results
     never reach the LLM.

Mocks: a fake ``LLMProvider`` lives next to the test (no transformer
or genai dependency). Keyword results are ``CategoryClassification``
fakes with controlled confidence so the threshold logic fires
deterministically.
"""

from __future__ import annotations

import asyncio
import time

import pytest
from imga_core.classifiers.base import CategoryClassifier
from imga_core.classifiers.hybrid import (
    CIRCUIT_BREAKER_FAIL_THRESHOLD,
    HybridClassifier,
)
from imga_core.llm.base import LLMProvider, LLMProviderError
from imga_core.models import CategoryClassification, LLMClassificationResult


# --- doubles ---------------------------------------------------------


class _StubKeyword(CategoryClassifier):
    """Keyword classifier that always returns the configured
    confidence — drives the hybrid threshold branches in tests."""

    def __init__(self, confidence: float, primary: str = "belirsiz") -> None:
        self._conf = confidence
        self._primary = primary

    def classify(self, text: str) -> CategoryClassification:
        return CategoryClassification(
            primary=self._primary,
            primary_confidence=self._conf,
            primary_matched_keywords=(),
            secondaries=(),
            method="keyword",
            requires_manual_review=False,
        )


class _SlowLLM(LLMProvider):
    """Sleeps in ``classify`` to simulate Gemini latency. Records
    every call so tests can assert call counts."""

    def __init__(self, delay_seconds: float = 0.1) -> None:
        self.delay = delay_seconds
        self.call_count = 0
        self.calls: list[str] = []

    def classify(
        self, text: str, available_categories: list[str]
    ) -> LLMClassificationResult:
        self.call_count += 1
        self.calls.append(text)
        time.sleep(self.delay)
        return LLMClassificationResult(
            primary=available_categories[0] if available_categories else "belirsiz",
            confidence=0.95,
            reasoning="stub",
            provider="stub",
            model="stub",
        )

    def health_check(self) -> bool:
        return True


class _FailingLLM(LLMProvider):
    """Raises every time. Drives the circuit-breaker test."""

    def __init__(self) -> None:
        self.call_count = 0

    def classify(
        self, text: str, available_categories: list[str]
    ) -> LLMClassificationResult:
        self.call_count += 1
        raise LLMProviderError("simulated outage")

    def health_check(self) -> bool:
        return False


# --- tests -----------------------------------------------------------


@pytest.mark.asyncio
async def test_classify_batch_async_parallelises_llm_fallback() -> None:
    """16 LLM-bound rows × 100ms each: 8-way parallel finishes in
    ~200ms (2 batches), sequential would take 1.6s."""
    keyword = _StubKeyword(confidence=0.3)  # always below threshold
    llm = _SlowLLM(delay_seconds=0.1)
    classifier = HybridClassifier(
        keyword_classifier=keyword,
        llm_provider=llm,
        confidence_threshold=0.7,
        available_categories=["a", "b"],
        llm_concurrency=8,
    )

    texts = [f"text {i}" for i in range(16)]
    start = time.monotonic()
    results = await classifier.classify_batch_async(texts)
    elapsed = time.monotonic() - start

    assert len(results) == 16
    assert llm.call_count == 16  # every row hit LLM
    # 16 calls × 100ms / 8-way = 200ms ideal; 0.5s margin for asyncio
    # scheduling + thread dispatch overhead.
    assert elapsed < 0.5, (
        f"Parallel LLM dispatch too slow: {elapsed:.3f}s "
        "(expected < 0.5s; sequential would be ~1.6s)"
    )
    # All rows merged with the LLM result, none left as
    # requires_manual_review.
    assert all(not r.requires_manual_review for r in results)
    assert all(r.method == "ensemble" for r in results)


@pytest.mark.asyncio
async def test_keyword_high_confidence_short_circuits_llm() -> None:
    """Keyword confidence at threshold ceiling means no LLM call —
    saves Gemini quota on demos with strong keyword matches
    (DEDAŞ-style)."""
    keyword = _StubKeyword(confidence=0.95)  # well above threshold
    llm = _SlowLLM(delay_seconds=10.0)  # would dominate wall-clock if hit
    classifier = HybridClassifier(
        keyword_classifier=keyword,
        llm_provider=llm,
        confidence_threshold=0.7,
        available_categories=["a"],
    )

    texts = [f"row {i}" for i in range(20)]
    start = time.monotonic()
    results = await classifier.classify_batch_async(texts)
    elapsed = time.monotonic() - start

    assert len(results) == 20
    assert llm.call_count == 0, (
        f"LLM was called {llm.call_count} times despite keyword "
        "confidence above threshold"
    )
    # Should land in milliseconds — pure keyword path.
    assert elapsed < 0.2


@pytest.mark.asyncio
async def test_classify_batch_async_no_llm_provider_marks_for_review() -> None:
    """When llm_provider is None, low-confidence rows surface for
    manual review instead of failing the batch."""
    keyword = _StubKeyword(confidence=0.3)
    classifier = HybridClassifier(
        keyword_classifier=keyword, llm_provider=None,
    )
    results = await classifier.classify_batch_async(["a", "b", "c"])
    assert len(results) == 3
    assert all(r.requires_manual_review for r in results)


@pytest.mark.asyncio
async def test_circuit_breaker_opens_after_consecutive_failures() -> None:
    """``CIRCUIT_BREAKER_FAIL_THRESHOLD`` consecutive LLM failures
    opens the circuit; subsequent rows in the same batch + the
    next batch within the cooldown window skip the LLM call
    entirely. (Sprint 9.0.5-A R7 lowered the threshold 5 -> 3, so
    this test reads the constant rather than hard-coding 5.)"""
    keyword = _StubKeyword(confidence=0.3)
    llm = _FailingLLM()
    classifier = HybridClassifier(
        keyword_classifier=keyword,
        llm_provider=llm,
        confidence_threshold=0.7,
        llm_concurrency=1,  # serialise so failure ordering is predictable
    )

    # First batch: triggers exactly enough failures to open the
    # circuit. Use threshold count so we know the breaker opens
    # mid-batch and the remaining rows skip the LLM.
    first_batch_size = CIRCUIT_BREAKER_FAIL_THRESHOLD + 3
    results = await classifier.classify_batch_async(
        [f"row {i}" for i in range(first_batch_size)]
    )
    assert len(results) == first_batch_size
    # Every result either came back from LLM (failed -> manual_review)
    # or was skipped due to circuit (manual_review). Either way the
    # flag is set.
    assert all(r.requires_manual_review for r in results)
    # LLM was called at most threshold times before the circuit
    # tripped — the rows that arrived after the trip skipped it
    # entirely.
    assert llm.call_count <= CIRCUIT_BREAKER_FAIL_THRESHOLD, (
        f"circuit breaker leaked: {llm.call_count} LLM calls vs "
        f"threshold {CIRCUIT_BREAKER_FAIL_THRESHOLD}"
    )

    # Second batch within the cooldown window: no LLM calls at all.
    pre_count = llm.call_count
    results2 = await classifier.classify_batch_async(["x", "y", "z"])
    assert len(results2) == 3
    assert all(r.requires_manual_review for r in results2)
    assert llm.call_count == pre_count, (
        "subsequent batch leaked LLM calls while circuit was open"
    )


@pytest.mark.asyncio
async def test_circuit_breaker_resets_on_success() -> None:
    """Sprint 9.0.5-A R4 — a string of failures shorter than the
    threshold doesn't trip the breaker; one success in between
    resets the counter so the next failure stretch starts fresh."""

    # Sprint 9.0.5-A R7 — fail count is parameterised on the
    # threshold constant so the test self-adjusts when R7 tightened
    # 5 -> 3. We need fewer failures than threshold so the breaker
    # never trips; one success then resets the counter.
    fail_count = max(1, CIRCUIT_BREAKER_FAIL_THRESHOLD - 1)

    class _FlakyLLM(LLMProvider):
        def __init__(self) -> None:
            self.call_count = 0
            self.fail_first_n = fail_count

        def classify(
            self, text: str, available_categories: list[str]
        ) -> LLMClassificationResult:
            self.call_count += 1
            if self.call_count <= self.fail_first_n:
                raise LLMProviderError("transient")
            return LLMClassificationResult(
                primary="ok",
                confidence=0.9,
                reasoning="",
                provider="stub",
                model="stub",
            )

        def health_check(self) -> bool:
            return True

    keyword = _StubKeyword(confidence=0.3)
    llm = _FlakyLLM()
    classifier = HybridClassifier(
        keyword_classifier=keyword,
        llm_provider=llm,
        confidence_threshold=0.7,
        llm_concurrency=1,
    )

    total_rows = 10
    results = await classifier.classify_batch_async(
        [f"r{i}" for i in range(total_rows)]
    )
    # fail_count fails (< threshold) + (total - fail_count) successes;
    # circuit never opens, all rows hit LLM, the trailing block
    # succeeds.
    assert llm.call_count == total_rows
    successes = [r for r in results if not r.requires_manual_review]
    assert len(successes) == total_rows - fail_count
    # Internal: counter is back to zero after the success run.
    assert classifier._consecutive_llm_failures == 0
    assert classifier._llm_circuit_open_until is None


@pytest.mark.asyncio
async def test_empty_text_skips_llm() -> None:
    """Whitespace-only rows can't carry useful signal for the LLM —
    they short-circuit to manual review without burning a call."""
    keyword = _StubKeyword(confidence=0.0)
    llm = _SlowLLM(delay_seconds=10.0)
    classifier = HybridClassifier(
        keyword_classifier=keyword, llm_provider=llm,
    )
    results = await classifier.classify_batch_async(["", "   ", "\t\n"])
    assert len(results) == 3
    assert llm.call_count == 0
    assert all(r.requires_manual_review for r in results)


@pytest.mark.asyncio
async def test_pipeline_analyze_batch_async_uses_async_classifier() -> None:
    """Pipeline.analyze_batch_async (R1) prefers classify_batch_async
    when available — verifies the wiring change in pipeline.py and
    catches a regression that drops back to the to_thread sync
    path (which would re-introduce the 161s sequential-LLM
    bottleneck)."""
    from imga_core import AnalysisPipeline
    from imga_core.analyzers.base import AnalyzerPrediction, SentimentAnalyzer
    from imga_core.config import LABEL_NEUTRAL

    class _StubAnalyzer(SentimentAnalyzer):
        def analyze_batch(
            self, texts: list[str]
        ) -> list[AnalyzerPrediction]:
            return [
                AnalyzerPrediction(label=LABEL_NEUTRAL, score=0.0)
                for _ in texts
            ]

    keyword = _StubKeyword(confidence=0.3)
    llm = _SlowLLM(delay_seconds=0.1)
    classifier = HybridClassifier(
        keyword_classifier=keyword,
        llm_provider=llm,
        confidence_threshold=0.7,
        llm_concurrency=8,
    )
    pipeline = AnalysisPipeline(analyzer=_StubAnalyzer(), classifier=classifier)

    texts = [f"text {i}" for i in range(16)]
    start = time.monotonic()
    results = await pipeline.analyze_batch_async(texts)
    elapsed = time.monotonic() - start

    assert len(results) == 16
    assert llm.call_count == 16
    # 16 × 100ms / 8 = 200ms LLM; +ε analyzer + assemble; <0.6s budget
    # comfortably above ideal but well below the 1.6s sequential
    # baseline regression would produce.
    assert elapsed < 0.6, (
        f"pipeline.analyze_batch_async appears to bypass the async "
        f"classifier path: elapsed={elapsed:.3f}s"
    )
