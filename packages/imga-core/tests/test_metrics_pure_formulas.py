"""Sprint 9.2 A — pure-formula sanity for the metrics package.

Each metric function gets a happy path + the empty-pool degenerate
case. The point isn't exhaustive numeric verification (the formulas
are textbook), it's pinning the wire shape: every formula returns a
``MetricResult`` with the right ``unit`` / ``coverage_percent`` /
``breakdown`` keys, so the snapshot service + frontend can rely on
the contract.
"""

from __future__ import annotations

from imga_core.metrics import (
    METRIC_DEFINITIONS,
    concentration_herfindahl,
    csat_from_ratings,
    get_metric_definition,
    list_metric_definitions,
    manual_review_rate_from_flags,
    nps_score_from_buckets,
    sentiment_distribution_from_labels,
    volume_count_reviews,
)


# --- registry ---


def test_registry_has_six_seeded_metrics() -> None:
    keys = {m.metric_key for m in METRIC_DEFINITIONS}
    assert keys == {
        "nps",
        "csat",
        "review_volume",
        "category_concentration",
        "sentiment_distribution",
        "manual_review_rate",
    }


def test_registry_lookup_raises_keyerror_for_unknown() -> None:
    import pytest

    with pytest.raises(KeyError, match="unknown metric_key"):
        get_metric_definition("nonexistent")


def test_registry_list_returns_copies_in_order() -> None:
    a = list_metric_definitions()
    b = list_metric_definitions()
    # Same content, distinct lists (caller can't mutate the registry).
    assert a == b
    assert a is not b


# --- NPS ---


def test_nps_canonical_formula_matches_sprint_9_0_5_b() -> None:
    """((promoter - detractor) / nps_bearing) * 100. The single
    line of math the platform has been arguing about since Sprint
    8.3.5; pinning it here means a future refactor can't drift."""
    result = nps_score_from_buckets(
        promoter_count=60,
        passive_count=20,
        detractor_count=20,
        total_review_count=100,
    )
    assert result.metric_key == "nps"
    assert result.unit == "score"
    assert result.value == 40.0  # (60-20)/100*100
    assert result.sample_count == 100
    assert result.coverage_percent == 100.0
    assert result.breakdown is not None
    assert result.breakdown["promoter_count"] == 60
    assert result.breakdown["promoter_pct"] == 60.0


def test_nps_empty_pool_returns_zero_with_zero_coverage() -> None:
    result = nps_score_from_buckets(
        promoter_count=0,
        passive_count=0,
        detractor_count=0,
        total_review_count=0,
    )
    assert result.value == 0.0
    assert result.coverage_percent == 0.0
    assert result.sample_count == 0


def test_nps_coverage_reflects_nps_bearing_share() -> None:
    """50 NPS-bearing rows out of 200 total → 25% coverage."""
    result = nps_score_from_buckets(
        promoter_count=30,
        passive_count=10,
        detractor_count=10,
        total_review_count=200,
    )
    assert result.sample_count == 50
    assert result.coverage_percent == 25.0


# --- CSAT ---


def test_csat_projects_likert_to_percentage() -> None:
    # Mean rating 4.0 → 80%
    result = csat_from_ratings([5, 5, 4, 4, 4, 3, 3], total_review_count=10)
    assert result.metric_key == "csat"
    assert result.unit == "percentage"
    assert round(result.value, 1) == 80.0
    assert result.sample_count == 7
    assert result.coverage_percent == 70.0


def test_csat_empty_returns_zero() -> None:
    result = csat_from_ratings([])
    assert result.value == 0.0
    assert result.sample_count == 0


# --- review volume ---


def test_volume_passthrough() -> None:
    result = volume_count_reviews(12345)
    assert result.value == 12345.0
    assert result.unit == "count"
    assert result.coverage_percent == 100.0


# --- concentration ---


def test_concentration_perfectly_diverse_is_low() -> None:
    """4 equal categories → 4 * 0.25^2 = 0.25."""
    result = concentration_herfindahl({"a": 25, "b": 25, "c": 25, "d": 25})
    assert result.value == 0.25
    assert result.unit == "ratio"


def test_concentration_one_category_dominates_is_one() -> None:
    result = concentration_herfindahl({"single": 100})
    assert result.value == 1.0


def test_concentration_empty_returns_zero() -> None:
    result = concentration_herfindahl({})
    assert result.value == 0.0
    assert result.coverage_percent == 0.0


# --- sentiment ---


def test_sentiment_distribution_renders_pct_breakdown() -> None:
    labels = ["POZITIF"] * 60 + ["NÖTR"] * 25 + ["NEGATIF"] * 15
    result = sentiment_distribution_from_labels(labels)
    assert result.metric_key == "sentiment_distribution"
    assert result.value == 60.0  # headline = positive_pct
    assert result.unit == "percentage"
    assert result.breakdown is not None
    pct = result.breakdown["pct"]
    assert pct["POZITIF"] == 60.0
    assert pct["NÖTR"] == 25.0
    assert pct["NEGATIF"] == 15.0


def test_sentiment_distribution_unknown_label_buckets_under_unknown() -> None:
    result = sentiment_distribution_from_labels(
        ["POZITIF", "POZITIF", "INVALID_LABEL"]
    )
    assert result.breakdown is not None
    assert result.breakdown["counts"]["unknown"] == 1


# --- manual review ---


def test_manual_review_rate_basic() -> None:
    result = manual_review_rate_from_flags(
        manual_review_count=10, total_review_count=200,
    )
    assert result.value == 5.0  # 10/200 * 100
    assert result.breakdown is not None
    assert result.breakdown["auto_decided_count"] == 190


def test_manual_review_rate_empty() -> None:
    result = manual_review_rate_from_flags(
        manual_review_count=0, total_review_count=0,
    )
    assert result.value == 0.0
    assert result.coverage_percent == 0.0
