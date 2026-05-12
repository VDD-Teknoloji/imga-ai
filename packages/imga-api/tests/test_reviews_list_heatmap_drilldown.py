"""Sprint 9.5 B1 — /tenants/me/reviews heatmap drilldown filter tests.

The /insights heatmap exposes 5 axis types: hour_of_day,
day_of_week, week_of_year, month, taxonomy_code. Clicking a
cell routes to /reviews with the matching axis values as query
params; this file pins the new EXTRACT-based filters on the
review list endpoint.

Each test seeds reviews at controlled ``created_at`` timestamps
(via direct SQLAlchemy INSERT — sidesteps the analyze pipeline's
``now()`` stamp) and asserts the filter picks exactly the rows
in the targeted hour / day-of-week / month / week bucket.
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


async def _insert_at(
    admin_session: AsyncSession,
    *,
    tenant_id: UUID,
    text_value: str,
    created_at: datetime,
    category: str = "kargo",
) -> Review:
    """Direct INSERT at a controlled ``created_at`` — the heatmap
    drilldown filters all run off ``EXTRACT(... FROM created_at)``
    so the seeded timestamp is load-bearing."""
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tenant_id)},
        )
        r = Review(
            tenant_id=tenant_id,
            text=text_value,
            text_hash=review_text_hash(text_value),
            sentiment_label="NÖTR",
            sentiment_score=0.0,
            primary_category=category,
            primary_confidence=0.8,
            automation_mode="semi_auto",
            decision=ReviewDecision.SKIPPED_THRESHOLD,
            decision_reason=None,
            submitted_by_user_id=None,
            batch_job_id=None,
            analyzed_at=created_at,
            created_at=created_at,
        )
        admin_session.add(r)
        await admin_session.flush()
        admin_session.expunge(r)
    return r


@pytest.mark.asyncio
async def test_filter_hour_of_day_returns_only_matching_hour(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    user, tid, pw = semi_auto_tenant
    # Reviews at hour 9 + hour 14. Filter for hour=9 → just one.
    base = datetime(2026, 5, 12, 9, 30, tzinfo=UTC)
    await _insert_at(
        admin_session, tenant_id=tid, text_value="nine", created_at=base,
    )
    await _insert_at(
        admin_session, tenant_id=tid, text_value="fourteen",
        created_at=base.replace(hour=14),
    )

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/reviews?hour_of_day=9",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["text"] == "nine"


@pytest.mark.asyncio
async def test_filter_day_of_week_postgres_dow_semantics(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """Postgres DOW: 0=Sunday..6=Saturday. The heatmap labels Pazartesi
    as the first day but stores it as DOW=1 in the raw key. The route
    must accept the raw Postgres value so the heatmap cell-click URL
    works without any client-side rebasing."""
    user, tid, pw = semi_auto_tenant
    # 2026-05-11 is a Monday → DOW=1. 2026-05-13 is Wednesday → DOW=3.
    await _insert_at(
        admin_session, tenant_id=tid, text_value="monday",
        created_at=datetime(2026, 5, 11, 10, 0, tzinfo=UTC),
    )
    await _insert_at(
        admin_session, tenant_id=tid, text_value="wednesday",
        created_at=datetime(2026, 5, 13, 10, 0, tzinfo=UTC),
    )

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/reviews?day_of_week=1",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["text"] == "monday"


@pytest.mark.asyncio
async def test_filter_month_combined_with_hour_of_day(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """Composite filter: heatmap with xAxis=hour_of_day + yAxis=month
    clicks emit both filters. AND semantics: only rows matching BOTH
    survive."""
    user, tid, pw = semi_auto_tenant
    # May @ 9, May @ 14, June @ 9 → only May@9 matches month=5+hour=9.
    await _insert_at(
        admin_session, tenant_id=tid, text_value="may9",
        created_at=datetime(2026, 5, 12, 9, 0, tzinfo=UTC),
    )
    await _insert_at(
        admin_session, tenant_id=tid, text_value="may14",
        created_at=datetime(2026, 5, 12, 14, 0, tzinfo=UTC),
    )
    await _insert_at(
        admin_session, tenant_id=tid, text_value="june9",
        created_at=datetime(2026, 6, 1, 9, 0, tzinfo=UTC),
    )

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/reviews?month=5&hour_of_day=9",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["text"] == "may9"


@pytest.mark.asyncio
async def test_filter_rejects_out_of_range_values(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    """Route Query(ge=, le=) bounds prevent garbage params. A
    drilldown URL forged by hand with hour_of_day=99 must 422,
    not silently return zero rows."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)

    r = batch_client.get(
        "/tenants/me/reviews?hour_of_day=99",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 422, r.text

    r2 = batch_client.get(
        "/tenants/me/reviews?day_of_week=7",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r2.status_code == 422
