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
    overrides_applied: list[dict[str, object]] | None = None,
    quality_flag: str | None = None,
    nps_score: int | None = None,
    # 2026-08-20 — Dalga 3 dimension breakdown testleri.
    channel: str | None = None,
    business_segment: str | None = None,
    product_line: str | None = None,
    customer_tier: str | None = None,
    entered_by: str | None = None,
    source: str | None = None,
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
            # Analitik ekseni review_date; testler tarihi analyzed_at
            # ile kurguladığı için ikisi aynı ana sabitleniyor.
            review_date=analyzed_at or datetime.now(UTC),
            overrides_applied=overrides_applied,
            # 2026-08-18 — WS2 include_flagged testleri için.
            quality_flag=quality_flag,
            nps_score=nps_score,
            channel=channel,
            business_segment=business_segment,
            product_line=product_line,
            customer_tier=customer_tier,
            entered_by=entered_by,
            source=source,
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
    """Reviews without an overrides_applied trace (NULL — predates
    migration 0014, or pipeline produced an empty list and we stored
    [] explicitly) must not contribute to any layer's count. The five
    known layer rows still surface so the UI's table doesn't shift."""
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
    # Every layer is present with zero counts; the NULL row contributes nothing.
    for row in body["data"]:
        assert row["trigger_count"] == 0
        assert row["avg_impact"] == 0.0
        assert row["max_impact"] == 0.0
        assert row["direction"] == "none"
    # Türkçe labels present
    assert any(row["layer_label_tr"] == "Bilgi Tabanı Kuralı" for row in body["data"])


@pytest.mark.asyncio
async def test_override_stats_aggregates_jsonb_layer_counts_and_direction(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """Sprint 8.3.4 — override_stats now aggregates the JSONB array.
    Three reviews seed three different layer mixes; assert the
    per-layer count, direction (boost/dampen/mixed), avg_impact, and
    trigger_percentage all line up with the fixture.
    """
    user, tid, pw = semi_auto_tenant
    # Review 1: critical fires twice (negative scores → dampen).
    await _seed(
        admin_session, tenant_id=tid, text_value="r1",
        sentiment="NEGATIF", score=-0.8,
        overrides_applied=[
            {"layer": "critical", "matched_keywords": ["kötü"], "score": -0.5, "detail": None},
            {"layer": "critical", "matched_keywords": ["berbat"], "score": -0.7, "detail": None},
        ],
    )
    # Review 2: sla once (negative — dampen) + tier1 once (also negative).
    await _seed(
        admin_session, tenant_id=tid, text_value="r2",
        sentiment="NEGATIF", score=-0.6,
        overrides_applied=[
            {"layer": "sla", "matched_keywords": ["3 gün"], "score": -0.3, "detail": "SLA ihlali"},
            {"layer": "tier1", "matched_keywords": ["yavaş"], "score": -0.4, "detail": None},
        ],
    )
    # Review 3: knowledge_base hit with a positive score (boost direction).
    await _seed(
        admin_session, tenant_id=tid, text_value="r3",
        sentiment="POZITIF", score=0.7,
        overrides_applied=[
            {"layer": "knowledge_base", "matched_keywords": ["teşekkür"], "score": 0.4, "detail": None},
        ],
    )

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/analytics/override-stats",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_reviews"] == 3
    by_layer = {row["layer"]: row for row in body["data"]}

    # critical: 2 hits, both negative → dampen, avg|abs| = 0.6, max = 0.7
    crit = by_layer["critical"]
    assert crit["trigger_count"] == 2
    assert crit["direction"] == "dampen"
    assert crit["avg_impact"] == 0.6
    assert crit["max_impact"] == 0.7
    # trigger_percentage: 2 hits over 3 reviews = 66.67%
    assert crit["trigger_percentage"] == round(100 * 2 / 3, 2)

    # sla: 1 hit, negative → dampen
    sla = by_layer["sla"]
    assert sla["trigger_count"] == 1
    assert sla["direction"] == "dampen"
    assert sla["avg_impact"] == 0.3

    # knowledge_base: 1 hit, positive → boost
    kb = by_layer["knowledge_base"]
    assert kb["trigger_count"] == 1
    assert kb["direction"] == "boost"
    assert kb["avg_impact"] == 0.4

    # tier2 had no hits — still surfaces with zero counts.
    t2 = by_layer["tier2"]
    assert t2["trigger_count"] == 0
    assert t2["direction"] == "none"


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


# ---- WS2 (2026-08-18) — include_flagged veri kalitesi filtresi -------


@pytest.mark.asyncio
async def test_sentiment_distribution_excludes_flagged_reviews_by_default(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """quality_flag IS NOT NULL satırlar varsayılanda dışlanır;
    include_flagged=true ile geri gelir. sentiment-distribution
    ``_apply_review_filters`` paylaşan 9 uç için temsilci."""
    user, tid, pw = semi_auto_tenant
    await _seed(
        admin_session, tenant_id=tid, text_value="clean",
        sentiment="NEGATIF", score=-0.6,
    )
    await _seed(
        admin_session, tenant_id=tid, text_value="dup",
        sentiment="POZITIF", score=0.6, quality_flag="duplicate",
    )

    token = login_token(batch_client, user.email, pw, tid)
    r_default = batch_client.get(
        "/tenants/me/analytics/sentiment-distribution",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r_default.status_code == 200, r_default.text
    assert r_default.json()["total"] == 1

    r_included = batch_client.get(
        "/tenants/me/analytics/sentiment-distribution?include_flagged=true",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r_included.status_code == 200
    assert r_included.json()["total"] == 2


@pytest.mark.asyncio
async def test_category_distribution_excludes_flagged_reviews_by_default(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """category-distribution ayrı bir GROUP BY + total sorgusu
    çalıştırır — include_flagged'ın her ikisine de uygulandığını
    (satır kümesi + total) doğrular."""
    user, tid, pw = semi_auto_tenant
    await _seed(
        admin_session, tenant_id=tid, text_value="clean",
        sentiment="NÖTR", score=0.0, category="kargo",
    )
    await _seed(
        admin_session, tenant_id=tid, text_value="meaningless",
        sentiment="NÖTR", score=0.0, category="kargo",
        quality_flag="meaningless",
    )

    token = login_token(batch_client, user.email, pw, tid)
    r_default = batch_client.get(
        "/tenants/me/analytics/category-distribution",
        headers={"Authorization": f"Bearer {token}"},
    )
    body = r_default.json()
    assert body["total"] == 1
    assert body["data"][0]["count"] == 1

    r_included = batch_client.get(
        "/tenants/me/analytics/category-distribution?include_flagged=true",
        headers={"Authorization": f"Bearer {token}"},
    )
    body2 = r_included.json()
    assert body2["total"] == 2
    assert body2["data"][0]["count"] == 2


@pytest.mark.asyncio
async def test_nps_summary_include_flagged_toggle(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """NPS ayrı bir kod yolundan geçer (compute_nps_summary,
    AnalyticsFilters kullanmaz) — include_flagged'ın orada da
    uygulandığını doğrular."""
    user, tid, pw = semi_auto_tenant
    await _seed(
        admin_session, tenant_id=tid, text_value="clean-detractor",
        sentiment="NEGATIF", score=-0.5, nps_score=0,
    )
    await _seed(
        admin_session, tenant_id=tid, text_value="flagged-promoter",
        sentiment="POZITIF", score=0.6, nps_score=10,
        quality_flag="empty",
    )

    token = login_token(batch_client, user.email, pw, tid)
    r_default = batch_client.get(
        "/tenants/me/analytics/nps-summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    body = r_default.json()
    assert body["total_count"] == 1
    assert body["score"] == -100.0

    r_included = batch_client.get(
        "/tenants/me/analytics/nps-summary?include_flagged=true",
        headers={"Authorization": f"Bearer {token}"},
    )
    body2 = r_included.json()
    assert body2["total_count"] == 2
    assert body2["score"] == 0.0


@pytest.mark.asyncio
async def test_headline_metrics_include_flagged_toggle(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """headline-metrics de ayrı bir kod yolu (compute_headline_metrics)
    — total_reviews üstünden include_flagged doğrulanır."""
    user, tid, pw = semi_auto_tenant
    await _seed(
        admin_session, tenant_id=tid, text_value="clean",
        sentiment="NEGATIF", score=-0.5,
    )
    await _seed(
        admin_session, tenant_id=tid, text_value="flagged",
        sentiment="POZITIF", score=0.5, quality_flag="informational",
    )

    token = login_token(batch_client, user.email, pw, tid)
    r_default = batch_client.get(
        "/tenants/me/analytics/headline-metrics",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r_default.json()["total_reviews"] == 1

    r_included = batch_client.get(
        "/tenants/me/analytics/headline-metrics?include_flagged=true",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r_included.json()["total_reviews"] == 2


@pytest.mark.asyncio
async def test_snapshot_service_excludes_flagged_reviews_from_metrics(
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """Yönetici özeti önbelleği (SnapshotService) — bayraklı satır
    review_volume/NPS'i hareket ettirmemeli; toggle yok, her zaman
    temiz veri."""
    from imga_api.services.snapshot_service import SnapshotService

    _user, tid, _pw = semi_auto_tenant
    today = datetime.now(UTC).date()
    base = datetime.combine(today, datetime.min.time(), tzinfo=UTC)
    await _seed(
        admin_session, tenant_id=tid, text_value="clean",
        sentiment="NEGATIF", score=-0.5, nps_score=0,
        analyzed_at=base + timedelta(hours=10),
    )
    await _seed(
        admin_session, tenant_id=tid, text_value="flagged",
        sentiment="POZITIF", score=0.5, nps_score=10,
        quality_flag="duplicate",
        analyzed_at=base + timedelta(hours=11),
    )

    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        payload = await SnapshotService(admin_session).get_or_compute(
            tenant_id=tid, period="daily", snapshot_date=today,
        )
    assert payload.metrics["review_volume"]["sample_count"] == 1
    assert payload.metrics["nps"]["sample_count"] == 1


@pytest.mark.asyncio
async def test_trend_alert_stats_excludes_flagged_reviews(
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """TrendAlertService._stats — bayraklı satır hacim/negatif-oran
    hesaplarına girmemeli (yanlış alarm tetiklememesi için)."""
    from imga_api.services.trend_alert_service import TrendAlertService

    _user, tid, _pw = semi_auto_tenant
    now = datetime.now(UTC)
    await _seed(
        admin_session, tenant_id=tid, text_value="clean-neg",
        sentiment="NEGATIF", score=-0.5,
        analyzed_at=now - timedelta(days=1),
    )
    await _seed(
        admin_session, tenant_id=tid, text_value="flagged-pos",
        sentiment="POZITIF", score=0.5, quality_flag="meaningless",
        analyzed_at=now - timedelta(days=1),
    )

    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        stats = await TrendAlertService(admin_session)._stats(
            tid, now - timedelta(days=7), now
        )
    assert stats.review_count == 1
    assert stats.negative_share == 1.0


@pytest.mark.asyncio
async def test_executive_briefing_compute_stats_excludes_flagged_reviews(
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """ExecutiveBriefingService._compute_stats — brifing girdisi de
    temiz veriden; total_reviews + top_categories bayraklı satırı
    saymamalı."""
    from imga_api.services.executive_briefing_service import (
        ExecutiveBriefingService,
    )

    user, tid, _pw = semi_auto_tenant
    today = datetime.now(UTC).date()
    base = datetime.combine(today, datetime.min.time(), tzinfo=UTC)
    await _seed(
        admin_session, tenant_id=tid, text_value="clean",
        sentiment="NEGATIF", score=-0.5, category="kargo",
        analyzed_at=base + timedelta(hours=10),
    )
    await _seed(
        admin_session, tenant_id=tid, text_value="flagged",
        sentiment="POZITIF", score=0.5, category="iade",
        quality_flag="informational",
        analyzed_at=base + timedelta(hours=11),
    )

    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        service = ExecutiveBriefingService(admin_session, tid, user.id)
        stats = await service._compute_stats(today, today, None)
    assert stats.total_reviews == 1
    assert stats.top_categories == [{"label": "Kargo / Lojistik", "count": 1}]


# ---- 2026-08-20 (Dalga 3) — business-dimension breakdown ------------
# GET /tenants/me/business-dimensions/{dimension}/breakdown. Covers
# bucket-folding (lower/trim, most-frequent raw label), the two new
# metric_keys, and the new date_from/date_to + include_flagged params.


@pytest.mark.asyncio
async def test_dimension_breakdown_folds_case_and_whitespace_variants(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """'FEDEX' (x3) + '  fedex  ' (x1, trim) + 'fedex' (x1) tek kovaya
    katlanır; görünen değer en sık ham varyantı (FEDEX — trim
    '  fedex  'yi 'fedex' yazımına taşıdığı için oy 3-2 kalır, hâlâ
    kesin çoğunluk). Ayrıca boş-string-sonrası-trim NULL sayılır:
    tamamen boşluktan oluşan bir satır kovaya girmez ama total_count'a
    girer (coverage_count'tan düşer)."""
    user, tid, pw = semi_auto_tenant
    for i in range(3):
        await _seed(
            admin_session, tenant_id=tid, text_value=f"fedex-major-{i}",
            sentiment="NEGATIF", score=-0.5, channel="FEDEX",
        )
    await _seed(
        admin_session, tenant_id=tid, text_value="fedex-whitespace",
        sentiment="POZITIF", score=0.5, channel="  fedex  ",
    )
    await _seed(
        admin_session, tenant_id=tid, text_value="fedex-minor",
        sentiment="POZITIF", score=0.5, channel="fedex",
    )
    # Trim sonrası boş — dimension_value_present() bunu NULL sayar:
    # total_count'a girer, coverage_count'a ve hiçbir kovaya girmez.
    await _seed(
        admin_session, tenant_id=tid, text_value="blank-channel",
        sentiment="NÖTR", score=0.0, channel="   ",
    )

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/business-dimensions/channel/breakdown",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["buckets"]) == 1
    bucket = body["buckets"][0]
    assert bucket["value"] == "FEDEX"
    assert bucket["count"] == 5
    assert bucket["score"] == 5
    assert body["total_count"] == 6
    assert body["coverage_count"] == 5


@pytest.mark.asyncio
async def test_dimension_breakdown_negative_share_and_avg_sentiment(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """Dalga 3'te eklenen iki yeni metric_key: negative_share (NEGATIF
    payı %) ve avg_sentiment (ortalama sentiment_score), aynı kovada."""
    user, tid, pw = semi_auto_tenant
    for txt, sent, score in [
        ("a", "NEGATIF", -0.8), ("b", "NEGATIF", -0.6), ("c", "POZITIF", 0.5),
    ]:
        await _seed(
            admin_session, tenant_id=tid, text_value=txt,
            sentiment=sent, score=score, channel="kanal-a",
        )

    token = login_token(batch_client, user.email, pw, tid)
    neg = batch_client.get(
        "/tenants/me/business-dimensions/channel/breakdown"
        "?metric_key=negative_share",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert neg.status_code == 200, neg.text
    neg_bucket = neg.json()["buckets"][0]
    assert neg_bucket["count"] == 3
    assert neg_bucket["score"] == pytest.approx(66.67, abs=0.01)

    avg = batch_client.get(
        "/tenants/me/business-dimensions/channel/breakdown"
        "?metric_key=avg_sentiment",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert avg.status_code == 200, avg.text
    avg_bucket = avg.json()["buckets"][0]
    assert avg_bucket["score"] == pytest.approx(-0.3, abs=0.001)


@pytest.mark.asyncio
async def test_dimension_breakdown_date_window_filters_by_review_date(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """date_from/date_to review_date üzerinde gün-hassasiyetli pencere
    açar (day_floor/day_ceil deseni) — pencere dışı satır düşer."""
    user, tid, pw = semi_auto_tenant
    await _seed(
        admin_session, tenant_id=tid, text_value="inside",
        sentiment="NÖTR", score=0.0, channel="kanal-b",
        analyzed_at=datetime(2026, 8, 3, 12, tzinfo=UTC),
    )
    await _seed(
        admin_session, tenant_id=tid, text_value="outside",
        sentiment="NÖTR", score=0.0, channel="kanal-b",
        analyzed_at=datetime(2026, 7, 1, 12, tzinfo=UTC),
    )

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/business-dimensions/channel/breakdown"
        "?date_from=2026-08-01&date_to=2026-08-05",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_count"] == 1
    assert body["buckets"][0]["count"] == 1


@pytest.mark.asyncio
async def test_dimension_breakdown_include_flagged_toggle(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """quality_flag'lı satır varsayılanda dışlanır (include_flagged
    varsayılanı False — analitik konvansiyonu); include_flagged=true
    ile geri gelir."""
    user, tid, pw = semi_auto_tenant
    await _seed(
        admin_session, tenant_id=tid, text_value="clean",
        sentiment="NEGATIF", score=-0.4, channel="kanal-c",
    )
    await _seed(
        admin_session, tenant_id=tid, text_value="flagged",
        sentiment="NEGATIF", score=-0.4, channel="kanal-c",
        quality_flag="duplicate",
    )

    token = login_token(batch_client, user.email, pw, tid)
    default = batch_client.get(
        "/tenants/me/business-dimensions/channel/breakdown",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert default.status_code == 200, default.text
    assert default.json()["buckets"][0]["count"] == 1

    included = batch_client.get(
        "/tenants/me/business-dimensions/channel/breakdown"
        "?include_flagged=true",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert included.status_code == 200, included.text
    assert included.json()["buckets"][0]["count"] == 2


@pytest.mark.asyncio
async def test_dimension_breakdown_entered_by_and_source_are_valid_dimensions(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """Dalga 3 — entered_by/source VALID_DIMENSIONS'a yeni katılan iki
    boyut; breakdown ucu ikisini de kabul eder ve katlar."""
    user, tid, pw = semi_auto_tenant
    await _seed(
        admin_session, tenant_id=tid, text_value="a",
        sentiment="NÖTR", score=0.0,
        entered_by="Ayşe Yılmaz", source="Email",
    )
    await _seed(
        admin_session, tenant_id=tid, text_value="b",
        sentiment="NÖTR", score=0.0,
        entered_by="ayşe yılmaz", source="email",
    )

    token = login_token(batch_client, user.email, pw, tid)
    by_agent = batch_client.get(
        "/tenants/me/business-dimensions/entered_by/breakdown",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert by_agent.status_code == 200, by_agent.text
    agent_buckets = by_agent.json()["buckets"]
    assert len(agent_buckets) == 1
    assert agent_buckets[0]["count"] == 2

    by_source = batch_client.get(
        "/tenants/me/business-dimensions/source/breakdown",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert by_source.status_code == 200, by_source.text
    source_buckets = by_source.json()["buckets"]
    assert len(source_buckets) == 1
    assert source_buckets[0]["count"] == 2


# Silence unused imports.
_ = uuid4
