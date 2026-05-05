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
from datetime import UTC, datetime
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
) -> None:
    """Daily file-reaper for ``upload_root``. Runs at startup once (so a
    fresh container cleans whatever the previous run left behind) plus
    daily thereafter. ``job_id`` defaults to a path-derived id so the
    function can be called multiple times for distinct directories
    (uploads + reports) without one replacing the other."""
    from imga_api.workers.cleanup import reap_stale_uploads

    label = job_id or f"cleanup-{upload_root}"

    def _job() -> None:
        deleted = reap_stale_uploads(
            root=upload_root, retention_hours=retention_hours
        )
        if deleted:
            log.info("cleanup [%s]: reaped %s stale files", label, deleted)

    scheduler.add_job(
        _job,
        trigger="interval",
        hours=24,
        next_run_time=None,  # start at +24h; lifespan calls _job() directly once
        id=label,
        replace_existing=True,
    )
    # Also run once immediately so a long-stopped container doesn't
    # delay cleanup until the next 24h tick.
    _job()


async def enqueue_batch_job(
    app: FastAPI,
    *,
    job_id: UUID,
    tenant_id: UUID,
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

    Returns:
        ``(worker_job_id, queued_at)``. Both ``None`` on the
        scheduler-fallback path so the route doesn't accidentally
        persist a fake arq id.
    """
    arq_pool = getattr(app.state, "arq_pool", None)
    if arq_pool is not None:
        try:
            job = await arq_pool.enqueue_job(
                "process_batch_task",
                str(job_id),
                str(tenant_id),
                _job_id=f"batch:{job_id}",
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

    scheduler = getattr(app.state, "batch_scheduler", None)
    worker_context = getattr(app.state, "batch_worker_context", None)
    if scheduler is None or worker_context is None:
        raise RuntimeError(
            "no dispatch target available — neither arq_pool nor "
            "batch_scheduler is wired on app.state"
        )
    submit_batch_job(scheduler, job_id=job_id, context=worker_context)
    return None, None


__all__ = [
    "build_scheduler",
    "enqueue_batch_job",
    "schedule_cleanup",
    "submit_batch_job",
    "submit_report_job",
]
