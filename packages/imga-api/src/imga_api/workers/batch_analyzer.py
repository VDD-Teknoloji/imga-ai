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
import time
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
from imga_core.llm import LLMProvider, RotatingGeminiProvider
from imga_core.llm.unified_classifier import (
    FewShotExample,
    GeminiUnifiedEngine,
    PerspectiveOptions,
)
from imga_core.text_utils import review_text_hash
from imga_db import create_engine, create_session_factory, set_current_tenant
from imga_db.models import (
    AnalyzeBatchJob,
    BatchJobStatus,
    CategoryTaxonomy,
    Review,
    ReviewDecision,
    TenantBusinessDimension,
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
    # Sprint 9.1 E — wall-clock timer for the per-batch summary log
    # emitted alongside the terminal transition. Same monotonic-clock
    # rationale as the per-chunk timer.
    job_started_at = time.monotonic()

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
        # Sprint 10.0 — adaptive chunk: progress yazımı her chunk
        # SONUNDA bir kez yapılır, dolayısıyla chunk_size aynı
        # zamanda kullanıcının gördüğü güncelleme sıklığıdır.
        # Configured default 200; 100 satırlık bir dosya tek
        # chunk'a sığar ve UI işlem bitene kadar 0'da donar (UML
        # test feedback'i). total_rows upload route'unda count_rows
        # ile dolduruluyor ve job row'unda hazır — küçük dosyada
        # chunk'ı küçültüp en az ~10 progress güncellemesi
        # garantiliyoruz. Büyük dosyada (total/10 > configured)
        # configured değer kazanır, davranış değişmez.
        total_rows_known = int(job.total_rows or 0)
        if total_rows_known > 0:
            target_chunk = max(10, -(-total_rows_known // 10))  # ceil(total/10)
            chunk_size = max(1, min(chunk_size, target_chunk))
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

    # Sprint 9.4 D — fetch the per-tenant business-dimension mapping
    # once at job start. Each enabled dimension with a non-null
    # ``csv_column_mapping`` contributes one entry; the file parser
    # uses these to populate the four nullable Review columns
    # (business_segment / product_line / channel / customer_tier).
    dimension_mapping = await _fetch_dimension_mapping(tenant_id, context)

    try:
        rows_iter = iter_rows(
            file_path,
            text_column=text_column,
            source_column=source_column,
            dimension_mapping=dimension_mapping,
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
    # Sprint 11.0 — birleşik LLM bağlamı (motor + düzeltme deposu).
    unified_ctx = await _build_unified_context(tenant_id, context)

    # 2026-08-10 — BERT yedeği kapatılabilir (prod: kapalı). 21k'lık
    # vakada parse reddi her chunk'ı BERT'e düşürüp worker'ı OOM'a
    # götürdü; ayrıca sessiz kalite düşüşü isteniyor değil. Bayrak
    # kapalıyken LLM bağlamı kurulamıyorsa iş baştan, net gerekçeyle
    # başarısız olur — operatör anahtarı düzeltip Yeniden Dene der.
    if unified_ctx is None and not _bert_fallback_enabled():
        await _record_catastrophic_failure(
            job_id,
            tenant_id,
            context,
            reason=(
                "Yapay zekâ sınıflandırma başlatılamadı (kurumda aktif "
                "LLM anahtarı yok ya da birleşik yol kapalı) ve BERT "
                "yedeği devre dışı (IMGA_BATCH_BERT_FALLBACK=false). "
                "Anahtar tanımlayıp işi Yeniden Dene ile başlatın."
            ),
        )
        return

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
                unified_ctx=unified_ctx,
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
            unified_ctx=unified_ctx,
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
        completed_job = await admin_session.get(AnalyzeBatchJob, job_id)
        # Sprint 9.2 C — invalidate today's executive snapshot for
        # this tenant. Best-effort: a failed invalidate just means
        # the next snapshot read sees the cursor advance and
        # recomputes anyway. Inline import keeps the worker free of
        # the snapshot dep at module load.
        from imga_api.services.snapshot_service import SnapshotService

        try:
            await SnapshotService(admin_session).invalidate(tenant_id=tenant_id)
        except Exception:
            log.exception(
                "batch worker: snapshot invalidation failed (non-fatal)",
                extra={"job_id": str(job_id), "tenant_id": str(tenant_id)},
            )
    await _publish_terminal(job_id, tenant_id, context)
    # Sprint 9.1 E — per-batch structured summary. Lands once at
    # successful completion (the cancellation + catastrophic-failure
    # paths return early above so they don't emit this line — those
    # have their own log entries on the way out).
    if completed_job is not None:
        duration = time.monotonic() - job_started_at
        processed = completed_job.processed_rows or 0
        log.info(
            "batch completed",
            extra={
                "batch_job_id": str(job_id),
                "tenant_id": str(tenant_id),
                "total_rows": completed_job.total_rows or 0,
                "rows_processed": processed,
                "rows_succeeded": completed_job.succeeded_rows or 0,
                "rows_failed": completed_job.failed_rows or 0,
                "tickets_created": completed_job.tickets_created or 0,
                "duplicates_skipped": completed_job.duplicates_skipped or 0,
                "duration_sec": round(duration, 2),
                "throughput_rows_per_sec": (
                    round(processed / duration, 2) if duration > 0 else 0.0
                ),
                "chunk_size": context.settings.chunk_size,
                "chunk_concurrency": context.chunk_concurrency,
            },
        )


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
    unified_ctx: UnifiedJobContext | None = None,
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
                unified_ctx=unified_ctx,
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
                unified_ctx=unified_ctx,
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
        # SIM113 bilinçli susturuldu: _chunked tembel bir jeneratör ve
        # döngü gövdesi erken return/drain içeriyor — sayaç akışı elle
        # tutuluyor, enumerate okunurluğu artırmıyor.
        chunk_index += 1  # noqa: SIM113

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
    unified_ctx: UnifiedJobContext | None = None,
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
    # Sprint 9.1 E — chunk-level timing for the structured log emitted
    # at the bottom of this function. ``time.monotonic()`` is the
    # right tool for elapsed measurement; wall-clock would be tripped
    # by NTP slews mid-run.
    chunk_started_at = time.monotonic()
    bert_seconds = 0.0
    db_seconds = 0.0
    llm_fallback_count = 0

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
    bert_started_at = time.monotonic()
    try:
        # Sprint 9.0.5-A B2 + B6 — analyze_batch_async runs BERT and
        # the category classifier on parallel threads via to_thread,
        # so the event loop is free for sibling chunks AND the two
        # slow steps overlap rather than serialise. Earlier this
        # method was a sync ``pipeline.analyze_batch(texts)`` call;
        # that held the loop for the entire BERT inference and was
        # the proximate cause of today's 21-min freeze on a 2852-row
        # CSV.
        # Sprint 9.5.5 A — pass a stats sink the pipeline forwards
        # to HybridClassifier.classify_batch_async. Pre-9.5.5 the
        # chunk audit row landed with input_tokens=NULL and
        # duration_ms=0 because the auditor wrapped only the
        # ~1ms flag-setting region below; the real LLM duration
        # + per-call token usage went uncaptured. The sink picks up
        # llm_total_input_tokens / llm_total_output_tokens /
        # llm_duration_ms from the BatchClassificationResult.
        classifier_stats: dict[str, int] = {}
        analyses: list[AnalysisResult] | None = None
        # Sprint 11.0 — birincil yol: birleşik Gemini sınıflandırma
        # (sentiment + kategori tek çağrı setinde, few-shot düzeltme
        # örnekleriyle). Motor üretemezse klasik yola düşülür: BERT
        # zinciri (uzak Modal → lazy lokal) + keyword/LLM classifier.
        semantic_hits: dict[int, Any] = {}
        # Sprint 13.1 — LLM'in seçtiği alt kategori kodları, satır
        # sırasına göre. Klasik yola düşülürse boş kalır ve persist
        # döngüsü tümüyle keyword sezgiseline güvenir.
        unified_perspectives: list[str | None] = []
        if unified_ctx is not None:
            try:
                few_shot, semantic_hits = await _few_shot_for_chunk(
                    unified_ctx, texts, context, tenant_id
                )
                analyses = await pipeline.analyze_batch_unified_async(
                    texts,
                    engine=unified_ctx.engine,
                    available_categories=unified_ctx.available_categories,
                    few_shot=few_shot,
                    stats_sink=classifier_stats,
                    perspective_options=unified_ctx.perspective_options,
                    perspective_sink=unified_perspectives,
                )
            except Exception as exc:
                if not _bert_fallback_enabled():
                    # BERT yedeği kapalı: sessiz kalite düşüşü yerine
                    # işi net gerekçeyle durdur. Checkpoint'e kadar
                    # işlenen satırlar kalıcı — Yeniden Dene kaldığı
                    # yerden sürer.
                    raise BertFallbackDisabledError(
                        "LLM sınıflandırma bu parça için kalıcı olarak "
                        "başarısız oldu ve BERT yedeği devre dışı "
                        f"(IMGA_BATCH_BERT_FALLBACK=false): {exc}"
                    ) from exc
                log.warning(
                    "unified classifier failed for chunk; falling back "
                    "to classic pipeline: %s",
                    exc,
                )
                analyses = None
                unified_perspectives = []
        if analyses is None:
            analyses = await pipeline.analyze_batch_async(
                texts,
                classifier=classifier_override,
                classifier_stats_sink=classifier_stats,
            )
        # Düzeltme katmanları — insan kararı her yolu ezer
        # (birebir + anlamsal).
        if unified_ctx is not None:
            analyses = _apply_corrections(
                analyses, texts, unified_ctx, semantic_hits
            )
        bert_seconds = time.monotonic() - bert_started_at
    except BertFallbackDisabledError:
        # Chunk-yerel "satırları failed say, devam et" düzeneğine
        # DÜŞMEZ: iş seviyesinde durdurulur (catastrophic path) ki
        # yüzlerce chunk tek tek başarısızlık geçidine dönmesin.
        raise
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

    # Count rows that triggered an LLM fallback (HybridClassifier
    # exposes ``llm_fallback`` on each AnalysisResult.categorization
    # when present). Best-effort: stays 0 for keyword-only pipelines.
    for analysis in analyses:
        cat = analysis.categorization
        if cat is not None and getattr(cat, "llm_fallback", False):
            llm_fallback_count += 1

    # Persist — RLS-bound app session so reviews + tickets land
    # tenant-scoped via the same path as /tenants/me/analyze.
    db_started_at = time.monotonic()
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

        # Sprint 9.4.3 A — chunk-level LLM audit. One row per chunk
        # (not per review) keeps the audit table manageable on a 10K
        # upload while still giving the operator a "this batch hit
        # the LLM at HH:MM" trace on /admin/llm-audit. The chunk's
        # actual BERT/LLM duration is recorded in the structured
        # log line at the bottom of this function; the auditor's
        # duration here covers the audit insert only (it runs
        # post-analyze) — that's a known trade-off documented in
        # the Sprint 9.4.3 commit.
        from imga_api.services.executive_briefing_service import (
            DEFAULT_MODEL_NAME,
        )
        from imga_api.services.llm_audit_service import (
            CALL_TYPE_CLASSIFICATION,
            LLMCallAuditor,
            LLMCallContext,
        )

        # Anchor the audit row to the chunk via a stable digest of the
        # first few rows' content. Operators can correlate "this audit
        # row" → "this chunk" by row_number range from the structured
        # log; the prompt_hash field provides the secondary join key.
        chunk_anchor = "\n".join(
            f"{p.row_number}:{p.text[:200]}"
            for p in valid_rows[: min(20, len(valid_rows))]
        )
        # OpenRouter entegrasyonu — audit satırı artık gerçek kazanan
        # sağlayıcı/modeli taşır (eskiden kod sabitinden geliyordu).
        # Unified motor varsa onun kimliği; yoksa klasik rotating
        # provider'ınki. Chunk-level yaklaşıklık (dokümante trade-off).
        audit_model_name = DEFAULT_MODEL_NAME
        audit_provider = "gemini"
        if unified_ctx is not None:
            audit_model_name = unified_ctx.engine.model_name
            audit_provider = unified_ctx.engine.provider
        elif classifier_override is not None:
            _llm = getattr(classifier_override, "llm", None)
            if _llm is not None:
                audit_model_name = getattr(
                    _llm, "model_name", DEFAULT_MODEL_NAME
                )
                _pname = str(getattr(_llm, "PROVIDER_NAME", "gemini"))
                audit_provider = (
                    "openrouter" if "openrouter" in _pname else "gemini"
                )
        audit_ctx = LLMCallContext(
            tenant_id=tenant_id,
            call_type=CALL_TYPE_CLASSIFICATION,
            model_name=audit_model_name,
            model_provider=audit_provider,
            actor_user_id=triggered_by_user_id,
            related_entity_type="analyze_batch_job",
            related_entity_id=job_id,
        )
        chunk_auditor = LLMCallAuditor(
            app_session, audit_ctx, prompt=chunk_anchor,
        )
        async with chunk_auditor:
            # The BERT/LLM call already ran outside the transaction
            # (line ~739); this block is a no-op body whose only job
            # is to flip the auditor flags and let __aexit__ flush
            # the row inside the savepoint. The fallback flag
            # reflects "any row in the chunk hit the keyword
            # fallback" — a coarser signal than per-row but matches
            # the chunk-level granularity we ship.
            chunk_auditor.mark_fallback_used(llm_fallback_count > 0)
            # Sprint 9.5.5 A — forward the LLM aggregates from the
            # classifier stats sink. Missing keys mean no LLM was
            # consulted (keyword-only chunk, LLM disabled, or the
            # circuit was open) — ``None`` keeps the audit row
            # honest: total_tokens == 0 + duration_ms == NULL is
            # different from "ran for 80s and forgot to log it".
            chunk_in = classifier_stats.get("llm_total_input_tokens")
            chunk_out = classifier_stats.get("llm_total_output_tokens")
            chunk_duration = classifier_stats.get("llm_duration_ms")
            chunk_auditor.record_success(
                input_tokens=chunk_in if chunk_in else None,
                output_tokens=chunk_out if chunk_out else None,
                duration_ms=chunk_duration if chunk_duration else None,
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
        taxonomy_snapshot = await _load_taxonomy_payload(app_session, tenant_id)

        for row_index, (parsed, analysis) in enumerate(
            zip(valid_rows, analyses, strict=True)
        ):
            from imga_core import review_text_hash

            text_hash = review_text_hash(parsed.text)
            # Tek an, üç dal: yorumun kendi tarihi yoksa review_date de
            # analyzed_at de aynı ingest anına düşsün.
            row_moment = datetime.now(UTC)

            # Sprint 8.3.5.6. Compute the heuristic perspective once per
            # row, reused below for whichever insertion path fires. The
            # auto_create branch routes through ReviewService which runs
            # its own taxonomy load + heuristic pass; we let that path
            # win for the row it owns and only persist this value on the
            # two direct-insert branches (intra-batch dedup + opt-out).
            # Sprint 13.1 — birleşik sınıflandırıcı bir alt kategori
            # kodu verdiyse (ve kod hâlâ kurumun taksonomisindeyse) o
            # kazanır; aksi halde davranış 8.3.5.6'daki gibi kalır.
            llm_perspective = (
                unified_perspectives[row_index]
                if row_index < len(unified_perspectives)
                else None
            )
            perspective_code: str | None
            perspective_label: str | None
            if llm_perspective is not None and (
                llm_perspective in taxonomy_snapshot.labels
            ):
                perspective_code = llm_perspective
                perspective_label = taxonomy_snapshot.labels[llm_perspective]
            else:
                perspective_hit = apply_company_heuristic(
                    parsed.text, taxonomy=taxonomy_snapshot.heuristic_entries
                )
                perspective_code = (
                    perspective_hit.code if perspective_hit is not None else None
                )
                perspective_label = (
                    perspective_hit.label_tr
                    if perspective_hit is not None
                    else None
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
                    analyzed_at=row_moment,
                    review_date=parsed.review_date or row_moment,
                    overrides_applied=[hit.model_dump() for hit in analysis.overrides_applied],
                    nps_score=parsed.nps_score,
                    company_perspective_code=perspective_code,
                    business_segment=parsed.business_segment,
                    product_line=parsed.product_line,
                    channel=parsed.channel,
                    customer_tier=parsed.customer_tier,
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
                        business_segment=parsed.business_segment,
                        product_line=parsed.product_line,
                        channel=parsed.channel,
                        customer_tier=parsed.customer_tier,
                        review_date=parsed.review_date,
                        perspective_override=(
                            (perspective_code, perspective_label)
                            if llm_perspective is not None
                            and perspective_code is not None
                            and perspective_label is not None
                            else None
                        ),
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
                    analyzed_at=row_moment,
                    review_date=parsed.review_date or row_moment,
                    overrides_applied=[hit.model_dump() for hit in analysis.overrides_applied],
                    nps_score=parsed.nps_score,
                    company_perspective_code=perspective_code,
                    business_segment=parsed.business_segment,
                    product_line=parsed.product_line,
                    channel=parsed.channel,
                    customer_tier=parsed.customer_tier,
                )
                app_session.add(review)
                succeeded += 1
                if parsed.nps_score is not None:
                    rows_with_nps_in_chunk += 1

    db_seconds = time.monotonic() - db_started_at

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

    # Sprint 9.1 E — chunk-level structured log. The per-chunk write
    # makes a 10K-row run produce ~50 traceable lines (chunk_size 200,
    # one per chunk) instead of one batch-summary line and a wall of
    # opaque progress writes. Fields are picked to answer "where did
    # the time go?" — bert vs db vs llm fallback overhead.
    log.info(
        "batch chunk processed",
        extra={
            "batch_job_id": str(job_id),
            "tenant_id": str(tenant_id),
            "chunk_index": chunk_index,
            "chunk_size": len(chunk),
            "rows_processed": len(chunk),
            "rows_succeeded": succeeded,
            "rows_failed": failed,
            "rows_with_llm_fallback": llm_fallback_count,
            "tickets_created": tickets,
            "duplicates_skipped": duplicates,
            "bert_ms": round(bert_seconds * 1000, 2),
            "db_ms": round(db_seconds * 1000, 2),
            "total_ms": round((time.monotonic() - chunk_started_at) * 1000, 2),
        },
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
    from imga_api.services.llm_credentials import load_active_llm_keys

    try:
        async with context.admin_session_factory() as session, session.begin():
            await set_current_tenant(session, tenant_id)
            selection = await load_active_llm_keys(session, tenant_id)
    except Exception:
        log.exception(
            "batch worker: failed to load tenant LLM keys; "
            "falling back to default classifier",
            extra={"tenant_id": str(tenant_id)},
        )
        return None

    if selection is None:
        log.info(
            "batch worker: tenant has no active LLM credentials; "
            "falling back to keyword-only classifier",
            extra={"tenant_id": str(tenant_id)},
        )
        return None
    keys = selection.keys

    # Sprint 9.0.5-A R7 — pull the parallel-LLM cap from
    # BatchSettings so a deploy can override
    # IMGA_BATCH_LLM_CONCURRENCY without code changes. Default 4
    # (R7 down from 8) keeps in-flight state bounded during a
    # provider outage so the circuit breaker can react fast.
    llm_concurrency = context.settings.llm_concurrency
    from imga_api.services.llm_provider_factory import resolve_model_name

    model_name = resolve_model_name(selection.provider, selection.model)
    if selection.provider == "openrouter":
        from imga_core.llm import RotatingOpenRouterProvider

        llm_provider: LLMProvider = RotatingOpenRouterProvider(
            keys=keys, model_name=model_name
        )
    else:
        llm_provider = RotatingGeminiProvider(
            keys=keys, model_name=model_name
        )
    log.info(
        "batch worker: tenant classifier built with %d %s key(s) "
        "(model=%s, rotator active, llm_concurrency=%d)",
        len(keys),
        selection.provider,
        model_name,
        llm_concurrency,
        extra={"tenant_id": str(tenant_id)},
    )
    return HybridClassifier(
        keyword_classifier=KeywordCategoryClassifier(),
        llm_provider=llm_provider,
        llm_concurrency=llm_concurrency,
    )


# --- Sprint 11.0 — birleşik LLM sınıflandırma bağlamı -------------------


@dataclass
class UnifiedJobContext:
    """Job-ömürlü birleşik sınıflandırma durumu: motor + kategori
    listesi + tenant düzeltme deposu + embedding key'leri. None ise
    job klasik yolda koşar (BERT zinciri + keyword/LLM classifier)."""

    engine: GeminiUnifiedEngine
    available_categories: list[str]
    store: Any  # CorrectionStore — imga_api.services.correction_store
    keys: list[Any]  # list[GeminiKey] — embedding çağrıları için
    # Sprint 13.1 — ana kategori başına alt kategori seçenekleri;
    # prompt'a girer, motor da dönen kodu bu listeye karşı doğrular.
    # Boş sözlük = kurumun eşlenmiş alt kategorisi yok; prompt bölümü
    # hiç yazılmaz ve her satır keyword sezgiseline düşer.
    perspective_options: PerspectiveOptions = field(default_factory=dict)


class BertFallbackDisabledError(RuntimeError):
    """LLM yolu başarısız ve BERT yedeği bayrakla kapalı — iş, chunk
    başına satır-failed geçidi yerine tek seferde durdurulur."""


def _bert_fallback_enabled() -> bool:
    """2026-08-10 — prod'da false: BERT yedeği hem sessiz kalite
    düşüşü hem (21k vakasında) worker OOM'u üretti. Testler ve LLM'siz
    geliştirme ortamları için varsayılan açık kalır."""
    import os

    return os.environ.get(
        "IMGA_BATCH_BERT_FALLBACK", "true"
    ).strip().lower() in ("1", "true", "yes")


def _unified_enabled() -> bool:
    import os

    return os.environ.get(
        "IMGA_UNIFIED_CLASSIFIER_ENABLED", "true"
    ).strip().lower() in ("1", "true", "yes")


def _unified_model_name() -> str:
    import os

    return (
        os.environ.get("IMGA_UNIFIED_GEMINI_MODEL")
        or os.environ.get("IMGA_GEMINI_MODEL")
        or "gemini-3-flash-preview"
    )


async def _build_unified_context(
    tenant_id: UUID, context: WorkerContext
) -> UnifiedJobContext | None:
    """Tenant'ın Gemini key'leri varsa birleşik motoru kur; yoksa
    None — job klasik yola düşer. Düzeltme deposu da burada, job
    başında bir kez yüklenir (snapshot semantiği)."""
    if not _unified_enabled():
        return None

    from imga_api.services.correction_store import load_correction_store
    from imga_api.services.llm_credentials import (
        load_active_gemini_keys,
        load_active_llm_keys,
    )

    try:
        async with context.admin_session_factory() as session, session.begin():
            await set_current_tenant(session, tenant_id)
            selection = await load_active_llm_keys(session, tenant_id)
            # Embedding API'si Gemini'ye özgü — kazanan sağlayıcı
            # OpenRouter olsa bile RAG embedding'leri Gemini anahtarı
            # ister; yoksa boş liste (embed yolu sessizce atlanır).
            embedding_keys = await load_active_gemini_keys(
                session, tenant_id
            )
            store = await load_correction_store(session, tenant_id)
            # Sprint 13.1 — alt kategori seçenekleri job başında bir
            # kez okunur (prompt payload'ı, chunk'lar arası sabit).
            taxonomy_snapshot = await _load_taxonomy_payload(
                session, tenant_id
            )
            # Sprint 11.3 — /settings/prompts override'ı: tenant
            # 'unified_classifier' şablonunu düzenlediyse system
            # prompt oradan akar (user prompt yapısını kod kurar).
            # Kendi try'ında — override OPSİYONEL; şablon sorgusu
            # patlarsa unified yolun tamamı feda edilmez, kod
            # varsayılanıyla devam edilir (code review bulgusu).
            system_prompt_override: str | None = None
            try:
                from imga_api.services.prompt_resolver import (
                    PromptResolver,
                )

                template_row = await PromptResolver(
                    session
                ).resolve_template(
                    template_key="unified_classifier", tenant_id=tenant_id
                )
                if template_row is not None:
                    system_prompt_override = template_row.system_prompt
            except Exception:
                log.warning(
                    "unified prompt override lookup failed; using "
                    "code default system prompt",
                    extra={"tenant_id": str(tenant_id)},
                )
    except Exception:
        log.exception(
            "batch worker: unified context build failed; classic path",
            extra={"tenant_id": str(tenant_id)},
        )
        return None
    if selection is None:
        log.info(
            "batch worker: no LLM keys; unified classifier disabled "
            "for this job (classic BERT+keyword path)",
            extra={"tenant_id": str(tenant_id)},
        )
        return None
    keys = selection.keys

    from imga_core.categories.taxonomy import GLOBAL_CATEGORY_CODES

    from imga_api.services.llm_provider_factory import resolve_model_name

    if selection.provider == "openrouter":
        unified_model = resolve_model_name("openrouter", selection.model)
    else:
        unified_model = selection.model or _unified_model_name()
    engine = GeminiUnifiedEngine(
        keys,
        model_name=unified_model,
        concurrency=max(1, context.settings.llm_concurrency // 2),
        system_prompt=system_prompt_override,
        provider=selection.provider,
    )
    log.info(
        "batch worker: unified classifier active (model=%s, keys=%d, "
        "corrections=%d)",
        engine.model_name,
        len(keys),
        len(store.exact),
        extra={"tenant_id": str(tenant_id)},
    )
    return UnifiedJobContext(
        engine=engine,
        available_categories=list(GLOBAL_CATEGORY_CODES),
        store=store,
        keys=embedding_keys,
        perspective_options=taxonomy_snapshot.perspective_options,
    )


async def _few_shot_for_chunk(
    unified_ctx: UnifiedJobContext,
    texts: list[str],
    context: WorkerContext,
    tenant_id: UUID,
) -> tuple[tuple[FewShotExample, ...], dict[int, Any]]:
    """Chunk için düzeltme bağlamı (RAG):

      * few-shot — güncel düzeltmeler + chunk merkezine anlamsal en
        yakın düzeltmeler;
      * semantik doğrudan override (Sprint 11.3) — embed edilen
        satırlardan, bir düzeltmeye cosine ≥ 0.95 benzeyenler insan
        kararını devralır (index -> CorrectedDecision).

    Embedding erişilemezse sessizce (few-shot=güncel, override=boş)
    moduna düşer — RAG hiçbir zaman analizi bloklamaz."""
    from imga_api.services.correction_store import (
        merge_few_shot,
        nearest_corrections,
        semantic_override_lookup,
    )
    from imga_api.services.embedding_service import embed_texts

    recent = unified_ctx.store.recent_examples
    semantic = []
    semantic_hits: dict[int, Any] = {}
    if recent:
        try:
            sample = texts[:64]
            vectors = await embed_texts(sample, unified_ctx.keys)
            if vectors:
                dim = len(vectors[0])
                centroid = [
                    sum(v[d] for v in vectors) / len(vectors)
                    for d in range(dim)
                ]
                async with (
                    context.admin_session_factory() as session,
                    session.begin(),
                ):
                    await set_current_tenant(session, tenant_id)
                    semantic = await nearest_corrections(
                        session, tenant_id, centroid
                    )
                    # Satır-bazlı doğrudan override — HNSW indeksli
                    # k=1 sorgular, embed edilen örneklem için (ek
                    # API maliyeti yok; vektörler zaten elimizde).
                    # Tenant'ta embedding'li düzeltme yoksa atla —
                    # chunk başına 64 boş sorgu (code review bulgusu).
                    if unified_ctx.store.has_embeddings:
                        for i, vector in enumerate(vectors):
                            decision = await semantic_override_lookup(
                                session, tenant_id, vector
                            )
                            if decision is not None:
                                semantic_hits[i] = decision
        except Exception as exc:
            log.warning("semantic few-shot lookup failed: %s", exc)
    merged = merge_few_shot(list(recent), list(semantic))
    few_shot = tuple(
        FewShotExample(
            text=e.text,
            sentiment_label=e.sentiment_label,
            category=e.category,
            reason=e.reason,
        )
        for e in merged
    )
    return few_shot, semantic_hits


def _apply_corrections(
    analyses: list[AnalysisResult],
    texts: list[str],
    unified_ctx: UnifiedJobContext,
    semantic_hits: dict[int, Any] | None = None,
) -> list[AnalysisResult]:
    """Düzeltme katmanları (insan kararı her yolu ezer):

      1. Birebir — text_hash eşleşmesi (eski 'Train & Save' KB
         davranışının DB-bazlı, tenant-scoped hali).
      2. Anlamsal (Sprint 11.3) — embed edilen satırlardan bir
         düzeltmeye cosine ≥ 0.95 benzeyenler. Birebir eşleşme
         önceliklidir."""
    from imga_api.services.correction_store import (
        patch_analysis_with_decision,
    )

    hits = semantic_hits or {}
    if not unified_ctx.store.has_corrections and not hits:
        return analyses

    patched: list[AnalysisResult] = []
    for i, (text, analysis) in enumerate(zip(texts, analyses, strict=True)):
        decision = unified_ctx.store.exact_lookup(review_text_hash(text))
        if decision is not None:
            patched.append(
                patch_analysis_with_decision(
                    analysis,
                    decision,
                    layer="user_correction_kb",
                    detail_prefix="Tenant düzeltme sözlüğü",
                )
            )
            continue
        semantic_decision = hits.get(i)
        if semantic_decision is not None:
            patched.append(
                patch_analysis_with_decision(
                    analysis,
                    semantic_decision,
                    layer="user_correction_semantic",
                    detail_prefix="Anlamsal düzeltme eşleşmesi (≥0.95)",
                )
            )
            continue
        patched.append(analysis)
    return patched


async def _fetch_dimension_mapping(
    tenant_id: UUID, context: WorkerContext
) -> dict[str, str]:
    """Sprint 9.4 D — load the tenant's enabled business-dimension
    config and return ``{dimension: csv_column_mapping}`` for every
    dimension whose mapping is set. Disabled dimensions and
    dimensions without a mapping are filtered out.

    Returned dict is empty when the tenant has no dimensions
    configured — the parser handles that as "no dimension columns",
    keeping the four Review.dimension columns NULL. Best-effort: a
    failure to load the config logs but doesn't break the upload —
    dimension data is observability-grade, not contract.
    """
    try:
        async with context.admin_session_factory() as session, session.begin():
            await set_current_tenant(session, tenant_id)
            stmt = (
                select(
                    TenantBusinessDimension.dimension,
                    TenantBusinessDimension.csv_column_mapping,
                )
                .where(TenantBusinessDimension.tenant_id == tenant_id)
                .where(TenantBusinessDimension.enabled.is_(True))
                .where(TenantBusinessDimension.csv_column_mapping.is_not(None))
            )
            rows = (await session.execute(stmt)).all()
    except Exception:
        log.exception(
            "batch worker: dimension mapping load failed; "
            "reviews will land with NULL dimension columns",
            extra={"tenant_id": str(tenant_id)},
        )
        return {}
    return {dim: col for dim, col in rows if col}


@dataclass(frozen=True, slots=True)
class TenantTaxonomySnapshot:
    """One read of ``category_taxonomies``, shaped for its three
    consumers (Sprint 13.1).

      * ``heuristic_entries`` — ``apply_company_heuristic``'in
        beklediği list-of-dicts. Tarihsel davranışı korumak için
        ``is_active`` filtresi YOK (sezgisel bu payload'ı 8.3.5.6'dan
        beri böyle görüyor).
      * ``perspective_options`` — birleşik sınıflandırıcı prompt'u:
        ana kategori -> [(alt kod, etiket)]. Yalnız AKTİF ve ana
        kategoriye eşlenmiş satırlar.
      * ``labels`` — kod -> Türkçe etiket; LLM'den gelen alt kategori
        kodunun ``company_perspective_label_tr`` karşılığı için.
    """

    heuristic_entries: list[TaxonomyEntry]
    perspective_options: PerspectiveOptions
    labels: dict[str, str]


async def _load_taxonomy_payload(
    session: AsyncSession, tenant_id: UUID
) -> TenantTaxonomySnapshot:
    """Read the tenant's CategoryTaxonomy rows once per chunk / job.

    Returns an empty snapshot when the tenant has no taxonomy (legacy /
    pre-8.3.5.5 tenants that never landed via ``TenantService.create``);
    the heuristic short-circuits to ``None`` on an empty list and the
    classifier prompt simply omits the sub-category section.
    """
    stmt = select(
        CategoryTaxonomy.code,
        CategoryTaxonomy.label_tr,
        CategoryTaxonomy.keywords,
        CategoryTaxonomy.priority,
        CategoryTaxonomy.primary_category_code,
        CategoryTaxonomy.is_active,
    ).where(CategoryTaxonomy.tenant_id == tenant_id)
    rows = (await session.execute(stmt)).all()

    entries: list[TaxonomyEntry] = []
    options: PerspectiveOptions = {}
    labels: dict[str, str] = {}
    for r in rows:
        entries.append(
            TaxonomyEntry(
                code=r.code,
                label_tr=r.label_tr,
                keywords=list(r.keywords),
                priority=r.priority,
            )
        )
        labels[r.code] = r.label_tr
        if r.is_active and r.primary_category_code:
            options.setdefault(r.primary_category_code, []).append(
                (r.code, r.label_tr)
            )
    return TenantTaxonomySnapshot(
        heuristic_entries=entries, perspective_options=options, labels=labels
    )


__all__ = [
    "WorkerContext",
    "build_worker_context",
    "process_batch_job",
    "recover_orphans",
]
