"""Concurrency policy coverage for the in-process batch worker.

Two assertions:
  * Per-tenant: the second of two same-tenant jobs only runs after the
    first finishes (asyncio.Lock per tenant).
  * Server-wide: with global concurrency = 2, three different-tenant
    jobs scheduled together leave one waiting until one of the first
    two completes.

Tests use ``asyncio.gather`` to launch worker invocations concurrently
and check timestamps in the DB. The stub pipeline is fast (no async
points), so we rely on the DB transaction commits between chunks as
natural yield points — chunk_size=2 + total=20 forces multiple yield
opportunities so the loop has a chance to schedule peers.

Concurrency primitives (``Semaphore`` + per-tenant ``Lock``) live on
``WorkerContext`` after round-2 of the asyncpg debug. These tests
deliberately bypass the ``run_worker`` helper (which builds a fresh
context per call) and instead build ONE shared context on the test's
event loop, then call ``process_batch_job`` directly with that context.
A fresh context per invocation would isolate the primitives and defeat
the whole assertion — semaphore-of-1 + 3 jobs would all run in
parallel each with their own semaphore.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from imga_db.models import (
    AnalyzeBatchJob,
    BatchJobStatus,
    User,
)
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.workers import batch_analyzer
from tests.batch_helpers import (
    cleanup_tenant,
    fetch_job,
    login_token,
    seed_tenant_with_admin,
    upload_csv,
    write_csv,
)


async def _shared_test_context(
    batch_client: TestClient,
) -> batch_analyzer.WorkerContext:
    """Build a WorkerContext on the *test's* event loop with a stub
    pipeline + the batch_client's settings. Concurrency tests share
    one context across N parallel ``process_batch_job`` calls so the
    Semaphore + tenant Lock semantics are exercised end-to-end."""
    test_app = batch_client.app  # type: ignore[attr-defined]
    return await batch_analyzer.build_worker_context(
        pipeline=test_app.state.pipeline,
        tenant_config_cache=test_app.state.tenant_config_cache,
        settings=test_app.state.settings.batch,
    )


def _twenty_row_csv(tmp_path: Path, name: str) -> Path:
    return write_csv(
        tmp_path / name,
        ["yorum"],
        [[f"yorum sayı {i}"] for i in range(20)],
    )


@pytest.mark.asyncio
async def test_per_tenant_lock_serialises_jobs(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    tmp_path: Path,
    admin_session: AsyncSession,
) -> None:
    """Two jobs from the same tenant launched in parallel: the lock
    must guarantee non-overlapping (started_at, completed_at) windows."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)

    r1 = upload_csv(
        batch_client, token=token, path=_twenty_row_csv(tmp_path, "j1.csv"),
        text_column="yorum",
    )
    r2 = upload_csv(
        batch_client, token=token, path=_twenty_row_csv(tmp_path, "j2.csv"),
        text_column="yorum",
    )
    j1 = UUID(r1.json()["job_id"])
    j2 = UUID(r2.json()["job_id"])

    # Concurrent worker invocations sharing one context — so the
    # tenant Lock guards both jobs (otherwise per-call contexts would
    # have separate locks and serialisation would not happen).
    context = await _shared_test_context(batch_client)
    try:
        await asyncio.gather(
            batch_analyzer.process_batch_job(j1, context),
            batch_analyzer.process_batch_job(j2, context),
        )
    finally:
        await context.dispose()

    job1 = await fetch_job(admin_session, j1)
    job2 = await fetch_job(admin_session, j2)
    assert job1.status == BatchJobStatus.COMPLETED
    assert job2.status == BatchJobStatus.COMPLETED

    # The earlier started_at finished before the later one started.
    earlier, later = sorted([job1, job2], key=_started_at)
    assert _started_at(earlier) is not None
    assert _completed_at(earlier) is not None
    assert _started_at(later) is not None
    assert _completed_at(earlier) <= _started_at(later), (
        "per-tenant lock must serialise: "
        f"earlier completed at {earlier.completed_at}, "
        f"later started at {later.started_at}"
    )


@pytest.mark.asyncio
async def test_global_semaphore_caps_parallelism_at_two(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
    tmp_path: Path,
) -> None:
    """Three jobs across three tenants with global_concurrency=2 must
    leave one job waiting on the semaphore. We assert this via overlap
    counting: at least one pair has no overlap, AND the third job's
    started_at is >= the earliest job's completed_at.

    Concurrency primitives (Semaphore + per-tenant Lock) now live on
    WorkerContext and ``run_worker`` builds a fresh context per call,
    so each invocation gets a clean Semaphore without a manual reset.
    """
    a_user, a_tid, a_pw = semi_auto_tenant
    b_user, b_tid, b_pw = await seed_tenant_with_admin(
        admin_session, name_prefix="Beta Co"
    )
    c_user, c_tid, c_pw = await seed_tenant_with_admin(
        admin_session, name_prefix="Gama Co"
    )
    try:
        a_token = login_token(batch_client, a_user.email, a_pw, a_tid)
        b_token = login_token(batch_client, b_user.email, b_pw, b_tid)
        c_token = login_token(batch_client, c_user.email, c_pw, c_tid)

        ra = upload_csv(batch_client, token=a_token, path=_twenty_row_csv(tmp_path, "a.csv"), text_column="yorum")
        rb = upload_csv(batch_client, token=b_token, path=_twenty_row_csv(tmp_path, "b.csv"), text_column="yorum")
        rc = upload_csv(batch_client, token=c_token, path=_twenty_row_csv(tmp_path, "c.csv"), text_column="yorum")
        ja, jb, jc = (UUID(r.json()["job_id"]) for r in (ra, rb, rc))

        # Shared context so the global Semaphore caps all three jobs.
        context = await _shared_test_context(batch_client)
        try:
            await asyncio.gather(
                batch_analyzer.process_batch_job(ja, context),
                batch_analyzer.process_batch_job(jb, context),
                batch_analyzer.process_batch_job(jc, context),
            )
        finally:
            await context.dispose()

        jobs = [
            await fetch_job(admin_session, jid) for jid in (ja, jb, jc)
        ]
        assert all(j.status == BatchJobStatus.COMPLETED for j in jobs)

        # Sort by started_at; the third (last to start) cannot have
        # begun before at least one of the first two finished —
        # otherwise three jobs ran in parallel, violating the cap.
        ordered = sorted(jobs, key=_started_at)
        third_start = _started_at(ordered[2])
        first_complete = _completed_at(ordered[0])
        assert third_start >= first_complete, (
            "global semaphore limit=2 violated: "
            "all three jobs ran simultaneously"
        )
    finally:
        await cleanup_tenant(admin_session, b_user.id, b_tid)
        await cleanup_tenant(admin_session, c_user.id, c_tid)


# --- helpers --------------------------------------------------------------


def _started_at(job: AnalyzeBatchJob) -> datetime:
    assert job.started_at is not None, f"job {job.id} never started"
    return job.started_at


def _completed_at(job: AnalyzeBatchJob) -> datetime:
    assert job.completed_at is not None, f"job {job.id} never completed"
    return job.completed_at
