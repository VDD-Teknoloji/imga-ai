"""Performance gate for the xlsx report generator.

Sprint 8.3.4. ``@pytest.mark.slow`` — opt in with:

    pytest -m slow tests/test_report_performance.py

Seeds 5K reviews directly via SQL (no analyze flow on the path) and
generates a comprehensive xlsx, asserting the generator finishes in
under 60s. The 5K row count is the dominant case — anything larger
hits the 50K hard cap during request validation.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from imga_core import review_text_hash
from imga_db.models import (
    ReportJob,
    ReportStatus,
    Review,
    ReviewDecision,
    User,
)
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.workers import report_generator
from tests.batch_helpers import login_token


async def _build_test_context(batch_client: TestClient) -> Any:
    settings = batch_client.app.state.settings.report  # type: ignore[attr-defined]
    return await report_generator.build_report_context(settings=settings)


async def _seed_n_reviews(
    admin_session: AsyncSession, *, tenant_id: UUID, n: int
) -> None:
    """Bulk-insert N reviews via a single transaction. We avoid per-row
    flushes — the goal is to set up the data, not test the orm."""
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tenant_id)},
        )
        moment = datetime.now(UTC)
        rows = []
        for i in range(n):
            text_value = f"perf yorum {i} kargo iade fatura"
            rows.append(
                Review(
                    tenant_id=tenant_id,
                    text=text_value,
                    text_hash=review_text_hash(text_value + str(i)),
                    sentiment_label="NEGATIF" if i % 3 == 0 else "POZITIF",
                    sentiment_score=-0.5 if i % 3 == 0 else 0.5,
                    primary_category="kargo",
                    primary_confidence=0.85,
                    automation_mode="semi_auto",
                    decision=ReviewDecision.SKIPPED_THRESHOLD,
                    decision_reason=None,
                    ticket_id=None,
                    submitted_by_user_id=None,
                    analyzed_at=moment,
                )
            )
        admin_session.add_all(rows)
        await admin_session.flush()


@pytest.mark.slow
@pytest.mark.timeout(120)
@pytest.mark.asyncio
async def test_5000_row_xlsx_under_60_seconds(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """5K-row comprehensive xlsx generation under 60s. Catches a
    regression in the xlsxwriter row-write loop or a missed index hit
    on the analytics joins inside the generator."""
    user, tid, pw = semi_auto_tenant
    await _seed_n_reviews(admin_session, tenant_id=tid, n=5000)

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.post(
        "/tenants/me/reports/generate",
        headers={"Authorization": f"Bearer {token}"},
        json={"report_type": "comprehensive", "format": "xlsx", "filters": {}},
    )
    assert r.status_code == 201, r.text
    report_id = UUID(r.json()["report_id"])

    context = await _build_test_context(batch_client)
    try:
        started = time.monotonic()
        await report_generator.generate_report_job(report_id, context)
        elapsed = time.monotonic() - started
    finally:
        await context.dispose()

    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        job = (
            await admin_session.execute(
                select(ReportJob).where(ReportJob.id == report_id)
            )
        ).scalar_one()
    assert str(job.status) == ReportStatus.COMPLETED.value
    assert (job.file_size_bytes or 0) > 0
    assert Path(str(job.file_path)).exists()
    assert elapsed < 60, (
        f"5K-row xlsx generation took {elapsed:.1f}s — performance gate "
        f"breached (xlsxwriter loop or aggregation regression)."
    )
