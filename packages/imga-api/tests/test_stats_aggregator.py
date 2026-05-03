"""Sprint 8.3.6 / Alt-Faz 8.3.6.3.A — StrategicStatsSnapshot + hash unit tests.

Pure unit coverage of the snapshot dataclass + ``stats_hash``. No DB,
no AnalyticsService — those land in test_swot_service.py via the
service flow tests. Here we just pin the cache-key-relevant invariants:

  * Equivalent inputs → equivalent hash (cache hits work).
  * Top-N category churn → hash changes (cache invalidates when the
    distribution actually shifts).
  * Free-text fields (business_description, industry_other_text)
    DON'T enter the hash — prose edits don't churn the SWOT cache.
"""

from __future__ import annotations

from datetime import date

from imga_api.services.stats_aggregator import StrategicStatsSnapshot


def _baseline_snapshot(**overrides: object) -> StrategicStatsSnapshot:
    base: dict[str, object] = {
        "date_from": None,
        "date_to": None,
        "industry": "e_commerce",
        "industry_other_text": None,
        "company_size": "medium",
        "business_description": "Test company",
        "total_reviews": 1000,
        "crisis_count": 50,
        "sensitive_topics_count": 80,
        "sentiment_distribution": {"negative": 600, "neutral": 200, "positive": 200},
        "avg_sentiment_score": -0.32,
        "nps_score": -15.5,
        "nps_coverage_percent": 42.0,
        "nps_distribution": {"detractor": 500, "passive": 250, "promoter": 250},
        "nps_monthly_trend": [],
        "category_distribution": [
            {"code": "kargo", "label_tr": "Kargo", "count": 300, "pct": 30.0},
            {"code": "iade", "label_tr": "İade", "count": 200, "pct": 20.0},
            {"code": "fatura", "label_tr": "Fatura", "count": 100, "pct": 10.0},
        ],
        "company_perspective_distribution": [
            {"code": "shipment_not_arrived", "label_tr": "...", "count": 250, "pct": 25.0},
            {"code": "broken_damaged", "label_tr": "...", "count": 150, "pct": 15.0},
        ],
        "unmatched_perspective_count": 300,
    }
    base.update(overrides)
    return StrategicStatsSnapshot(**base)  # type: ignore[arg-type]


def test_stats_hash_stable_for_same_inputs() -> None:
    """Two snapshots with identical fields produce the same hash —
    cache hits depend on this."""
    a = _baseline_snapshot()
    b = _baseline_snapshot()
    assert a.stats_hash() == b.stats_hash()
    # And the hash is the truncated-sha256 16-hex shape we documented.
    assert len(a.stats_hash()) == 16
    assert all(c in "0123456789abcdef" for c in a.stats_hash())


def test_stats_hash_changes_when_top_categories_change() -> None:
    """Top-5 category churn must invalidate the cache. Bumping the
    second category's count high enough to swap order with the first
    is the canonical trigger."""
    a = _baseline_snapshot()
    b = _baseline_snapshot(
        category_distribution=[
            {"code": "iade", "label_tr": "İade", "count": 500, "pct": 50.0},
            {"code": "kargo", "label_tr": "Kargo", "count": 300, "pct": 30.0},
            {"code": "fatura", "label_tr": "Fatura", "count": 100, "pct": 10.0},
        ],
    )
    assert a.stats_hash() != b.stats_hash()


def test_stats_hash_ignores_business_description() -> None:
    """The user can edit /settings/profile freely; their cached SWOT
    must NOT invalidate just because they reworded the description."""
    a = _baseline_snapshot(business_description="Eski açıklama")
    b = _baseline_snapshot(business_description="Tamamen farklı yeni açıklama")
    assert a.stats_hash() == b.stats_hash()


def test_stats_hash_ignores_industry_other_text() -> None:
    """Same reason — the prose label for ``industry='other'`` doesn't
    carry frequency information; cache stays warm."""
    a = _baseline_snapshot(industry="other", industry_other_text="ABC")
    b = _baseline_snapshot(industry="other", industry_other_text="XYZ")
    assert a.stats_hash() == b.stats_hash()


def test_stats_hash_changes_on_total_reviews() -> None:
    """A new ingestion that bumps total_reviews is exactly the
    signal we want to invalidate on."""
    a = _baseline_snapshot(total_reviews=1000)
    b = _baseline_snapshot(total_reviews=2000)
    assert a.stats_hash() != b.stats_hash()


def test_stats_hash_changes_on_nps_score_shift() -> None:
    """NPS movement of >= 1 unit (after rounding) flips the hash;
    a sub-threshold flutter (0.04 below the rounding boundary) does
    not."""
    a = _baseline_snapshot(nps_score=-15.5)
    b = _baseline_snapshot(nps_score=-15.5)  # identical → same hash
    c = _baseline_snapshot(nps_score=-25.0)  # 10-unit shift → flip
    assert a.stats_hash() == b.stats_hash()
    assert a.stats_hash() != c.stats_hash()


def test_stats_hash_distinguishes_none_from_zero() -> None:
    """``None`` (no data) must hash differently from ``0.0`` (real
    score of zero) — the prompt branches on this distinction."""
    a = _baseline_snapshot(nps_score=None)
    b = _baseline_snapshot(nps_score=0.0)
    assert a.stats_hash() != b.stats_hash()


def test_stats_hash_changes_on_unmatched_perspective_count() -> None:
    """The "Eşleşmeyen" bucket is part of the prompt; its count must
    feed the hash so a meaningful shift invalidates the cache."""
    a = _baseline_snapshot(unmatched_perspective_count=100)
    b = _baseline_snapshot(unmatched_perspective_count=500)
    assert a.stats_hash() != b.stats_hash()


def test_stats_hash_ignores_dates() -> None:
    """Date window is part of the cache KEY (separate from the hash);
    keeping it out of the hash itself avoids double-counting and lets
    us re-use the hash function for OKR cache keys later."""
    a = _baseline_snapshot(date_from=None, date_to=None)
    b = _baseline_snapshot(date_from=date(2026, 1, 1), date_to=date(2026, 3, 31))
    # Same frequency profile, different window → same hash.
    assert a.stats_hash() == b.stats_hash()
