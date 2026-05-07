"""Sprint 9.0.5-A R6 — async + global-concurrency regression tests.

R5 incident: ``RotatingGeminiProvider.classify_async`` was declared
``async def`` but its rotator-operation closure never awaited
anything — the sync ``provider.classify`` call ran inline, holding
the event loop for the full Gemini round-trip. Result: peer LLM
tasks in HybridClassifier's batch path serialised behind each other
and the demo measured 165s on a 98-row LLM-bound batch despite the
8-way semaphore.

Two regressions are pinned here:

  1. ``classify_async`` actually yields the loop while the SDK call
     runs. The rotator-operation closure now wraps
     ``provider.classify`` in ``asyncio.to_thread`` so peer tasks
     actually overlap. The test uses a stub provider with a real
     ``time.sleep`` inside ``classify`` (not ``asyncio.sleep``) so
     a regression that drops the to_thread wrap shows up as a 4×
     wall-clock blow-up.

  2. HybridClassifier's LLM concurrency cap is per-instance, not
     per-call. R5's ``classify_batch_async`` constructed a fresh
     Semaphore inside the method, so two parallel batches on the
     same classifier doubled the in-flight ceiling. With the R6
     instance-level semaphore, two batches share one cap.
"""

from __future__ import annotations

import asyncio
import time

import pytest
from imga_core.classifiers.hybrid import HybridClassifier
from imga_core.llm import RotatingGeminiProvider
from imga_core.llm.base import LLMProvider
from imga_core.llm.key_rotation import GeminiKey
from imga_core.models import CategoryClassification, LLMClassificationResult


def _result() -> LLMClassificationResult:
    return LLMClassificationResult(
        primary="ok",
        confidence=0.9,
        reasoning="stub",
        provider="gemini",
        model="gemini-2.5-flash",
    )


class _BlockingStubProvider:
    """Mimics GeminiProvider but ``classify`` does a real
    ``time.sleep`` to model the SDK's blocking
    ``generate_content`` call."""

    def __init__(self, api_key: str, model_name: str = "x", **_kw: object) -> None:
        self._key = api_key

    def classify(
        self, text: str, available_categories: list[str]
    ) -> LLMClassificationResult:
        time.sleep(0.1)
        return _result()

    def health_check(self) -> bool:
        return True


@pytest.mark.asyncio
async def test_classify_async_yields_loop_via_to_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sprint 9.0.5-A R6 freeze regression for the classifier path.

    Four concurrent calls × 100ms blocking sleep each must finish in
    ~100-200ms with the to_thread wrap (each call runs in its own
    thread, all overlap). Without the wrap they serialise at ~400ms.

    The threshold is 0.3s — comfortably above the parallel ideal
    plus thread-pool overhead, well below the regression case.
    """
    monkeypatch.setattr(
        "imga_core.llm.rotating_gemini.GeminiProvider",
        _BlockingStubProvider,
    )

    keys = [GeminiKey(id="k1", value="key", label="solo", priority=0)]
    rp = RotatingGeminiProvider(keys=keys)

    start = time.monotonic()
    results = await asyncio.gather(
        *[rp.classify_async(f"text {i}", ["a", "b"]) for i in range(4)]
    )
    elapsed = time.monotonic() - start

    assert len(results) == 4
    assert elapsed < 0.3, (
        f"RotatingGeminiProvider.classify_async appears to block the "
        f"event loop: 4 × 100ms ran in {elapsed:.3f}s "
        "(expected < 0.3s for true parallel via to_thread)"
    )


# --- HybridClassifier instance-level semaphore -----------------------


class _CountingLLM(LLMProvider):
    """Tracks concurrent in-flight calls so a test can assert the
    semaphore actually caps them."""

    def __init__(self, delay: float = 0.05) -> None:
        self.delay = delay
        self._concurrent = 0
        self._peak_concurrent = 0
        self._lock = asyncio.Lock()
        self.call_count = 0

    @property
    def peak_concurrent(self) -> int:
        return self._peak_concurrent

    def classify(
        self, text: str, available_categories: list[str]
    ) -> LLMClassificationResult:  # pragma: no cover — async path used
        return _result()

    async def classify_async(
        self, text: str, available_categories: list[str]
    ) -> LLMClassificationResult:
        async with self._lock:
            self._concurrent += 1
            if self._concurrent > self._peak_concurrent:
                self._peak_concurrent = self._concurrent
            self.call_count += 1
        try:
            await asyncio.sleep(self.delay)
        finally:
            async with self._lock:
                self._concurrent -= 1
        return _result()

    def health_check(self) -> bool:
        return True


@pytest.mark.asyncio
async def test_instance_level_semaphore_shared_across_batches() -> None:
    """Sprint 9.0.5-A R6 — two parallel ``classify_batch_async``
    calls on the SAME HybridClassifier must share the LLM
    semaphore. With the cap set to 4 and two simultaneous batches
    of 6 LLM-fallback rows each (12 total), peak in-flight should
    be exactly 4, not 8."""

    class _AlwaysLowConfidenceKeyword:
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

    llm = _CountingLLM(delay=0.05)
    classifier = HybridClassifier(
        keyword_classifier=_AlwaysLowConfidenceKeyword(),  # type: ignore[arg-type]
        llm_provider=llm,
        confidence_threshold=0.7,
        llm_concurrency=4,
    )

    batch_a = [f"a-{i}" for i in range(6)]
    batch_b = [f"b-{i}" for i in range(6)]

    await asyncio.gather(
        classifier.classify_batch_async(batch_a),
        classifier.classify_batch_async(batch_b),
    )

    assert llm.call_count == 12
    assert llm.peak_concurrent <= 4, (
        f"instance-level semaphore leaked: peak {llm.peak_concurrent} "
        "concurrent LLM calls vs. cap 4. Two batches must share."
    )


@pytest.mark.asyncio
async def test_per_call_semaphore_would_let_concurrency_double() -> None:
    """Counter-test: build TWO HybridClassifier instances (each with
    its own cap) and run them in parallel — the semaphores are
    independent, so peak concurrency is the sum, not the cap. This
    pins the 'one classifier per job' contract: if you want
    job-level global concurrency you must reuse one classifier
    instance, not build a fresh one per batch."""

    class _AlwaysLowConfidenceKeyword:
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

    llm = _CountingLLM(delay=0.05)
    cls_a = HybridClassifier(
        keyword_classifier=_AlwaysLowConfidenceKeyword(),  # type: ignore[arg-type]
        llm_provider=llm,
        confidence_threshold=0.7,
        llm_concurrency=4,
    )
    cls_b = HybridClassifier(
        keyword_classifier=_AlwaysLowConfidenceKeyword(),  # type: ignore[arg-type]
        llm_provider=llm,
        confidence_threshold=0.7,
        llm_concurrency=4,
    )

    await asyncio.gather(
        cls_a.classify_batch_async([f"a-{i}" for i in range(6)]),
        cls_b.classify_batch_async([f"b-{i}" for i in range(6)]),
    )

    # Two independent caps -> peak can rise above 4 (up to 8). We
    # assert > 4 to lock in that DIFFERENT instances do not share —
    # the contract being tested is "shared cap requires shared
    # instance", not the converse.
    assert llm.peak_concurrent > 4, (
        f"distinct classifiers unexpectedly capped peak at "
        f"{llm.peak_concurrent} — semaphores look shared somehow"
    )


# --- chunk_size default ---------------------------------------------


def test_default_chunk_size_is_200() -> None:
    """Sprint 9.0.5-A R6 — chunk_size default lowered 1000 -> 200
    so a 2852-row LLM-bound run commits progress every ~30s instead
    of every ~9min. Pinning the constant directly so a future
    refactor that touches the field can't silently raise it back to
    1000 without explicit acknowledgement."""
    from imga_api.settings import BatchSettings

    assert BatchSettings().chunk_size == 200

    # And the env-driven path agrees when no override is set.
    import os

    original = os.environ.pop("IMGA_BATCH_CHUNK_SIZE", None)
    try:
        from imga_api.settings import Settings

        s = Settings.from_env()
        assert s.batch.chunk_size == 200
    finally:
        if original is not None:
            os.environ["IMGA_BATCH_CHUNK_SIZE"] = original
