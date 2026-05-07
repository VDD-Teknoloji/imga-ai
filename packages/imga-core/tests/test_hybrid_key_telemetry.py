"""Sprint 9.0.5-A R6 follow-up — key-usage telemetry coverage.

The R5 prompt asked for key-usage stats (which keys served the
batch, how many times the rotator fell through on rate-limit) and
both R5 and R6 deferred them. This file pins the contract that
finally landed:

  * ``RotatingGeminiProvider.get_batch_stats()`` returns cumulative
    counters since the provider was constructed.
  * The rate-limit counter increments when the rotator's operation
    closure surfaces a ``RateLimitError`` (either directly or
    via the legacy-message sniff in ``_maybe_rotate``).
  * ``HybridClassifier.classify_batch_async`` reads the stats and
    folds them into the per-batch INFO log line.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from imga_core.classifiers.hybrid import HybridClassifier
from imga_core.llm import RotatingGeminiProvider
from imga_core.llm.errors import RateLimitError
from imga_core.llm.key_rotation import GeminiKey
from imga_core.models import CategoryClassification, LLMClassificationResult


def _llm_result() -> LLMClassificationResult:
    return LLMClassificationResult(
        primary="ok",
        confidence=0.9,
        reasoning="stub",
        provider="gemini",
        model="gemini-2.5-flash",
    )


class _StubProvider:
    """Per-key behaviour stub. Tests configure ``behaviours`` keyed
    by api_key string before invoking the rotating provider."""

    behaviours: dict[str, Exception | LLMClassificationResult] = {}

    def __init__(self, api_key: str, model_name: str = "x", **_kw: object) -> None:
        self._key = api_key

    def classify(
        self, text: str, available_categories: list[str]
    ) -> LLMClassificationResult:
        outcome = self.behaviours.get(self._key)
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, LLMClassificationResult):
            return outcome
        return _llm_result()

    def health_check(self) -> bool:
        return True


@pytest.fixture
def stub_provider(monkeypatch: pytest.MonkeyPatch) -> type[_StubProvider]:
    _StubProvider.behaviours = {}
    monkeypatch.setattr(
        "imga_core.llm.rotating_gemini.GeminiProvider", _StubProvider
    )
    return _StubProvider


def _make_keys(*aliases: str) -> list[GeminiKey]:
    return [
        GeminiKey(id=f"id-{a}", value=f"key-{a}", label=a, priority=i)
        for i, a in enumerate(aliases)
    ]


# --- get_batch_stats counters ----------------------------------------


@pytest.mark.asyncio
async def test_get_batch_stats_starts_at_zero(
    stub_provider: type[_StubProvider],
) -> None:
    """A fresh provider reports nothing used / nothing rate-limited.
    Pinned so a future refactor that changes the field names trips
    the assertion."""
    rp = RotatingGeminiProvider(keys=_make_keys("solo"))
    stats = rp.get_batch_stats()
    assert stats == {
        "keys_used": 0,
        "rate_limit_events": 0,
        "keys_total": 1,
    }


@pytest.mark.asyncio
async def test_keys_used_records_winning_key(
    stub_provider: type[_StubProvider],
) -> None:
    """One successful call records exactly one entry in ``keys_used``."""
    rp = RotatingGeminiProvider(keys=_make_keys("primary"))
    await rp.classify_async("x", ["a"])
    assert rp.get_batch_stats()["keys_used"] == 1


@pytest.mark.asyncio
async def test_rate_limit_event_counter_increments_on_fall_through(
    stub_provider: type[_StubProvider],
) -> None:
    """Rotator falls through the primary on RateLimitError; the
    counter records each fall-through. Two-key setup with primary
    rate-limited produces 1 rate_limit_events + 1 keys_used (the
    fallback that succeeded)."""
    stub_provider.behaviours = {
        "key-primary": RateLimitError(),
        "key-fallback": _llm_result(),
    }
    rp = RotatingGeminiProvider(keys=_make_keys("primary", "fallback"))
    await rp.classify_async("x", ["a"])
    stats = rp.get_batch_stats()
    assert stats["rate_limit_events"] == 1
    assert stats["keys_used"] == 1  # only the fallback served
    assert stats["keys_total"] == 2


@pytest.mark.asyncio
async def test_reset_batch_stats_clears_counters(
    stub_provider: type[_StubProvider],
) -> None:
    """Explicit reset zeroes the cumulative state so a future
    scheduler that reuses providers across jobs can scope
    telemetry correctly."""
    rp = RotatingGeminiProvider(keys=_make_keys("k1"))
    await rp.classify_async("x", ["a"])
    assert rp.get_batch_stats()["keys_used"] == 1
    rp.reset_batch_stats()
    stats = rp.get_batch_stats()
    assert stats["keys_used"] == 0
    assert stats["rate_limit_events"] == 0


# --- HybridClassifier batch summary log ------------------------------


class _LowConfidenceKeyword:
    """Keyword stub that always trips the LLM fallback threshold."""

    def classify(self, text: str) -> CategoryClassification:
        return CategoryClassification(
            primary="belirsiz",
            primary_confidence=0.1,
            primary_matched_keywords=(),
            secondaries=(),
            method="keyword",
            requires_manual_review=False,
        )

    def classify_batch(
        self, texts: list[str]
    ) -> list[CategoryClassification]:
        return [self.classify(t) for t in texts]


@pytest.mark.asyncio
async def test_batch_summary_log_includes_key_usage_for_rotating_provider(
    caplog: pytest.LogCaptureFixture,
    stub_provider: type[_StubProvider],
) -> None:
    """Sprint 9.0.5-A R6 follow-up — when the LLM provider exposes
    ``get_batch_stats``, HybridClassifier folds the values into the
    per-batch INFO summary log so an operator tailing journalctl
    sees rotator fan-out alongside the timing breakdown."""
    rp = RotatingGeminiProvider(keys=_make_keys("k1", "k2"))
    classifier = HybridClassifier(
        keyword_classifier=_LowConfidenceKeyword(),  # type: ignore[arg-type]
        llm_provider=rp,
        confidence_threshold=0.7,
        llm_concurrency=2,
    )

    with caplog.at_level(logging.INFO, logger="imga_core.classifiers.hybrid"):
        await classifier.classify_batch_async(["a", "b", "c"])

    summary_records = [
        r for r in caplog.records
        if "HybridClassifier batch" in r.getMessage()
    ]
    assert summary_records, "expected one HybridClassifier batch INFO log"
    msg = summary_records[-1].getMessage()
    assert "keys_used=" in msg, msg
    assert "/2" in msg, msg  # keys_total denominator
    assert "rate_limit_events=" in msg, msg


@pytest.mark.asyncio
async def test_batch_summary_log_omits_key_fields_for_legacy_provider(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Single-key GeminiProvider (or any LLMProvider without
    ``get_batch_stats``) should still produce a clean batch summary
    log — the key fields just drop, no exception, no `keys_used=0`
    noise."""
    from imga_core.llm.base import LLMProvider

    class _LegacyProvider(LLMProvider):
        def classify(
            self, text: str, available_categories: list[str]
        ) -> LLMClassificationResult:
            return _llm_result()

        def health_check(self) -> bool:
            return True

    classifier = HybridClassifier(
        keyword_classifier=_LowConfidenceKeyword(),  # type: ignore[arg-type]
        llm_provider=_LegacyProvider(),
        confidence_threshold=0.7,
        llm_concurrency=1,
    )

    with caplog.at_level(logging.INFO, logger="imga_core.classifiers.hybrid"):
        await classifier.classify_batch_async(["x"])

    summary_records = [
        r for r in caplog.records
        if "HybridClassifier batch" in r.getMessage()
    ]
    assert summary_records
    msg = summary_records[-1].getMessage()
    # Legacy provider has no get_batch_stats, so the key suffix is
    # absent. The rest of the line stays intact.
    assert "keys_used" not in msg
    assert "rate_limit_events" not in msg
    assert "mode=" in msg


@pytest.mark.asyncio
async def test_batch_summary_log_handles_provider_stats_exception(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A buggy provider raising from ``get_batch_stats`` shouldn't
    take down the batch — HybridClassifier logs the failure and
    drops the key fields gracefully."""
    from imga_core.llm.base import LLMProvider

    class _ExplodingStatsProvider(LLMProvider):
        def classify(
            self, text: str, available_categories: list[str]
        ) -> LLMClassificationResult:
            return _llm_result()

        def get_batch_stats(self) -> dict[str, int]:
            raise RuntimeError("stats path is broken")

        def health_check(self) -> bool:
            return True

    classifier = HybridClassifier(
        keyword_classifier=_LowConfidenceKeyword(),  # type: ignore[arg-type]
        llm_provider=_ExplodingStatsProvider(),
        confidence_threshold=0.7,
        llm_concurrency=1,
    )

    with caplog.at_level(
        logging.DEBUG, logger="imga_core.classifiers.hybrid"
    ):
        results = await classifier.classify_batch_async(["x"])

    assert len(results) == 1
    msgs = [r.getMessage() for r in caplog.records]
    # The stats failure logs exception; the batch summary still emits.
    assert any("failed to read provider batch stats" in m for m in msgs)
    assert any("HybridClassifier batch" in m for m in msgs)


def _assert(condition: bool, message: str) -> None:  # pragma: no cover
    """Helper kept around in case a future test wants it without
    pytest's ``assert``-rewriting noise."""
    assert condition, message


_ = Any  # silence unused-import noise on the typing alias
