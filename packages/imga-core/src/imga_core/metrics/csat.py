"""Sprint 9.2 A — CSAT (Customer Satisfaction Score) formula.

CSAT scaled to 0-100. The canonical formula treats incoming ratings
as a 1-5 Likert and projects onto a 0-100 scale: ``mean(rating) *
20``. Service callers fetch the rating column and pass the list;
this module owns the projection + sample-coverage math.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Sequence

from imga_core.metrics.base import MetricResult, MetricScope


def score_from_ratings(
    ratings: Sequence[float | int],
    *,
    total_review_count: int | None = None,
    scope: MetricScope | None = None,
) -> MetricResult:
    """Compute CSAT from a list of 1-5 ratings.

    ``total_review_count`` is the universe; ``len(ratings)`` is the
    rating-bearing subset (rows where the customer actually answered
    the rating prompt). Coverage = bearing / total.
    """
    bearing = len(ratings)
    if bearing == 0:
        value = 0.0
        coverage = 0.0
    else:
        mean_rating = sum(ratings) / bearing
        value = float(mean_rating) * 20.0  # 1..5 → 20..100
        coverage = (
            (bearing / total_review_count) * 100.0
            if total_review_count
            else 100.0
        )
    return MetricResult(
        metric_key="csat",
        value=round(value, 2),
        unit="percentage",
        sample_count=bearing,
        coverage_percent=round(coverage, 2),
        breakdown=None,
        computed_at=datetime.now(UTC),
        scope=scope,
    )


__all__ = ["score_from_ratings"]
