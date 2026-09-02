"""Post-batch root-cause auto-generation — "hazırlanıyor" tracking.

2026-09. Replaces the single Redis STRING key
``root_cause_autogen:{tenant_id}`` (20 min TTL, set at enqueue time,
deleted in the task's ``finally``) that ``batch_analyzer`` /
``arq_worker`` / ``tenant_insights`` used to share. Audited problems
with that design:

  1. ``imga-batch`` is a single-worker FIFO queue (``arq_worker.
     WorkerSettings.max_jobs = 1``, ``job_timeout`` 4h). A big batch
     queued ahead of a small one can hold the queue well past the
     20-min TTL — the flag expires and the UI spinner disappears while
     generation is still pending behind it.
  2. Two batches for the same tenant: the FIRST task's ``finally``
     deletes the shared key, hiding the SECOND task that is still
     queued or running.
  3. The flag was set even when ``enqueue_job`` returned ``None``
     (arq's own job-id dedup) — a phantom "hazırlanıyor" with nothing
     behind it.
  4. A generation failure (most commonly ``NoCredentialsError`` — the
     tenant has no active LLM key and no platform fallback) was
     logged + swallowed with no trace for the UI; the overview just
     fell back to its generic "not enough data" empty state.

Fix: a Redis SET, ``root_cause_autogen_jobs:{tenant_id}``, one member
per in-flight ``batch_job_id`` (covers #1 — TTL is refreshed when the
worker actually starts — and #2, since each batch's member is its own
independent membership). ``mark_enqueued`` is only called when
``enqueue_job`` returned a real job (covers #3). A companion STRING,
``root_cause_autogen_error:{tenant_id}``, carries the outcome of the
most recent run so the overview can distinguish "still generating"
from "tried and failed" (covers #4).

A NEW key name is deliberate, not cosmetic: the live key
``root_cause_autogen:{tenant_id}`` is a STRING. Reusing it as a SET
would raise ``WRONGTYPE`` on every SADD until its own TTL happened to
expire — a self-inflicted outage during rollout. No code anywhere
else in the codebase should reference the old key name.

Every function here is best-effort, matching the SWOT / root-cause
service's existing cache convention: a Redis exception is logged and
swallowed, never raised. Writers (``mark_enqueued`` / ``mark_started``
/ ``mark_finished``) silently no-op on failure; readers
(``is_generating`` / ``last_error``) default to ``False`` / ``None``.
This is a UI hint, never allowed to block a batch or fail a read.
"""

from __future__ import annotations

import logging
from uuid import UUID

from imga_api.cache.redis_client import get_redis_client

_logger = logging.getLogger("imga-api.services.root_cause_autogen")

# Enqueue-time TTL — comfortably covers arq queue latency ahead of a
# big batch (the old flag's 20 min was the actual incident trigger).
_ENQUEUED_TTL_SECONDS = 60 * 60
# Refreshed once the worker actually picks the job up — shorter than
# the enqueue TTL because from here the only wait is the job's own
# run time, not queue depth.
_STARTED_TTL_SECONDS = 30 * 60
# Error code retention — long enough that an operator checking back a
# few days later still sees why the last attempt failed.
_ERROR_TTL_SECONDS = 7 * 24 * 60 * 60


def _jobs_key(tenant_id: UUID) -> str:
    return f"root_cause_autogen_jobs:{tenant_id}"


def _error_key(tenant_id: UUID) -> str:
    return f"root_cause_autogen_error:{tenant_id}"


async def mark_enqueued(tenant_id: UUID, batch_job_id: UUID) -> None:
    """Called by ``batch_analyzer._enqueue_root_cause_auto_gen`` right
    after ``enqueue_job`` returns a real job (never for a ``None`` —
    arq's dedup return means no new job exists to track)."""
    try:
        client = get_redis_client()
        key = _jobs_key(tenant_id)
        await client.sadd(key, str(batch_job_id))
        await client.expire(key, _ENQUEUED_TTL_SECONDS)
    except Exception:
        _logger.exception(
            "root-cause auto-gen: mark_enqueued failed (non-fatal)",
            extra={"tenant_id": str(tenant_id), "batch_job_id": str(batch_job_id)},
        )


async def mark_started(tenant_id: UUID, batch_job_id: UUID) -> None:
    """Called at the very top of ``generate_root_causes_task``. SADDs
    the member again (not just EXPIRE) because the single-worker FIFO
    queue can sit behind a big batch long enough for the enqueue-time
    TTL to have already lapsed — re-adding recreates a legacy-expired
    set instead of leaving ``is_generating`` stuck reporting False for
    a job that is, in fact, now running."""
    try:
        client = get_redis_client()
        key = _jobs_key(tenant_id)
        await client.sadd(key, str(batch_job_id))
        await client.expire(key, _STARTED_TTL_SECONDS)
    except Exception:
        _logger.exception(
            "root-cause auto-gen: mark_started failed (non-fatal)",
            extra={"tenant_id": str(tenant_id), "batch_job_id": str(batch_job_id)},
        )


async def mark_finished(
    tenant_id: UUID,
    batch_job_id: UUID | None,
    *,
    error: str | None,
) -> None:
    """Called from the task's ``finally`` — success, partial success,
    or total failure all reach here exactly once.

    ``batch_job_id=None`` means a legacy job enqueued before this
    change shipped (the old task signature carried no batch id): there
    is no member to SREM, so the whole set is deleted instead — a
    conservative fallback that can't leave a phantom membership behind
    for a job that will never call ``mark_finished`` again.

    ``error`` is exactly one of ``"no_credentials"`` / ``"failed"`` /
    ``None`` — the caller (``arq_worker.generate_root_causes_task``)
    owns that classification; this function just persists it."""
    try:
        client = get_redis_client()
        key = _jobs_key(tenant_id)
        if batch_job_id is None:
            await client.delete(key)
        else:
            await client.srem(key, str(batch_job_id))
    except Exception:
        _logger.exception(
            "root-cause auto-gen: mark_finished job-clear failed (non-fatal)",
            extra={
                "tenant_id": str(tenant_id),
                "batch_job_id": str(batch_job_id) if batch_job_id is not None else None,
            },
        )

    try:
        client = get_redis_client()
        error_key = _error_key(tenant_id)
        if error is None:
            await client.delete(error_key)
        else:
            await client.set(error_key, error, ex=_ERROR_TTL_SECONDS)
    except Exception:
        _logger.exception(
            "root-cause auto-gen: mark_finished error-flag write failed (non-fatal)",
            extra={"tenant_id": str(tenant_id)},
        )


async def is_generating(tenant_id: UUID) -> bool:
    """True while at least one batch's root-cause job is enqueued or
    running for this tenant. Any Redis failure defaults to False —
    this is a visual hint only, never allowed to block the overview
    read."""
    try:
        client = get_redis_client()
        count = await client.scard(_jobs_key(tenant_id))
    except Exception:
        _logger.warning(
            "root-cause auto-gen: is_generating read failed; defaulting to False",
            extra={"tenant_id": str(tenant_id)},
        )
        return False
    return int(count) > 0


async def last_error(tenant_id: UUID) -> str | None:
    """The error code from the most recent finished run, or ``None``
    if the last run succeeded (or none has run yet). Any Redis failure
    defaults to None, same defensive contract as ``is_generating``."""
    try:
        client = get_redis_client()
        raw = await client.get(_error_key(tenant_id))
    except Exception:
        _logger.warning(
            "root-cause auto-gen: last_error read failed; defaulting to None",
            extra={"tenant_id": str(tenant_id)},
        )
        return None
    if raw is None:
        return None
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return str(raw)


__all__ = [
    "is_generating",
    "last_error",
    "mark_enqueued",
    "mark_finished",
    "mark_started",
]
