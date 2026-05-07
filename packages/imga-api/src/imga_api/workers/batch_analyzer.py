"""Async batch upload worker.

Sprint 8.3.1. ``process_batch_job`` is the entrypoint scheduled by
APScheduler: when ``POST /tenants/me/analyze/batch`` finishes writing
the file + creating the queued job row, it calls
``submit_batch_job(scheduler, job_id)`` which adds an immediate-fire
date trigger.

Concurrency is in-memory:

  * ``_GLOBAL_SEMAPHORE`` — server-wide simultaneous job count
    (default 2). BERT inference is CPU-bound; running too many
    parallel jobs sandbags everyone.
  * ``_TENANT_LOCKS`` — per-tenant ``asyncio.Lock`` so a tenant's
    second upload waits for the first to finish. The lock is held
    across the entire run; queued jobs sit in QUEUED status with
    waiters lined up FIFO inside ``Lock.acquire``.

Single-API-instance assumption: the in-memory locks don't survive
container restarts or multi-instance deployments. ``recover_orphans``
runs at lifespan start and re-queues any jobs left in PROCESSING from
a crashed previous run; multi-instance support (advisory locks)
lands in Sprint 9.

Cancellation: the worker calls ``BatchAnalyzeService.is_cancelled``
at every chunk boundary. A user hitting DELETE flips the status to
CANCELLED and the worker bails on the next check (max one chunk's
worth of latency).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

from imga_core import (
    AnalysisPipeline,
    AnalysisResult,
    CategoryClassifier,
    HybridClassifier,
    KeywordCategoryClassifier,
)
from imga_core.categorizers import TaxonomyEntry, apply_company_heuristic
from imga_core.llm import RotatingGeminiProvider
from imga_db import create_engine, create_session_factory, set_current_tenant
from imga_db.models import (
    AnalyzeBatchJob,
    BatchJobStatus,
    CategoryTaxonomy,
    Review,
    ReviewDecision,
)
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from imga_api.services.audit_service import AuditService
from imga_api.services.batch_service import (
    BatchAnalyzeService,
    BatchProgress,
)
from imga_api.services.review_service import ReviewService
from imga_api.services.tenant_config_service import TenantConfigService
from imga_api.services.ticket_service import TicketService
from imga_api.settings import BatchSettings
from imga_api.workers.file_parser import (
    FileParseError,
    UnknownColumnError,
    iter_rows,
    peek_detected_nps_column,
)

if TYPE_CHECKING:
    from cachetools import TTLCache

log = logging.getLogger("imga-api.workers.batch")


# ---------------------------------------------------------------------------
# Worker context — built once per job, NOT per chunk.
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class WorkerContext:
    """Plumbing the worker grabs from app state once per job.

    Owns BOTH engines AND concurrency primitives (semaphore + per-tenant
    locks). asyncio.Lock / asyncio.Semaphore bind to the event loop that
    first awaits them, so module-level globals leaked across pytest's
    function-scoped loops and tripped 'got Future attached to a different
    loop' on cleanup. Putting them on the context that's built per
    lifespan (prod) or per test (pytest) keeps everything on one loop.

    Production wires one context per app process via the FastAPI lifespan;
    tests build a fresh one per test (see ``run_worker`` helper).

    Sprint 9.0.5-A additions (all optional, defaults preserve existing
    serial behaviour so the test seam stays untouched):

      * ``pipeline_pool`` — N pre-built ``AnalysisPipeline`` instances
        for ``chunk_concurrency``-way parallel BERT inference. The HF
        pipeline isn't thread-safe, so each parallel chunk needs its
        own model. ``None`` falls back to the single ``pipeline``
        instance (serial path the legacy tests exercise).
      * ``chunk_concurrency`` — max chunks running BERT inference at
        once. 1 = serial. Production defaults to 4 (matches the
        per-chunk model budget vs. the 3 GiB api container ceiling).
      * ``chunk_pool_semaphore`` — bounds the parallel chunks. Built
        on construction so it binds to the right event loop.
      * ``dedup_lock`` — guards the per-job ``seen_hashes`` set when
        chunks run in parallel (CPython set ops aren't atomic across
        await boundaries; a Lock is plenty since the critical section
        is two dict ops per row and BERT inference dwarfs it).
      * ``redis_publisher`` — Redis client for SSE progress publish.
        ``None`` skips the pub/sub call (test path).
    """

    pipeline: AnalysisPipeline
    admin_engine: AsyncEngine
    app_engine: AsyncEngine
    admin_session_factory: async_sessionmaker[AsyncSession]
    app_session_factory: async_sessionmaker[AsyncSession]
    tenant_config_cache: TTLCache[UUID, dict[str, Any]]
    settings: BatchSettings
    global_semaphore: asyncio.Semaphore
    tenant_locks: dict[UUID, asyncio.Lock]
    # Sprint 9.0.5-A additions
    pipeline_pool: list[AnalysisPipeline] | None = None
    chunk_concurrency: int = 1
    chunk_pool_semaphore: asyncio.Semaphore | None = None
    dedup_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    redis_publisher: Any | None = None

    def lock_for(self, tenant_id: UUID) -> asyncio.Lock:
        """Per-tenant Lock cache. Returns the same Lock for repeated
        calls within the context's lifetime; binds to the current loop
        on first await."""
        lock = self.tenant_locks.get(tenant_id)
        if lock is None:
            lock = asyncio.Lock()
            self.tenant_locks[tenant_id] = lock
        return lock

    async def dispose(self) -> None:
        """Close both engines' connection pools. Lifespan calls this
        on shutdown; tests call it on fixture teardown so the next
        test's event loop starts with no asyncpg connections bound to
        a dead loop. Safe to call twice (engine.dispose is idempotent
        on disposed engines)."""
        await self.admin_engine.dispose()
        await self.app_engine.dispose()


async def build_worker_context(
    *,
    pipeline: AnalysisPipeline,
    tenant_config_cache: TTLCache[UUID, dict[str, Any]],
    settings: BatchSettings,
    pipeline_pool: list[AnalysisPipeline] | None = None,
    chunk_concurrency: int = 1,
    redis_publisher: Any | None = None,
) -> WorkerContext:
    """Build a fresh WorkerContext, including its own engine pair AND
    its own concurrency primitives.

    Both engines and the Semaphore bind to the asyncpg event loop active
    at construction time. That's exactly what we want — the lifespan's
    loop in prod, the test's loop in pytest. Earlier iterations carried
    these as module-level singletons (engines, Semaphore, init-Lock) and
    every layer broke pytest isolation in turn: the first test's loop
    owned the primitives, every subsequent test got either 'another
    operation is in progress' (engines) or 'Future attached to a
    different loop' (semaphore / lock).

    Sprint 9.0.5-A — when ``pipeline_pool`` is non-None, the worker
    runs up to ``chunk_concurrency`` chunks in parallel with one model
    instance per chunk. Default ``None`` + ``chunk_concurrency=1``
    keeps the legacy serial path so the existing test fixture
    (``run_worker``) doesn't have to change.
    """
    admin_engine = create_engine("admin")
    app_engine = create_engine("app")
    effective_concurrency = max(1, chunk_concurrency)
    pool_semaphore: asyncio.Semaphore | None = None
    if pipeline_pool is not None and effective_concurrency > 1:
        pool_semaphore = asyncio.Semaphore(effective_concurrency)
    return WorkerContext(
        pipeline=pipeline,
        admin_engine=admin_engine,
        app_engine=app_engine,
        admin_session_factory=create_session_factory(admin_engine),
        app_session_factory=create_session_factory(app_engine),
        tenant_config_cache=tenant_config_cache,
        settings=settings,
        global_semaphore=asyncio.Semaphore(settings.global_concurrency),
        tenant_locks={},
        pipeline_pool=pipeline_pool,
        chunk_concurrency=effective_concurrency,
        chunk_pool_semaphore=pool_semaphore,
        dedup_lock=asyncio.Lock(),
        redis_publisher=redis_publisher,
    )


def _select_pipeline(
    context: WorkerContext, *, chunk_index: int | None
) -> AnalysisPipeline:
    """Pick the AnalysisPipeline a chunk should run BERT through.

    Sprint 9.0.5-A. Serial path (or anything without a pool) gets
    ``context.pipeline``. Parallel path picks ``pool[chunk_index %
    len(pool)]`` so the modulo handles the case where chunk count
    exceeds pool size (the pool semaphore still bounds in-flight work
    to ``chunk_concurrency``, so two chunks never share a pipeline at
    the same time).
    """
    pool = context.pipeline_pool
    if pool is None or chunk_index is None or not pool:
        return context.pipeline
    return pool[chunk_index % len(pool)]


# ---------------------------------------------------------------------------
# Main entry — one call per scheduled job
# ---------------------------------------------------------------------------


async def process_batch_job(job_id: UUID, context: WorkerContext) -> None:
    """Pick up a queued job, run it to completion / cancellation /
    failure. Idempotent on retries because the QUEUED → PROCESSING
    transition is guarded inside BatchAnalyzeService."""
    # Step 1 — read tenant_id (admin session, no RLS bind needed).
    tenant_id = await _read_tenant_id(job_id, context.admin_session_factory)
    if tenant_id is None:
        log.warning("batch worker: job %s missing or already gone", job_id)
        return

    # Step 2 — wait for both concurrency tickets. Both primitives are
    # owned by the context (so they bind to the loop the context was
    # built on; tests construct a fresh context per call to keep loop
    # ownership consistent).
    async with context.global_semaphore, context.lock_for(tenant_id):
        log.info("batch worker: starting job %s (tenant %s)", job_id, tenant_id)
        try:
            await _run_job(job_id, tenant_id, context)
        except Exception as exc:
            log.exception("batch worker: job %s crashed: %s", job_id, exc)
            await _record_catastrophic_failure(
                job_id, tenant_id, context, reason=str(exc)
            )


async def _read_tenant_id(
    job_id: UUID,
    factory: async_sessionmaker[AsyncSession],
) -> UUID | None:
    async with factory() as session, session.begin():
        stmt = select(AnalyzeBatchJob.tenant_id).where(
            AnalyzeBatchJob.id == job_id
        )
        return (await session.execute(stmt)).scalar_one_or_none()


async def _record_catastrophic_failure(
    job_id: UUID,
    tenant_id: UUID,
    context: WorkerContext,
    *,
    reason: str,
) -> None:
    async with context.admin_session_factory() as session, session.begin():
        await set_current_tenant(session, tenant_id)
        audit = AuditService(session)
        service = BatchAnalyzeService(session, audit)
        try:
            await service.mark_failed(job_id, reason=reason)
        except Exception:
            log.exception("could not mark job %s failed", job_id)


# ---------------------------------------------------------------------------
# Inner loop — per chunk
# ---------------------------------------------------------------------------


def _chunked(iterable: Iterable[Any], size: int) -> Iterator[list[Any]]:
    chunk: list[Any] = []
    for item in iterable:
        chunk.append(item)
        if len(chunk) >= size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


async def _run_job(
    job_id: UUID,
    tenant_id: UUID,
    context: WorkerContext,
) -> None:
    # Initial transition: queued → processing.
    # mark_processing is idempotent: it returns the row untouched if the
    # status is no longer QUEUED. The cancel endpoint runs in a separate
    # transaction, so a job cancelled while it sat in the scheduler queue
    # comes back here with status=CANCELLED — bail without parsing the
    # file or holding the BERT pipeline.
    async with context.admin_session_factory() as admin_session, admin_session.begin():
        await set_current_tenant(admin_session, tenant_id)
        audit = AuditService(admin_session)
        batch_service = BatchAnalyzeService(admin_session, audit)
        job = await batch_service.mark_processing(job_id)
        if job.status != BatchJobStatus.PROCESSING:
            log.info(
                "batch worker: job %s already in terminal state %s; skipping",
                job_id, job.status,
            )
            return
        file_path = Path(job.file_path)
        text_column = job.text_column
        source_column = job.source_column
        auto_create = job.auto_create_tickets
        triggered_by_user_id = job.triggered_by_user_id
        chunk_size = context.settings.chunk_size
        # Sprint 9.0 — resume support. last_checkpoint_row > 0 means a
        # previous run made it through that row before failing /
        # being cancelled; the operator hit /retry to pick up here.
        # The worker streams the file from the start (the parser has
        # no native seek for XLSX) and skips rows whose row_number is
        # at or below the checkpoint.
        resume_from_row = job.last_checkpoint_row

    # Open the file outside the transaction (streaming).
    if not file_path.exists():
        await _record_catastrophic_failure(
            job_id, tenant_id, context, reason=f"upload file missing: {file_path}"
        )
        return

    # Sprint 8.3.5. Auto-detect the NPS column once before chunks start
    # landing so analyze_batch_jobs.detected_nps_column is correct from
    # the very first progress write. peek failures fall through to
    # iter_rows() below; the catastrophic-failure path there is the
    # right place to record the unrecoverable state.
    detected_nps: str | None = None
    with contextlib.suppress(FileParseError):
        detected_nps = peek_detected_nps_column(file_path)
    if detected_nps is not None:
        async with context.admin_session_factory() as admin_session, admin_session.begin():
            await set_current_tenant(admin_session, tenant_id)
            await admin_session.execute(
                update(AnalyzeBatchJob)
                .where(AnalyzeBatchJob.id == job_id)
                .values(detected_nps_column=detected_nps)
            )

    try:
        rows_iter = iter_rows(
            file_path, text_column=text_column, source_column=source_column
        )
    except (FileParseError, UnknownColumnError) as exc:
        await _record_catastrophic_failure(
            job_id, tenant_id, context, reason=str(exc)
        )
        return

    # Intra-batch dedup — same text twice in the same upload collapses
    # to one review (the second is counted as duplicates_skipped).
    seen_hashes_in_batch: set[str] = set()

    # Sprint 9.0.5-A R5 — per-job tenant-scoped classifier with
    # rotator-aware Gemini provider. None means "use the pipeline's
    # default classifier" (the lifespan-built ENV-driven one). Built
    # ONCE per job so the rotator state (priority order + RateLimit
    # fall-through) lives for the full run.
    tenant_classifier = await _build_tenant_classifier(tenant_id, context)

    # Sprint 9.0 — resume filter. When resume_from_row > 0 we drop
    # already-processed rows from the iterator before they hit
    # _chunked, so the worker only burns BERT inference on rows
    # the previous run hadn't reached.
    if resume_from_row > 0:
        rows_iter = (
            row for row in rows_iter if row.row_number > resume_from_row
        )

    chunk_concurrency = max(1, context.chunk_concurrency)
    if chunk_concurrency <= 1:
        # Serial path — preserved verbatim so the existing
        # ``run_worker`` test fixture (single pipeline, no pool) sees
        # zero behavioural change. Sprint 9.0.5-A B6 already wraps the
        # BERT call in asyncio.to_thread inside _process_chunk, so
        # even on the serial path the loop yields between BERT
        # forwards and the API request loop stays responsive.
        for chunk in _chunked(rows_iter, chunk_size):
            if await _is_cancelled(job_id, tenant_id, context):
                log.info("batch worker: job %s cancelled", job_id)
                await _publish_terminal(job_id, tenant_id, context)
                return

            await _process_chunk(
                job_id=job_id,
                tenant_id=tenant_id,
                chunk=chunk,
                auto_create=auto_create,
                triggered_by_user_id=triggered_by_user_id,
                seen_hashes=seen_hashes_in_batch,
                context=context,
                classifier_override=tenant_classifier,
            )
    else:
        # Sprint 9.0.5-A B3 — bounded parallel path. Up to
        # ``chunk_concurrency`` chunks in flight at once, each
        # holding one model from the pipeline pool via
        # ``chunk_pool_semaphore``. The producer (``_chunked`` over
        # the streaming iterator) only outpaces the workers by 2× the
        # concurrency before pausing for a drain — that bounds the in-
        # memory ParsedRow buffer at ``2 × chunk_concurrency × chunk_size``
        # rows (≈8K rows worst case at default settings, well under
        # any reasonable container budget).
        await _run_chunks_parallel(
            job_id=job_id,
            tenant_id=tenant_id,
            rows_iter=rows_iter,
            chunk_size=chunk_size,
            auto_create=auto_create,
            triggered_by_user_id=triggered_by_user_id,
            seen_hashes=seen_hashes_in_batch,
            context=context,
            chunk_concurrency=chunk_concurrency,
            classifier_override=tenant_classifier,
        )
        if await _is_cancelled(job_id, tenant_id, context):
            log.info("batch worker: job %s cancelled (parallel)", job_id)
            await _publish_terminal(job_id, tenant_id, context)
            return

    # Final transition.
    async with context.admin_session_factory() as admin_session, admin_session.begin():
        await set_current_tenant(admin_session, tenant_id)
        audit = AuditService(admin_session)
        batch_service = BatchAnalyzeService(admin_session, audit)
        await batch_service.mark_completed(job_id)
    await _publish_terminal(job_id, tenant_id, context)


async def _run_chunks_parallel(
    *,
    job_id: UUID,
    tenant_id: UUID,
    rows_iter: Iterator[Any],
    chunk_size: int,
    auto_create: bool,
    triggered_by_user_id: UUID | None,
    seen_hashes: set[str],
    context: WorkerContext,
    chunk_concurrency: int,
    classifier_override: CategoryClassifier | None = None,
) -> None:
    """Drive ``_process_chunk`` in parallel with a bounded in-flight
    set. Each task acquires the pool semaphore before invoking
    ``_process_chunk`` so total concurrent BERT inferences ≤
    ``chunk_concurrency``. Cancellation is checked at every chunk
    boundary on the producer side AND inside each task before the
    BERT call (the inside check covers the long-running tail where
    a cancel that arrived mid-job would otherwise wait for every
    in-flight chunk to finish)."""
    pool_semaphore = context.chunk_pool_semaphore
    if pool_semaphore is None:
        # Defensive: build_worker_context only sets this when
        # chunk_concurrency > 1 AND pipeline_pool is non-None. If
        # the caller bypassed that, fall back to serial.
        log.warning(
            "batch worker: parallel path requested but pool semaphore "
            "missing; falling back to serial",
        )
        for chunk in _chunked(rows_iter, chunk_size):
            if await _is_cancelled(job_id, tenant_id, context):
                return
            await _process_chunk(
                job_id=job_id, tenant_id=tenant_id, chunk=chunk,
                auto_create=auto_create,
                triggered_by_user_id=triggered_by_user_id,
                seen_hashes=seen_hashes, context=context,
                classifier_override=classifier_override,
            )
        return

    async def _bounded_chunk(idx: int, chunk: list[Any]) -> None:
        async with pool_semaphore:
            if await _is_cancelled(job_id, tenant_id, context):
                return
            await _process_chunk(
                job_id=job_id,
                tenant_id=tenant_id,
                chunk=chunk,
                auto_create=auto_create,
                triggered_by_user_id=triggered_by_user_id,
                seen_hashes=seen_hashes,
                context=context,
                chunk_index=idx,
                classifier_override=classifier_override,
            )

    in_flight: set[asyncio.Task[None]] = set()
    chunk_index = 0
    drain_threshold = chunk_concurrency * 2

    for chunk in _chunked(rows_iter, chunk_size):
        if await _is_cancelled(job_id, tenant_id, context):
            for t in in_flight:
                t.cancel()
            with contextlib.suppress(BaseException):
                await asyncio.gather(*in_flight, return_exceptions=True)
            return

        task = asyncio.create_task(_bounded_chunk(chunk_index, chunk))
        in_flight.add(task)
        chunk_index += 1

        # Drain finished tasks to surface exceptions early + bound
        # the in-flight queue size.
        if len(in_flight) >= drain_threshold:
            done, pending = await asyncio.wait(
                in_flight, return_when=asyncio.FIRST_COMPLETED
            )
            in_flight = pending
            for t in done:
                exc = t.exception()
                if exc is not None:
                    for p in in_flight:
                        p.cancel()
                    with contextlib.suppress(BaseException):
                        await asyncio.gather(*in_flight, return_exceptions=True)
                    raise exc

    # Drain everything still running.
    if in_flight:
        results = await asyncio.gather(*in_flight, return_exceptions=True)
        for r in results:
            if isinstance(r, BaseException):
                raise r


async def _publish_terminal(
    job_id: UUID, tenant_id: UUID, context: WorkerContext
) -> None:
    """Read the job's terminal state and publish a final SSE event so
    the consumer knows to disconnect.

    Sprint 9.0.5-A. Best-effort — we already journalled the state
    transition (mark_completed / mark_failed / cancel_job) in its own
    transaction; this is just the live-update tail. Failure is
    logged + swallowed."""
    if context.redis_publisher is None:
        return
    try:
        async with context.admin_session_factory() as session, session.begin():
            await set_current_tenant(session, tenant_id)
            row = await session.get(AnalyzeBatchJob, job_id)
            if row is None:
                return
            snapshot = _progress_snapshot(row)
        await context.redis_publisher.publish(
            _progress_channel(job_id),
            json.dumps(snapshot),
        )
    except Exception:
        log.exception(
            "batch worker: terminal SSE publish failed",
            extra={"job_id": str(job_id)},
        )


async def _is_cancelled(
    job_id: UUID,
    tenant_id: UUID,
    context: WorkerContext,
) -> bool:
    async with context.admin_session_factory() as session, session.begin():
        await set_current_tenant(session, tenant_id)
        stmt = select(AnalyzeBatchJob.status).where(
            AnalyzeBatchJob.id == job_id
        )
        status = (await session.execute(stmt)).scalar_one_or_none()
        return status == BatchJobStatus.CANCELLED


async def _process_chunk(
    *,
    job_id: UUID,
    tenant_id: UUID,
    chunk: list[Any],  # list[ParsedRow]
    auto_create: bool,
    triggered_by_user_id: UUID | None,
    seen_hashes: set[str],
    context: WorkerContext,
    chunk_index: int | None = None,
    classifier_override: CategoryClassifier | None = None,
) -> None:
    """Analyze and persist one chunk worth of rows. Each chunk is its
    own transaction so a row-level error rolls back ONLY the bad row,
    not the whole job."""
    error_entries: list[dict[str, Any]] = []
    succeeded = 0
    failed = 0
    tickets = 0
    duplicates = 0
    rows_with_nps_in_chunk = 0

    # Pre-filter empty rows (don't burn BERT inference on whitespace).
    valid_rows: list[Any] = []
    for parsed in chunk:
        if not parsed.text:
            failed += 1
            error_entries.append(
                {"row": parsed.row_number, "error": "empty text"}
            )
            continue
        valid_rows.append(parsed)

    # Sprint 9.0 — checkpoint = highest row_number in this chunk.
    # The chunk is ordered by row_number (iter_rows is sequential), so
    # max() == chunk[-1].row_number; computing max defensively in case
    # a later refactor shuffles ordering.
    chunk_checkpoint = max((p.row_number for p in chunk), default=0)

    if not valid_rows:
        await _commit_progress(
            job_id=job_id,
            tenant_id=tenant_id,
            context=context,
            progress=BatchProgress(
                processed_delta=len(chunk),
                failed_delta=failed,
                error_entries=error_entries or None,
                checkpoint_row=chunk_checkpoint,
            ),
        )
        return

    # BERT inference — outside any DB transaction.
    # Sprint 9.0.5-A B6: pipeline.analyze_batch is sync and the
    # transformers pipeline is a sync C extension that doesn't yield
    # back to the event loop during inference. Awaiting through
    # ``asyncio.to_thread`` parks the call on the default executor so
    # the worker process keeps serving other coroutines (in
    # particular: progress writes from sibling chunks once B3 lands,
    # and the API request loop in dev/test paths where worker + API
    # share a process). Today's 21-min freeze on a 2852-row CSV had
    # processed_rows=0 the whole time because the sync call held the
    # loop until BERT finished (~1.4s × 2852 = ~67 min projected).
    texts = [r.text for r in valid_rows]
    pipeline = _select_pipeline(context, chunk_index=chunk_index)
    try:
        # Sprint 9.0.5-A B2 + B6 — analyze_batch_async runs BERT and
        # the category classifier on parallel threads via to_thread,
        # so the event loop is free for sibling chunks AND the two
        # slow steps overlap rather than serialise. Earlier this
        # method was a sync ``pipeline.analyze_batch(texts)`` call;
        # that held the loop for the entire BERT inference and was
        # the proximate cause of today's 21-min freeze on a 2852-row
        # CSV.
        analyses: list[AnalysisResult] = await pipeline.analyze_batch_async(
            texts, classifier=classifier_override,
        )
    except Exception as exc:
        log.exception("batch chunk inference failed: %s", exc)
        for parsed in valid_rows:
            error_entries.append(
                {"row": parsed.row_number, "error": f"pipeline failed: {exc}"}
            )
            failed += 1
        await _commit_progress(
            job_id=job_id,
            tenant_id=tenant_id,
            context=context,
            progress=BatchProgress(
                processed_delta=len(chunk),
                failed_delta=failed,
                error_entries=error_entries or None,
                checkpoint_row=chunk_checkpoint,
            ),
        )
        return

    # Persist — RLS-bound app session so reviews + tickets land
    # tenant-scoped via the same path as /tenants/me/analyze.
    async with context.app_session_factory() as app_session, app_session.begin():
        await set_current_tenant(app_session, tenant_id)
        audit = AuditService(app_session)
        ticket_service = TicketService(app_session, audit)
        config_service = TenantConfigService(
            app_session, audit, context.tenant_config_cache
        )
        review_service = ReviewService(
            app_session, audit, ticket_service, config_service
        )

        # Snapshot the tenant's real automation_mode once per chunk.
        # The reviews CHECK constraint allows ONLY 'manual' / 'semi_auto' /
        # 'full_auto'; batch-specific intent (intra-batch dedup, opt-out)
        # is expressed by `decision` + `decision_reason`, not by inventing
        # sentinel mode values. Earlier sentinel values (`batch_intra_dedup`,
        # `batch_opt_out`) violated ck_reviews_automation_mode and crashed
        # the whole batch.
        tenant_config = await config_service.get_config(tenant_id)
        tenant_mode = str(tenant_config["automation_mode"])

        # Sprint 8.3.5.6. Fetch the company taxonomy once per chunk so
        # the heuristic reranker doesn't hit the DB per row. The auto-
        # create branch routes through ReviewService.record_and_decide
        # which has its own fetch — duplicate work, but keeps both
        # paths self-sufficient and the read is cheap (21 rows max,
        # B-tree index on tenant_id).
        taxonomy_payload = await _load_taxonomy_payload(app_session, tenant_id)

        for parsed, analysis in zip(valid_rows, analyses, strict=True):
            from imga_core import review_text_hash

            text_hash = review_text_hash(parsed.text)

            # Sprint 8.3.5.6. Compute the heuristic perspective once per
            # row, reused below for whichever insertion path fires. The
            # auto_create branch routes through ReviewService which runs
            # its own taxonomy load + heuristic pass; we let that path
            # win for the row it owns and only persist this value on the
            # two direct-insert branches (intra-batch dedup + opt-out).
            perspective_hit = apply_company_heuristic(
                parsed.text, taxonomy=taxonomy_payload
            )
            perspective_code = (
                perspective_hit.code if perspective_hit is not None else None
            )

            # Intra-batch dedup — already seen this text in this job.
            # Sprint 9.0.5-A — wrap the check-and-add in dedup_lock so
            # the parallel-chunk path can't race two chunks both
            # reading "not in set" for the same hash. Lock held only
            # for the dict ops (μs); the heavy persistence work below
            # runs unlocked.
            async with context.dedup_lock:
                is_duplicate = text_hash in seen_hashes
                if not is_duplicate:
                    seen_hashes.add(text_hash)

            if is_duplicate:
                review = Review(
                    tenant_id=tenant_id,
                    text=parsed.text,
                    text_hash=text_hash,
                    sentiment_label=analysis.sentiment_label,
                    sentiment_score=float(analysis.sentiment_score),
                    primary_category=(
                        analysis.categorization.primary
                        if analysis.categorization
                        else "belirsiz"
                    ),
                    primary_confidence=float(
                        analysis.categorization.primary_confidence
                        if analysis.categorization
                        else 0.0
                    ),
                    automation_mode=tenant_mode,
                    decision=ReviewDecision.SKIPPED_DEDUP,
                    decision_reason="intra_batch_duplicate",
                    ticket_id=None,
                    submitted_by_user_id=triggered_by_user_id,
                    batch_job_id=job_id,
                    analyzed_at=datetime.now(UTC),
                    overrides_applied=[hit.model_dump() for hit in analysis.overrides_applied],
                    nps_score=parsed.nps_score,
                    company_perspective_code=perspective_code,
                )
                app_session.add(review)
                duplicates += 1
                succeeded += 1
                if parsed.nps_score is not None:
                    rows_with_nps_in_chunk += 1
                continue

            if auto_create:
                try:
                    result = await review_service.record_and_decide(
                        tenant_id=tenant_id,
                        text=parsed.text,
                        analysis=analysis,
                        actor_user_id=triggered_by_user_id,
                        nps_score=parsed.nps_score,
                    )
                except Exception as exc:
                    log.exception("row %s record_and_decide", parsed.row_number)
                    error_entries.append(
                        {
                            "row": parsed.row_number,
                            "error": f"record_and_decide failed: {exc}",
                        }
                    )
                    failed += 1
                    continue
                # Back-fill batch_job_id on the review record_and_decide
                # just inserted (the bridge has no batch awareness).
                await app_session.execute(
                    update(Review)
                    .where(Review.id == result.review_id)
                    .values(batch_job_id=job_id)
                )
                if result.decision == ReviewDecision.CREATE:
                    tickets += 1
                elif result.decision == ReviewDecision.SKIPPED_DEDUP:
                    duplicates += 1
                succeeded += 1
                if parsed.nps_score is not None:
                    rows_with_nps_in_chunk += 1
            else:
                # Opt-out path: persist a review row marked SKIPPED_MODE
                # so the user still sees the analysis, but no ticket.
                primary = (
                    analysis.categorization.primary
                    if analysis.categorization
                    else "belirsiz"
                )
                confidence = float(
                    analysis.categorization.primary_confidence
                    if analysis.categorization
                    else 0.0
                )
                review = Review(
                    tenant_id=tenant_id,
                    text=parsed.text,
                    text_hash=text_hash,
                    sentiment_label=analysis.sentiment_label,
                    sentiment_score=float(analysis.sentiment_score),
                    primary_category=primary,
                    primary_confidence=confidence,
                    automation_mode=tenant_mode,
                    decision=ReviewDecision.SKIPPED_MODE,
                    decision_reason="auto_create_tickets_disabled",
                    ticket_id=None,
                    submitted_by_user_id=triggered_by_user_id,
                    batch_job_id=job_id,
                    analyzed_at=datetime.now(UTC),
                    overrides_applied=[hit.model_dump() for hit in analysis.overrides_applied],
                    nps_score=parsed.nps_score,
                    company_perspective_code=perspective_code,
                )
                app_session.add(review)
                succeeded += 1
                if parsed.nps_score is not None:
                    rows_with_nps_in_chunk += 1

    # Single progress write per chunk on the admin session (RLS still
    # applied via FORCE; we set tenant context).
    await _commit_progress(
        job_id=job_id,
        tenant_id=tenant_id,
        context=context,
        progress=BatchProgress(
            processed_delta=len(chunk),
            succeeded_delta=succeeded,
            failed_delta=failed,
            tickets_created_delta=tickets,
            duplicates_skipped_delta=duplicates,
            rows_with_nps_delta=rows_with_nps_in_chunk,
            error_entries=error_entries or None,
            checkpoint_row=chunk_checkpoint,
        ),
    )


async def _commit_progress(
    *,
    job_id: UUID,
    tenant_id: UUID,
    context: WorkerContext,
    progress: BatchProgress,
) -> None:
    async with context.admin_session_factory() as session, session.begin():
        await set_current_tenant(session, tenant_id)
        audit = AuditService(session)
        service = BatchAnalyzeService(session, audit)
        job = await service.apply_progress(job_id=job_id, progress=progress)
        snapshot = _progress_snapshot(job)
    # Sprint 9.0.5-A — SSE progress publish. Outside the DB
    # transaction so a Redis-side hiccup can't roll back the chunk
    # commit. Best-effort: log + swallow any exception (the SSE
    # client will pick up the next chunk's event, and the GET
    # endpoint also reads the persisted job row as the initial
    # state so a missed publish degrades to "no live update for
    # this chunk").
    if context.redis_publisher is not None:
        try:
            await context.redis_publisher.publish(
                _progress_channel(job_id),
                json.dumps(snapshot),
            )
        except Exception:
            log.exception(
                "batch worker: SSE progress publish failed",
                extra={"job_id": str(job_id)},
            )


def _progress_channel(job_id: UUID) -> str:
    """Redis pub/sub channel name for live batch progress.

    Sprint 9.0.5-A. The SSE endpoint subscribes on the same key.
    Channel is per-job — no fan-out, one subscriber per active
    upload UI session.
    """
    return f"batch:progress:{job_id}"


def _progress_snapshot(job: AnalyzeBatchJob) -> dict[str, Any]:
    """Wire shape for SSE progress events. Mirrors what the GET
    /analyze/batch/{id}/progress endpoint emits as the initial state
    so the frontend can use one schema for both."""
    total = max(0, int(job.total_rows or 0))
    processed = max(0, int(job.processed_rows or 0))
    percent = (processed / total * 100.0) if total > 0 else 0.0
    # ETA: rough — assume the rest of the job goes at the same rate
    # as the average so far. ``started_at`` is the anchor; if the
    # worker hasn't started yet we omit the ETA rather than emit a
    # nonsensical infinity.
    eta_seconds: int | None = None
    started_at = job.started_at
    if started_at is not None and processed > 0 and processed < total:
        elapsed = (datetime.now(UTC) - started_at).total_seconds()
        if elapsed > 0:
            rate = processed / elapsed  # rows/sec
            if rate > 0:
                eta_seconds = max(0, int((total - processed) / rate))
    return {
        "job_id": str(job.id),
        "status": str(job.status),
        "processed": processed,
        "total": total,
        "percent": round(percent, 2),
        "succeeded": int(job.succeeded_rows or 0),
        "failed": int(job.failed_rows or 0),
        "tickets_created": int(job.tickets_created or 0),
        "duplicates_skipped": int(job.duplicates_skipped or 0),
        "eta_seconds": eta_seconds,
        "last_checkpoint_row": int(job.last_checkpoint_row or 0),
    }


# ---------------------------------------------------------------------------
# Recovery (called from lifespan)
# ---------------------------------------------------------------------------


async def recover_orphans(context: WorkerContext) -> int:
    """At startup, any job left in PROCESSING came from a previous run
    that died mid-flight (the in-memory locks vanished with the
    process). Mark those jobs as failed so the user sees an actionable
    state instead of a frozen progress bar. Returns the count for log
    visibility."""
    async with context.admin_session_factory() as session, session.begin():
        stmt = (
            select(AnalyzeBatchJob.id, AnalyzeBatchJob.tenant_id)
            .where(AnalyzeBatchJob.status == BatchJobStatus.PROCESSING)
        )
        rows = list((await session.execute(stmt)).all())

    for job_id, tenant_id in rows:
        await _record_catastrophic_failure(
            job_id,
            tenant_id,
            context,
            reason="worker process restarted before this job finished",
        )
    return len(rows)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _build_tenant_classifier(
    tenant_id: UUID, context: WorkerContext
) -> CategoryClassifier | None:
    """Sprint 9.0.5-A R5 — load the tenant's active Gemini credentials
    and assemble a per-job ``HybridClassifier`` with a
    ``RotatingGeminiProvider``.

    Returns:
        * A ``HybridClassifier`` wrapping the tenant's keys when at
          least one decryptable credential exists.
        * ``None`` when the tenant has no active credentials — the
          caller falls back to the pipeline's default classifier
          (lifespan-built; ENV-driven for the api-worker container).

    The classifier is single-use per job: rotator state (priority
    order, RateLimit fall-through) is built fresh from the current
    ``tenant_llm_credentials`` rows so a credential added /
    rotated mid-day takes effect on the next job without an api-
    worker restart. Cost is one admin-session DB query +
    decryption — milliseconds against a multi-minute batch.
    """
    from imga_api.services.llm_credentials import load_active_gemini_keys

    try:
        async with context.admin_session_factory() as session, session.begin():
            await set_current_tenant(session, tenant_id)
            keys = await load_active_gemini_keys(session, tenant_id)
    except Exception:
        log.exception(
            "batch worker: failed to load tenant Gemini keys; "
            "falling back to default classifier",
            extra={"tenant_id": str(tenant_id)},
        )
        return None

    if not keys:
        log.info(
            "batch worker: tenant has no active Gemini credentials; "
            "falling back to keyword-only classifier",
            extra={"tenant_id": str(tenant_id)},
        )
        return None

    # Sprint 9.0.5-A R7 — pull the parallel-LLM cap from
    # BatchSettings so a deploy can override
    # IMGA_BATCH_LLM_CONCURRENCY without code changes. Default 4
    # (R7 down from 8) keeps in-flight state bounded during a
    # provider outage so the circuit breaker can react fast.
    llm_concurrency = context.settings.llm_concurrency
    log.info(
        "batch worker: tenant classifier built with %d Gemini key(s) "
        "(rotator active, llm_concurrency=%d)",
        len(keys),
        llm_concurrency,
        extra={"tenant_id": str(tenant_id)},
    )
    return HybridClassifier(
        keyword_classifier=KeywordCategoryClassifier(),
        llm_provider=RotatingGeminiProvider(keys=keys),
        llm_concurrency=llm_concurrency,
    )


async def _load_taxonomy_payload(
    session: AsyncSession, tenant_id: UUID
) -> list[TaxonomyEntry]:
    """Read the tenant's CategoryTaxonomy rows and shape them as the
    list-of-dicts payload ``apply_company_heuristic`` expects.

    Returns ``[]`` when the tenant has no taxonomy (legacy / pre-8.3.5.5
    tenants that never landed via ``TenantService.create``); the
    heuristic short-circuits to ``None`` on an empty list.
    """
    stmt = select(
        CategoryTaxonomy.code,
        CategoryTaxonomy.label_tr,
        CategoryTaxonomy.keywords,
        CategoryTaxonomy.priority,
    ).where(CategoryTaxonomy.tenant_id == tenant_id)
    rows = (await session.execute(stmt)).all()
    return [
        TaxonomyEntry(
            code=r.code,
            label_tr=r.label_tr,
            keywords=list(r.keywords),
            priority=r.priority,
        )
        for r in rows
    ]


__all__ = [
    "WorkerContext",
    "build_worker_context",
    "process_batch_job",
    "recover_orphans",
]
