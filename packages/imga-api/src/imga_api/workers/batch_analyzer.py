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
from uuid import UUID, uuid4

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
    Category,
    CategoryTaxonomy,
    Review,
    ReviewDecision,
    ReviewFact,
    TenantBusinessDimension,
    TenantCategory,
    TenantFactMapping,
)
from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from imga_api.services.audit_service import AuditService
from imga_api.services.batch_service import (
    BatchAnalyzeService,
    BatchProgress,
)
from imga_api.services.data_quality import classify_data_quality, detect_content_type
from imga_api.services.fact_parsing import build_fact_row
from imga_api.services.review_service import ReviewService
from imga_api.services.root_cause_autogen import mark_enqueued
from imga_api.services.tenant_config_service import TenantConfigService
from imga_api.services.ticket_service import TicketService
from imga_api.settings import BatchSettings
from imga_api.workers.file_parser import (
    FileParseError,
    UnknownColumnError,
    iter_rows,
    peek_date_column_found,
    peek_detected_nps_column,
)

if TYPE_CHECKING:
    from cachetools import TTLCache

    from imga_api.services.correction_store import CorrectedDecision

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
      * ``arq_pool`` — the arq worker's own Redis job-queue connection
        (``ctx["redis"]``, wired at process startup — see
        ``arq_worker._startup_impl``). ``None`` in tests / the
        in-process fallback path; the post-batch root-cause
        auto-generation enqueue is a no-op then, matching the same
        "no dispatch target, don't crash the batch" contract
        ``scheduler.enqueue_batch_job`` uses for the API side.
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
    arq_pool: Any | None = None

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
    arq_pool: Any | None = None,
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
        arq_pool=arq_pool,
    )


def _select_pipeline(context: WorkerContext, *, chunk_index: int | None) -> AnalysisPipeline:
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
            await _record_catastrophic_failure(job_id, tenant_id, context, reason=str(exc))


async def _read_tenant_id(
    job_id: UUID,
    factory: async_sessionmaker[AsyncSession],
) -> UUID | None:
    async with factory() as session, session.begin():
        stmt = select(AnalyzeBatchJob.tenant_id).where(AnalyzeBatchJob.id == job_id)
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
                job_id,
                job.status,
            )
            return
        file_path = Path(job.file_path)
        text_column = job.text_column
        source_column = job.source_column
        # 2026-08-20 (migration 0044) — operatörün Step-2'de elle seçtiği
        # tarih kolonu; boşsa file_parser'ın (güçlendirilmiş) otomatik
        # tespitine düşülür. Bkz. aşağıdaki uyarı bloğu + iter_rows çağrısı.
        date_column = job.date_column
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

    # 2026-08-20 (migration 0044) — operatör açıkça bir tarih kolonu
    # seçtiyse ama bu dosyada o başlık yoksa (ör. önizlemeden sonra
    # dosya değiştirildi), iş YİNE DE işlenir — satırlar tarihsiz kalır
    # (bkz. file_parser._resolve_columns) — ama operatör "neden tüm
    # yorumlar bugüne düştü" sorusunu kendi kendine cevaplayabilsin diye
    # job üzerinde görünür bir uyarı bırakılır. apply_progress zaten
    # var olan error_summary'ye EKLER (100 kayıt tavanıyla), üzerine
    # yazmaz.
    if date_column:
        date_column_found = True
        with contextlib.suppress(FileParseError):
            date_column_found = peek_date_column_found(file_path, date_column)
        if not date_column_found:
            async with context.admin_session_factory() as admin_session, admin_session.begin():
                await set_current_tenant(admin_session, tenant_id)
                warn_audit = AuditService(admin_session)
                await BatchAnalyzeService(admin_session, warn_audit).apply_progress(
                    job_id=job_id,
                    progress=BatchProgress(
                        error_entries=[
                            {
                                "row": None,
                                "error": (
                                    f"Seçilen tarih kolonu '{date_column}' "
                                    "dosyada bulunamadı; tüm satırlar "
                                    "yükleme anının tarihini alacak."
                                ),
                            }
                        ]
                    ),
                )

    # Sprint 9.4 D — fetch the per-tenant business-dimension mapping
    # once at job start. Each enabled dimension with a non-null
    # ``csv_column_mapping`` contributes one entry; the file parser
    # uses these to populate the four nullable Review columns
    # (business_segment / product_line / channel / customer_tier).
    dimension_mapping = await _fetch_dimension_mapping(tenant_id, context)

    # Migration 0046 — same pattern, for the operational "facts"
    # columns (SLA/CSAT/effort/compensation/delivery).
    fact_mapping = await _fetch_fact_mapping(tenant_id, context)

    try:
        rows_iter = iter_rows(
            file_path,
            text_column=text_column,
            source_column=source_column,
            dimension_mapping=dimension_mapping,
            fact_mapping=fact_mapping,
            date_column=date_column,
        )
    except (FileParseError, UnknownColumnError) as exc:
        await _record_catastrophic_failure(job_id, tenant_id, context, reason=str(exc))
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
        rows_iter = (row for row in rows_iter if row.row_number > resume_from_row)

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
    await _enqueue_root_cause_auto_gen(
        tenant_id,
        context,
        batch_job_id=job_id,
        rows_succeeded=(completed_job.succeeded_rows or 0) if completed_job is not None else 0,
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
                job_id=job_id,
                tenant_id=tenant_id,
                chunk=chunk,
                auto_create=auto_create,
                triggered_by_user_id=triggered_by_user_id,
                seen_hashes=seen_hashes,
                context=context,
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
            done, pending = await asyncio.wait(in_flight, return_when=asyncio.FIRST_COMPLETED)
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


async def _enqueue_root_cause_auto_gen(
    tenant_id: UUID,
    context: WorkerContext,
    *,
    batch_job_id: UUID,
    rows_succeeded: int,
) -> None:
    """Sprint 13.x+ — fire-and-forget kickoff for the post-batch root-
    cause auto-generation task (``generate_root_causes_task``,
    workers/arq_worker.py).

    2026-09 — ``_job_id`` artık ``batch_job_id`` içerir, yani her
    tamamlanan batch KENDİ arq işini tetikler. Eski format
    (``rootcause:{tenant_id}:{date}``) aynı gün içindeki ikinci bir
    yüklemeyi arq'ın kendi job-id dedup'ına düşürüyordu — o gün ikinci
    kez yükleyen kullanıcı hiçbir güncelleme görmüyordu. Maliyet
    kontrolü artık burada DEĞİL: ``rows_succeeded`` task'a taşınır,
    task orada ``force_refresh``'i karara bağlar (bkz.
    ``generate_root_causes_task`` docstring'i) ve ``RootCauseService``'in
    12h cache'i küçük tekrar-yüklemeleri ücretsiz karşılar.

    "Hazırlanıyor" bayrağı — 2026-09 sonrası bir Redis SET'e taşındı
    (``services/root_cause_autogen.py``): her batch kendi
    ``batch_job_id``'sini o SET'e üye ekler, task başlarken üyeliği
    yeniler (imga-batch tek işçili FIFO — büyük bir batch kuyrukta
    öndeyse eski string-bayrağın TTL'i işin gerçek başlangıcından ÖNCE
    dolabiliyordu) ve kendi ``finally``'sinde SADECE kendi üyeliğini
    siler — iki eşzamanlı yükleme artık birbirinin bayrağını erken
    kapatmaz (eski tasarımın ikinci audited kusuru). ``enqueue_job``
    ``None`` döndüğünde (arq'ın kendi job-id dedup'ı) HİÇBİR üyelik
    eklenmez — izlenecek yeni bir iş yok.

    Best-effort like ``_publish_terminal``: no arq pool wired (tests,
    or the in-process-scheduler fallback deploy) is a silent no-op,
    and an enqueue failure is logged + swallowed — a stalled root-
    cause refresh must never fail the batch that already succeeded.
    ``mark_enqueued`` is equally best-effort on its own (see
    ``root_cause_autogen.py``); a Redis failure there is logged +
    swallowed, never allowed to fail the batch.
    """
    if context.arq_pool is None:
        return
    try:
        job = await context.arq_pool.enqueue_job(
            "generate_root_causes_task",
            str(tenant_id),
            rows_succeeded,
            str(batch_job_id),
            _job_id=f"rootcause:{tenant_id}:{batch_job_id}",
            _queue_name="imga-batch",
        )
    except Exception:
        log.exception(
            "batch worker: root-cause auto-gen enqueue failed (non-fatal)",
            extra={"tenant_id": str(tenant_id), "batch_job_id": str(batch_job_id)},
        )
        return

    if job is None:
        # arq dedup: a job with this _job_id already exists (queued or
        # in flight). No NEW job means nothing new to track — that
        # existing job's own mark_enqueued/mark_started/mark_finished
        # lifecycle already owns the tracking-set membership.
        return

    await mark_enqueued(tenant_id, batch_job_id)


async def _publish_terminal(job_id: UUID, tenant_id: UUID, context: WorkerContext) -> None:
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
        stmt = select(AnalyzeBatchJob.status).where(AnalyzeBatchJob.id == job_id)
        status = (await session.execute(stmt)).scalar_one_or_none()
        return status == BatchJobStatus.CANCELLED


async def _write_empty_reviews(
    app_session: AsyncSession,
    *,
    tenant_id: UUID,
    job_id: UUID,
    empty_rows: list[Any],  # list[ParsedRow]
    tenant_mode: str,
    triggered_by_user_id: UUID | None,
) -> None:
    """2026-08-18 (migration 0042) WS2 — persist one Review row per
    empty-text ``ParsedRow``: ``quality_flag='empty'``, sentiment
    NÖTR/0.0, ``primary_category='belirsiz'``, confidence 0.0,
    ``decision=SKIPPED_QUALITY``. Never touches BERT/LLM or
    ``seen_hashes`` — every empty text normalizes to the SAME
    ``text_hash`` (sha256 of an empty string), so if these rows ever
    flowed through the normal dedup/exact-lookup paths the second one
    onward would be misclassified as 'duplicate'. Called from both the
    normal per-chunk success path and the catastrophic-BERT-failure
    fallback (empty rows never depended on BERT, so they must not be
    lost when the rest of the chunk fails).

    Migration 0046 — an empty-text row can still carry facts (SLA/CSAT/
    etc. are independent of the review text cell); each row's
    ``parsed.facts`` is parsed and accumulated into one bulk
    ``review_facts`` upsert at the end, same as the three Review
    branches in ``_process_chunk``."""
    row_moment = datetime.now(UTC)
    fact_rows: list[dict[str, Any]] = []
    for parsed in empty_rows:
        review_id = uuid4()
        review = Review(
            id=review_id,
            tenant_id=tenant_id,
            text=parsed.text,
            text_hash=review_text_hash(parsed.text),
            sentiment_label="NÖTR",
            sentiment_score=0.0,
            primary_category="belirsiz",
            primary_confidence=0.0,
            automation_mode=tenant_mode,
            decision=ReviewDecision.SKIPPED_QUALITY,
            decision_reason="empty_text",
            quality_flag="empty",
            ticket_id=None,
            submitted_by_user_id=triggered_by_user_id,
            batch_job_id=job_id,
            analyzed_at=row_moment,
            review_date=parsed.review_date or row_moment,
            overrides_applied=[],
            nps_score=parsed.nps_score,
            business_segment=parsed.business_segment,
            product_line=parsed.product_line,
            channel=parsed.channel,
            customer_tier=parsed.customer_tier,
            entered_by=parsed.entered_by,
            source=parsed.source,
            source_url=parsed.source_url,
            content_type=None,  # boş metin hiçbir zaman soru olamaz
            source_meta=parsed.source_meta,
        )
        app_session.add(review)
        if parsed.facts:
            fact_row = build_fact_row(parsed.facts)
            if fact_row is not None:
                fact_rows.append({"review_id": review_id, "tenant_id": tenant_id, **fact_row})
    await _upsert_review_facts(app_session, fact_rows)


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
    # 2026-08-18 (migration 0042) WS2 — veri kalitesi bayrak sayaçları.
    # quality_duplicate hem intra-batch hem cross-batch (record_and_decide
    # SKIPPED_DEDUP) dalından gelir; ``duplicates`` (yukarıdaki) zaten bu
    # ikisini toplar, quality_duplicate onun quality_flag'e yansıyan
    # aynasıdır.
    quality_duplicate = 0
    quality_empty = 0
    quality_informational = 0
    quality_meaningless = 0
    # Sprint 9.1 E — chunk-level timing for the structured log emitted
    # at the bottom of this function. ``time.monotonic()`` is the
    # right tool for elapsed measurement; wall-clock would be tripped
    # by NTP slews mid-run.
    chunk_started_at = time.monotonic()
    bert_seconds = 0.0
    db_seconds = 0.0
    llm_fallback_count = 0

    # 2026-08-18 (migration 0042) WS2 — boş metin artık 'failed'
    # sayılmaz: her boş satır aşağıdaki DB bloğunda quality_flag='empty'
    # bir Review olarak YAZILIR (BERT/LLM'e hiç girmeden — bkz.
    # _write_empty_reviews). KRİTİK: bu satırlar seen_hashes'e HİÇ
    # girmez (hash("") çakışması olmasın diye intra-batch dedup, cross-
    # batch dedup lookup'ı ve birebir düzeltme lookup'ı tamamı valid_rows
    # üzerinden çalışan aşağıdaki döngüye/record_and_decide çağrısına
    # hiç girmeyen bu listeden atlanır — ayrı bir guard eklemeye gerek
    # yok, yapısal olarak zaten dokunulmuyor).
    valid_rows: list[Any] = []
    empty_rows: list[Any] = []
    for parsed in chunk:
        if not parsed.text:
            empty_rows.append(parsed)
            continue
        valid_rows.append(parsed)

    # Sprint 9.0 — checkpoint = highest row_number in this chunk.
    # The chunk is ordered by row_number (iter_rows is sequential), so
    # max() == chunk[-1].row_number; computing max defensively in case
    # a later refactor shuffles ordering.
    chunk_checkpoint = max((p.row_number for p in chunk), default=0)

    # BERT inference — outside any DB transaction. Skipped entirely
    # when the chunk has no non-empty text (an all-empty chunk still
    # falls through to the DB block below to persist the empty rows).
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
    classifier_stats: dict[str, int] = {}
    analyses: list[AnalysisResult] = []
    semantic_hits: dict[int, Any] = {}
    unified_perspectives: list[str | None] = []
    unified_experiences: list[str | None] = []
    # 2026-08-18 (migration 0042, B3 sözleşme notu) — satır başına
    # UYGULANAN insan düzeltmesi (None = düzeltme yok). experience_type
    # / perspective_code AnalysisResult'a giremediği için
    # patch_analysis_with_decision yalnız izlenebilirlik metni yazar;
    # bu liste per-satır döngüsünün deneyim/perspektif hesaplamasına
    # düzeltmeyi UYGULAMASI için taşınır.
    correction_overrides: list[CorrectedDecision | None] = []
    if valid_rows:
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
            # Sprint 11.0 — birincil yol: birleşik Gemini sınıflandırma
            # (sentiment + kategori tek çağrı setinde, few-shot düzeltme
            # örnekleriyle). Motor üretemezse klasik yola düşülür: BERT
            # zinciri (uzak Modal → lazy lokal) + keyword/LLM classifier.
            # Sprint 13.1 — LLM'in seçtiği alt kategori kodları, satır
            # sırasına göre. Klasik yola düşülürse boş kalır ve persist
            # döngüsü tümüyle keyword sezgiseline güvenir.
            # 2026-08-10 — LLM'in temas noktası kararı, satır sırasına göre.
            # Klasik yola düşülürse boş kalır ve satırlar NULL persist edilir.
            unified_analyses: list[AnalysisResult] | None = None
            if unified_ctx is not None:
                try:
                    few_shot, semantic_hits = await _few_shot_for_chunk(
                        unified_ctx, texts, context, tenant_id
                    )
                    unified_analyses = await pipeline.analyze_batch_unified_async(
                        texts,
                        engine=unified_ctx.engine,
                        available_categories=unified_ctx.available_categories,
                        few_shot=few_shot,
                        stats_sink=classifier_stats,
                        perspective_options=unified_ctx.perspective_options,
                        perspective_sink=unified_perspectives,
                        category_descriptions=unified_ctx.category_descriptions,
                        experience_sink=unified_experiences,
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
                        "unified classifier failed for chunk; falling back to classic pipeline: %s",
                        exc,
                    )
                    unified_analyses = None
                    unified_perspectives = []
                    unified_experiences = []
            if unified_analyses is None:
                analyses = await pipeline.analyze_batch_async(
                    texts,
                    classifier=classifier_override,
                    classifier_stats_sink=classifier_stats,
                )
            else:
                analyses = unified_analyses
            # Düzeltme katmanları — insan kararı her yolu ezer
            # (birebir + anlamsal).
            if unified_ctx is not None:
                analyses, correction_overrides = _apply_corrections(
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
                error_entries.append({"row": parsed.row_number, "error": f"pipeline failed: {exc}"})
                failed += 1
            # 2026-08-18 WS2 — boş satırlar BERT'e hiç bağımlı değildi;
            # valid_rows analizi tamamen çökse bile empty_rows kaybolmasın
            # diye burada da persist edilir (aksi halde checkpoint bu
            # satırların row_number'ını da geçer ve bir daha asla
            # görünmezlerdi — bkz. _write_empty_reviews docstring).
            empty_succeeded = 0
            if empty_rows:
                async with (
                    context.app_session_factory() as fallback_session,
                    fallback_session.begin(),
                ):
                    await set_current_tenant(fallback_session, tenant_id)
                    fallback_audit = AuditService(fallback_session)
                    fallback_config_service = TenantConfigService(
                        fallback_session,
                        fallback_audit,
                        context.tenant_config_cache,
                    )
                    fallback_tenant_config = await fallback_config_service.get_config(tenant_id)
                    await _write_empty_reviews(
                        fallback_session,
                        tenant_id=tenant_id,
                        job_id=job_id,
                        empty_rows=empty_rows,
                        tenant_mode=str(fallback_tenant_config["automation_mode"]),
                        triggered_by_user_id=triggered_by_user_id,
                    )
                empty_succeeded = len(empty_rows)
            await _commit_progress(
                job_id=job_id,
                tenant_id=tenant_id,
                context=context,
                progress=BatchProgress(
                    processed_delta=len(chunk),
                    succeeded_delta=empty_succeeded,
                    failed_delta=failed,
                    quality_empty_delta=empty_succeeded,
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
        config_service = TenantConfigService(app_session, audit, context.tenant_config_cache)
        review_service = ReviewService(app_session, audit, ticket_service, config_service)

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
            f"{p.row_number}:{p.text[:200]}" for p in valid_rows[: min(20, len(valid_rows))]
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
                audit_model_name = getattr(_llm, "model_name", DEFAULT_MODEL_NAME)
                _pname = str(getattr(_llm, "PROVIDER_NAME", "gemini"))
                audit_provider = "openrouter" if "openrouter" in _pname else "gemini"
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
            app_session,
            audit_ctx,
            prompt=chunk_anchor,
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

        # 2026-08-18 (migration 0042) WS2 — boş metinli satırlar burada
        # yazılır: BERT/LLM'e hiç girmediler, hash'e de girmediler
        # (yukarıdaki modül docstring'i). succeeded'a eklenir, failed'a
        # DEĞİL.
        if empty_rows:
            await _write_empty_reviews(
                app_session,
                tenant_id=tenant_id,
                job_id=job_id,
                empty_rows=empty_rows,
                tenant_mode=tenant_mode,
                triggered_by_user_id=triggered_by_user_id,
            )
            quality_empty = len(empty_rows)
            succeeded += quality_empty

        # Sprint 8.3.5.6. Fetch the company taxonomy once per chunk so
        # the heuristic reranker doesn't hit the DB per row. The auto-
        # create branch routes through ReviewService.record_and_decide
        # which has its own fetch — duplicate work, but keeps both
        # paths self-sufficient and the read is cheap (21 rows max,
        # B-tree index on tenant_id).
        taxonomy_snapshot = await _load_taxonomy_payload(app_session, tenant_id)

        # Migration 0046 — accumulated across all three Review-insertion
        # branches below (dedup / auto_create / opt-out) and upserted
        # in ONE bulk statement after the loop, mirroring the existing
        # per-chunk-transaction persist shape.
        fact_rows: list[dict[str, Any]] = []

        for row_index, (parsed, analysis) in enumerate(zip(valid_rows, analyses, strict=True)):
            from imga_core import review_text_hash

            text_hash = review_text_hash(parsed.text)
            # Tek an, üç dal: yorumun kendi tarihi yoksa review_date de
            # analyzed_at de aynı ingest anına düşsün.
            row_moment = datetime.now(UTC)

            # Migration 0049 — content_type quality_flag'ten (aşağıdaki
            # row_quality_flag) BAĞIMSIZ: tanımlayıcı bir biçim işareti,
            # düzeltme guard'ı (FX1, ~satır 1300) onu etkilemez ve intra-
            # batch dedup dalı (aşağıda, row_quality_flag hesaplanmadan
            # ÖNCE `continue` eder) da ona ihtiyaç duyar — bu yüzden
            # burada, text_hash ile aynı anda, koşulsuz hesaplanır.
            content_type = detect_content_type(parsed.text)

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
                unified_perspectives[row_index] if row_index < len(unified_perspectives) else None
            )
            # 2026-08-18 (migration 0042, B3 sözleşme notu) — bu satır
            # birebir/anlamsal düzeltmeyle eşleştiyse (bkz.
            # _apply_corrections), kayıtlı deneyim/perspektif İNSAN
            # KARARI olarak LLM'in kendi tahmininin ÖNÜNE geçer.
            # decision alanı NULL ise (operatör o alanı boş bıraktıysa)
            # LLM/heuristik değeri aynen korunur.
            correction_override = (
                correction_overrides[row_index] if row_index < len(correction_overrides) else None
            )
            experience_type = normalize_experience_type(
                correction_override.experience_type
                if correction_override is not None
                and correction_override.experience_type is not None
                else (
                    unified_experiences[row_index] if row_index < len(unified_experiences) else None
                )
            )
            perspective_code: str | None
            perspective_label: str | None
            correction_perspective = (
                correction_override.perspective_code if correction_override is not None else None
            )
            if correction_perspective is not None:
                perspective_code = correction_perspective
                perspective_label = taxonomy_snapshot.labels.get(
                    correction_perspective, correction_perspective
                )
            elif llm_perspective is not None and (llm_perspective in taxonomy_snapshot.labels):
                perspective_code = llm_perspective
                perspective_label = taxonomy_snapshot.labels[llm_perspective]
            else:
                perspective_hit = apply_company_heuristic(
                    parsed.text, taxonomy=taxonomy_snapshot.heuristic_entries
                )
                perspective_code = perspective_hit.code if perspective_hit is not None else None
                perspective_label = (
                    perspective_hit.label_tr if perspective_hit is not None else None
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
                dup_review_id = uuid4()
                review = Review(
                    id=dup_review_id,
                    tenant_id=tenant_id,
                    text=parsed.text,
                    text_hash=text_hash,
                    sentiment_label=analysis.sentiment_label,
                    sentiment_score=float(analysis.sentiment_score),
                    primary_category=(
                        analysis.categorization.primary if analysis.categorization else "belirsiz"
                    ),
                    primary_confidence=float(
                        analysis.categorization.primary_confidence
                        if analysis.categorization
                        else 0.0
                    ),
                    automation_mode=tenant_mode,
                    decision=ReviewDecision.SKIPPED_DEDUP,
                    decision_reason="intra_batch_duplicate",
                    quality_flag="duplicate",
                    ticket_id=None,
                    submitted_by_user_id=triggered_by_user_id,
                    batch_job_id=job_id,
                    analyzed_at=row_moment,
                    review_date=parsed.review_date or row_moment,
                    overrides_applied=[hit.model_dump() for hit in analysis.overrides_applied],
                    nps_score=parsed.nps_score,
                    company_perspective_code=perspective_code,
                    experience_type=experience_type,
                    business_segment=parsed.business_segment,
                    product_line=parsed.product_line,
                    channel=parsed.channel,
                    customer_tier=parsed.customer_tier,
                    entered_by=parsed.entered_by,
                    source=parsed.source,
                    source_url=parsed.source_url,
                    content_type=content_type,
                    source_meta=parsed.source_meta,
                )
                app_session.add(review)
                if parsed.facts:
                    fact_row = build_fact_row(parsed.facts)
                    if fact_row is not None:
                        fact_rows.append(
                            {
                                "review_id": dup_review_id,
                                "tenant_id": tenant_id,
                                **fact_row,
                            }
                        )
                duplicates += 1
                quality_duplicate += 1
                succeeded += 1
                if parsed.nps_score is not None:
                    rows_with_nps_in_chunk += 1
                continue

            # 2026-08-18 (migration 0042) WS2 — deterministik Türkçe
            # heuristik (imga_api.services.data_quality). Motor yolundan
            # (unified/classic) bağımsız, her zaman burada koşar; sadece
            # quality_flag'i doldurur, decision akışını DEĞİŞTİRMEZ.
            # Cross-batch dedup (record_and_decide'ın kendi SKIPPED_DEDUP
            # kararı) bu değeri aşağıda ezer — dedup her zaman içerik
            # kalitesinden önceliktir (0042 backfill semantiğiyle aynı).
            # 2026-08-18 adversarial inceleme FX1 — satır birebir/anlamsal
            # bir düzeltmeyle eşleştiyse (correction_override is not None)
            # heuristik HİÇ ÇALIŞTIRILMAZ: bir insan bu metni gerçek yorum
            # sayıp deneyim/perspektif kararı verdi, dolayısıyla quality_flag
            # None'a sabitlenir — aksi halde heuristik aynı satırı
            # 'informational'/'meaningless' damgalayıp insan kararını
            # analitikten sessizce düşürebilirdi.
            row_quality_flag = (
                None if correction_override is not None else classify_data_quality(parsed.text)
            )

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
                        # 2026-08-18 — bir insan düzeltmesi perspective_code
                        # sağladıysa (correction_perspective) LLM'inkiyle
                        # AYNI önceliği taşır: ikisinden biri varsa
                        # record_and_decide'ın kendi heuristiğini ezer.
                        perspective_override=(
                            (perspective_code, perspective_label)
                            if (correction_perspective is not None or llm_perspective is not None)
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
                # 2026-08-10 — experience_type de aynı UPDATE'e binir:
                # köprü de temas noktası kavramından habersiz. 2026-08-18
                # (migration 0042) — entered_by/source/quality_flag de
                # aynı desene biner (record_and_decide imzası
                # genişletilmedi — mevcut back-fill deseni izlendi).
                # Cross-batch dedup (SKIPPED_DEDUP) 'duplicate' ile
                # içerik-kalitesi bayrağının ÖNÜNE geçer.
                final_quality_flag = (
                    "duplicate"
                    if result.decision == ReviewDecision.SKIPPED_DEDUP
                    else row_quality_flag
                )
                # Migration 0049 — content_type/source_meta aynı desene
                # biner AMA final_quality_flag'in aksine dedup kararından
                # ETKİLENMEZ: cross-batch bir tekrar da hâlâ aynı soru
                # biçimini/sayaçları taşır — quality_flag "düşük kalite"
                # yargısı, content_type yalnızca metnin biçimi.
                if parsed.facts:
                    fact_row = build_fact_row(parsed.facts)
                    if fact_row is not None:
                        fact_rows.append(
                            {
                                "review_id": result.review_id,
                                "tenant_id": tenant_id,
                                **fact_row,
                            }
                        )
                await app_session.execute(
                    update(Review)
                    .where(Review.id == result.review_id)
                    .values(
                        batch_job_id=job_id,
                        experience_type=experience_type,
                        quality_flag=final_quality_flag,
                        entered_by=parsed.entered_by,
                        source=parsed.source,
                        source_url=parsed.source_url,
                        content_type=content_type,
                        source_meta=parsed.source_meta,
                    )
                )
                if result.decision == ReviewDecision.CREATE:
                    tickets += 1
                if result.decision == ReviewDecision.SKIPPED_DEDUP:
                    duplicates += 1
                    quality_duplicate += 1
                elif final_quality_flag == "informational":
                    quality_informational += 1
                elif final_quality_flag == "meaningless":
                    quality_meaningless += 1
                succeeded += 1
                if parsed.nps_score is not None:
                    rows_with_nps_in_chunk += 1
            else:
                # Opt-out path: persist a review row marked SKIPPED_MODE
                # so the user still sees the analysis, but no ticket.
                primary = analysis.categorization.primary if analysis.categorization else "belirsiz"
                confidence = float(
                    analysis.categorization.primary_confidence if analysis.categorization else 0.0
                )
                opt_out_review_id = uuid4()
                review = Review(
                    id=opt_out_review_id,
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
                    quality_flag=row_quality_flag,
                    ticket_id=None,
                    submitted_by_user_id=triggered_by_user_id,
                    batch_job_id=job_id,
                    analyzed_at=row_moment,
                    review_date=parsed.review_date or row_moment,
                    overrides_applied=[hit.model_dump() for hit in analysis.overrides_applied],
                    nps_score=parsed.nps_score,
                    company_perspective_code=perspective_code,
                    experience_type=experience_type,
                    business_segment=parsed.business_segment,
                    product_line=parsed.product_line,
                    channel=parsed.channel,
                    customer_tier=parsed.customer_tier,
                    entered_by=parsed.entered_by,
                    source=parsed.source,
                    source_url=parsed.source_url,
                    content_type=content_type,
                    source_meta=parsed.source_meta,
                )
                app_session.add(review)
                if parsed.facts:
                    fact_row = build_fact_row(parsed.facts)
                    if fact_row is not None:
                        fact_rows.append(
                            {
                                "review_id": opt_out_review_id,
                                "tenant_id": tenant_id,
                                **fact_row,
                            }
                        )
                succeeded += 1
                if row_quality_flag == "informational":
                    quality_informational += 1
                elif row_quality_flag == "meaningless":
                    quality_meaningless += 1
                if parsed.nps_score is not None:
                    rows_with_nps_in_chunk += 1

        await _upsert_review_facts(app_session, fact_rows)

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
            quality_duplicate_delta=quality_duplicate,
            quality_empty_delta=quality_empty,
            quality_informational_delta=quality_informational,
            quality_meaningless_delta=quality_meaningless,
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
        # 2026-08-18 (migration 0042) WS2 — veri kalitesi bayrak
        # sayaçları. Frontend Dalga 3'te bağlanacak (bkz. plan
        # dokümanı); backend yüzeyi burada + BatchJobResponse'da hazır.
        "quality_duplicate_rows": int(job.quality_duplicate_rows or 0),
        "quality_empty_rows": int(job.quality_empty_rows or 0),
        "quality_informational_rows": int(job.quality_informational_rows or 0),
        "quality_meaningless_rows": int(job.quality_meaningless_rows or 0),
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
        stmt = select(AnalyzeBatchJob.id, AnalyzeBatchJob.tenant_id).where(
            AnalyzeBatchJob.status == BatchJobStatus.PROCESSING
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
            "batch worker: failed to load tenant LLM keys; falling back to default classifier",
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

        llm_provider: LLMProvider = RotatingOpenRouterProvider(keys=keys, model_name=model_name)
    else:
        llm_provider = RotatingGeminiProvider(keys=keys, model_name=model_name)
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
    # 2026-08-10 — kod -> tanım (prompt rubric'i). Kod tabanındaki
    # CATEGORY_DESCRIPTIONS_TR taban alınır, DB'deki dolu
    # ``categories.description`` satırları üstüne bindirilir.
    category_descriptions: dict[str, str] = field(default_factory=dict)


EXPERIENCE_TYPES: frozenset[str] = frozenset({"dijital", "operasyonel"})


def normalize_experience_type(value: str | None) -> str | None:
    """LLM'den gelen temas noktası değerini DB sözleşmesine indirger.

    ``ck_reviews_experience_type`` yalnız iki değeri kabul eder; motor
    beklenmedik bir şey döndürürse (model halüsinasyonu, prompt
    sürüm kayması) tek satır yüzünden chunk transaction'ı patlamasın
    diye burada NULL'a düşürülür."""
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized if normalized in EXPERIENCE_TYPES else None


class BertFallbackDisabledError(RuntimeError):
    """LLM yolu başarısız ve BERT yedeği bayrakla kapalı — iş, chunk
    başına satır-failed geçidi yerine tek seferde durdurulur."""


def _bert_fallback_enabled() -> bool:
    """2026-08-10 — prod'da false: BERT yedeği hem sessiz kalite
    düşüşü hem (21k vakasında) worker OOM'u üretti. Testler ve LLM'siz
    geliştirme ortamları için varsayılan açık kalır."""
    import os

    return os.environ.get("IMGA_BATCH_BERT_FALLBACK", "true").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _unified_enabled() -> bool:
    import os

    return os.environ.get("IMGA_UNIFIED_CLASSIFIER_ENABLED", "true").strip().lower() in (
        "1",
        "true",
        "yes",
    )


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
            embedding_keys = await load_active_gemini_keys(session, tenant_id)
            store = await load_correction_store(session, tenant_id)
            # Sprint 13.1 — alt kategori seçenekleri job başında bir
            # kez okunur (prompt payload'ı, chunk'lar arası sabit).
            taxonomy_snapshot = await _load_taxonomy_payload(session, tenant_id)
            # 2026-08-10 — kategori tanımları da job başında bir kez.
            # 2026-08-18 (WS1) — artık dinamik kod kümesiyle TEK
            # sorguda, tutarlı biçimde (bkz. TenantCategorySnapshot).
            category_snapshot = await _load_tenant_category_snapshot(session, tenant_id)
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

                template_row = await PromptResolver(session).resolve_template(
                    template_key="unified_classifier", tenant_id=tenant_id
                )
                if template_row is not None:
                    system_prompt_override = template_row.system_prompt
            except Exception:
                log.warning(
                    "unified prompt override lookup failed; using code default system prompt",
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
        "batch worker: unified classifier active (model=%s, keys=%d, corrections=%d)",
        engine.model_name,
        len(keys),
        len(store.exact),
        extra={"tenant_id": str(tenant_id)},
    )
    return UnifiedJobContext(
        engine=engine,
        available_categories=category_snapshot.codes,
        store=store,
        keys=embedding_keys,
        perspective_options=taxonomy_snapshot.perspective_options,
        category_descriptions=category_snapshot.descriptions,
    )


async def _embed_chunk_rows(texts: list[str], keys: list[Any]) -> list[list[float]] | None:
    """2026-08-18 (WS3 kapsam düzeltmesi) — chunk'ın TÜM satırlarını
    embed eder, ``embed_texts``'in tek çağrıda kabul ettiği 64'lük API
    partileri hâlinde (mevcut sınır — bkz. eski ``texts[:64]``
    örneklemesi). Eskiden yalnız chunk'ın ilk 64 satırı embed
    edilirdi; 200 satırlık varsayılan chunk boyutunda geri kalan
    ~136 satır centroid'i hiç etkilemiyor, satır-bazlı anlamsal
    override'ı (bkz. ``semantic_override_lookup`` döngüsü aşağıda)
    hiç görmüyordu.

    Bir parti başarısız olursa (``None``) TÜMÜ ``None`` döner: kısmi
    bir vektör listesiyle devam etmek centroid'i çarpıtır VE
    ``semantic_hits``'in satır-index hizalamasını bozar (``vectors[i]``
    ``texts[i]``'e karşılık gelmeyi bırakır); RAG'ın "ya tam kapsama
    ya da sessiz-fallback" best-effort ilkesiyle tutarlı (bkz.
    docs/analysis/2026-08-18-rag-mimari.md §1) — kısmi kapsamayla
    devam etmek yerine tek seferde eski davranışa (yalnız güncel
    few-shot, satır-bazlı override yok) düşülür.

    Maliyet notu: Gemini ``embed_content`` karakter başına ücretlendirir
    ve LLM sınıflandırma çağrısına göre ihmal edilebilir ölçekte ucuz;
    200 satırlık bir chunk için ~4 parti çağrısı, önceki 64-satır
    kapsamasına göre marjinal ek maliyet, kapsam kazancının yanında
    önemsiz. Per-LLM-çağrısı (25'lik parti) centroid granülerliği
    BİLİNÇLİ ERTELENDİ (bkz. rag-mimari.md §5) — bu fonksiyon yalnız
    örnekleme genişliğini (64→tüm chunk) düzeltir, centroid'in chunk
    başına tek olması değişmedi."""
    from imga_api.services.embedding_service import embed_texts

    vectors: list[list[float]] = []
    for start in range(0, len(texts), 64):
        batch_vectors = await embed_texts(texts[start : start + 64], keys)
        if batch_vectors is None:
            return None
        vectors.extend(batch_vectors)
    return vectors


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

    2026-08-18 (WS3 kapsam düzeltmesi) — chunk'ın TÜM satırları embed
    edilir (bkz. ``_embed_chunk_rows``), yalnız ilk 64 değil: centroid
    artık chunk'ın tamamının ortalaması ve satır-bazlı override
    araması her satırı kapsar.

    Embedding erişilemezse sessizce (few-shot=güncel, override=boş)
    moduna düşer — RAG hiçbir zaman analizi bloklamaz."""
    from imga_api.services.correction_store import (
        merge_few_shot,
        nearest_corrections,
        semantic_override_lookup,
    )

    recent = unified_ctx.store.recent_examples
    semantic = []
    semantic_hits: dict[int, Any] = {}
    if recent:
        try:
            vectors = await _embed_chunk_rows(texts, unified_ctx.keys)
            if vectors:
                dim = len(vectors[0])
                centroid = [sum(v[d] for v in vectors) / len(vectors) for d in range(dim)]
                async with (
                    context.admin_session_factory() as session,
                    session.begin(),
                ):
                    await set_current_tenant(session, tenant_id)
                    semantic = await nearest_corrections(session, tenant_id, centroid)
                    # Satır-bazlı doğrudan override — HNSW indeksli
                    # k=1 sorgular, embed edilen TÜM chunk satırları
                    # için (ek API maliyeti yok; vektörler zaten
                    # elimizde — bkz. _embed_chunk_rows). Tenant'ta
                    # embedding'li düzeltme yoksa atla — chunk başına
                    # (artık ≤200) boş sorgu (code review bulgusu).
                    if unified_ctx.store.has_embeddings:
                        for i, vector in enumerate(vectors):
                            decision = await semantic_override_lookup(session, tenant_id, vector)
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
) -> tuple[list[AnalysisResult], list[CorrectedDecision | None]]:
    """Düzeltme katmanları (insan kararı her yolu ezer):

      1. Birebir — text_hash eşleşmesi (eski 'Train & Save' KB
         davranışının DB-bazlı, tenant-scoped hali).
      2. Anlamsal (Sprint 11.3) — embed edilen satırlardan bir
         düzeltmeye cosine ≥ 0.95 benzeyenler. Birebir eşleşme
         önceliklidir.

    2026-08-18 (migration 0042, B3 sözleşme notu) — satır sırasına
    göre UYGULANAN ``CorrectedDecision``'ı da döner (None = düzeltme
    yok). ``patch_analysis_with_decision`` yalnız ``AnalysisResult``'a
    giren alanları (sentiment/kategori/skor) yazar —
    ``decision.experience_type`` / ``decision.perspective_code``
    ``AnalysisResult``'a giremez (pydantic ``extra=\"forbid\"``,
    imga-core donuk); çağıran (``_process_chunk``'ın per-satır döngüsü)
    bu ikisini decision nesnesinden DOĞRUDAN okuyup kendi
    experience_type/perspective_code hesaplamasına uygulamalı."""
    from imga_api.services.correction_store import (
        patch_analysis_with_decision,
    )

    hits = semantic_hits or {}
    if not unified_ctx.store.has_corrections and not hits:
        return analyses, [None] * len(analyses)

    patched: list[AnalysisResult] = []
    applied: list[CorrectedDecision | None] = []
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
            applied.append(decision)
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
            applied.append(semantic_decision)
            continue
        patched.append(analysis)
        applied.append(None)
    return patched, applied


async def _fetch_dimension_mapping(tenant_id: UUID, context: WorkerContext) -> dict[str, str]:
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


async def _fetch_fact_mapping(tenant_id: UUID, context: WorkerContext) -> dict[str, str]:
    """Migration 0046 — load the tenant's enabled operational-"facts"
    config and return ``{fact_field: csv_column_mapping}``. Mirrors
    ``_fetch_dimension_mapping`` exactly: best-effort (a load failure
    logs but doesn't break the upload — facts are observability-grade,
    not contract), empty dict when the tenant has no facts configured."""
    try:
        async with context.admin_session_factory() as session, session.begin():
            await set_current_tenant(session, tenant_id)
            stmt = (
                select(
                    TenantFactMapping.fact_field,
                    TenantFactMapping.csv_column_mapping,
                )
                .where(TenantFactMapping.tenant_id == tenant_id)
                .where(TenantFactMapping.enabled.is_(True))
            )
            rows = (await session.execute(stmt)).all()
    except Exception:
        log.exception(
            "batch worker: fact mapping load failed; reviews will land without review_facts rows",
            extra={"tenant_id": str(tenant_id)},
        )
        return {}
    return {field_name: col for field_name, col in rows if col}


async def _upsert_review_facts(app_session: AsyncSession, rows: list[dict[str, Any]]) -> None:
    """Migration 0046 — one bulk upsert per chunk for the accumulated
    ``review_facts`` rows (all four Review-insertion branches in
    ``_process_chunk`` + ``_write_empty_reviews`` funnel here). Every
    element of ``rows`` carries the SAME key set (``fact_parsing.
    build_fact_row``'s full 14-column output plus review_id/tenant_id)
    so a single ``insert().values([...])`` covers the whole chunk.
    File is the source of truth on a re-run (reanalysis / re-upload):
    every non-PK column is overwritten from ``excluded``."""
    if not rows:
        return
    stmt = pg_insert(ReviewFact).values(rows)
    update_columns = {
        col.name: getattr(stmt.excluded, col.name)
        for col in ReviewFact.__table__.columns
        if col.name not in ("review_id", "tenant_id", "created_at")
    }
    stmt = stmt.on_conflict_do_update(index_elements=["review_id"], set_=update_columns)
    await app_session.execute(stmt)


@dataclass(frozen=True, slots=True)
class TenantCategorySnapshot:
    """WS1 (2026-08-18, migration 0042 çalışması) — sınıflandırıcı
    prompt'una giden dinamik kod kümesi + kod->tanım sözlüğü, TEK
    sorguda tutarlı biçimde üretilir.

    ``codes`` — tenant'ın ETKİN globalleri (``tenant_categories.
    is_enabled``) + etkin custom ``Category`` kodları; ikisi de AYNI
    (tenant, category) join satırı üzerinden gelir —
    ``TenantConfigService.toggle_category`` global/custom ayrımı
    yapmadan ikisini de aynı mekanizmayla açıp kapatıyor, dolayısıyla
    burada da tek bir sorgu ikisini birden kapsıyor.
    ``ensure_fallback_category`` 'belirsiz'i koşulsuz garanti eder.

    GÜVENLİ GERİ DÖNÜŞ: etkin kategori (global+custom toplamı) hiç
    kalmamışsa (legacy tenant, hiç seed edilmemiş ``tenant_categories``
    ya da — kasıtlı olsun olmasın — hepsi kapatılmış) TÜM globallere
    düşülür; aksi halde prompt'a giden kod kümesi fiilen boşalır ve
    her satır zorunlu olarak 'belirsiz' sınıflandırılırdı. Tenant
    yalnız custom taksonomiye güveniyorsa (bilinçli olarak tüm
    globalleri kapattıysa) bu geri dönüş TETİKLENMEZ — ``combined``
    boş değildir, custom kodlar zaten oradadır.

    ``descriptions`` — kod tabanındaki ``CATEGORY_DESCRIPTIONS_TR``
    tabanı, üstüne DB'deki dolu ``description`` satırları biner;
    yalnız ``codes`` kümesindeki kodlar için tutulur — eskiden bu
    sözlük devre dışı globallerin tanımını da taşıyordu (kod
    kümesiyle tutarsızdı), artık taşımıyor.
    """

    codes: list[str]
    descriptions: dict[str, str]


async def _load_tenant_category_snapshot(
    session: AsyncSession, tenant_id: UUID
) -> TenantCategorySnapshot:
    """Sorgu patlarsa çağıran tarafın işi durmasın diye burada değil,
    ``_build_unified_context``'in ortak try'ında yakalanır (o yol
    zaten klasik path'e düşürür)."""
    from imga_core.categories.taxonomy import (
        CATEGORY_DESCRIPTIONS_TR,
        GLOBAL_CATEGORY_CODES,
        ensure_fallback_category,
    )

    stmt = (
        select(Category.code, Category.tenant_id, Category.description)
        .join(
            TenantCategory,
            and_(
                TenantCategory.category_id == Category.id,
                TenantCategory.tenant_id == tenant_id,
            ),
        )
        .where(Category.deleted_at.is_(None))
        .where(Category.is_active.is_(True))
        .where(TenantCategory.is_enabled.is_(True))
        .where(
            or_(
                Category.tenant_id.is_(None),
                Category.tenant_id == tenant_id,
            )
        )
    )
    rows = (await session.execute(stmt)).all()
    global_codes = [code for code, cat_tenant_id, _desc in rows if cat_tenant_id is None]
    custom_codes = [code for code, cat_tenant_id, _desc in rows if cat_tenant_id is not None]

    combined = global_codes + custom_codes
    if not combined:
        combined = list(GLOBAL_CATEGORY_CODES)
    codes = ensure_fallback_category(combined)
    code_set = set(codes)

    descriptions: dict[str, str] = {
        code: desc for code, desc in CATEGORY_DESCRIPTIONS_TR.items() if code in code_set
    }
    for code, _cat_tenant_id, desc in rows:
        if desc and code in code_set:
            descriptions[code] = desc
    return TenantCategorySnapshot(codes=codes, descriptions=descriptions)


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


async def _load_taxonomy_payload(session: AsyncSession, tenant_id: UUID) -> TenantTaxonomySnapshot:
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
            options.setdefault(r.primary_category_code, []).append((r.code, r.label_tr))
    return TenantTaxonomySnapshot(
        heuristic_entries=entries, perspective_options=options, labels=labels
    )


__all__ = [
    "EXPERIENCE_TYPES",
    "WorkerContext",
    "build_worker_context",
    "normalize_experience_type",
    "process_batch_job",
    "recover_orphans",
]
