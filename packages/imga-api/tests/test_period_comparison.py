"""Coverage for WS4's ``GET /tenants/me/analytics/period-comparison``.

Two independent date windows (A, B) reduced to the same metric bundle
+ their delta. Tests focus on:
  * Correct per-window counts (sentiment / category / total)
  * Disjoint window boundaries — the executive-briefing pitfall this
    endpoint deliberately avoids (``prior_to = date_from`` double-
    counts the boundary day; period-comparison binds A and B
    independently via ``[day_floor(from), day_ceil(to)]``)
  * Delta sign + direction (up/down/flat)
  * include_flagged toggle (WS2 veri kalitesi)
  * Basic request validation (both windows required; inverted range)
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from imga_core import review_text_hash
from imga_db.models import Review, ReviewDecision, User
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.batch_helpers import login_token


async def _seed(
    admin_session: AsyncSession,
    *,
    tenant_id: UUID,
    text_value: str,
    sentiment: str,
    score: float,
    review_date: datetime,
    category: str = "kargo",
    quality_flag: str | None = None,
    nps_score: int | None = None,
) -> Review:
    """Mirrors ``test_analytics._seed`` — kept local per this test
    suite's convention (each analytics test module owns its seed
    helper rather than importing across files)."""
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tenant_id)},
        )
        review = Review(
            tenant_id=tenant_id,
            text=text_value,
            text_hash=review_text_hash(text_value),
            sentiment_label=sentiment,
            sentiment_score=score,
            primary_category=category,
            primary_confidence=0.8,
            automation_mode="semi_auto",
            decision=ReviewDecision.SKIPPED_THRESHOLD,
            decision_reason=None,
            ticket_id=None,
            submitted_by_user_id=None,
            batch_job_id=None,
            analyzed_at=review_date,
            review_date=review_date,
            quality_flag=quality_flag,
            nps_score=nps_score,
        )
        admin_session.add(review)
        await admin_session.flush()
        admin_session.expunge(review)
    return review


@pytest.mark.asyncio
async def test_period_comparison_counts_and_distributions(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """A: 3 NEGATIF + 1 POZITIF, all 'kargo'. B: 1 NEGATIF + 3 POZITIF,
    all 'iade'. Clean round-number percentages make the delta easy to
    pin exactly."""
    user, tid, pw = semi_auto_tenant
    a_day = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)
    for i in range(3):
        await _seed(
            admin_session, tenant_id=tid, text_value=f"a-neg-{i}",
            sentiment="NEGATIF", score=-0.6, review_date=a_day,
            category="kargo",
        )
    await _seed(
        admin_session, tenant_id=tid, text_value="a-poz",
        sentiment="POZITIF", score=0.6, review_date=a_day, category="kargo",
    )

    b_day = datetime(2026, 2, 5, 12, 0, tzinfo=UTC)
    await _seed(
        admin_session, tenant_id=tid, text_value="b-neg",
        sentiment="NEGATIF", score=-0.6, review_date=b_day, category="iade",
    )
    for i in range(3):
        await _seed(
            admin_session, tenant_id=tid, text_value=f"b-poz-{i}",
            sentiment="POZITIF", score=0.6, review_date=b_day,
            category="iade",
        )

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/analytics/period-comparison"
        "?a_from=2026-01-01&a_to=2026-01-10"
        "&b_from=2026-02-01&b_to=2026-02-10",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()

    period_a = body["period_a"]
    period_b = body["period_b"]
    assert period_a["total_reviews"] == 4
    assert period_a["sentiment_counts"] == {"NEGATIF": 3, "POZITIF": 1}
    assert period_a["category_counts"] == {"kargo": 4}
    assert period_a["avg_sentiment_score"] == pytest.approx(-0.3, abs=1e-6)

    assert period_b["total_reviews"] == 4
    assert period_b["sentiment_counts"] == {"NEGATIF": 1, "POZITIF": 3}
    assert period_b["category_counts"] == {"iade": 4}
    assert period_b["avg_sentiment_score"] == pytest.approx(0.3, abs=1e-6)

    delta = body["delta"]
    assert delta["total_reviews_diff"] == 0
    assert delta["total_reviews_direction"] == "flat"
    assert delta["sentiment_pct_point_diff"] == {"NEGATIF": -50.0, "POZITIF": 50.0}
    assert delta["category_pct_point_diff"] == {"kargo": -100.0, "iade": 100.0}
    assert delta["avg_sentiment_score_diff"] == pytest.approx(0.6, abs=1e-6)
    assert delta["avg_sentiment_direction"] == "up"


@pytest.mark.asyncio
async def test_period_comparison_boundary_days_not_double_counted(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """a_to=2026-03-10, b_from=2026-03-11 (a_to + 1 day) — the two
    windows share no calendar day. A review at 23:59:59 on a_to must
    land in A only; a review at 00:00:00 on b_from must land in B
    only. This is the disjoint-boundary behaviour the executive-
    briefing ``prior_to = date_from`` pattern does NOT have (that
    pattern shares one instant between both windows)."""
    user, tid, pw = semi_auto_tenant
    await _seed(
        admin_session, tenant_id=tid, text_value="a-mid",
        sentiment="NÖTR", score=0.0,
        review_date=datetime(2026, 3, 10, 12, 0, tzinfo=UTC),
    )
    await _seed(
        admin_session, tenant_id=tid, text_value="a-last-second",
        sentiment="NÖTR", score=0.0,
        review_date=datetime(2026, 3, 10, 23, 59, 59, tzinfo=UTC),
    )
    await _seed(
        admin_session, tenant_id=tid, text_value="b-first-moment",
        sentiment="NÖTR", score=0.0,
        review_date=datetime(2026, 3, 11, 0, 0, 0, tzinfo=UTC),
    )
    await _seed(
        admin_session, tenant_id=tid, text_value="b-mid",
        sentiment="NÖTR", score=0.0,
        review_date=datetime(2026, 3, 11, 12, 0, tzinfo=UTC),
    )

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/analytics/period-comparison"
        "?a_from=2026-03-01&a_to=2026-03-10"
        "&b_from=2026-03-11&b_to=2026-03-20",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["period_a"]["total_reviews"] == 2
    assert body["period_b"]["total_reviews"] == 2
    # No shared row: the two windows' counts sum to exactly what was seeded.
    assert body["period_a"]["total_reviews"] + body["period_b"]["total_reviews"] == 4


@pytest.mark.asyncio
async def test_period_comparison_delta_direction_down_and_nps(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """B has fewer reviews and a lower NPS than A — direction fields
    must read "down", and nps_score_diff must be negative."""
    user, tid, pw = semi_auto_tenant
    a_day = datetime(2026, 4, 5, 12, 0, tzinfo=UTC)
    for i in range(4):
        await _seed(
            admin_session, tenant_id=tid, text_value=f"a-promoter-{i}",
            sentiment="POZITIF", score=0.6, review_date=a_day, nps_score=10,
        )
    b_day = datetime(2026, 5, 5, 12, 0, tzinfo=UTC)
    await _seed(
        admin_session, tenant_id=tid, text_value="b-detractor",
        sentiment="NEGATIF", score=-0.6, review_date=b_day, nps_score=0,
    )

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/analytics/period-comparison"
        "?a_from=2026-04-01&a_to=2026-04-10"
        "&b_from=2026-05-01&b_to=2026-05-10",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    delta = body["delta"]
    assert delta["total_reviews_diff"] == -3  # 1 - 4
    assert delta["total_reviews_direction"] == "down"
    assert body["period_a"]["nps"]["score"] == 100.0
    assert body["period_b"]["nps"]["score"] == -100.0
    assert delta["nps_score_diff"] == -200.0
    assert delta["nps_direction"] == "down"


@pytest.mark.asyncio
async def test_period_comparison_include_flagged_toggle(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """A flagged row in period B is excluded by default and counted
    with include_flagged=true — same WS2 contract as every other
    /analytics endpoint."""
    user, tid, pw = semi_auto_tenant
    a_day = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
    await _seed(
        admin_session, tenant_id=tid, text_value="a-clean",
        sentiment="NEGATIF", score=-0.5, review_date=a_day,
    )
    b_day = datetime(2026, 7, 5, 12, 0, tzinfo=UTC)
    await _seed(
        admin_session, tenant_id=tid, text_value="b-clean",
        sentiment="NEGATIF", score=-0.5, review_date=b_day,
    )
    await _seed(
        admin_session, tenant_id=tid, text_value="b-flagged",
        sentiment="POZITIF", score=0.5, review_date=b_day,
        quality_flag="duplicate",
    )

    token = login_token(batch_client, user.email, pw, tid)
    base_url = (
        "/tenants/me/analytics/period-comparison"
        "?a_from=2026-06-01&a_to=2026-06-10"
        "&b_from=2026-07-01&b_to=2026-07-10"
    )
    r_default = batch_client.get(base_url, headers={"Authorization": f"Bearer {token}"})
    assert r_default.status_code == 200
    assert r_default.json()["period_b"]["total_reviews"] == 1

    r_included = batch_client.get(
        base_url + "&include_flagged=true",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r_included.status_code == 200
    assert r_included.json()["period_b"]["total_reviews"] == 2


@pytest.mark.asyncio
async def test_period_comparison_requires_all_four_dates(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    """a_from/a_to/b_from/b_to are all required — omitting one is a
    422, not a silently-defaulted window."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/analytics/period-comparison"
        "?a_from=2026-01-01&a_to=2026-01-10&b_from=2026-02-01",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_period_comparison_rejects_inverted_window(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    """a_to before a_from is a 400 with a Turkish detail message."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/analytics/period-comparison"
        "?a_from=2026-01-10&a_to=2026-01-01"
        "&b_from=2026-02-01&b_to=2026-02-10",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400
