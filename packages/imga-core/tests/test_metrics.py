"""Aggregate metric calculations."""

from __future__ import annotations

from imga_core import AnalysisResult
from imga_core.metrics import (
    calculate_executive_metrics,
    calculate_shi,
    count_crises,
    is_alert_state,
    negative_rate,
    top_bottlenecks,
)


def _mk(label: str, score: float, company: str | None = None) -> AnalysisResult:
    return AnalysisResult(
        text="x",
        sentiment_label=label,  # type: ignore[arg-type]
        sentiment_score=score,
        company_perspective=company,
    )


def test_shi_empty_returns_zero() -> None:
    assert calculate_shi([]) == 0


def test_shi_all_positive_is_100() -> None:
    results = [_mk("POZITIF", 0.9) for _ in range(5)]
    assert calculate_shi(results) == 100


def test_shi_all_neutral_is_50() -> None:
    results = [_mk("NÖTR", 0.0) for _ in range(4)]
    assert calculate_shi(results) == 50


def test_shi_all_negative_is_zero() -> None:
    results = [_mk("NEGATIF", -0.5) for _ in range(3)]
    assert calculate_shi(results) == 0


def test_shi_formula_matches_legacy() -> None:
    # 2 pos, 1 neu, 3 neg over 6 -> (2/6)*100 + (1/6)*50 = 33.33 + 8.33 = 41.66 -> int 41
    results = [
        _mk("POZITIF", 0.8),
        _mk("POZITIF", 0.7),
        _mk("NÖTR", 0.0),
        _mk("NEGATIF", -0.4),
        _mk("NEGATIF", -0.6),
        _mk("NEGATIF", -0.9),
    ]
    assert calculate_shi(results) == 41


def test_count_crises_uses_threshold() -> None:
    results = [
        _mk("NEGATIF", -0.95),  # crisis
        _mk("NEGATIF", -0.80),  # boundary, included (<= threshold)
        _mk("NEGATIF", -0.75),  # not crisis
        _mk("POZITIF", 0.9),
    ]
    assert count_crises(results) == 2


def test_negative_rate_basic() -> None:
    results = [
        _mk("POZITIF", 0.5),
        _mk("NEGATIF", -0.5),
        _mk("NEGATIF", -0.6),
        _mk("NÖTR", 0.0),
    ]
    assert negative_rate(results) == 0.5


def test_negative_rate_empty() -> None:
    assert negative_rate([]) == 0.0


def test_top_bottlenecks_only_counts_negative() -> None:
    results = [
        _mk("NEGATIF", -0.5, "Lojistik"),
        _mk("NEGATIF", -0.6, "Lojistik"),
        _mk("NEGATIF", -0.4, "Stok"),
        _mk("POZITIF", 0.9, "Lojistik"),  # not counted
    ]
    top = top_bottlenecks(results)
    assert top[0] == ("Lojistik", 2)
    assert ("Stok", 1) in top


def test_top_bottlenecks_respects_n() -> None:
    results = [
        _mk("NEGATIF", -0.5, f"Cat{i}") for i in range(10)
    ]
    assert len(top_bottlenecks(results, n=3)) == 3


def test_executive_metrics_bundles_all_kpis() -> None:
    results = [
        _mk("POZITIF", 0.8),
        _mk("NEGATIF", -0.95, "Lojistik"),
        _mk("NEGATIF", -0.4, "Stok"),
    ]
    m = calculate_executive_metrics(results)
    assert m.total == 3
    assert m.crisis_count == 1
    assert m.shi_score == int((1 / 3) * 100)
    assert ("Lojistik", 1) in m.top_bottlenecks


def test_alert_state_above_threshold() -> None:
    # 30% negative -> alert
    results = [_mk("NEGATIF", -0.5)] * 3 + [_mk("POZITIF", 0.5)] * 7
    assert is_alert_state(results) is True


def test_alert_state_below_threshold() -> None:
    # 10% negative -> no alert
    results = [_mk("NEGATIF", -0.5)] + [_mk("POZITIF", 0.5)] * 9
    assert is_alert_state(results) is False
