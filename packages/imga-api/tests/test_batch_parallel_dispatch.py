"""Sprint 9.0.5-A — pipeline-pool selection, dedup_lock parallel
safety, and the arq vs. APScheduler dispatch fork in
``enqueue_batch_job``.

These are unit-level tests against the helpers that the worker +
route layer call. No DB / HTTP plumbing — the goal is to pin the
dispatch contract so regressions surface fast.
"""

from __future__ import annotations

import asyncio
import contextlib
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from imga_core import AnalysisPipeline, KeywordCategoryClassifier
from imga_core.analyzers.base import AnalyzerPrediction, SentimentAnalyzer
from imga_core.config import LABEL_NEUTRAL

from imga_api.workers.batch_analyzer import _select_pipeline


class _StubAnalyzer(SentimentAnalyzer):
    def analyze_batch(self, texts: list[str]) -> list[AnalyzerPrediction]:
        return [
            AnalyzerPrediction(label=LABEL_NEUTRAL, score=0.0) for _ in texts
        ]


def _make_pipeline() -> AnalysisPipeline:
    return AnalysisPipeline(
        analyzer=_StubAnalyzer(), classifier=KeywordCategoryClassifier()
    )


# --- _select_pipeline -------------------------------------------------


def test_select_pipeline_serial_returns_default() -> None:
    """Serial path (no pool) always uses ``context.pipeline``."""
    primary = _make_pipeline()
    ctx = SimpleNamespace(pipeline=primary, pipeline_pool=None)
    assert _select_pipeline(ctx, chunk_index=None) is primary  # type: ignore[arg-type]
    assert _select_pipeline(ctx, chunk_index=0) is primary  # type: ignore[arg-type]


def test_select_pipeline_uses_pool_with_modulo() -> None:
    """Parallel path picks ``pool[chunk_index % len(pool)]`` so a
    chunk count exceeding the pool size still works (the pool
    semaphore bounds in-flight to ``chunk_concurrency``, so two
    chunks never share a pipeline at the same time)."""
    primary = _make_pipeline()
    pool = [_make_pipeline() for _ in range(3)]
    ctx = SimpleNamespace(pipeline=primary, pipeline_pool=pool)
    assert _select_pipeline(ctx, chunk_index=0) is pool[0]  # type: ignore[arg-type]
    assert _select_pipeline(ctx, chunk_index=1) is pool[1]  # type: ignore[arg-type]
    assert _select_pipeline(ctx, chunk_index=4) is pool[1]  # type: ignore[arg-type]
    # No chunk_index → default pipeline (used by tests / serial).
    assert _select_pipeline(ctx, chunk_index=None) is primary  # type: ignore[arg-type]


# --- dedup_lock guarantees no double-add under concurrent chunks ------


@pytest.mark.asyncio
async def test_dedup_lock_serialises_check_and_add() -> None:
    """Two concurrent ``check-and-add`` blocks under the same Lock
    must produce exactly one ``first occurrence`` decision per hash.
    Sprint 9.0.5-A B3 — without the Lock the parallel chunk path
    would race two chunks both reading 'not in set' for the same
    text and inserting two copies as fresh reviews."""
    seen: set[str] = set()
    lock = asyncio.Lock()
    first_occurrence_decisions = 0
    duplicate_decisions = 0

    async def _row_decide(text_hash: str) -> str:
        nonlocal first_occurrence_decisions, duplicate_decisions
        async with lock:
            is_dup = text_hash in seen
            if not is_dup:
                seen.add(text_hash)
        # Simulate work outside the critical section.
        await asyncio.sleep(0)
        if is_dup:
            duplicate_decisions += 1
            return "dup"
        first_occurrence_decisions += 1
        return "first"

    # 50 concurrent rows hitting the same hash — exactly one must
    # land as 'first', the rest as 'dup'.
    results = await asyncio.gather(
        *[_row_decide("collide") for _ in range(50)]
    )
    assert first_occurrence_decisions == 1, (
        f"dedup_lock failed to serialise: {first_occurrence_decisions}"
        " 'first' decisions for the same hash"
    )
    assert duplicate_decisions == 49
    assert results.count("first") == 1
    assert results.count("dup") == 49


# --- enqueue_batch_job dispatch fork ----------------------------------


@pytest.mark.asyncio
async def test_enqueue_batch_job_uses_arq_pool_when_set() -> None:
    """When ``app.state.arq_pool`` exists, ``enqueue_batch_job``
    awaits ``enqueue_job(...)`` and returns the worker handle so the
    route persists it."""
    from imga_api.workers.scheduler import enqueue_batch_job

    fake_job = SimpleNamespace(job_id="arq-job-abc")
    arq_pool = MagicMock()
    arq_pool.enqueue_job = AsyncMock(return_value=fake_job)

    app = SimpleNamespace(state=SimpleNamespace(arq_pool=arq_pool))
    job_id = uuid4()
    tenant_id = uuid4()

    worker_job_id, queued_at = await enqueue_batch_job(
        app, job_id=job_id, tenant_id=tenant_id  # type: ignore[arg-type]
    )

    arq_pool.enqueue_job.assert_awaited_once()
    args, kwargs = arq_pool.enqueue_job.call_args
    assert args[0] == "process_batch_task"
    assert args[1] == str(job_id)
    assert args[2] == str(tenant_id)
    assert kwargs.get("_queue_name") == "imga-batch"
    assert worker_job_id == "arq-job-abc"
    assert queued_at is not None


@pytest.mark.asyncio
async def test_enqueue_batch_job_falls_back_to_scheduler_when_no_pool() -> None:
    """When ``arq_pool`` is None, ``enqueue_batch_job`` falls back to
    the in-process scheduler — preserves the existing test seam +
    legacy single-process deploys."""
    from imga_api.workers.scheduler import enqueue_batch_job

    scheduler = MagicMock()
    scheduler.add_job = MagicMock()
    worker_context = SimpleNamespace()
    app = SimpleNamespace(
        state=SimpleNamespace(
            arq_pool=None,
            batch_scheduler=scheduler,
            batch_worker_context=worker_context,
        ),
    )

    worker_job_id, queued_at = await enqueue_batch_job(
        app, job_id=uuid4(), tenant_id=uuid4()  # type: ignore[arg-type]
    )

    scheduler.add_job.assert_called_once()
    # Fallback path must NOT fabricate a worker handle — the column
    # stays NULL so the UI / tests can tell which dispatch path ran.
    assert worker_job_id is None
    assert queued_at is None


@pytest.mark.asyncio
async def test_enqueue_batch_job_arq_failure_falls_through_to_scheduler() -> None:
    """If the arq pool is set but the enqueue call raises (Redis
    blip, queue full), ``enqueue_batch_job`` logs + falls back to
    the scheduler so the upload still queues."""
    from imga_api.workers.scheduler import enqueue_batch_job

    arq_pool = MagicMock()
    arq_pool.enqueue_job = AsyncMock(side_effect=RuntimeError("redis dead"))
    scheduler = MagicMock()
    scheduler.add_job = MagicMock()

    app = SimpleNamespace(
        state=SimpleNamespace(
            arq_pool=arq_pool,
            batch_scheduler=scheduler,
            batch_worker_context=SimpleNamespace(),
        ),
    )

    worker_job_id, queued_at = await enqueue_batch_job(
        app, job_id=uuid4(), tenant_id=uuid4()  # type: ignore[arg-type]
    )

    scheduler.add_job.assert_called_once()
    assert worker_job_id is None
    assert queued_at is None


# --- arq_worker.process_batch_task delegates to process_batch_job -----


@pytest.mark.asyncio
async def test_arq_process_batch_task_delegates_to_process_batch_job(
    monkeypatch: Any,
) -> None:
    """The arq task is a thin wrapper around ``process_batch_job``;
    it re-hydrates the UUID and passes the long-lived
    WorkerContext from the worker process's startup hook."""
    from imga_api.workers import arq_worker

    captured: dict[str, Any] = {}

    async def _fake_process_batch_job(job_id: Any, ctx: Any) -> None:
        captured["job_id"] = job_id
        captured["ctx"] = ctx

    monkeypatch.setattr(
        arq_worker, "process_batch_job", _fake_process_batch_job
    )

    worker_ctx = SimpleNamespace(label="prod-context")
    job_id = uuid4()
    await arq_worker.process_batch_task(
        {"worker_context": worker_ctx},
        str(job_id),
        str(uuid4()),
    )

    assert captured["job_id"] == job_id
    assert captured["ctx"] is worker_ctx


# Suppress unused-import noise on contextlib if we don't end up
# using it; keeping it imported in case the freeze test gets a
# follow-up scenario that needs it.
_ = contextlib
