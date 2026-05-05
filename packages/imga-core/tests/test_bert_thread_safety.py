"""Sprint 9.0.5-A R2 — BERT concurrent initialization regression.

Staging smoke surfaced a transformers ``_LazyModule`` race: under
Sprint 9.0.5-A B3 parallel chunk dispatch (4 worker threads each
constructing a BertSentimentAnalyzer + calling _ensure_loaded), the
method-level ``from transformers import pipeline`` raced — thread 1
held the lazy-module init, threads 2-4 saw an ImportError and the
entire batch crashed before a single review was inserted.

The fix:
  * imga_core.analyzers.bert moves ``from transformers import
    pipeline as hf_pipeline`` to module top level — lazy module
    init runs during the single-threaded module-load phase.
  * _PIPELINE_FACTORY_LOCK serialises the factory call itself
    (belt-and-suspenders against any internal race in transformers'
    model construction we don't know about).

This test pins the property by spawning N threads that each build
a fresh analyzer and call into _ensure_loaded concurrently. With
the fix in place all N succeed. Without it (method-level import +
no lock) the run trips ImportError on the threads that lost the
race.

The test imports a stub analyzer subclass that monkey-patches the
heavy ``hf_pipeline`` factory so we don't actually load BERT in
unit tests — the value being measured is the concurrent
initialisation contract, not the model loading itself.
"""

from __future__ import annotations

import threading
import time
from typing import Any
from unittest.mock import patch

import pytest
from imga_core.analyzers.bert import BertSentimentAnalyzer


def _fake_hf_pipeline(*_args: Any, **_kwargs: Any) -> Any:
    """Stand-in for ``transformers.pipeline``. Sleeps briefly so
    concurrent calls overlap inside the lock window. Returns a
    callable that mimics the HF Pipeline shape (``__call__``
    returning a list of dicts)."""
    time.sleep(0.05)

    def _runner(texts: list[str], **__: Any) -> list[dict[str, Any]]:
        return [{"label": "neutral", "score": 0.0} for _ in texts]

    return _runner


def test_concurrent_initialization_no_import_error() -> None:
    """Sprint 9.0.5-A R2 regression. 8 threads each build a fresh
    analyzer + force load. With the eager import + factory lock no
    thread sees an ImportError; all 8 land a working pipeline. The
    sleep in the fake factory ensures threads actually overlap
    inside the critical section so a regression that drops the
    lock would surface racing behaviour."""

    THREAD_COUNT = 8
    errors: list[BaseException] = []
    pipelines: list[Any] = []
    barrier = threading.Barrier(THREAD_COUNT)

    def _worker() -> None:
        try:
            barrier.wait(timeout=5.0)  # release all threads at once
            analyzer = BertSentimentAnalyzer()
            preds = analyzer.analyze_batch(["hızlı testi"])
            pipelines.append(preds)
        except BaseException as exc:  # noqa: BLE001 — capture for assertion
            errors.append(exc)

    with patch(
        "imga_core.analyzers.bert.hf_pipeline",
        side_effect=_fake_hf_pipeline,
    ):
        threads = [
            threading.Thread(target=_worker) for _ in range(THREAD_COUNT)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)

    assert errors == [], (
        f"concurrent BERT init raised: "
        f"{[type(e).__name__ + ': ' + str(e) for e in errors]}"
    )
    assert len(pipelines) == THREAD_COUNT, (
        f"only {len(pipelines)}/{THREAD_COUNT} threads completed — "
        "factory lock may have deadlocked or threads failed silently"
    )


def test_factory_lock_serialises_construction() -> None:
    """Sprint 9.0.5-A R2 — the factory lock is the belt to the
    eager-import suspenders. Verify it actually runs constructions
    sequentially: 4 fake factory calls each sleeping 100ms must
    take >= 380ms wall-clock under the lock (vs. ~100ms if the
    lock leaked + everything ran in parallel).
    """
    THREAD_COUNT = 4
    construction_times: list[float] = []
    lock = threading.Lock()

    def _slow_factory(*_args: Any, **_kwargs: Any) -> Any:
        time.sleep(0.1)
        with lock:
            construction_times.append(time.monotonic())
        return lambda texts, **__: [
            {"label": "neutral", "score": 0.0} for _ in texts
        ]

    barrier = threading.Barrier(THREAD_COUNT)

    def _worker() -> None:
        barrier.wait(timeout=5.0)
        analyzer = BertSentimentAnalyzer()
        analyzer.analyze_batch(["test"])

    start = time.monotonic()
    with patch(
        "imga_core.analyzers.bert.hf_pipeline",
        side_effect=_slow_factory,
    ):
        threads = [
            threading.Thread(target=_worker) for _ in range(THREAD_COUNT)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)
    elapsed = time.monotonic() - start

    assert len(construction_times) == THREAD_COUNT
    # Lock-serialised: 4 * 100ms = 400ms minimum (some scheduler
    # overhead is fine; we just need to disprove the unlocked-
    # parallel ~100ms case).
    assert elapsed >= 0.38, (
        f"factory lock leaked: 4 threads x 100ms factory completed "
        f"in {elapsed:.3f}s (expected >= 0.38s for serial execution)"
    )


@pytest.mark.parametrize("instances", [1, 4, 8])
def test_per_instance_pipeline_is_independent(instances: int) -> None:
    """Sprint 9.0.5-A R2 sanity — concurrent constructions yield
    DISTINCT pipeline instances (per-chunk model pattern is
    preserved). The lock serialises construction; it doesn't
    accidentally short-circuit to a shared singleton."""
    pipelines: list[Any] = []
    barrier = threading.Barrier(instances)

    def _worker() -> None:
        barrier.wait(timeout=5.0)
        analyzer = BertSentimentAnalyzer()
        analyzer.analyze_batch(["test"])
        pipelines.append(analyzer._pipeline)

    with patch(
        "imga_core.analyzers.bert.hf_pipeline",
        side_effect=_fake_hf_pipeline,
    ):
        threads = [threading.Thread(target=_worker) for _ in range(instances)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)

    assert len(pipelines) == instances
    # All distinct objects — no accidental sharing.
    assert len({id(p) for p in pipelines}) == instances
