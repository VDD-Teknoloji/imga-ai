"""Sprint 9.2 A — shared dataclasses for metric formulas.

``MetricResult`` is the wire shape every formula returns. It mirrors
the JSON shape the snapshot service persists into
``executive_snapshots.metrics`` and the executive_briefing service
embeds in the LLM prompt context, so the same payload flows from
formula → snapshot → briefing → frontend without re-shaping.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class MetricScope:
    """Filters that produced this metric result. Persisted alongside
    the value so the snapshot reader can tell what slice of the data
    the number describes (\"NPS=65 over last 30 days, Acme tenant,
    no batch filter\")."""

    tenant_id: str | None = None
    batch_id: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "batch_id": self.batch_id,
            "date_from": self.date_from.isoformat() if self.date_from else None,
            "date_to": self.date_to.isoformat() if self.date_to else None,
            **self.extra,
        }


@dataclass(frozen=True, slots=True)
class MetricResult:
    """Pure-formula output. ``value`` is the headline number; ``unit``
    matches the registry's ``unit`` column (score / percentage / count
    / ratio). ``coverage_percent`` is the fraction of the input pool
    that fed the calculation — for NPS this is the share of reviews
    that carried an nps_score, for review_volume it's always 100.

    ``breakdown`` is a metric-specific JSON-able dict (NPS exposes
    promoter/passive/detractor counts; sentiment_distribution exposes
    the per-label percentage). The dashboard reads it for sub-bar
    visualisations; the snapshot serialises it raw.
    """

    metric_key: str
    value: float
    unit: str
    sample_count: int
    coverage_percent: float
    breakdown: dict[str, Any] | None = None
    computed_at: datetime | None = None
    scope: MetricScope | None = None

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "metric_key": self.metric_key,
            "value": self.value,
            "unit": self.unit,
            "sample_count": self.sample_count,
            "coverage_percent": self.coverage_percent,
            "breakdown": self.breakdown,
            "computed_at": (
                self.computed_at.isoformat() if self.computed_at else None
            ),
            "scope": self.scope.to_jsonable() if self.scope else None,
        }
