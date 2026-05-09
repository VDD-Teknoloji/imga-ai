"""Sprint 9.2 A — sentiment distribution (positive/neutral/negative).

The keyword classifier emits sentiment_label as one of ``POZITIF`` /
``NÖTR`` / ``NEGATIF`` (Turkish; the BERT model returns the same
labels). The metric exposes the percentage breakdown plus the raw
counts so the dashboard can show both a ratio bar and the absolute
totals.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Iterable

from imga_core.metrics.base import MetricResult, MetricScope

_LABELS = ("POZITIF", "NÖTR", "NEGATIF")


def distribution_from_labels(
    labels: Iterable[str],
    *,
    scope: MetricScope | None = None,
) -> MetricResult:
    """Count + pct breakdown from a flat label iterable. Unknown
    labels (a future model adds a fourth bucket, say) get bucketed
    under ``unknown`` so the headline percentages still sum to 100."""
    counts: Counter[str] = Counter()
    for raw in labels:
        if raw in _LABELS:
            counts[raw] += 1
        else:
            counts["unknown"] += 1
    total = sum(counts.values())
    if total == 0:
        return MetricResult(
            metric_key="sentiment_distribution",
            value=0.0,
            unit="percentage",
            sample_count=0,
            coverage_percent=0.0,
            breakdown=None,
            computed_at=datetime.now(UTC),
            scope=scope,
        )
    pct = {
        label: round((counts.get(label, 0) / total) * 100.0, 2)
        for label in (*_LABELS, "unknown")
        if counts.get(label, 0)
    }
    # Headline value: positive percentage. The "positive share" is the
    # single number an executive can quote ("78% positive sentiment");
    # the breakdown carries the full picture.
    positive_pct = pct.get("POZITIF", 0.0)
    return MetricResult(
        metric_key="sentiment_distribution",
        value=positive_pct,
        unit="percentage",
        sample_count=total,
        coverage_percent=100.0,
        breakdown={
            "counts": dict(counts),
            "pct": pct,
        },
        computed_at=datetime.now(UTC),
        scope=scope,
    )


__all__ = ["distribution_from_labels"]
