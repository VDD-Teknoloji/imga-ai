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
import logging
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

from imga_core import AnalysisPipeline, AnalysisResult
from imga_db import create_engine, create_session_factory, set_current_tenant
from imga_db.models import (
    AnalyzeBatchJob,
    BatchJobStatus,
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
)

if TYPE_CHECKING:
    from cachetools import TTLCache

log = logging.getLogger("imga-api.workers.batch")


# ---------------------------------------------------------------------------
# In-memory concurrency primitives
# ---------------------------------------------------------------------------

_GLOBAL_SEMAPHORE: asyncio.Semaphore | None = None
_TENANT_LOCKS: dict[UUID, asyncio.Lock] = defaultdict(asyncio.Lock)
_LOCK_INIT = asyncio.Lock()


async def _get_global_semaphore(limit: int) -> asyncio.Semaphore:
    """Lazy-init the global semaphore. Called once per process; the
    limit is read from BatchSettings at first use and never re-read."""
    global _GLOBAL_SEMAPHORE
    async with _LOCK_INIT:
        if _GLOBAL_SEMAPHORE is None:
            _GLOBAL_SEMAPHORE = asyncio.Semaphore(limit)
    return _GLOBAL_SEMAPHORE


def _tenant_lock(tenant_id: UUID) -> asyncio.Lock:
    return _TENANT_LOCKS[tenant_id]


# ---------------------------------------------------------------------------
# Worker context — built once per job, NOT per chunk.
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class WorkerContext:
    """Plumbing the worker grabs from app state once per job.

    Engines are owned by the context (not module-level singletons) so
    each lifespan gets its own pool and ``dispose()`` cleanly shuts
    them down. Production wires one context per app process via the
    FastAPI lifespan; tests build a fresh one per test so asyncpg
    connections never bleed across event loops.
    """

    pipeline: AnalysisPipeline
    admin_engine: AsyncEngine
    app_engine: AsyncEngine
    admin_session_factory: async_sessionmaker[AsyncSession]
    app_session_factory: async_sessionmaker[AsyncSession]
    tenant_config_cache: TTLCache[UUID, dict[str, Any]]
    settings: BatchSettings

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
) -> WorkerContext:
    """Build a fresh WorkerContext, including its own engine pair.

    Both engines bind to the asyncpg event loop active at construction
    time. That's exactly what we want — the lifespan's loop in prod,
    the test's loop in pytest. Module-level singletons used to live
    here and broke pytest isolation: the first test's loop owned the
    pool, every subsequent test got 'another operation is in progress'
    once that loop closed.
    """
    admin_engine = create_engine("admin")
    app_engine = create_engine("app")
    return WorkerContext(
        pipeline=pipeline,
        admin_engine=admin_engine,
        app_engine=app_engine,
        admin_session_factory=create_session_factory(admin_engine),
        app_session_factory=create_session_factory(app_engine),
        tenant_config_cache=tenant_config_cache,
        settings=settings,
    )


# ---------------------------------------------------------------------------
# Main entry — one call per scheduled job
# ---------------------------------------------------------------------------


async def process_batch_job(job_id: UUID, context: WorkerContext) -> None:
    """Pick up a queued job, run it to completion / cancellation /
    failure. Idempotent on retries because the QUEUED → PROCESSING
    transition is guarded inside BatchAnalyzeService."""
    semaphore = await _get_global_semaphore(context.settings.global_concurrency)

    # Step 1 — read tenant_id (admin session, no RLS bind needed).
    tenant_id = await _read_tenant_id(job_id, context.admin_session_factory)
    if tenant_id is None:
        log.warning("batch worker: job %s missing or already gone", job_id)
        return

    # Step 2 — wait for both concurrency tickets.
    async with semaphore, _tenant_lock(tenant_id):
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

    # Open the file outside the transaction (streaming).
    if not file_path.exists():
        await _record_catastrophic_failure(
            job_id, tenant_id, context, reason=f"upload file missing: {file_path}"
        )
        return

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

    for chunk in _chunked(rows_iter, chunk_size):
        # Cancel check before every chunk.
        if await _is_cancelled(job_id, tenant_id, context):
            log.info("batch worker: job %s cancelled", job_id)
            return

        await _process_chunk(
            job_id=job_id,
            tenant_id=tenant_id,
            chunk=chunk,
            auto_create=auto_create,
            triggered_by_user_id=triggered_by_user_id,
            seen_hashes=seen_hashes_in_batch,
            context=context,
        )

    # Final transition.
    async with context.admin_session_factory() as admin_session, admin_session.begin():
        await set_current_tenant(admin_session, tenant_id)
        audit = AuditService(admin_session)
        batch_service = BatchAnalyzeService(admin_session, audit)
        await batch_service.mark_completed(job_id)


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
) -> None:
    """Analyze and persist one chunk worth of rows. Each chunk is its
    own transaction so a row-level error rolls back ONLY the bad row,
    not the whole job."""
    error_entries: list[dict[str, Any]] = []
    succeeded = 0
    failed = 0
    tickets = 0
    duplicates = 0

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

    if not valid_rows:
        await _commit_progress(
            job_id=job_id,
            tenant_id=tenant_id,
            context=context,
            progress=BatchProgress(
                processed_delta=len(chunk),
                failed_delta=failed,
                error_entries=error_entries or None,
            ),
        )
        return

    # BERT inference — outside any DB transaction.
    texts = [r.text for r in valid_rows]
    try:
        analyses: list[AnalysisResult] = context.pipeline.analyze_batch(texts)
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

        for parsed, analysis in zip(valid_rows, analyses, strict=True):
            from imga_core import review_text_hash

            text_hash = review_text_hash(parsed.text)

            # Intra-batch dedup — already seen this text in this job.
            if text_hash in seen_hashes:
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
                )
                app_session.add(review)
                duplicates += 1
                succeeded += 1
                continue

            seen_hashes.add(text_hash)

            if auto_create:
                try:
                    result = await review_service.record_and_decide(
                        tenant_id=tenant_id,
                        text=parsed.text,
                        analysis=analysis,
                        actor_user_id=triggered_by_user_id,
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
                )
                app_session.add(review)
                succeeded += 1

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
            error_entries=error_entries or None,
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
        await service.apply_progress(job_id=job_id, progress=progress)


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

__all__ = [
    "WorkerContext",
    "build_worker_context",
    "process_batch_job",
    "recover_orphans",
]
