"""Sprint 9.2 A — Review Volume (count) metric."""

from __future__ import annotations

from datetime import UTC, datetime

from imga_core.metrics.base import MetricResult, MetricScope


def count_reviews(
    total: int,
    *,
    scope: MetricScope | None = None,
) -> MetricResult:
    """Total review count in scope. Coverage is always 100% (a count
    is its own population)."""
    return MetricResult(
        metric_key="review_volume",
        value=float(total),
        unit="count",
        sample_count=total,
        coverage_percent=100.0,
        breakdown=None,
        computed_at=datetime.now(UTC),
        scope=scope,
    )


__all__ = ["count_reviews"]
