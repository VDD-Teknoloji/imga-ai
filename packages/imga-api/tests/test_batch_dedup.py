"""Dedup coverage for the batch worker.

Two layers of dedup:
  * Cross-batch (24h window) — the bridge's existing rule from Sprint
    7.5.5 / Alt-Faz 3. The batch worker re-uses ReviewService.
  * Intra-batch — same text twice in the SAME upload collapses to one
    bridge call. The worker keeps an in-memory set of text_hashes and
    writes a SKIPPED_DEDUP review for the second occurrence.

Plus a sanity test that the Turkish-aware text_hash collapses 'İYİ'
and 'iyi' to the same key.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from imga_core import review_text_hash
from imga_db.models import (
    BatchJobStatus,
    Review,
    ReviewDecision,
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
)


@pytest.mark.asyncio
async def test_intra_batch_dedup_collapses_repeated_text(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    tmp_path: Path,
    admin_session: AsyncSession,
) -> None:
    """Same text twice in the same CSV → one full review + one
    SKIPPED_DEDUP review pointing nowhere (intra-batch flag, no ticket
    lookup happens because there's no prior cross-batch row)."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)

    csv_path = write_csv(
        tmp_path / "dup.csv",
        ["yorum"],
        [
            ["aynı metin"],
            ["başka metin"],
            ["aynı metin"],  # intra-batch dup
        ],
    )
    r = upload_csv(batch_client, token=token, path=csv_path, text_column="yorum")
    job_id = UUID(r.json()["job_id"])

    await run_worker(batch_client, job_id)
    job = await fetch_job(admin_session, job_id)
    assert job.status == BatchJobStatus.COMPLETED
    assert job.processed_rows == 3
    assert job.duplicates_skipped == 1
    assert job.succeeded_rows == 3  # both dup rows still count as succeeded

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
    decisions = [r.decision for r in rows]
    assert decisions.count(ReviewDecision.SKIPPED_DEDUP) == 1


@pytest.mark.asyncio
async def test_cross_batch_dedup_24h_window_links_to_existing_ticket(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    tmp_path: Path,
    admin_session: AsyncSession,
) -> None:
    """First batch creates a review + ticket (auto_create on); a second
    batch with the same text within 24h must reuse that ticket via the
    SKIPPED_DEDUP branch."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)

    # Needs 4+ kargo keyword hits so the semi_auto threshold
    # (confidence > 0.7) is met and the first batch actually mints a
    # ticket — the dedup assertion depends on that. KeywordClassifier
    # divides by 5, so 4 hits = 0.8.
    repeat_text = (
        "kargom kargocu gelmedi, teslimat ulaşmadı, "
        "takip kodu yanlış, çok kötü hizmet"
    )

    # Batch 1 — creates a review + (auto_create_tickets=True) a ticket.
    csv1 = write_csv(tmp_path / "first.csv", ["yorum"], [[repeat_text]])
    r1 = upload_csv(
        batch_client, token=token, path=csv1, text_column="yorum",
        auto_create_tickets=True,
    )
    job1 = UUID(r1.json()["job_id"])
    await run_worker(batch_client, job1)
    job_obj1 = await fetch_job(admin_session, job1)
    assert job_obj1.tickets_created == 1, "first batch should mint a ticket"

    # Batch 2 — same text within 24h.
    csv2 = write_csv(tmp_path / "second.csv", ["yorum"], [[repeat_text]])
    r2 = upload_csv(
        batch_client, token=token, path=csv2, text_column="yorum",
        auto_create_tickets=True,
    )
    job2 = UUID(r2.json()["job_id"])
    await run_worker(batch_client, job2)
    job_obj2 = await fetch_job(admin_session, job2)

    assert job_obj2.tickets_created == 0, "second batch must NOT mint a ticket"
    assert job_obj2.duplicates_skipped == 1

    # Verify the dedup review points at the existing ticket.
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        review = (
            await admin_session.execute(
                select(Review)
                .where(Review.batch_job_id == job2)
                .where(Review.decision == ReviewDecision.SKIPPED_DEDUP)
            )
        ).scalar_one()
    assert review.ticket_id is not None


@pytest.mark.asyncio
async def test_cross_batch_dedup_outside_24h_window_creates_fresh_ticket(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    tmp_path: Path,
    admin_session: AsyncSession,
) -> None:
    """A review whose analyzed_at is older than 24h must NOT block a
    fresh ticket. We backdate the first review directly in the DB and
    confirm the second batch mints a new ticket instead of reusing the
    stale one."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)

    # Needs 4+ kargo keyword hits so the semi_auto threshold
    # (confidence > 0.7) is met and the first batch actually mints a
    # ticket — the dedup assertion depends on that. KeywordClassifier
    # divides by 5, so 4 hits = 0.8.
    repeat_text = (
        "kargom kargocu gelmedi, teslimat ulaşmadı, "
        "takip kodu yanlış, çok kötü hizmet"
    )

    csv1 = write_csv(tmp_path / "first.csv", ["yorum"], [[repeat_text]])
    r1 = upload_csv(
        batch_client, token=token, path=csv1, text_column="yorum",
        auto_create_tickets=True,
    )
    job1 = UUID(r1.json()["job_id"])
    await run_worker(batch_client, job1)

    # Backdate the original review past the 24h window.
    stale = datetime.now(UTC) - timedelta(hours=25)
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        await admin_session.execute(
            text(
                "UPDATE reviews SET analyzed_at = :ts "
                "WHERE batch_job_id = :j"
            ),
            {"ts": stale, "j": str(job1)},
        )

    csv2 = write_csv(tmp_path / "second.csv", ["yorum"], [[repeat_text]])
    r2 = upload_csv(
        batch_client, token=token, path=csv2, text_column="yorum",
        auto_create_tickets=True,
    )
    job2 = UUID(r2.json()["job_id"])
    await run_worker(batch_client, job2)
    job_obj2 = await fetch_job(admin_session, job2)
    assert job_obj2.tickets_created == 1, (
        "expected a fresh ticket — old review is past the dedup window"
    )
    assert job_obj2.duplicates_skipped == 0


def test_text_hash_is_turkish_case_insensitive() -> None:
    """``İYİ``.lower() in vanilla Python is `i̇yi̇` (combining-dot trap),
    which would break dedup for any text mixing the dotted-uppercase
    Turkish I. ``review_text_hash`` normalises through the I/İ → i/ı
    map first; tests the hash directly so the worker can rely on it
    for intra-batch dedup."""
    assert review_text_hash("İYİ") == review_text_hash("iyi")
    # Bare-bones casing variations also collapse.
    assert review_text_hash("Kargom KÖTÜ") == review_text_hash("kargom kötü")
