"""Worker orphan recovery — Sprint 8.3.1.

When the API process dies mid-batch, the in-memory locks vanish but the
``analyze_batch_jobs`` row stays in PROCESSING. On the next startup
``recover_orphans`` walks the table and flips those rows to FAILED with
an audit-log entry so the UI surfaces an actionable state instead of a
stalled progress bar.

Tests: insert a fake PROCESSING row, call ``recover_orphans``, assert
status flipped + reason captured. Plus a sanity test that a fresh
QUEUED job is left alone — the recovery sweep is precision-targeted.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from imga_db.models import (
    AnalyzeBatchJob,
    BatchJobStatus,
    User,
)
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.main import app
from imga_api.workers.batch_analyzer import recover_orphans


async def _insert_job(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    status: BatchJobStatus,
) -> UUID:
    job_id = uuid4()
    async with session.begin():
        await session.execute(
            text(
                "INSERT INTO analyze_batch_jobs "
                "(id, tenant_id, status, file_name, file_size_bytes, "
                "file_path, text_column, total_rows, created_at) "
                "VALUES (:id, :tid, :status, 'orphan.csv', 100, "
                "'/tmp/orphan', 'yorum', 5, now())"
            ),
            {"id": str(job_id), "tid": str(tenant_id), "status": status.value},
        )
    return job_id


@pytest.mark.asyncio
async def test_recover_flips_processing_jobs_to_failed(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """A PROCESSING row with no live worker = a crash artefact. The
    recovery sweep must mark it FAILED + log a reason."""
    _user, tid, _pw = semi_auto_tenant

    job_id = await _insert_job(
        admin_session, tenant_id=tid, status=BatchJobStatus.PROCESSING
    )

    context = app.state.batch_worker_context
    count = await recover_orphans(context)
    assert count >= 1, "recover_orphans should report at least the orphan we just inserted"

    async with admin_session.begin():
        result = await admin_session.execute(
            select(AnalyzeBatchJob.status, AnalyzeBatchJob.error_summary).where(
                AnalyzeBatchJob.id == job_id
            )
        )
        status, error_summary = result.one()
    assert status == BatchJobStatus.FAILED
    # The reason field is appended into error_summary by mark_failed.
    assert any(
        "restart" in (entry.get("error") or "") for entry in (error_summary or [])
    )


@pytest.mark.asyncio
async def test_recover_leaves_queued_jobs_alone(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """A queued job hasn't started yet — it has no in-memory lock to
    lose to a crash, so the recovery sweep must NOT touch it."""
    _user, tid, _pw = semi_auto_tenant

    job_id = await _insert_job(
        admin_session, tenant_id=tid, status=BatchJobStatus.QUEUED
    )

    context = app.state.batch_worker_context
    await recover_orphans(context)

    async with admin_session.begin():
        result = await admin_session.execute(
            select(AnalyzeBatchJob.status).where(AnalyzeBatchJob.id == job_id)
        )
        status = result.scalar_one()
    assert status == BatchJobStatus.QUEUED
