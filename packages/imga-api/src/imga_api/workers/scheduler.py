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
from typing import TYPE_CHECKING, Any
from uuid import UUID

from apscheduler.schedulers.asyncio import AsyncIOScheduler

if TYPE_CHECKING:
    from imga_api.workers.batch_analyzer import WorkerContext

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


def schedule_cleanup(
    scheduler: AsyncIOScheduler,
    *,
    upload_root: Any,
    retention_hours: int,
) -> None:
    """Daily upload-reaper. Runs at startup once (so a fresh container
    cleans whatever the previous run left behind) plus daily
    thereafter."""
    from imga_api.workers.cleanup import reap_stale_uploads

    def _job() -> None:
        deleted = reap_stale_uploads(
            root=upload_root, retention_hours=retention_hours
        )
        if deleted:
            log.info("cleanup: reaped %s stale upload files", deleted)

    scheduler.add_job(
        _job,
        trigger="interval",
        hours=24,
        next_run_time=None,  # start at +24h; lifespan calls _job() directly once
        id="upload-cleanup-daily",
        replace_existing=True,
    )
    # Also run once immediately so a long-stopped container doesn't
    # delay cleanup until the next 24h tick.
    _job()


__all__ = ["build_scheduler", "schedule_cleanup", "submit_batch_job"]
