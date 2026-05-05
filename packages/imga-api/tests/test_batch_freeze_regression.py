"""Sprint 9.0.5-A B6 — freeze regression coverage.

Today's incident: a 2852-row CSV upload sat at processed_rows=0 for
21 minutes while the API container itself stopped serving /reviews
/ /insights. The proximate cause: ``pipeline.analyze_batch(...)`` is
a sync call into the transformers C extension; running it on the
event loop holds the loop until BERT finishes the entire batch.

The fix:
  * imga-core's ``AnalysisPipeline`` now exposes ``analyze_batch_async``
    which dispatches BERT + classifier work to threads via
    ``asyncio.to_thread`` and gathers — the loop stays free.
  * The batch worker (``_process_chunk``) calls the async variant.

These tests pin the *property* the fix establishes. They live as
unit tests against ``AnalysisPipeline`` so they don't need DB / HTTP
plumbing — just an event loop and a deliberately-slow stub
analyzer. If a future refactor reverts to a sync call, the
``test_event_loop_responsive_during_bert_inference`` ticker count
collapses to near zero and the freeze comes back.
"""

from __future__ import annotations

import asyncio
import time

import pytest
from imga_core import AnalysisPipeline, KeywordCategoryClassifier
from imga_core.analyzers.base import AnalyzerPrediction, SentimentAnalyzer
from imga_core.config import LABEL_NEUTRAL


class _SlowStubAnalyzer(SentimentAnalyzer):
    """Sleeps in ``analyze_batch`` to simulate the sync BERT C
    extension that doesn't yield to the loop."""

    def __init__(self, delay_seconds: float) -> None:
        self._delay = delay_seconds

    def analyze_batch(self, texts: list[str]) -> list[AnalyzerPrediction]:
        # Deliberate sync sleep — the whole point of this test is to
        # verify that asyncio.to_thread frees the loop while THIS
        # function holds a real OS thread.
        time.sleep(self._delay)
        return [
            AnalyzerPrediction(label=LABEL_NEUTRAL, score=0.0)
            for _ in texts
        ]


@pytest.mark.asyncio
async def test_event_loop_responsive_during_bert_inference() -> None:
    """B6 freeze regression. While the pipeline runs (sync sleep
    600ms), a concurrent ticker coroutine should still get many
    chances to run. If the loop is blocked the ticker count
    collapses to ≤ 1; with the async variant it runs hundreds of
    times."""
    pipeline = AnalysisPipeline(
        analyzer=_SlowStubAnalyzer(delay_seconds=0.6),
        classifier=KeywordCategoryClassifier(),
    )

    inference = asyncio.create_task(
        pipeline.analyze_batch_async(["yorum"] * 5)
    )

    tick_count = 0

    async def _ticker() -> None:
        nonlocal tick_count
        while not inference.done():
            tick_count += 1
            # Yield without sleeping so the loop's responsiveness is
            # what we're measuring (asyncio.sleep(0) is the textbook
            # way to give the scheduler a chance).
            await asyncio.sleep(0)

    ticker = asyncio.create_task(_ticker())
    results = await inference
    await ticker

    assert len(results) == 5
    # Conservative floor — on a hot loop with sleep(0) yields, this
    # is normally 10K+. We just need it to be obviously non-zero so
    # a regression that re-introduces the sync call (tick_count ≤ 1)
    # trips the assertion loudly.
    assert tick_count > 100, (
        f"event loop was blocked during BERT inference: tick_count="
        f"{tick_count} (expected > 100). The asyncio.to_thread wrap "
        "in AnalysisPipeline.analyze_batch_async likely regressed."
    )


@pytest.mark.asyncio
async def test_analyze_batch_async_returns_one_result_per_input() -> None:
    """Smoke: the async variant produces the same shape as the
    sync ``analyze_batch``. Sprint 9.0.5-A."""
    pipeline = AnalysisPipeline(
        analyzer=_SlowStubAnalyzer(delay_seconds=0.0),
        classifier=KeywordCategoryClassifier(),
    )
    results = await pipeline.analyze_batch_async(
        ["birinci yorum", "ikinci yorum", "üçüncü yorum"]
    )
    assert len(results) == 3
    assert all(r.text for r in results)
    # Categorization comes from the keyword classifier — fallback
    # bucket on these inputs but always present.
    assert all(r.categorization is not None for r in results)


@pytest.mark.asyncio
async def test_analyze_batch_async_empty_input() -> None:
    """Edge: empty input returns empty list, no thread dispatch."""
    pipeline = AnalysisPipeline(
        analyzer=_SlowStubAnalyzer(delay_seconds=0.0),
        classifier=KeywordCategoryClassifier(),
    )
    results = await pipeline.analyze_batch_async([])
    assert results == []


@pytest.mark.asyncio
async def test_analyze_batch_async_runs_analyzer_and_classifier_in_parallel() -> None:
    """B2 parallelism — when both analyzer and classifier each take
    ~D seconds, the total wall-clock should be ≤ ~D + small overhead,
    not ~2D (which sequential execution would produce). Conservative
    bound: total ≤ 1.6 × D."""
    delay = 0.4

    class _SlowClassifier:
        def classify(self, text: str) -> object:
            raise NotImplementedError

        def classify_batch(self, texts: list[str]) -> list[object]:
            time.sleep(delay)
            return [None] * len(texts)

    pipeline = AnalysisPipeline(
        analyzer=_SlowStubAnalyzer(delay_seconds=delay),
        classifier=_SlowClassifier(),  # type: ignore[arg-type]
    )

    start = time.monotonic()
    await pipeline.analyze_batch_async(["yorum"] * 3)
    elapsed = time.monotonic() - start

    # Sequential would be ~2 × delay = 0.8s; parallel ≈ 0.4s + jitter.
    assert elapsed < delay * 1.6, (
        f"analyze_batch_async appears to run analyzer + classifier "
        f"sequentially: elapsed={elapsed:.3f}s vs. expected "
        f"< {delay * 1.6:.3f}s for parallel execution"
    )
