"""``/tenants/me/analyze/batch/{job_id}/progress`` — live SSE feed.

Sprint 9.0.5-A. Demo wow moment: the upload UI subscribes here while
the worker runs and gets per-chunk progress events with ETA. The
worker publishes to the ``batch:progress:{job_id}`` Redis channel
after every ``_commit_progress`` call and again on terminal
transitions (completed / failed / cancelled).

Event format:

    event: progress
    data: {"job_id": "...", "status": "processing", "processed": 1024,
           "total": 5000, "percent": 20.48, "succeeded": 1010,
           "failed": 14, "tickets_created": 0, "duplicates_skipped": 0,
           "eta_seconds": 240, "last_checkpoint_row": 1024}

    event: ping        (every 30s, Cloudflare keepalive)
    data:

    event: complete
    data: { ... terminal snapshot ... }

The endpoint emits the persisted job row as the *initial* event so a
late subscriber (worker is mid-flight, browser refresh) still gets a
state snapshot before the next pub/sub message lands.

logger.exception() in every catch path — Sprint 8.3.6.6 round-3
baseline note.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from imga_db.models import AnalyzeBatchJob, BatchJobStatus, UserTenantRole
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from imga_api.auth_deps import CurrentUser, bind_tenant, require_role
from imga_api.db_deps import get_app_session
from imga_api.workers.batch_analyzer import (
    _progress_channel,
    _progress_snapshot,
)

_logger = logging.getLogger("imga-api.routes.batch.progress")

router = APIRouter(
    prefix="/tenants/me/analyze/batch", tags=["Analyze"]
)

_AnyMember = Depends(require_role(
    UserTenantRole.TENANT_ADMIN,
    UserTenantRole.ANALYST,
    UserTenantRole.VIEWER,
))


# Cloudflare proxies kill idle connections at ~100s. 30s ping keeps
# the stream warm from both ends; sse-starlette's built-in keepalive
# would also work but rolling our own gives us a dedicated ``ping``
# event the client can ignore by name (vs. a comment-line ping that
# bumps the EventSource readyState noisily).
_PING_INTERVAL_SECONDS = 30.0

# Defensive ceiling: the worker's terminal publish should always
# arrive, but if it gets dropped (Redis blip, crashed worker before
# publish), the stream would otherwise hang until the client
# disconnects. After this many seconds with the job in a terminal
# DB state we close the stream ourselves.
_TERMINAL_LINGER_SECONDS = 5.0

_TERMINAL_STATUSES = {
    BatchJobStatus.COMPLETED,
    BatchJobStatus.FAILED,
    BatchJobStatus.CANCELLED,
}


def _require_active_tenant(current: CurrentUser) -> UUID:
    if current.active_tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="active tenant context required for this endpoint",
        )
    return current.active_tenant_id


async def _load_initial_snapshot(
    session: AsyncSession,
    current: CurrentUser,
    job_id: UUID,
) -> dict[str, Any]:
    """Read the persisted batch row and shape it as a snapshot dict.
    Raises HTTPException(404) when the job doesn't exist or the
    tenant has no read access (RLS hides cross-tenant rows)."""
    async with session.begin():
        await bind_tenant(session, current)
        row = await session.get(AnalyzeBatchJob, job_id)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="batch job not found",
            )
        return _progress_snapshot(row)


@router.get(
    "/{job_id}/progress",
    summary="Live server-sent-events stream of batch progress.",
    description=(
        "Sprint 9.0.5-A. Subscribes to the worker's progress channel "
        "and streams events until the job reaches a terminal state. "
        "Emits an initial snapshot from the persisted row so late "
        "subscribers don't see a blank screen until the next chunk "
        "commits. 30s ping keeps the stream alive across Cloudflare's "
        "100s idle-kill window."
    ),
    responses={
        404: {"description": "Job not found or hidden by RLS."},
    },
)
async def stream_batch_progress(
    job_id: UUID,
    request: Request,
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> EventSourceResponse:
    _require_active_tenant(current)
    initial = await _load_initial_snapshot(app_session, current, job_id)
    redis_client = getattr(request.app.state, "arq_pool", None)
    # arq_pool exposes the same ``publish`` / ``pubsub`` surface as a
    # plain redis.asyncio.Redis (it IS one, with extras). When arq
    # didn't bind we fall through to the cache module's singleton —
    # the worker writes to that same Redis URL.
    if redis_client is None:
        from imga_api.cache.redis_client import get_redis_client

        redis_client = get_redis_client()

    async def _event_source() -> Any:
        # Prime the stream with the persisted snapshot so the client
        # sees state immediately, even if the worker won't publish
        # again for several seconds.
        yield {"event": "progress", "data": json.dumps(initial)}

        if str(initial.get("status")) in {s.value for s in _TERMINAL_STATUSES}:
            # Already terminal — emit the close marker and bail.
            yield {"event": "complete", "data": json.dumps(initial)}
            return

        pubsub = None
        try:
            pubsub = redis_client.pubsub()
            channel = _progress_channel(job_id)
            await pubsub.subscribe(channel)
            terminal_observed_at: float | None = None

            while True:
                if await request.is_disconnected():
                    return

                try:
                    message = await asyncio.wait_for(
                        pubsub.get_message(
                            ignore_subscribe_messages=True,
                            timeout=_PING_INTERVAL_SECONDS,
                        ),
                        timeout=_PING_INTERVAL_SECONDS + 1.0,
                    )
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": ""}
                    continue

                if message is None:
                    yield {"event": "ping", "data": ""}
                    continue

                payload = message.get("data")
                if isinstance(payload, bytes | bytearray):
                    payload_str = payload.decode("utf-8", errors="replace")
                else:
                    payload_str = str(payload)

                try:
                    snapshot = json.loads(payload_str)
                except json.JSONDecodeError:
                    _logger.warning(
                        "batch progress: malformed pub/sub payload: %r",
                        payload_str,
                    )
                    continue

                status_value = str(snapshot.get("status", ""))
                is_terminal = status_value in {
                    s.value for s in _TERMINAL_STATUSES
                }
                event_name = "complete" if is_terminal else "progress"
                yield {"event": event_name, "data": json.dumps(snapshot)}

                if is_terminal:
                    return
                # If a stale terminal slipped through without the
                # complete event, give the worker a brief window to
                # publish the canonical terminal snapshot then bail.
                if terminal_observed_at is not None:
                    elapsed = (
                        asyncio.get_event_loop().time() - terminal_observed_at
                    )
                    if elapsed > _TERMINAL_LINGER_SECONDS:
                        return
        except Exception:
            _logger.exception(
                "batch progress stream failed",
                extra={"job_id": str(job_id)},
            )
        finally:
            if pubsub is not None:
                try:
                    await pubsub.unsubscribe()
                    await pubsub.aclose()
                except Exception:
                    _logger.exception(
                        "batch progress: pubsub teardown failed",
                        extra={"job_id": str(job_id)},
                    )

    return EventSourceResponse(_event_source())
