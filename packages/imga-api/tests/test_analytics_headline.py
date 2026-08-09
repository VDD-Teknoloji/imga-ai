"""Coverage for /tenants/me/analytics/headline-metrics — the dashboard
top-row aggregator (Sprint 8.3.5 / Alt-Faz 8.3.5.4).

Eight metrics in one round-trip; tests pin every field's "no data"
contract (None for nps/avg, 0 for counts), the JSONB EXISTS path for
sensitive_topics_count (tier1/tier2 layers, distinct), the Istanbul-
local "today" boundary for today_new_tickets, and the date-range
filter scope (review-side metrics only — tickets stay live).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from imga_core import review_text_hash
from imga_db.models import (
    Category,
    Review,
    ReviewDecision,
    Ticket,
    TicketState,
    User,
)
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.batch_helpers import (
    cleanup_tenant,
    login_token,
    seed_tenant_with_admin,
)


async def _pick_kargo_id(admin_session: AsyncSession) -> UUID:
    """Global 'kargo' category — every fresh tenant inherits it via
    the platform-default seeds, so tickets can carry a real category
    FK without a per-tenant insert."""
    async with admin_session.begin():
        row = await admin_session.execute(
            select(Category.id)
            .where(Category.tenant_id.is_(None))
            .where(Category.code == "kargo")
        )
        return UUID(str(row.scalar_one()))


async def _seed_review(
    admin_session: AsyncSession,
    *,
    tenant_id: UUID,
    text_value: str,
    sentiment_score: float = 0.0,
    nps_score: int | None = None,
    created_at: datetime | None = None,
    overrides_applied: list[dict[str, object]] | None = None,
    batch_job_id: UUID | None = None,
) -> Review:
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tenant_id)},
        )
        kwargs: dict[str, object] = {
            "tenant_id": tenant_id,
            "text": text_value,
            "text_hash": review_text_hash(text_value),
            "sentiment_label": "NÖTR",
            "sentiment_score": sentiment_score,
            "primary_category": "kargo",
            "primary_confidence": 0.5,
            "automation_mode": "semi_auto",
            "decision": ReviewDecision.SKIPPED_THRESHOLD,
            "decision_reason": None,
            "ticket_id": None,
            "submitted_by_user_id": None,
            "batch_job_id": batch_job_id,
            "analyzed_at": datetime.now(UTC),
            "nps_score": nps_score,
            "overrides_applied": overrides_applied,
        }
        if created_at is not None:
            kwargs["created_at"] = created_at
            kwargs["review_date"] = created_at
        review = Review(**kwargs)
        admin_session.add(review)
        await admin_session.flush()
        admin_session.expunge(review)
    return review


async def _seed_ticket(
    admin_session: AsyncSession,
    *,
    tenant_id: UUID,
    category_id: UUID,
    state: TicketState = TicketState.OPEN,
    opened_at: datetime | None = None,
) -> UUID:
    moment = opened_at or datetime.now(UTC)
    ticket = Ticket(
        tenant_id=tenant_id,
        category_id=category_id,
        title="hdr-test",
        state=state,
        opened_at=moment,
        last_state_change_at=moment,
    )
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tenant_id)},
        )
        admin_session.add(ticket)
        await admin_session.flush()
        ticket_id = ticket.id
    return ticket_id


# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_headline_metrics_empty_tenant_returns_zero_or_none(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    """No reviews + no tickets → every count 0, both score fields None,
    coverage 0%. Pins the empty-state contract for the dashboard."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/analytics/headline-metrics",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {
        "total_reviews": 0,
        "open_tickets": 0,
        "today_new_tickets": 0,
        "crisis_count": 0,
        "nps_score": None,
        "nps_coverage_percent": 0.0,
        "avg_sentiment_score": None,
        "sensitive_topics_count": 0,
    }


@pytest.mark.asyncio
async def test_headline_metrics_populated_yields_correct_aggregates(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """Mixed review + ticket seed; assert every aggregated field hits
    the value the data implies."""
    user, tid, pw = semi_auto_tenant
    cat = await _pick_kargo_id(admin_session)

    # Five reviews with varying scores + NPS.
    # Three crisis (<=-0.80), one positive, one neutral.
    await _seed_review(
        admin_session, tenant_id=tid, text_value="crisis-1",
        sentiment_score=-0.95, nps_score=0,
    )
    await _seed_review(
        admin_session, tenant_id=tid, text_value="crisis-2",
        sentiment_score=-0.85, nps_score=2,
    )
    await _seed_review(
        admin_session, tenant_id=tid, text_value="crisis-3",
        sentiment_score=-0.80, nps_score=4,  # at threshold counts
    )
    await _seed_review(
        admin_session, tenant_id=tid, text_value="positive",
        sentiment_score=0.6, nps_score=10,
    )
    await _seed_review(
        admin_session, tenant_id=tid, text_value="neutral",
        sentiment_score=0.0, nps_score=8,
    )

    # Three tickets — 2 active (OPEN, IN_PROGRESS), 1 closed.
    await _seed_ticket(admin_session, tenant_id=tid, category_id=cat)
    await _seed_ticket(
        admin_session, tenant_id=tid, category_id=cat,
        state=TicketState.IN_PROGRESS,
    )
    await _seed_ticket(
        admin_session, tenant_id=tid, category_id=cat,
        state=TicketState.CLOSED,
    )

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/analytics/headline-metrics",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_reviews"] == 5
    assert body["crisis_count"] == 3
    # NPS: 4 detractors (0/2/4) + 1 passive (8) + 1 promoter (10)?
    # Wait: 0,2,4 → detractor (3), 8 → passive (1), 10 → promoter (1).
    # Total 5; (1 - 3) / 5 * 100 = -40.0
    assert body["nps_score"] == -40.0
    assert body["nps_coverage_percent"] == 100.0
    # avg_sentiment_score: (-0.95 - 0.85 - 0.80 + 0.6 + 0.0) / 5 = -0.4
    assert body["avg_sentiment_score"] == -0.4
    # sensitive_topics_count: no overrides_applied set → 0
    assert body["sensitive_topics_count"] == 0
    # Tickets — 2 active, today's intake = 3 (all seeded just now in
    # Istanbul-today window).
    assert body["open_tickets"] == 2
    assert body["today_new_tickets"] >= 3  # at least the 3 we seeded


@pytest.mark.asyncio
async def test_headline_metrics_sensitive_topics_jsonb_exists(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """sensitive_topics_count uses JSONB EXISTS for tier1/tier2 layers,
    counts each review at most once even with multiple matching layers,
    and skips rows whose overrides_applied is NULL."""
    user, tid, pw = semi_auto_tenant
    # 1. tier1 only → counted once.
    await _seed_review(
        admin_session, tenant_id=tid, text_value="t1-only",
        overrides_applied=[
            {"layer": "tier1", "matched_keywords": ["a"], "score": -0.6, "detail": None},
        ],
    )
    # 2. tier2 only → counted once.
    await _seed_review(
        admin_session, tenant_id=tid, text_value="t2-only",
        overrides_applied=[
            {"layer": "tier2", "matched_keywords": ["b"], "score": -0.4, "detail": None},
        ],
    )
    # 3. both tier1 + tier2 + critical (extra) → counted ONCE not three.
    await _seed_review(
        admin_session, tenant_id=tid, text_value="both-and-extra",
        overrides_applied=[
            {"layer": "tier1", "matched_keywords": ["c"], "score": -0.5, "detail": None},
            {"layer": "tier2", "matched_keywords": ["d"], "score": -0.3, "detail": None},
            {"layer": "critical", "matched_keywords": ["e"], "score": -0.95, "detail": None},
        ],
    )
    # 4. critical only (NOT tier1/tier2) → NOT counted.
    await _seed_review(
        admin_session, tenant_id=tid, text_value="critical-only",
        overrides_applied=[
            {"layer": "critical", "matched_keywords": ["f"], "score": -0.95, "detail": None},
        ],
    )
    # 5. NULL overrides_applied → NOT counted (no NPE on COALESCE).
    await _seed_review(
        admin_session, tenant_id=tid, text_value="null-overrides",
    )
    # 6. Empty array overrides_applied → NOT counted.
    await _seed_review(
        admin_session, tenant_id=tid, text_value="empty-overrides",
        overrides_applied=[],
    )

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/analytics/headline-metrics",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Three rows have tier1 OR tier2; #3 carries both but counts once.
    assert body["sensitive_topics_count"] == 3
    assert body["total_reviews"] == 6


@pytest.mark.asyncio
async def test_headline_metrics_date_filter_only_affects_review_metrics(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """date_from / date_to filter total_reviews + crisis + nps + avg
    + sensitive — but open_tickets and today_new_tickets stay live
    (the dashboard never pretends "yesterday's open tickets")."""
    user, tid, pw = semi_auto_tenant
    cat = await _pick_kargo_id(admin_session)

    # In-window review.
    await _seed_review(
        admin_session, tenant_id=tid, text_value="in-window",
        sentiment_score=-0.9, nps_score=0,
        created_at=datetime(2026, 1, 15, 12, 0, tzinfo=UTC),
    )
    # Out-of-window review.
    await _seed_review(
        admin_session, tenant_id=tid, text_value="out-of-window",
        sentiment_score=0.5, nps_score=10,
        created_at=datetime(2026, 3, 1, 12, 0, tzinfo=UTC),
    )
    # Open ticket — opened today (live state, ignored by date filter).
    await _seed_ticket(admin_session, tenant_id=tid, category_id=cat)

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/analytics/headline-metrics"
        "?date_from=2026-01-01&date_to=2026-01-31",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    # Review metrics narrow to the in-window row.
    assert body["total_reviews"] == 1
    assert body["crisis_count"] == 1
    assert body["nps_score"] == -100.0  # 1 detractor only
    assert body["avg_sentiment_score"] == -0.9
    # Ticket metrics still live.
    assert body["open_tickets"] == 1
    assert body["today_new_tickets"] >= 1


@pytest.mark.asyncio
async def test_headline_metrics_rls_isolates_tenants(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """Tenant A's data must not leak to tenant B's dashboard. One
    representative test for the namespace; the policy is shared."""
    _user_a, tid_a, _pw_a = semi_auto_tenant
    cat = await _pick_kargo_id(admin_session)
    await _seed_review(
        admin_session, tenant_id=tid_a, text_value="alpha-r",
        sentiment_score=-0.9, nps_score=0,
    )
    await _seed_ticket(admin_session, tenant_id=tid_a, category_id=cat)

    user_b, tid_b, pw_b = await seed_tenant_with_admin(
        admin_session, name_prefix="Beta Hdr"
    )
    try:
        token_b = login_token(batch_client, user_b.email, pw_b, tid_b)
        r = batch_client.get(
            "/tenants/me/analytics/headline-metrics",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert r.status_code == 200
        body = r.json()
        # Tenant B sees nothing from tenant A.
        assert body["total_reviews"] == 0
        assert body["crisis_count"] == 0
        assert body["open_tickets"] == 0
        assert body["nps_score"] is None
    finally:
        await cleanup_tenant(admin_session, user_b.id, tid_b)


@pytest.mark.asyncio
async def test_headline_metrics_batch_id_scopes_review_side_only(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """Sprint 9.5 B4 — ``batch_id`` was already supported by the
    service but the route dropped it. With the param wired through,
    a batch-scoped call must:

      * count only the reviews tied to that batch (not tenant-wide);
      * still report live open_tickets (ticket counts are NEVER
        batch-scoped — the service contract);
      * leave the unscoped call untouched (both reviews counted).

    Regression guard: if the route signature ever loses ``batch_id``
    again, both halves of the assertion flip and this test fails
    loudly."""
    from datetime import timedelta

    from imga_db.models import AnalyzeBatchJob, BatchJobStatus

    user, tid, pw = semi_auto_tenant
    cat = await _pick_kargo_id(admin_session)

    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        job = AnalyzeBatchJob(
            tenant_id=tid,
            triggered_by_user_id=user.id,
            status=BatchJobStatus.COMPLETED,
            file_name="b4.csv",
            file_size_bytes=42,
            file_path="/tmp/b4.csv",
            text_column="yorum",
            source_column=None,
            auto_create_tickets=False,
            total_rows=1,
            processed_rows=1,
            succeeded_rows=1,
            failed_rows=0,
            tickets_created=0,
            duplicates_skipped=0,
            error_summary=[],
            created_at=datetime.now(UTC),
            started_at=datetime.now(UTC) - timedelta(seconds=5),
            completed_at=datetime.now(UTC),
        )
        admin_session.add(job)
        await admin_session.flush()
        batch_id = job.id

    # One review in the batch, one tenant-wide outside it.
    await _seed_review(
        admin_session, tenant_id=tid, text_value="in-batch",
        sentiment_score=-0.9, batch_job_id=batch_id,
    )
    await _seed_review(
        admin_session, tenant_id=tid, text_value="not-in-batch",
        sentiment_score=0.5,
    )
    # Open ticket — proves it stays in the count regardless of scope.
    await _seed_ticket(admin_session, tenant_id=tid, category_id=cat)

    token = login_token(batch_client, user.email, pw, tid)

    # 1. Unscoped — both reviews counted.
    r_all = batch_client.get(
        "/tenants/me/analytics/headline-metrics",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r_all.status_code == 200, r_all.text
    assert r_all.json()["total_reviews"] == 2
    assert r_all.json()["open_tickets"] == 1

    # 2. Batch-scoped — only the batched review counted; ticket count
    # stays live.
    r_batch = batch_client.get(
        f"/tenants/me/analytics/headline-metrics?batch_id={batch_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r_batch.status_code == 200, r_batch.text
    body = r_batch.json()
    assert body["total_reviews"] == 1, (
        "batch_id must scope review-side metrics; if total_reviews is 2 "
        "here the route dropped the query param before reaching the "
        "service."
    )
    assert body["crisis_count"] == 1  # the in-batch review is crisis
    assert body["open_tickets"] == 1, (
        "open_tickets must stay live — tickets are never batch-scoped"
    )


def test_istanbul_today_start_returns_utc_midnight_at_local_day_boundary() -> None:
    """The "today" anchor is local Istanbul midnight, returned in UTC.
    Istanbul is UTC+3 year-round (no DST since 2016), so today starts
    at 21:00 UTC the previous calendar day. Pin the conversion so a
    future change to ZoneInfo data doesn't silently flip the boundary.
    """
    from imga_api.services.analytics_service import _istanbul_today_start_utc

    # 2026-04-15T10:00:00 UTC → in Istanbul that's 13:00 same date.
    # Istanbul "today" starts at 2026-04-15T00:00 local = 2026-04-14T21:00 UTC.
    midday_utc = datetime(2026, 4, 15, 10, 0, tzinfo=UTC)
    result = _istanbul_today_start_utc(midday_utc)
    assert result == datetime(2026, 4, 14, 21, 0, tzinfo=UTC)

    # 2026-04-15T20:00 UTC → in Istanbul still same calendar date (23:00).
    late_utc = datetime(2026, 4, 15, 20, 0, tzinfo=UTC)
    assert _istanbul_today_start_utc(late_utc) == datetime(
        2026, 4, 14, 21, 0, tzinfo=UTC
    )

    # 2026-04-15T21:30 UTC → Istanbul 00:30 next day; "today" rolled.
    after_roll_utc = datetime(2026, 4, 15, 21, 30, tzinfo=UTC)
    assert _istanbul_today_start_utc(after_roll_utc) == datetime(
        2026, 4, 15, 21, 0, tzinfo=UTC
    )
