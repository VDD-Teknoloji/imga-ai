"""Sprint 8.3.9 — /tenants/me/insights/* route tests.

Hits the live FastAPI app via ``batch_client`` so the tests exercise
auth + RLS binding + Redis fall-through end-to-end. The assertions
focus on response shape + validation; the analyzer math is covered
by the dedicated unit tests in test_word_cloud_generator.py +
test_cohort_heatmap.py.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from imga_db.models import User

from tests.batch_helpers import login_token


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- cohort -------------------------------------------------------------


@pytest.mark.asyncio
async def test_cohort_returns_empty_cohorts_for_clean_tenant(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    """Fresh tenant has zero reviews → cohorts list is empty but the
    response shape is intact (period + dimension echoed back)."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/insights/cohort?period=month&dimension=taxonomy",
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["period"] == "month"
    assert body["dimension"] == "taxonomy"
    assert body["cohorts"] == []


@pytest.mark.asyncio
async def test_cohort_rejects_invalid_period(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/insights/cohort?period=fortnight&dimension=taxonomy",
        headers=_auth(token),
    )
    assert r.status_code == 400, r.text


@pytest.mark.asyncio
async def test_cohort_rejects_invalid_dimension(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/insights/cohort?period=month&dimension=zodiac",
        headers=_auth(token),
    )
    assert r.status_code == 400, r.text


@pytest.mark.asyncio
async def test_cohort_clamps_limit(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    """``limit_cohorts`` over the FastAPI Query bound (50) returns
    422; under (0) too. The service only sees clamped values."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/insights/cohort?limit_cohorts=999",
        headers=_auth(token),
    )
    assert r.status_code == 422, r.text


# --- word cloud ---------------------------------------------------------


@pytest.mark.asyncio
async def test_word_cloud_empty_tenant_returns_zero_words(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/insights/word-cloud", headers=_auth(token)
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["words"] == []
    assert body["total_reviews_analyzed"] == 0


@pytest.mark.asyncio
async def test_word_cloud_rejects_invalid_sentiment(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/insights/word-cloud?sentiment=mixed",
        headers=_auth(token),
    )
    assert r.status_code == 400, r.text


@pytest.mark.asyncio
async def test_word_cloud_clamps_limit_words(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    """Backend cap is 5..500. 1000 → 422 from FastAPI Query bound."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/insights/word-cloud?limit_words=1000",
        headers=_auth(token),
    )
    assert r.status_code == 422, r.text


# --- heatmap ------------------------------------------------------------


@pytest.mark.asyncio
async def test_heatmap_returns_full_calendar_axes_on_empty_tenant(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    """Calendar axes (24 hours, 7 days) render empty cells rather
    than gaps — the heatmap UI wants a full grid even on a fresh
    tenant. Cell values default to 0 for ``count`` metric."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/insights/heatmap"
        "?x_axis=hour_of_day&y_axis=day_of_week&metric=count",
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["x_labels"]) == 24
    assert len(body["y_labels"]) == 7
    assert body["y_labels"][0] == "Pazartesi"
    assert body["values"] == [[0] * 24 for _ in range(7)]
    assert body["metric_label"] == "Yorum Sayısı"


@pytest.mark.asyncio
async def test_heatmap_rejects_same_axes(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/insights/heatmap"
        "?x_axis=day_of_week&y_axis=day_of_week",
        headers=_auth(token),
    )
    assert r.status_code == 400, r.text


@pytest.mark.asyncio
async def test_heatmap_rejects_invalid_x_axis(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/insights/heatmap?x_axis=phase_of_moon",
        headers=_auth(token),
    )
    assert r.status_code == 400, r.text


@pytest.mark.asyncio
async def test_heatmap_rejects_invalid_metric(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/insights/heatmap?metric=variance",
        headers=_auth(token),
    )
    assert r.status_code == 400, r.text


@pytest.mark.asyncio
async def test_heatmap_avg_sentiment_returns_null_cells_on_empty(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    """avg_sentiment must surface NULL cells (not 0) for empty
    buckets; rendering 0 would imply neutral sentiment which is
    misleading."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/insights/heatmap?metric=avg_sentiment",
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Empty tenant → every cell is None.
    flat = [v for row in body["values"] for v in row]
    assert all(v is None for v in flat)


# --- redis fall-through (cache off) ------------------------------------


@pytest.mark.asyncio
async def test_cohort_works_when_redis_unavailable(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    """If the Redis client is unset the cache layer logs a warning
    and falls through to the slow path — the endpoint still returns
    a valid response. Verified by the absence of a 500."""
    from imga_api.cache.redis_client import set_redis_client

    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    set_redis_client(None)
    try:
        r = batch_client.get(
            "/tenants/me/insights/cohort", headers=_auth(token)
        )
        assert r.status_code == 200, r.text
    finally:
        set_redis_client(None)
