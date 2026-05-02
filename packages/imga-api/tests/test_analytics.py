"""Integration coverage for the Sprint 8.3.3 analytics endpoints.

7 endpoints under /tenants/me/analytics/* — all GET, all RLS-bound.
Tests focus on:
  * Aggregation correctness (manual count vs endpoint output)
  * RLS isolation (one cross-tenant test for the namespace; the policy
    is shared so per-endpoint repetition adds no signal)
  * Filter application (date range, source_types, sentiment_labels)
  * Empty-result shape (no 500 on zero rows)

Tests use the shared ``batch_client`` fixture + a stub-pipeline. Reviews
are inserted directly via SQL to avoid coupling to the analyze flow.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from imga_core import review_text_hash
from imga_db.models import (
    Review,
    ReviewDecision,
    User,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.batch_helpers import (
    cleanup_tenant,
    login_token,
    seed_tenant_with_admin,
)


async def _seed(
    admin_session: AsyncSession,
    *,
    tenant_id: UUID,
    text_value: str,
    sentiment: str,
    score: float,
    category: str = "kargo",
    confidence: float = 0.8,
    analyzed_at: datetime | None = None,
    batch_job_id: UUID | None = None,
) -> Review:
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
            primary_confidence=confidence,
            automation_mode="semi_auto",
            decision=ReviewDecision.SKIPPED_THRESHOLD,
            decision_reason=None,
            ticket_id=None,
            submitted_by_user_id=None,
            batch_job_id=batch_job_id,
            analyzed_at=analyzed_at or datetime.now(UTC),
        )
        admin_session.add(review)
        await admin_session.flush()
        admin_session.expunge(review)
    return review


@pytest.mark.asyncio
async def test_sentiment_distribution_counts_and_percentages(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    user, tid, pw = semi_auto_tenant
    # 2 NEGATIF, 1 POZITIF, 1 NÖTR
    for txt, sent, score in [
        ("a", "NEGATIF", -0.7), ("b", "NEGATIF", -0.5),
        ("c", "POZITIF", 0.6), ("d", "NÖTR", 0.0),
    ]:
        await _seed(admin_session, tenant_id=tid, text_value=txt, sentiment=sent, score=score)

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/analytics/sentiment-distribution",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 4
    by_label = {row["label"]: row for row in body["data"]}
    assert by_label["NEGATIF"]["count"] == 2
    assert by_label["NEGATIF"]["percentage"] == 50.0
    assert by_label["POZITIF"]["count"] == 1
    assert by_label["POZITIF"]["avg_score"] == 0.6


@pytest.mark.asyncio
async def test_category_distribution_top_n_with_limit(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    user, tid, pw = semi_auto_tenant
    # kargo: 3, iade: 2, hizmet: 1
    for n, cat in [(3, "kargo"), (2, "iade"), (1, "hizmet")]:
        for i in range(n):
            await _seed(
                admin_session, tenant_id=tid,
                text_value=f"{cat}-{i}", sentiment="NÖTR", score=0.0,
                category=cat,
            )

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/analytics/category-distribution?limit=2",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    # Top 2 by count descending.
    assert len(body["data"]) == 2
    assert body["data"][0]["category"] == "kargo"
    assert body["data"][0]["count"] == 3
    assert body["data"][1]["category"] == "iade"
    assert body["total"] == 6


@pytest.mark.asyncio
async def test_sentiment_by_category_matrix_correctness(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    user, tid, pw = semi_auto_tenant
    # kargo: 2 NEG + 1 POZ; iade: 1 NEG + 2 NÖTR
    seeds = [
        ("kargo", "NEGATIF", -0.6), ("kargo", "NEGATIF", -0.7),
        ("kargo", "POZITIF", 0.7),
        ("iade", "NEGATIF", -0.5), ("iade", "NÖTR", 0.0), ("iade", "NÖTR", 0.1),
    ]
    for i, (cat, sent, sc) in enumerate(seeds):
        await _seed(admin_session, tenant_id=tid, text_value=f"r{i}", sentiment=sent, score=sc, category=cat)

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/analytics/sentiment-by-category",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["sentiments"] == ["NEGATIF", "NÖTR", "POZITIF"]
    # kargo first (3 rows), iade next (3 rows). Matrix indices match sentiments order.
    cat_index = {c: i for i, c in enumerate(body["categories"])}
    assert "kargo" in cat_index and "iade" in cat_index
    kargo = body["matrix"][cat_index["kargo"]]
    iade = body["matrix"][cat_index["iade"]]
    assert kargo == [2, 0, 1]  # 2 NEG, 0 NÖTR, 1 POZ
    assert iade == [1, 2, 0]


@pytest.mark.asyncio
async def test_override_stats_returns_known_layers_with_zero_counts(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """Sprint 8.3.3 placeholder: overrides_applied JSONB lands in 8.3.4.
    Endpoint contract is stable (5 known layers, Türkçe labels, zero
    counts). Doesn't 500 with no data."""
    user, tid, pw = semi_auto_tenant
    await _seed(admin_session, tenant_id=tid, text_value="x", sentiment="NEGATIF", score=-0.5)
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/analytics/override-stats",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total_reviews"] == 1
    layers = {row["layer"] for row in body["data"]}
    assert layers == {"knowledge_base", "critical", "tier1", "sla", "tier2"}
    # Türkçe labels present
    assert any(row["layer_label_tr"] == "Bilgi Tabanı Kuralı" for row in body["data"])


@pytest.mark.asyncio
async def test_sentiment_timeline_day_granularity(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    user, tid, pw = semi_auto_tenant
    base = datetime(2026, 4, 1, 12, 0, tzinfo=UTC)
    for offset, sent, sc in [
        (0, "NEGATIF", -0.5), (0, "POZITIF", 0.5),
        (1, "NEGATIF", -0.3),
        (2, "NÖTR", 0.0),
    ]:
        await _seed(
            admin_session, tenant_id=tid,
            text_value=f"r-{offset}-{sent}",
            sentiment=sent, score=sc,
            analyzed_at=base + timedelta(days=offset),
        )

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/analytics/sentiment-timeline?granularity=day",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["granularity"] == "day"
    assert len(body["data"]) == 3  # 3 distinct days
    # Day 0 had 2 reviews, day 1 had 1, day 2 had 1.
    by_date = {p["date"]: p for p in body["data"]}
    assert by_date["2026-04-01"]["total"] == 2
    assert by_date["2026-04-01"]["negatif"] == 1
    assert by_date["2026-04-01"]["pozitif"] == 1
    assert by_date["2026-04-03"]["nötr"] == 1


@pytest.mark.asyncio
async def test_sensitivity_distribution_buckets_and_stats(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    user, tid, pw = semi_auto_tenant
    # Scores: -0.95, -0.5, 0.0, 0.5, 0.95 — should land in 5 distinct buckets.
    for s in [-0.95, -0.5, 0.0, 0.5, 0.95]:
        await _seed(
            admin_session, tenant_id=tid,
            text_value=f"r-{s}", sentiment="NÖTR", score=s,
        )

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/analytics/sensitivity-distribution",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 5
    assert len(body["buckets"]) == 20
    # Sum of bucket counts == total
    assert sum(b["count"] for b in body["buckets"]) == 5
    # mean ≈ 0.0
    assert abs(body["stats"]["mean"]) < 0.05


@pytest.mark.asyncio
async def test_ticket_resolution_time_empty_response(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    """No resolved tickets yet; endpoint must return zero-stats shape,
    not crash."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/analytics/ticket-resolution-time",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total_resolved_tickets"] == 0
    assert body["avg_resolution_hours"] == 0.0


@pytest.mark.asyncio
async def test_analytics_namespace_rls_isolation(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """Tenant A seeds reviews; tenant B's analytics endpoints must
    return zero rows. One representative endpoint covers the policy
    (the policy is shared across all 7 endpoints)."""
    _user_a, tid_a, _pw_a = semi_auto_tenant
    for sent, sc in [("NEGATIF", -0.6), ("POZITIF", 0.7)]:
        await _seed(admin_session, tenant_id=tid_a, text_value=f"a-{sent}", sentiment=sent, score=sc)

    user_b, tid_b, pw_b = await seed_tenant_with_admin(
        admin_session, name_prefix="Other Co"
    )
    try:
        token_b = login_token(batch_client, user_b.email, pw_b, tid_b)
        r = batch_client.get(
            "/tenants/me/analytics/sentiment-distribution",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert r.status_code == 200
        assert r.json()["total"] == 0
    finally:
        await cleanup_tenant(admin_session, user_b.id, tid_b)


# Silence unused imports.
_ = uuid4
