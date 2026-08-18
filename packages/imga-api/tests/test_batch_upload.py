"""Integration coverage for the Sprint 8.3.1 batch upload pipeline.

Tests run against a real Postgres + the stub pipeline (deterministic
keyword sentiment, no BERT load). The TestClient lifespan replaces the
real APScheduler with a recording no-op, so each test drives the worker
manually via ``run_worker`` for determinism.

Covered surfaces:
  * Upload validation: file size, row count, missing column, empty file
  * Worker happy path: every row analyzed, status=completed
  * Worker row-level resilience: empty text rows persist as quality-
    flagged rows without aborting (2026-08-18, migration 0042 WS2 —
    see the renamed test below for the behaviour-change rationale)
  * auto_create_tickets toggle interactions with tenant automation_mode
  * Cancellation: pre-pickup queued, between chunks
  * RLS: cross-tenant lookup returns 404
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from imga_db.models import (
    AnalyzeBatchJob,
    BatchJobStatus,
    Review,
    ReviewDecision,
    Ticket,
    User,
)
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.main import app
from tests.batch_helpers import (
    cleanup_tenant,
    fetch_job,
    login_token,
    run_worker,
    seed_tenant_with_admin,
    upload_csv,
    write_csv,
)

# --- upload validation ----------------------------------------------------


@pytest.mark.asyncio
async def test_upload_happy_path_creates_queued_job(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    tmp_path: Path,
    admin_session: AsyncSession,
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)

    csv_path = write_csv(
        tmp_path / "ok.csv",
        ["yorum"],
        [["birinci yorum"], ["ikinci yorum"], ["üçüncü yorum"]],
    )
    r = upload_csv(batch_client, token=token, path=csv_path, text_column="yorum")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "queued"
    assert body["total_rows"] == 3
    assert body["processed_rows"] == 0
    assert body["auto_create_tickets"] is False

    # Recording scheduler should have a registered dispatch entry.
    scheduler = app.state.batch_scheduler
    assert len(scheduler.added) == 1


@pytest.mark.asyncio
async def test_upload_rejects_unknown_text_column(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    tmp_path: Path,
) -> None:
    """Sprint 9.8 — şablon uyum kontrolü artık ilk önce çalışıyor:
    header'da 'yorum' (veya legacy 'text') yoksa daha kullanışlı bir
    422 mesajıyla reddediyoruz, eski "text column 'metin' not in
    header" 400 yerine. text_column'a farklı bir değer geçilirse de
    sonuç aynı — kullanıcı şablonu indirsin uyarısı düşer."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)

    csv_path = write_csv(tmp_path / "bad.csv", ["foo"], [["x"]])
    r = upload_csv(
        batch_client, token=token, path=csv_path, text_column="metin"
    )
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    # Mesaj kullanıcıyı şablona yönlendirmeli ve mevcut kolonları
    # (yani "foo"'yu) raporlamalı ki yanlışı düzeltebilsin.
    assert "yorum" in detail
    assert "foo" in detail


@pytest.mark.asyncio
async def test_upload_rejects_empty_file(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    tmp_path: Path,
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)

    # Header-only CSV → total_rows == 0.
    csv_path = write_csv(tmp_path / "empty.csv", ["yorum"], [])
    r = upload_csv(batch_client, token=token, path=csv_path, text_column="yorum")
    assert r.status_code == 400, r.text


@pytest.mark.asyncio
async def test_upload_rejects_too_many_rows(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Configured ceiling rejects oversized files at the upload boundary
    before the worker is dispatched."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)

    # 5 rows; cap to 3 for this test only via app.state mutation.
    settings = app.state.settings
    from imga_api.settings import BatchSettings

    new_batch = BatchSettings(
        upload_dir=settings.batch.upload_dir,
        max_file_bytes=settings.batch.max_file_bytes,
        max_rows=3,
        chunk_size=settings.batch.chunk_size,
        retention_hours=settings.batch.retention_hours,
        global_concurrency=settings.batch.global_concurrency,
        per_tenant_concurrency=settings.batch.per_tenant_concurrency,
    )
    object.__setattr__(settings, "batch", new_batch)

    csv_path = write_csv(
        tmp_path / "big.csv",
        ["yorum"],
        [["a"], ["b"], ["c"], ["d"], ["e"]],
    )
    r = upload_csv(batch_client, token=token, path=csv_path, text_column="yorum")
    assert r.status_code == 400, r.text
    assert "satır" in r.json()["detail"]


@pytest.mark.asyncio
async def test_upload_rejects_too_large_file(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    tmp_path: Path,
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)

    # Shrink the cap to 256 bytes for this test.
    from imga_api.settings import BatchSettings

    settings = app.state.settings
    object.__setattr__(
        settings,
        "batch",
        BatchSettings(
            upload_dir=settings.batch.upload_dir,
            max_file_bytes=256,
            max_rows=settings.batch.max_rows,
            chunk_size=settings.batch.chunk_size,
            retention_hours=settings.batch.retention_hours,
            global_concurrency=settings.batch.global_concurrency,
            per_tenant_concurrency=settings.batch.per_tenant_concurrency,
        ),
    )

    csv_path = tmp_path / "huge.csv"
    csv_path.write_bytes(b"yorum\n" + (b"x" * 1024) + b"\n")
    r = upload_csv(batch_client, token=token, path=csv_path, text_column="yorum")
    assert r.status_code == 413, r.text


# --- worker happy path ----------------------------------------------------


@pytest.mark.asyncio
async def test_worker_processes_all_rows_and_marks_completed(
    batch_client: TestClient,
    manual_tenant: tuple[User, UUID, str],
    tmp_path: Path,
    admin_session: AsyncSession,
) -> None:
    """Manual mode + auto_create=False → reviews persisted, no tickets."""
    user, tid, pw = manual_tenant
    token = login_token(batch_client, user.email, pw, tid)

    csv_path = write_csv(
        tmp_path / "rows.csv",
        ["yorum"],
        [["bir kargo yorumu"], ["güzel hizmet"], ["normal bir mesaj"]],
    )
    r = upload_csv(batch_client, token=token, path=csv_path, text_column="yorum")
    assert r.status_code == 201
    job_id = UUID(r.json()["job_id"])

    await run_worker(batch_client, job_id)

    job = await fetch_job(admin_session, job_id)
    assert job.status == BatchJobStatus.COMPLETED, job.status
    assert job.processed_rows == 3
    assert job.succeeded_rows == 3
    assert job.failed_rows == 0
    assert job.tickets_created == 0  # auto_create_tickets default False

    # Reviews actually landed.
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        rows = (
            await admin_session.execute(
                select(Review).where(Review.batch_job_id == job_id)
            )
        ).scalars().all()
    assert len(rows) == 3
    assert all(r.batch_job_id == job_id for r in rows)


@pytest.mark.asyncio
async def test_worker_persists_empty_text_rows_as_quality_flagged(
    batch_client: TestClient,
    manual_tenant: tuple[User, UUID, str],
    tmp_path: Path,
    admin_session: AsyncSession,
) -> None:
    """2026-08-18 (migration 0042 WS2) — BEHAVIOUR CHANGE from the
    original ``test_worker_skips_empty_text_rows_as_failed``: empty
    rows are no longer dropped into ``failed_rows`` with no DB trace.
    They now persist as a normal Review row (quality_flag='empty',
    decision=SKIPPED_QUALITY, sentiment NÖTR/0.0, primary_category
    'belirsiz'/0.0) and count toward ``succeeded_rows`` /
    ``quality_empty_rows`` instead — the low-quality-data report needs
    a durable record of every skipped-content row, not just a
    fire-and-forget counter. Full field-level coverage (decision_reason,
    exact sentiment/category values, the empty-text-hash dedup
    exception) lives in ``tests/test_batch_quality.py``; this test only
    pins the job-level counters so this file's original "row-level
    resilience" narrative stays accurate."""
    user, tid, pw = manual_tenant
    token = login_token(batch_client, user.email, pw, tid)

    csv_path = write_csv(
        tmp_path / "mixed.csv",
        ["yorum"],
        [["dolu satır"], [""], ["başka dolu"], ["   "]],
    )
    r = upload_csv(batch_client, token=token, path=csv_path, text_column="yorum")
    job_id = UUID(r.json()["job_id"])

    await run_worker(batch_client, job_id)
    job = await fetch_job(admin_session, job_id)

    assert job.status == BatchJobStatus.COMPLETED
    assert job.processed_rows == 4
    assert job.succeeded_rows == 4
    assert job.failed_rows == 0
    assert job.quality_empty_rows == 2
    assert job.error_summary == []


# --- auto_create_tickets toggle ------------------------------------------


@pytest.mark.asyncio
async def test_auto_create_disabled_skips_ticket_creation(
    batch_client: TestClient,
    full_auto_tenant: tuple[User, UUID, str],
    tmp_path: Path,
    admin_session: AsyncSession,
) -> None:
    """Even in full_auto mode, auto_create_tickets=False keeps the bridge
    out of the batch path — every row writes a SKIPPED_MODE review."""
    user, tid, pw = full_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)

    csv_path = write_csv(
        tmp_path / "neg.csv",
        ["yorum"],
        [["kargom kötü ve gelmedi"], ["bir başka kötü deneyim"]],
    )
    r = upload_csv(
        batch_client,
        token=token,
        path=csv_path,
        text_column="yorum",
        auto_create_tickets=False,
    )
    job_id = UUID(r.json()["job_id"])

    await run_worker(batch_client, job_id)
    job = await fetch_job(admin_session, job_id)
    assert job.tickets_created == 0
    assert job.succeeded_rows == 2

    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        rows = list(
            (
                await admin_session.execute(
                    select(Review.decision, Review.automation_mode).where(
                        Review.batch_job_id == job_id
                    )
                )
            ).all()
        )
    assert all(r.decision == ReviewDecision.SKIPPED_MODE for r in rows)
    # Regression: reviews CHECK constraint accepts only the three real
    # automation_mode enum values. The worker must snapshot the tenant's
    # actual mode (full_auto here) — earlier 'batch_opt_out' sentinel
    # tripped ck_reviews_automation_mode and crashed the whole batch.
    assert all(r.automation_mode == "full_auto" for r in rows)


@pytest.mark.asyncio
async def test_intra_batch_dedup_uses_real_tenant_automation_mode(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    tmp_path: Path,
    admin_session: AsyncSession,
) -> None:
    """Companion regression: the second of two duplicate rows in the
    same upload also persists a Review row (decision=SKIPPED_DEDUP).
    Its ``automation_mode`` must be the tenant's real mode, not the
    pre-fix 'batch_intra_dedup' sentinel that violated the CHECK
    constraint."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)

    csv_path = write_csv(
        tmp_path / "dup.csv",
        ["yorum"],
        [["aynı satır"], ["aynı satır"]],
    )
    r = upload_csv(batch_client, token=token, path=csv_path, text_column="yorum")
    job_id = UUID(r.json()["job_id"])
    await run_worker(batch_client, job_id)

    job = await fetch_job(admin_session, job_id)
    assert job.status == BatchJobStatus.COMPLETED
    assert job.duplicates_skipped == 1

    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        modes = list(
            (
                await admin_session.execute(
                    select(Review.automation_mode).where(
                        Review.batch_job_id == job_id
                    )
                )
            ).scalars()
        )
    assert all(m == "semi_auto" for m in modes), (
        f"all rows must store tenant.automation_mode; got {modes}"
    )


@pytest.mark.asyncio
async def test_auto_create_enabled_in_semi_auto_creates_tickets_for_negatives(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    tmp_path: Path,
    admin_session: AsyncSession,
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)

    csv_path = write_csv(
        tmp_path / "neg.csv",
        ["yorum"],
        [
            # Strong negative AND high-confidence kargo classification.
            # KeywordCategoryClassifier divides hit count by 5; semi_auto
            # threshold needs confidence > 0.7, so we need ≥ 4 kargo
            # keyword hits. "kargom kötü ve gelmedi" only had 2 hits
            # (0.4 confidence) which fails the threshold check and the
            # bridge falls through to SKIPPED_THRESHOLD instead of CREATE.
            [
                "kargom kargocu gelmedi, teslimat ulaşmadı, "
                "takip kodu yanlış, çok kötü hizmet"
            ],
            # Neutral "iyi" — POZITIF, no ticket in semi_auto.
            ["iyi bir gün"],
        ],
    )
    r = upload_csv(
        batch_client,
        token=token,
        path=csv_path,
        text_column="yorum",
        auto_create_tickets=True,
    )
    job_id = UUID(r.json()["job_id"])

    await run_worker(batch_client, job_id)
    job = await fetch_job(admin_session, job_id)
    assert job.status == BatchJobStatus.COMPLETED
    assert job.tickets_created == 1, (
        f"expected one ticket from the negative row, got {job.tickets_created}"
    )

    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        ticket_count = (
            await admin_session.execute(
                select(Ticket).where(Ticket.tenant_id == tid)
            )
        ).scalars().all()
    assert len(ticket_count) == 1


@pytest.mark.asyncio
async def test_auto_create_enabled_in_manual_mode_yields_no_tickets(
    batch_client: TestClient,
    manual_tenant: tuple[User, UUID, str],
    tmp_path: Path,
    admin_session: AsyncSession,
) -> None:
    """auto_create_tickets=True hands rows to ReviewService, which still
    respects the tenant's automation_mode (MANUAL ⇒ skipped_mode)."""
    user, tid, pw = manual_tenant
    token = login_token(batch_client, user.email, pw, tid)

    csv_path = write_csv(
        tmp_path / "neg.csv",
        ["yorum"],
        [["kargom kötü ve gelmedi"]],
    )
    r = upload_csv(
        batch_client,
        token=token,
        path=csv_path,
        text_column="yorum",
        auto_create_tickets=True,
    )
    job_id = UUID(r.json()["job_id"])

    await run_worker(batch_client, job_id)
    job = await fetch_job(admin_session, job_id)
    assert job.tickets_created == 0


# --- cancellation ---------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_before_worker_pickup_keeps_job_cancelled(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    tmp_path: Path,
    admin_session: AsyncSession,
) -> None:
    """The cancel endpoint flips status while the job is still QUEUED;
    when the worker eventually runs, mark_processing is a no-op and the
    rest of the pipeline bails. Worker must not parse the file or
    persist any reviews."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)

    csv_path = write_csv(
        tmp_path / "rows.csv",
        ["yorum"],
        [["bir"], ["iki"], ["üç"]],
    )
    r = upload_csv(batch_client, token=token, path=csv_path, text_column="yorum")
    job_id = UUID(r.json()["job_id"])

    cancel_resp = batch_client.delete(
        f"/tenants/me/analyze/batch/{job_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "cancelled"

    # Drive the worker after cancel — it must respect the flag.
    await run_worker(batch_client, job_id)

    job = await fetch_job(admin_session, job_id)
    assert job.status == BatchJobStatus.CANCELLED
    assert job.processed_rows == 0  # worker bailed before any chunk

    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        rows = (
            await admin_session.execute(
                select(Review).where(Review.batch_job_id == job_id)
            )
        ).scalars().all()
    assert rows == [], "no reviews should have been written for a cancelled job"


@pytest.mark.asyncio
async def test_cancel_terminal_job_returns_409(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    tmp_path: Path,
    admin_session: AsyncSession,
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)

    csv_path = write_csv(tmp_path / "ok.csv", ["yorum"], [["x"]])
    r = upload_csv(batch_client, token=token, path=csv_path, text_column="yorum")
    job_id = UUID(r.json()["job_id"])

    await run_worker(batch_client, job_id)

    cancel = batch_client.delete(
        f"/tenants/me/analyze/batch/{job_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert cancel.status_code == 409, cancel.text


# --- RLS isolation ---------------------------------------------------------


@pytest.mark.asyncio
async def test_rls_isolates_batch_jobs_across_tenants(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
    tmp_path: Path,
) -> None:
    """Tenant A creates a batch; tenant B logged in via switch-tenant
    must get 404 on the same job_id."""
    user_a, tid_a, pw_a = semi_auto_tenant
    token_a = login_token(batch_client, user_a.email, pw_a, tid_a)

    csv_path = write_csv(tmp_path / "a.csv", ["yorum"], [["a-yorum"]])
    r = upload_csv(batch_client, token=token_a, path=csv_path, text_column="yorum")
    job_id = UUID(r.json()["job_id"])

    # Spin up tenant B + its admin and try to fetch tenant A's job.
    user_b, tid_b, pw_b = await seed_tenant_with_admin(
        admin_session, name_prefix="Other Co"
    )
    try:
        token_b = login_token(batch_client, user_b.email, pw_b, tid_b)
        cross = batch_client.get(
            f"/tenants/me/analyze/batch/{job_id}",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert cross.status_code == 404, cross.text

        list_b = batch_client.get(
            "/tenants/me/analyze/batch",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert list_b.status_code == 200
        assert list_b.json()["jobs"] == []
    finally:
        await cleanup_tenant(admin_session, user_b.id, tid_b)



_ = AnalyzeBatchJob  # exported for future tests


@pytest.mark.asyncio
async def test_retry_clears_stale_error_state(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    tmp_path: Path,
    admin_session: AsyncSession,
) -> None:
    """Retry, eski last_error + error_summary'yi temizler (2026-08-09
    OOM vakasi: is devam ederken UI eski hatayi gostermeye devam
    ediyordu). Denetim izi batch.retry audit kaydinda saklanir."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)

    csv_path = write_csv(
        tmp_path / "retry.csv", ["yorum"], [["bir"], ["iki"]]
    )
    r = upload_csv(batch_client, token=token, path=csv_path, text_column="yorum")
    assert r.status_code == 201, r.text
    job_id = UUID(r.json()["job_id"])

    cancel = batch_client.delete(
        f"/tenants/me/analyze/batch/{job_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert cancel.status_code == 200, cancel.text

    async with admin_session.begin():
        await admin_session.execute(
            text(
                "UPDATE analyze_batch_jobs SET last_error = :e, "
                "error_summary = CAST(:s AS jsonb) WHERE id = :id"
            ),
            {
                "e": "worker process restarted before this job finished",
                "s": '[{"row": null, "error": "worker restarted"}]',
                "id": str(job_id),
            },
        )

    retry = batch_client.post(
        f"/tenants/me/analyze/batch/{job_id}/retry",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert retry.status_code == 200, retry.text
    body = retry.json()
    assert body["status"] == "queued"
    assert body["last_error"] is None
    assert body["error_summary"] == []
