"""Sprint 9.2 A — manual review rate.

Share of reviews routed to manual operator review. Lower is better
(an automated pipeline that can decide on its own); a rising rate
signals classifier confidence drop or a new content shape the
keyword/LLM stack hasn't seen.
"""

from __future__ import annotations

from datetime import UTC, datetime

from imga_core.metrics.base import MetricResult, MetricScope


def rate_from_flags(
    *,
    manual_review_count: int,
    total_review_count: int,
    scope: MetricScope | None = None,
) -> MetricResult:
    """Percentage of reviews flagged ``requires_manual_review=true``."""
    if total_review_count == 0:
        value = 0.0
    else:
        value = (manual_review_count / total_review_count) * 100.0
    return MetricResult(
        metric_key="manual_review_rate",
        value=round(value, 2),
        unit="percentage",
        sample_count=total_review_count,
        coverage_percent=100.0 if total_review_count else 0.0,
        breakdown={
            "manual_review_count": manual_review_count,
            "auto_decided_count": total_review_count - manual_review_count,
        },
        computed_at=datetime.now(UTC),
        scope=scope,
    )


__all__ = ["rate_from_flags"]
