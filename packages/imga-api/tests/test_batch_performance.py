"""Performance gate for the batch upload pipeline.

Sprint 8.3.4. These run under ``@pytest.mark.slow`` so the default
test compose skips them; manual trigger:

    pytest -m slow tests/test_batch_performance.py

The test loads a real CSV through the upload route and drives the
worker to completion against the stub pipeline (deterministic keyword
sentiment, no BERT load). The wall-clock window is generous because
the stub pipeline is the *floor* — adding the real BERT model on a
production GPU is a separate gate. What this test catches is a
regression in the orchestration layer: chunking, dedup lookups,
session round-trips, audit writes.
"""

from __future__ import annotations

import time
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from imga_db.models import AnalyzeBatchJob, BatchJobStatus, User
from sqlalchemy.ext.asyncio import AsyncSession

from tests.batch_helpers import (
    fetch_job,
    login_token,
    run_worker,
    upload_csv,
    write_csv,
)


@pytest.mark.slow
@pytest.mark.timeout(180)
@pytest.mark.asyncio
async def test_batch_1000_rows_under_3_minutes(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    tmp_path: Path,
    admin_session: AsyncSession,
) -> None:
    """1K-row batch must complete in under 180 seconds with the stub
    pipeline. The 180s ceiling is the orchestration-layer SLA; real
    BERT timing is captured separately."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)

    csv_path = write_csv(
        tmp_path / "perf_1k.csv",
        ["yorum"],
        [[f"perf yorum satır {i} kargo iade fatura"] for i in range(1000)],
    )
    upload_resp = upload_csv(
        batch_client, token=token, path=csv_path, text_column="yorum"
    )
    assert upload_resp.status_code == 201
    job_id = UUID(upload_resp.json()["id"])

    started = time.monotonic()
    await run_worker(batch_client, job_id)
    elapsed = time.monotonic() - started

    job = await fetch_job(admin_session, job_id)
    assert isinstance(job, AnalyzeBatchJob)
    assert job.status == BatchJobStatus.COMPLETED
    assert job.processed_rows == 1000
    assert elapsed < 180, (
        f"1K-row batch took {elapsed:.1f}s — performance gate breached "
        f"(orchestration regression suspect, stub pipeline is the floor)."
    )
