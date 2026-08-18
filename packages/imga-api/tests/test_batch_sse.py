"""Sprint 9.0.5-A — SSE progress endpoint.

Validates the helpers that the SSE endpoint and the worker share —
``_progress_snapshot`` shape (one wire format for both initial state
and live events) + ``_progress_channel`` naming + the endpoint's
authorization gate (404 on unknown / cross-tenant job).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from imga_db.models import BatchJobStatus, User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.workers.batch_analyzer import (
    _progress_channel,
    _progress_snapshot,
)


# --- _progress_snapshot wire shape ------------------------------------


def _fake_job(**overrides: object) -> object:
    base = dict(
        id=uuid4(),
        status=BatchJobStatus.PROCESSING,
        total_rows=5000,
        processed_rows=1024,
        succeeded_rows=1010,
        failed_rows=14,
        tickets_created=0,
        duplicates_skipped=0,
        last_checkpoint_row=1024,
        started_at=datetime.now(UTC) - timedelta(seconds=60),
        # 2026-08-18 (migration 0042) WS2 — real AnalyzeBatchJob rows
        # always carry these (NOT NULL, server_default 0); the fake
        # needs them too since _progress_snapshot reads them directly.
        quality_duplicate_rows=0,
        quality_empty_rows=0,
        quality_informational_rows=0,
        quality_meaningless_rows=0,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_progress_snapshot_emits_expected_keys() -> None:
    """Sprint 9.0.5-A. The frontend BatchProgressStream depends on
    these keys; if a future refactor renames them silently the SSE
    feed regresses."""
    snap = _progress_snapshot(_fake_job())  # type: ignore[arg-type]
    expected = {
        "job_id",
        "status",
        "processed",
        "total",
        "percent",
        "succeeded",
        "failed",
        "tickets_created",
        "duplicates_skipped",
        "eta_seconds",
        "last_checkpoint_row",
        "quality_duplicate_rows",
        "quality_empty_rows",
        "quality_informational_rows",
        "quality_meaningless_rows",
    }
    assert set(snap.keys()) == expected


def test_progress_snapshot_percent_rounded_to_two_decimals() -> None:
    snap = _progress_snapshot(
        _fake_job(processed_rows=1234, total_rows=5000)
    )  # type: ignore[arg-type]
    # 1234/5000 = 24.68
    assert snap["percent"] == 24.68


def test_progress_snapshot_eta_omitted_when_processed_zero() -> None:
    """ETA can't be inferred without progress; the worker emits None
    rather than a fake-infinity number."""
    snap = _progress_snapshot(
        _fake_job(processed_rows=0)
    )  # type: ignore[arg-type]
    assert snap["eta_seconds"] is None


def test_progress_snapshot_eta_when_started_and_progressed() -> None:
    """1024 rows in 60s → rate 17.07 rows/s → remaining (5000-1024)
    /17.07 ≈ 233s."""
    snap = _progress_snapshot(_fake_job())  # type: ignore[arg-type]
    eta = snap["eta_seconds"]
    assert eta is not None
    assert 200 < eta < 270


def test_progress_snapshot_total_zero_safe() -> None:
    """Defensive: total_rows=0 must not divide-by-zero."""
    snap = _progress_snapshot(
        _fake_job(total_rows=0, processed_rows=0)
    )  # type: ignore[arg-type]
    assert snap["percent"] == 0.0
    assert snap["eta_seconds"] is None


def test_progress_channel_per_job() -> None:
    """Pub/sub channel name format. Both the worker publisher and
    the SSE subscriber compute it from job_id; a drift would
    silently break the live feed."""
    job_id = UUID("11111111-2222-3333-4444-555555555555")
    assert _progress_channel(job_id) == (
        "batch:progress:11111111-2222-3333-4444-555555555555"
    )


# --- endpoint 404 / RLS path ------------------------------------------


@pytest.mark.asyncio
async def test_progress_endpoint_returns_404_for_unknown_job(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    """Tenant-scoped read: an unknown job id (or one belonging to
    another tenant — RLS hides it) returns 404 before the SSE
    stream opens. Sprint 9.0.5-A — same pattern as GET batch/{id}."""
    from tests.batch_helpers import login_token

    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    bogus = uuid4()
    r = batch_client.get(
        f"/tenants/me/analyze/batch/{bogus}/progress",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_progress_endpoint_streams_initial_then_complete_for_terminal_job(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """When the job already terminated, the endpoint emits the
    initial snapshot AND a ``complete`` event then closes — no
    indefinite pub/sub wait."""
    from imga_db.models import AnalyzeBatchJob

    from tests.batch_helpers import (
        cleanup_tenant,  # noqa: F401  (fixture is teardown-driven)
        login_token,
    )

    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)

    # Seed a completed batch row directly so we don't have to drive
    # the worker. The endpoint reads the persisted row for the
    # initial snapshot; with status=COMPLETED it short-circuits the
    # pub/sub loop and emits ``complete``.
    job_id = uuid4()
    async with admin_session.begin():
        row = AnalyzeBatchJob(
            id=job_id,
            tenant_id=tid,
            triggered_by_user_id=user.id,
            status=BatchJobStatus.COMPLETED,
            file_name="terminal.csv",
            file_size_bytes=42,
            file_path="/tmp/terminal.csv",
            text_column="yorum",
            source_column=None,
            auto_create_tickets=False,
            total_rows=10,
            processed_rows=10,
            succeeded_rows=10,
            failed_rows=0,
            tickets_created=0,
            duplicates_skipped=0,
            error_summary=[],
            created_at=datetime.now(UTC),
            started_at=datetime.now(UTC) - timedelta(seconds=5),
            completed_at=datetime.now(UTC),
        )
        admin_session.add(row)

    try:
        with batch_client.stream(
            "GET",
            f"/tenants/me/analyze/batch/{job_id}/progress",
            headers={"Authorization": f"Bearer {token}"},
        ) as response:
            assert response.status_code == 200
            body = ""
            for chunk in response.iter_text():
                body += chunk
                if "event: complete" in body:
                    break
        assert "event: progress" in body
        assert "event: complete" in body
        assert '"status": "completed"' in body
    finally:
        async with admin_session.begin():
            stmt = select(AnalyzeBatchJob).where(
                AnalyzeBatchJob.id == job_id
            )
            row = (await admin_session.execute(stmt)).scalar_one_or_none()
            if row is not None:
                await admin_session.delete(row)
