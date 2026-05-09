"""Sprint 9.2 A — KPI metric contract: pure-formula side.

The platform's metric calculations used to be re-implemented per
service: the dashboard's NPS, the executive briefing's NPS, and the
trend alert's NPS each had their own SQL aggregation. Sprint 9.0.5-B
fixed the canonical formula but didn't fix the duplication; Sprint
9.2 closes that by housing every formula in one Python module per
metric, callable from any service.

The split between this package and the service layer follows the
``imga-core has zero DB deps`` rule: the formulas here take
already-fetched primitives (counts, lists, ratios) and return a
``MetricResult``. Each service still owns its data fetch (the
filters around perspective, automation mode, NPS-bearing review
pool, etc. are service-specific) but the math is shared.

The registry exposes:

  * ``MetricResult`` — the wire shape every formula returns.
  * ``CANONICAL_METRICS`` — module-level dict mapping metric_key to
    a callable that produces a MetricResult; used by services that
    want a generic dispatch (e.g. snapshot_service iterating all
    metrics).
  * ``get_metric_definition(key)`` / ``list_metric_definitions()``
    — frontend-facing meta lookup mirroring the
    ``metric_definitions`` table seeded in Migration 0026.

Adding a new metric:
  1. Add a Python module under ``imga_core/metrics/`` with a
     canonical function returning ``MetricResult``.
  2. Append the registry entry in ``CANONICAL_METRICS`` below.
  3. Insert a row in ``metric_definitions`` (Migration 0026 covers
     the initial six; new metrics get a follow-up migration).
"""

from imga_core.metrics.base import MetricResult, MetricScope
from imga_core.metrics.csat import score_from_ratings as csat_from_ratings
from imga_core.metrics.executive import (
    ExecutiveMetrics,
    calculate_executive_metrics,
    calculate_shi,
    count_crises,
    is_alert_state,
    negative_rate,
    top_bottlenecks,
)
from imga_core.metrics.manual_review import (
    rate_from_flags as manual_review_rate_from_flags,
)
from imga_core.metrics.concentration import (
    herfindahl_index as concentration_herfindahl,
)
from imga_core.metrics.nps import score_from_buckets as nps_score_from_buckets
from imga_core.metrics.registry import (
    CANONICAL_METRICS,
    METRIC_DEFINITIONS,
    MetricDefinitionMeta,
    get_metric_definition,
    list_metric_definitions,
)
from imga_core.metrics.sentiment import (
    distribution_from_labels as sentiment_distribution_from_labels,
)
from imga_core.metrics.volume import count_reviews as volume_count_reviews

__all__ = [
    "CANONICAL_METRICS",
    "METRIC_DEFINITIONS",
    "ExecutiveMetrics",
    "MetricDefinitionMeta",
    "MetricResult",
    "MetricScope",
    "calculate_executive_metrics",
    "calculate_shi",
    "concentration_herfindahl",
    "count_crises",
    "csat_from_ratings",
    "get_metric_definition",
    "is_alert_state",
    "list_metric_definitions",
    "manual_review_rate_from_flags",
    "negative_rate",
    "nps_score_from_buckets",
    "sentiment_distribution_from_labels",
    "top_bottlenecks",
    "volume_count_reviews",
]
