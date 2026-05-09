"""Sprint 9.2 A — registry of metric metadata.

The ``METRIC_DEFINITIONS`` constant mirrors the seed data in
Migration 0026, so frontend code can read the same shape without a
DB hop and tests can verify the registry stays in sync. The
``CANONICAL_METRICS`` dict maps each metric_key to a callable
returning a ``MetricResult`` — services that want a generic
dispatch (e.g. snapshot service iterating the full registry) call
through here. Most services still call the per-metric functions
directly because the call signature varies (NPS wants buckets, CSAT
wants ratings, sentiment wants labels).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from imga_core.metrics.base import MetricResult


@dataclass(frozen=True, slots=True)
class MetricDefinitionMeta:
    """Frozen mirror of the ``metric_definitions`` table seed."""

    metric_key: str
    display_name: str
    description: str
    formula: str
    unit: str
    range_min: float | None
    range_max: float | None
    higher_is_better: bool
    aggregation: str
    canonical_implementation: str


METRIC_DEFINITIONS: tuple[MetricDefinitionMeta, ...] = (
    MetricDefinitionMeta(
        metric_key="nps",
        display_name="Net Promoter Score",
        description=(
            "Promoter % minus Detractor % over the NPS-bearing review pool."
        ),
        formula="((promoter_count - detractor_count) / nps_bearing_count) * 100",
        unit="score",
        range_min=-100.0,
        range_max=100.0,
        higher_is_better=True,
        aggregation="aggregate",
        canonical_implementation="imga_core.metrics.nps:score_from_buckets",
    ),
    MetricDefinitionMeta(
        metric_key="csat",
        display_name="Customer Satisfaction Score",
        description="Average satisfaction rating scaled to 0-100.",
        formula="mean(rating) * 20",
        unit="percentage",
        range_min=0.0,
        range_max=100.0,
        higher_is_better=True,
        aggregation="average",
        canonical_implementation="imga_core.metrics.csat:score_from_ratings",
    ),
    MetricDefinitionMeta(
        metric_key="review_volume",
        display_name="Review Volume",
        description="Total review rows in scope.",
        formula="count(*)",
        unit="count",
        range_min=0.0,
        range_max=None,
        higher_is_better=True,
        aggregation="count",
        canonical_implementation="imga_core.metrics.volume:count_reviews",
    ),
    MetricDefinitionMeta(
        metric_key="category_concentration",
        display_name="Category Concentration (Herfindahl)",
        description=(
            "Sum of squared category share — 0=spread evenly, "
            "1=one category dominates."
        ),
        formula="sum(category_share^2)",
        unit="ratio",
        range_min=0.0,
        range_max=1.0,
        higher_is_better=False,
        aggregation="aggregate",
        canonical_implementation=(
            "imga_core.metrics.concentration:herfindahl_index"
        ),
    ),
    MetricDefinitionMeta(
        metric_key="sentiment_distribution",
        display_name="Sentiment Distribution",
        description="Percent breakdown across positive / neutral / negative.",
        formula="pct_breakdown(sentiment_label)",
        unit="percentage",
        range_min=0.0,
        range_max=100.0,
        higher_is_better=True,
        aggregation="distribution",
        canonical_implementation=(
            "imga_core.metrics.sentiment:distribution_from_labels"
        ),
    ),
    MetricDefinitionMeta(
        metric_key="manual_review_rate",
        display_name="Manual Review Rate",
        description="Share of reviews routed to manual operator review.",
        formula="(manual_review_count / total) * 100",
        unit="percentage",
        range_min=0.0,
        range_max=100.0,
        higher_is_better=False,
        aggregation="percentage",
        canonical_implementation=(
            "imga_core.metrics.manual_review:rate_from_flags"
        ),
    ),
)


_BY_KEY: dict[str, MetricDefinitionMeta] = {
    m.metric_key: m for m in METRIC_DEFINITIONS
}


def get_metric_definition(metric_key: str) -> MetricDefinitionMeta:
    """Lookup with a clear KeyError when the caller asks for a metric
    that hasn't been registered."""
    if metric_key not in _BY_KEY:
        raise KeyError(
            f"unknown metric_key={metric_key!r}; "
            f"registered={list(_BY_KEY)}"
        )
    return _BY_KEY[metric_key]


def list_metric_definitions() -> list[MetricDefinitionMeta]:
    """Frontend dispatch reads this once at app load to populate the
    metric meta cache (units, ranges, labels for chart axes etc.)."""
    return list(METRIC_DEFINITIONS)


# ---------------------------------------------------------------------
# Generic dispatch — for callers that iterate the whole registry.
# Each entry is a thin closure that adapts the per-metric signature
# to a uniform ``(payload: dict, scope) -> MetricResult`` shape so
# the snapshot service doesn't have to special-case each metric.
# ---------------------------------------------------------------------


def _nps_dispatch(payload: dict[str, Any], scope: Any) -> MetricResult:
    from imga_core.metrics.nps import score_from_buckets

    return score_from_buckets(
        promoter_count=payload["promoter_count"],
        passive_count=payload["passive_count"],
        detractor_count=payload["detractor_count"],
        total_review_count=payload.get("total_review_count"),
        scope=scope,
    )


def _csat_dispatch(payload: dict[str, Any], scope: Any) -> MetricResult:
    from imga_core.metrics.csat import score_from_ratings

    return score_from_ratings(
        payload["ratings"],
        total_review_count=payload.get("total_review_count"),
        scope=scope,
    )


def _volume_dispatch(payload: dict[str, Any], scope: Any) -> MetricResult:
    from imga_core.metrics.volume import count_reviews

    return count_reviews(payload["total"], scope=scope)


def _concentration_dispatch(payload: dict[str, Any], scope: Any) -> MetricResult:
    from imga_core.metrics.concentration import herfindahl_index

    return herfindahl_index(payload["category_counts"], scope=scope)


def _sentiment_dispatch(payload: dict[str, Any], scope: Any) -> MetricResult:
    from imga_core.metrics.sentiment import distribution_from_labels

    return distribution_from_labels(payload["labels"], scope=scope)


def _manual_review_dispatch(payload: dict[str, Any], scope: Any) -> MetricResult:
    from imga_core.metrics.manual_review import rate_from_flags

    return rate_from_flags(
        manual_review_count=payload["manual_review_count"],
        total_review_count=payload["total_review_count"],
        scope=scope,
    )


CANONICAL_METRICS: dict[str, Callable[[dict[str, Any], Any], MetricResult]] = {
    "nps": _nps_dispatch,
    "csat": _csat_dispatch,
    "review_volume": _volume_dispatch,
    "category_concentration": _concentration_dispatch,
    "sentiment_distribution": _sentiment_dispatch,
    "manual_review_rate": _manual_review_dispatch,
}


__all__ = [
    "CANONICAL_METRICS",
    "METRIC_DEFINITIONS",
    "MetricDefinitionMeta",
    "get_metric_definition",
    "list_metric_definitions",
]
