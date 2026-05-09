"""Sprint 9.2 A — Category concentration (Herfindahl-Hirschman index).

Sum of squared category share. Range 0..1 (0 = perfectly diverse, 1
= one category accounts for everything). The strategic report uses
this to flag a tenant whose feedback is dominated by a single
category — a high HHI means the SWOT analysis can lean hard on
that category; a low HHI means the operator has many distinct
problem buckets to triage.

Lower is better here (more diverse customer signal); the registry
seeds ``higher_is_better=FALSE`` for this metric.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Mapping

from imga_core.metrics.base import MetricResult, MetricScope


def herfindahl_index(
    category_counts: Mapping[str, int],
    *,
    scope: MetricScope | None = None,
) -> MetricResult:
    """Compute HHI from a {category_code: count} mapping."""
    total = sum(category_counts.values())
    if total == 0:
        value = 0.0
        breakdown: dict[str, float] = {}
    else:
        shares = {
            code: count / total for code, count in category_counts.items()
        }
        value = sum(s * s for s in shares.values())
        # Top-5 share sorted desc — the dashboard tooltip uses this.
        top = sorted(shares.items(), key=lambda kv: kv[1], reverse=True)[:5]
        breakdown = {code: round(share, 4) for code, share in top}
    return MetricResult(
        metric_key="category_concentration",
        value=round(value, 4),
        unit="ratio",
        sample_count=total,
        coverage_percent=100.0 if total else 0.0,
        breakdown={"top_shares": breakdown} if breakdown else None,
        computed_at=datetime.now(UTC),
        scope=scope,
    )


__all__ = ["herfindahl_index"]
