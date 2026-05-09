"""Sprint 9.2 A — NPS formula.

Sprint 9.0.5-B fixed the canonical NPS in
``analytics_service.compute_nps_summary``: NPS = promoter%% -
detractor%%, where the percentage denominator is the *NPS-bearing*
review pool (rows with a non-null ``nps_score``), not the total
review pool. The formula here is the same; the service caller is
responsible for fetching the bucket counts (which involves the
NPS-bearing filter the service already applies).

Promoter / passive / detractor bands are the canonical NPS
definition: 9-10 / 7-8 / 0-6.
"""

from __future__ import annotations

from datetime import UTC, datetime

from imga_core.metrics.base import MetricResult, MetricScope


def is_promoter(score: int) -> bool:
    return score >= 9


def is_detractor(score: int) -> bool:
    return score <= 6


def is_passive(score: int) -> bool:
    return 7 <= score <= 8


def score_from_buckets(
    *,
    promoter_count: int,
    passive_count: int,
    detractor_count: int,
    total_review_count: int | None = None,
    scope: MetricScope | None = None,
) -> MetricResult:
    """Compute NPS from already-bucketed counts.

    ``total_review_count`` is the universe (all reviews in scope,
    NPS-bearing or not) — it's used to compute coverage_percent.
    When None, coverage defaults to 100 (caller is asserting the
    bucket counts already represent the universe).
    """
    nps_bearing = promoter_count + passive_count + detractor_count
    if nps_bearing == 0:
        value = 0.0
        coverage = 0.0
    else:
        value = (
            (promoter_count - detractor_count) / nps_bearing
        ) * 100.0
        coverage = (
            (nps_bearing / total_review_count) * 100.0
            if total_review_count
            else 100.0
        )
    return MetricResult(
        metric_key="nps",
        value=round(value, 2),
        unit="score",
        sample_count=nps_bearing,
        coverage_percent=round(coverage, 2),
        breakdown={
            "promoter_count": promoter_count,
            "passive_count": passive_count,
            "detractor_count": detractor_count,
            "promoter_pct": round(
                (promoter_count / nps_bearing) * 100.0, 2
            )
            if nps_bearing
            else 0.0,
            "passive_pct": round(
                (passive_count / nps_bearing) * 100.0, 2
            )
            if nps_bearing
            else 0.0,
            "detractor_pct": round(
                (detractor_count / nps_bearing) * 100.0, 2
            )
            if nps_bearing
            else 0.0,
        },
        computed_at=datetime.now(UTC),
        scope=scope,
    )


__all__ = [
    "is_detractor",
    "is_passive",
    "is_promoter",
    "score_from_buckets",
]
