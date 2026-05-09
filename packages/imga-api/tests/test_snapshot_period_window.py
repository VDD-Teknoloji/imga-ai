"""Sprint 9.4 C — executive snapshot period-window regression.

Two pre-9.4 bugs that the briefing surface masked:

  1. ``review_volume`` metric used the all-time count instead of
     the period window — a monthly briefing claimed ``review_volume
     = 9_770`` when only 120 of those landed in the last 30 days.

  2. ``Review.created_at <= snapshot_date`` cast a ``date`` value
     to midnight, dropping every review created on the snapshot
     day after 00:00:00.

Both compute paths now use explicit datetime bounds covering the
entire window (date_from 00:00:00 UTC → snapshot_date 23:59:59 UTC).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from imga_core import review_text_hash
from imga_db.models import Review, ReviewDecision, User
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.services.snapshot_service import SnapshotService


async def _seed_review(
    admin_session: AsyncSession,
    *,
    tenant_id: UUID,
    text_value: str,
    created_at: datetime,
    nps_score: int | None = None,
) -> Review:
    """Seed one Review at a controlled created_at — direct SQL so
    we sidestep the analyze pipeline's "now()" stamp."""
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tenant_id)},
        )
        review = Review(
            tenant_id=tenant_id,
            text=text_value,
            text_hash=review_text_hash(text_value),
            sentiment_label="NÖTR",
            sentiment_score=0.0,
            primary_category="kargo",
            primary_confidence=0.8,
            automation_mode="semi_auto",
            decision=ReviewDecision.SKIPPED_THRESHOLD,
            decision_reason=None,
            ticket_id=None,
            submitted_by_user_id=None,
            batch_job_id=None,
            analyzed_at=created_at,
            nps_score=nps_score,
            created_at=created_at,
        )
        admin_session.add(review)
        await admin_session.flush()
        admin_session.expunge(review)
    return review


@pytest.mark.asyncio
async def test_snapshot_review_volume_uses_period_window(
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """30 reviews, 10 inside the monthly window, 20 outside.
    Pre-9.4: review_volume = 30. Post-9.4: review_volume = 10."""
    _user, tid, _pw = semi_auto_tenant
    snapshot_day = datetime.now(UTC).date()

    # 10 inside the 30-day window (5 days back).
    in_window_at = datetime.now(UTC) - timedelta(days=5)
    for i in range(10):
        await _seed_review(
            admin_session,
            tenant_id=tid,
            text_value=f"in-window-{i}",
            created_at=in_window_at,
        )

    # 20 outside (45 days back — past the monthly window edge).
    out_of_window_at = datetime.now(UTC) - timedelta(days=45)
    for i in range(20):
        await _seed_review(
            admin_session,
            tenant_id=tid,
            text_value=f"out-of-window-{i}",
            created_at=out_of_window_at,
        )

    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        service = SnapshotService(admin_session)
        payload = await service.get_or_compute(
            tenant_id=tid, period="monthly", snapshot_date=snapshot_day,
        )

    review_volume = payload.metrics["review_volume"]
    assert review_volume["value"] == 10.0, (
        f"review_volume must be period-windowed; got {review_volume['value']} "
        "(if 30, the all-time-count regression is back)"
    )
    assert review_volume["sample_count"] == 10


@pytest.mark.asyncio
async def test_snapshot_includes_full_snapshot_day(
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """A review created on the snapshot day at 23:30 must be in the
    cache. Pre-9.4 the SQL bound ``<= snapshot_date`` (midnight cast)
    so anything after 00:00:00 of that day fell out."""
    _user, tid, _pw = semi_auto_tenant
    snapshot_day = datetime.now(UTC).date()
    # 23:30 UTC on the snapshot day — well past the midnight cast.
    late_in_day = datetime.combine(
        snapshot_day, datetime.min.time(), tzinfo=UTC,
    ) + timedelta(hours=23, minutes=30)

    await _seed_review(
        admin_session,
        tenant_id=tid,
        text_value="late-on-snapshot-day",
        created_at=late_in_day,
    )

    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        service = SnapshotService(admin_session)
        payload = await service.get_or_compute(
            tenant_id=tid, period="daily", snapshot_date=snapshot_day,
        )

    assert payload.metrics["review_volume"]["value"] == 1.0, (
        "snapshot_day 23:30 review must be inside the window — "
        "if value=0, the midnight-cast regression is back"
    )
