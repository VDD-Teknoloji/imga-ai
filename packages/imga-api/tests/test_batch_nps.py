"""Integration coverage for the Sprint 8.3.5 batch upload NPS path.

Live Postgres + the stub pipeline. Each test uploads a CSV/XLSX whose
header carries (or doesn't carry) one of the recognized NPS column
names, drives the worker, and asserts:

  * ``analyze_batch_jobs.detected_nps_column`` reflects the auto-detect
    decision (column name when found, NULL when absent).
  * ``analyze_batch_jobs.rows_with_nps`` counts rows that landed with
    a non-null nps_score.
  * The persisted Review rows carry the per-row NPS (or NULL when
    the cell was empty / out of range).

Fixtures (CSV/XLSX with NPS columns) are built in-test via the existing
write_csv/write_xlsx helpers — keeps the data inline with the assertion
so a future pattern-list change is easy to spot.
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
    User,
)
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.batch_helpers import (
    fetch_job,
    login_token,
    run_worker,
    upload_csv,
    write_csv,
    write_xlsx,
)


@pytest.mark.asyncio
async def test_batch_upload_with_score_column_persists_nps(
    batch_client: TestClient,
    manual_tenant: tuple[User, UUID, str],
    tmp_path: Path,
    admin_session: AsyncSession,
) -> None:
    """``Score`` legacy pattern → detected, every valid value lands on
    the Review row and increments rows_with_nps."""
    user, tid, pw = manual_tenant
    token = login_token(batch_client, user.email, pw, tid)

    csv_path = write_csv(
        tmp_path / "with_score.csv",
        ["yorum", "Score"],
        [
            ["birinci yorum kargo", "9"],
            ["ikinci yorum iade", "3"],
            ["üçüncü yorum hizmet", "10"],
        ],
    )
    r = upload_csv(batch_client, token=token, path=csv_path, text_column="yorum")
    assert r.status_code == 201, r.text
    job_id = UUID(r.json()["job_id"])

    await run_worker(batch_client, job_id)

    job = await fetch_job(admin_session, job_id)
    assert job.status == BatchJobStatus.COMPLETED
    assert job.detected_nps_column == "Score"
    assert job.rows_with_nps == 3

    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        rows = (
            await admin_session.execute(
                select(Review)
                .where(Review.batch_job_id == job_id)
                .order_by(Review.text)
            )
        ).scalars().all()
    nps_by_text = {r.text: r.nps_score for r in rows}
    assert nps_by_text["birinci yorum kargo"] == 9
    assert nps_by_text["ikinci yorum iade"] == 3
    assert nps_by_text["üçüncü yorum hizmet"] == 10
    # Computed column derives the bucket from nps_score.
    nps_cat_by_text = {r.text: r.nps_category for r in rows}
    assert nps_cat_by_text["birinci yorum kargo"] == "promoter"
    assert nps_cat_by_text["ikinci yorum iade"] == "detractor"
    assert nps_cat_by_text["üçüncü yorum hizmet"] == "promoter"


@pytest.mark.asyncio
async def test_batch_upload_xlsx_with_nps_column(
    batch_client: TestClient,
    manual_tenant: tuple[User, UUID, str],
    tmp_path: Path,
    admin_session: AsyncSession,
) -> None:
    """XLSX path: ``NPS`` legacy pattern, mixed valid + invalid cells.
    Rows with empty / out-of-range cells land with nps_score=NULL
    and don't count toward rows_with_nps."""
    user, tid, pw = manual_tenant
    token = login_token(batch_client, user.email, pw, tid)

    xlsx_path = write_xlsx(
        tmp_path / "with_nps.xlsx",
        ["yorum", "NPS"],
        [
            ["xlsx birinci yorum", "8"],
            ["xlsx ikinci yorum", ""],   # empty cell
            ["xlsx üçüncü yorum", "15"],  # out of range
            ["xlsx dördüncü yorum", "0"],
        ],
    )
    r = upload_csv(batch_client, token=token, path=xlsx_path, text_column="yorum")
    assert r.status_code == 201, r.text
    job_id = UUID(r.json()["job_id"])

    await run_worker(batch_client, job_id)

    job = await fetch_job(admin_session, job_id)
    assert job.status == BatchJobStatus.COMPLETED
    assert job.detected_nps_column == "NPS"
    # Only 2 rows had valid in-range values.
    assert job.rows_with_nps == 2

    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        rows = (
            await admin_session.execute(
                select(Review)
                .where(Review.batch_job_id == job_id)
                .order_by(Review.text)
            )
        ).scalars().all()
    nps_by_text = {r.text: r.nps_score for r in rows}
    assert nps_by_text["xlsx birinci yorum"] == 8
    assert nps_by_text["xlsx ikinci yorum"] is None
    assert nps_by_text["xlsx üçüncü yorum"] is None  # 15 → out of range
    assert nps_by_text["xlsx dördüncü yorum"] == 0


@pytest.mark.asyncio
async def test_batch_upload_with_rating_score_column(
    batch_client: TestClient,
    manual_tenant: tuple[User, UUID, str],
    tmp_path: Path,
    admin_session: AsyncSession,
) -> None:
    """Sprint 8.3.5 addition: ``Rating Score`` (compound English) is one
    of the patterns added on top of the legacy 5."""
    user, tid, pw = manual_tenant
    token = login_token(batch_client, user.email, pw, tid)

    csv_path = write_csv(
        tmp_path / "rating.csv",
        ["yorum", "Rating Score"],
        [["rating bir", "7"], ["rating iki", "4"]],
    )
    r = upload_csv(batch_client, token=token, path=csv_path, text_column="yorum")
    assert r.status_code == 201
    job_id = UUID(r.json()["job_id"])

    await run_worker(batch_client, job_id)

    job = await fetch_job(admin_session, job_id)
    assert job.detected_nps_column == "Rating Score"
    assert job.rows_with_nps == 2


@pytest.mark.asyncio
async def test_batch_upload_without_nps_column(
    batch_client: TestClient,
    manual_tenant: tuple[User, UUID, str],
    tmp_path: Path,
    admin_session: AsyncSession,
) -> None:
    """No recognizable header → detected_nps_column NULL, rows_with_nps
    stays at 0, all reviews carry nps_score NULL."""
    user, tid, pw = manual_tenant
    token = login_token(batch_client, user.email, pw, tid)

    csv_path = write_csv(
        tmp_path / "plain.csv",
        ["yorum"],
        [["plain bir"], ["plain iki"]],
    )
    r = upload_csv(batch_client, token=token, path=csv_path, text_column="yorum")
    assert r.status_code == 201
    job_id = UUID(r.json()["job_id"])

    await run_worker(batch_client, job_id)

    job = await fetch_job(admin_session, job_id)
    assert job.detected_nps_column is None
    assert job.rows_with_nps == 0

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
    assert len(rows) == 2
    assert all(r.nps_score is None for r in rows)
    assert all(r.nps_category is None for r in rows)


@pytest.mark.asyncio
async def test_batch_metadata_records_detected_column_at_job_start(
    batch_client: TestClient,
    manual_tenant: tuple[User, UUID, str],
    tmp_path: Path,
    admin_session: AsyncSession,
) -> None:
    """The detected_nps_column is written before any chunks land — peek
    the column at job start, not after the last row's progress write —
    so a job that fails mid-stream still reports what NPS column it
    had."""
    user, tid, pw = manual_tenant
    token = login_token(batch_client, user.email, pw, tid)

    csv_path = write_csv(
        tmp_path / "puan.csv",
        ["yorum", "PUAN"],
        [["başlangıç", "10"]],
    )
    r = upload_csv(batch_client, token=token, path=csv_path, text_column="yorum")
    assert r.status_code == 201
    job_id = UUID(r.json()["job_id"])

    await run_worker(batch_client, job_id)

    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        job = (
            await admin_session.execute(
                select(AnalyzeBatchJob).where(AnalyzeBatchJob.id == job_id)
            )
        ).scalar_one()
    # Detected even though only 1 row total.
    assert job.detected_nps_column == "PUAN"
    assert job.rows_with_nps == 1
