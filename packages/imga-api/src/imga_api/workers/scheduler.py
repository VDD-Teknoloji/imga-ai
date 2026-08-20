"""APScheduler glue.

Sprint 8.3.1. The lifespan starts a single ``AsyncIOScheduler`` and
hands it to whichever code wants to schedule work — today, the batch
upload route (``submit_batch_job``) and the lifespan startup hook
(daily cleanup interval). The route doesn't touch APScheduler types
directly, so swapping schedulers later (Redis-backed, multi-instance)
is a one-file change.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID

from apscheduler.schedulers.asyncio import AsyncIOScheduler

if TYPE_CHECKING:
    from fastapi import FastAPI

    from imga_api.workers.batch_analyzer import WorkerContext
    from imga_api.workers.report_generator import ReportContext

log = logging.getLogger("imga-api.workers.scheduler")


def build_scheduler() -> AsyncIOScheduler:
    """One scheduler per process; ``misfire_grace_time`` is generous
    because our jobs are tens-of-minutes long."""
    return AsyncIOScheduler(
        job_defaults={
            "coalesce": True,
            "max_instances": 1,
            "misfire_grace_time": 60 * 60,  # 1h
        }
    )


def submit_batch_job(
    scheduler: AsyncIOScheduler,
    *,
    job_id: UUID,
    context: WorkerContext,
) -> None:
    """Schedule a batch job for immediate dispatch. The worker itself
    handles concurrency caps (semaphore + per-tenant lock) so we
    don't need to gate at the scheduler layer."""
    from imga_api.workers.batch_analyzer import process_batch_job

    scheduler.add_job(
        process_batch_job,
        trigger="date",  # fire once, ASAP
        args=[job_id, context],
        id=f"batch-{job_id}",
        replace_existing=True,
    )
    log.info("scheduler: queued batch job %s", job_id)


def submit_reanalysis_job(
    scheduler: AsyncIOScheduler,
    *,
    job_id: UUID,
    context: WorkerContext,
) -> None:
    """2026-08-10 — ``submit_batch_job``'ın yeniden analiz ikizi. Aynı
    WorkerContext, aynı eşzamanlılık biletleri; farkı yalnız çağrılan
    işçi fonksiyonu."""
    from imga_api.workers.reanalyzer import process_reanalysis_job

    scheduler.add_job(
        process_reanalysis_job,
        trigger="date",
        args=[job_id, context],
        id=f"reanalyze-{job_id}",
        replace_existing=True,
    )
    log.info("scheduler: queued reanalysis job %s", job_id)


def submit_report_job(
    scheduler: AsyncIOScheduler,
    *,
    job_id: UUID,
    context: ReportContext,
) -> None:
    """Schedule a report-generation job for immediate dispatch. Same
    pattern as ``submit_batch_job`` — concurrency cap lives on the
    worker side (per-tenant lock on the ReportContext)."""
    from imga_api.workers.report_generator import generate_report_job

    scheduler.add_job(
        generate_report_job,
        trigger="date",
        args=[job_id, context],
        id=f"report-{job_id}",
        replace_existing=True,
    )
    log.info("scheduler: queued report job %s", job_id)


def schedule_cleanup(
    scheduler: AsyncIOScheduler,
    *,
    upload_root: Any,
    retention_hours: int,
    job_id: str | None = None,
    keep_paths_provider: (
        Callable[[], Awaitable[set[str]]] | None
    ) = None,
) -> None:
    """Daily file-reaper for ``upload_root``. Runs at startup once (so a
    fresh container cleans whatever the previous run left behind) plus
    daily thereafter. ``job_id`` defaults to a path-derived id so the
    function can be called multiple times for distinct directories
    (uploads + reports) without one replacing the other.

    ``keep_paths_provider`` (2026-08-19 Kitap1 vakası): terminal olmayan
    (queued/processing/failed) işlerin dosya yolları — retention dolsa
    da silinmez, yoksa checkpoint "Tekrar Dene" imkânsızlaşır. Liste
    alınamazsa o tur HİÇBİR ŞEY silinmez (güvenli taraf)."""
    from imga_api.workers.cleanup import reap_stale_uploads

    label = job_id or f"cleanup-{upload_root}"

    async def _job() -> None:
        keep: set[str] = set()
        if keep_paths_provider is not None:
            try:
                keep = await keep_paths_provider()
            except Exception:
                log.warning(
                    "cleanup [%s]: keep listesi alinamadi, tur atlandi",
                    label,
                )
                return
        deleted = reap_stale_uploads(
            root=upload_root,
            retention_hours=retention_hours,
            keep_paths=keep,
        )
        if deleted:
            log.info("cleanup [%s]: reaped %s stale files", label, deleted)

    scheduler.add_job(
        _job,
        trigger="interval",
        hours=24,
        next_run_time=None,
        id=label,
        replace_existing=True,
    )
    # Also run once shortly after startup so a long-stopped container
    # doesn't delay cleanup until the next 24h tick. (async job — sync
    # doğrudan çağrı yerine date-trigger; scheduler.start() lifespan'da
    # hemen sonra geliyor.)
    scheduler.add_job(
        _job,
        trigger="date",
        run_date=datetime.now(UTC) + timedelta(seconds=30),
        id=f"{label}-startup",
        replace_existing=True,
    )


def schedule_provider_healthcheck(
    scheduler: AsyncIOScheduler, *, interval_seconds: int = 60
) -> None:
    """§3.5 — Gemini provider liveness probe'u her ``interval_seconds`` sn.

    Coroutine job (AsyncIOScheduler doğrudan çalıştırır). ``next_run_time`` =
    şimdi → scheduler.start() sonrası ilk probe hemen koşar; böylece boot'tan
    saniyeler sonra ``GET /v1/health`` gerçek provider durumunu yansıtır."""
    from imga_api.services.provider_health import probe_provider

    scheduler.add_job(
        probe_provider,
        trigger="interval",
        seconds=interval_seconds,
        id="provider-healthcheck",
        replace_existing=True,
        next_run_time=datetime.now(UTC),
    )
    log.info("scheduler: provider healthcheck every %ss", interval_seconds)


def schedule_data_retention(
    scheduler: AsyncIOScheduler, *, interval_hours: int = 24
) -> None:
    """§3.8 — 30-gün KVKK retention purge, günlük + boot'ta bir kez.

    Her koşuda kısa-ömürlü admin (BYPASSRLS) engine kurar/kapatır — kalıcı bir
    BYPASSRLS pool tutmamak için (job günde bir kez koşar). Boot'ta çalışması
    idempotent: yalnız 30 günü aşmış satırlar silinir."""
    from imga_db import create_engine, create_session_factory

    from imga_api.services.data_retention import purge_expired

    async def _job() -> None:
        engine = create_engine("admin")
        try:
            factory = create_session_factory(engine)
            async with factory() as session:
                await purge_expired(session)
        except Exception:
            log.exception("data retention purge failed")
        finally:
            await engine.dispose()

    scheduler.add_job(
        _job,
        trigger="interval",
        hours=interval_hours,
        id="data-retention-purge",
        replace_existing=True,
        next_run_time=datetime.now(UTC),
    )
    log.info("scheduler: data retention purge every %sh", interval_hours)


async def enqueue_batch_job(
    app: FastAPI,
    *,
    job_id: UUID,
    tenant_id: UUID,
    attempt: int = 0,
) -> tuple[str | None, datetime | None]:
    """Sprint 9.0.5-A — pick the right dispatch path.

    Production wires ``app.state.arq_pool`` in the lifespan; this
    enqueues into the arq queue and returns the arq job id +
    queued-at timestamp so the route can persist them on the
    ``analyze_batch_jobs`` row (operator can later inspect / cancel
    a specific arq run).

    Test stack and any deploy that didn't manage to bring up Redis at
    startup falls back to the in-process APScheduler — same behaviour
    as before this sprint, no regression for the existing test seam
    (``run_worker`` / ``RecordingScheduler``).

    ``attempt`` (2026-08-09): arq görev kimliği deneme-numaralıdır
    (``batch:{id}:r{n}``). Çöken bir koşunun Redis'te bıraktığı görev
    kaydı, retry'ın AYNI kimlikle kuyruklamasını engelliyordu; arq'nın
    dedup-None dönüşü de sessizce in-process yedeğine düşüyordu — 3G
    limitli api konteyneri BERT koşturup OOM riskine giriyordu. Deneme
    kimliği çakışmayı bitirir; dedup yalnız aynı denemenin çift
    tıklamasını süzer ve o durumda in-process'e DÜŞÜLMEZ.

    Returns:
        ``(worker_job_id, queued_at)``. Both ``None`` on the
        scheduler-fallback path so the route doesn't accidentally
        persist a fake arq id.
    """
    arq_job_id = f"batch:{job_id}" + (f":r{attempt}" if attempt else "")
    arq_pool = getattr(app.state, "arq_pool", None)
    if arq_pool is not None:
        try:
            job = await arq_pool.enqueue_job(
                "process_batch_task",
                str(job_id),
                str(tenant_id),
                _job_id=arq_job_id,
                _queue_name="imga-batch",
            )
        except Exception:
            log.exception(
                "scheduler: arq enqueue failed; falling back to in-process",
                extra={"job_id": str(job_id)},
            )
        else:
            if job is not None:
                queued_at = datetime.now(UTC)
                worker_job_id = getattr(job, "job_id", None)
                log.info(
                    "scheduler: enqueued batch job %s on arq (worker_job_id=%s)",
                    job_id,
                    worker_job_id,
                )
                return worker_job_id, queued_at
            # Dedup: aynı deneme zaten kuyrukta/işleniyor. In-process'e
            # düşme — çift dispatch hem yanlış hem api'yi şişirir.
            log.warning(
                "scheduler: arq dedup hit for %s (attempt %d); job is "
                "already queued, not re-enqueueing",
                job_id,
                attempt,
            )
            return arq_job_id, None

    scheduler = getattr(app.state, "batch_scheduler", None)
    worker_context = getattr(app.state, "batch_worker_context", None)
    if scheduler is None or worker_context is None:
        raise RuntimeError(
            "no dispatch target available — neither arq_pool nor "
            "batch_scheduler is wired on app.state"
        )
    submit_batch_job(scheduler, job_id=job_id, context=worker_context)
    return None, None


async def enqueue_reanalysis_job(
    app: FastAPI,
    *,
    job_id: UUID,
    tenant_id: UUID,
    attempt: int = 0,
) -> tuple[str | None, datetime | None]:
    """``enqueue_batch_job``'ın yeniden analiz ikizi.

    Aynı kuyruk (``imga-batch``) kullanılır — yeniden analiz de LLM
    ağırlıklı ve aynı worker pool'unun kapasitesini tüketiyor; ayrı
    kuyruk ikinci bir konteyner gerektirirdi. Görev kimliği
    ``reanalyze:{job_id}[:r{n}]``: yükleme kimlikleriyle çakışmaz ve
    çöken bir denemenin Redis kaydı retry'ı bloklamaz (bkz.
    ``enqueue_batch_job`` docstring'i).
    """
    arq_job_id = f"reanalyze:{job_id}" + (f":r{attempt}" if attempt else "")
    arq_pool = getattr(app.state, "arq_pool", None)
    if arq_pool is not None:
        try:
            job = await arq_pool.enqueue_job(
                "process_reanalysis_task",
                str(job_id),
                str(tenant_id),
                _job_id=arq_job_id,
                _queue_name="imga-batch",
            )
        except Exception:
            log.exception(
                "scheduler: arq reanalysis enqueue failed; falling back "
                "to in-process",
                extra={"job_id": str(job_id)},
            )
        else:
            if job is not None:
                queued_at = datetime.now(UTC)
                worker_job_id = getattr(job, "job_id", None)
                log.info(
                    "scheduler: enqueued reanalysis job %s on arq "
                    "(worker_job_id=%s)",
                    job_id,
                    worker_job_id,
                )
                return worker_job_id, queued_at
            log.warning(
                "scheduler: arq dedup hit for reanalysis %s (attempt %d); "
                "not re-enqueueing",
                job_id,
                attempt,
            )
            return arq_job_id, None

    scheduler = getattr(app.state, "batch_scheduler", None)
    worker_context = getattr(app.state, "batch_worker_context", None)
    if scheduler is None or worker_context is None:
        raise RuntimeError(
            "no dispatch target available — neither arq_pool nor "
            "batch_scheduler is wired on app.state"
        )
    submit_reanalysis_job(scheduler, job_id=job_id, context=worker_context)
    return None, None


__all__ = [
    "build_scheduler",
    "enqueue_batch_job",
    "enqueue_reanalysis_job",
    "schedule_cleanup",
    "schedule_data_retention",
    "schedule_provider_healthcheck",
    "submit_batch_job",
    "submit_reanalysis_job",
    "submit_report_job",
]
