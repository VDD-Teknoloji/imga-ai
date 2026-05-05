"""Heatmap aggregation — 2D matrix of count / avg_sentiment / avg_nps.

Sprint 8.3.9. Pure SQL aggregation against ``reviews``. The route
caller picks an x_axis + y_axis pair (``hour_of_day`` /
``day_of_week`` / ``week_of_year`` / ``month`` / ``taxonomy_code``)
and a metric (``count`` / ``avg_sentiment`` / ``avg_nps``); the
generator returns a dense 2D matrix with Türkçe labels for the
calendar dimensions so the frontend renders ready-to-paint cells
without locale work.

Cache: 1 hour TTL.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal
from uuid import UUID

from imga_db.models import CategoryTaxonomy, Review
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.services.insights_cache import cache_get_or_compute


@dataclass(frozen=True)
class _AxisResolution:
    """Internal: ordered raw values + their human-friendly labels."""

    raw_values: list[Any]
    labels: list[str]

_logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 3600

HeatmapAxis = Literal[
    "hour_of_day", "day_of_week", "week_of_year", "month", "taxonomy_code"
]
HeatmapMetric = Literal["count", "avg_sentiment", "avg_nps"]

ALLOWED_X_AXES: frozenset[str] = frozenset(
    {"hour_of_day", "day_of_week", "week_of_year"}
)
ALLOWED_Y_AXES: frozenset[str] = frozenset(
    {"day_of_week", "month", "taxonomy_code"}
)
ALLOWED_METRICS: frozenset[str] = frozenset(
    {"count", "avg_sentiment", "avg_nps"}
)

# Türkçe label tables — server-side render so the frontend stays
# locale-agnostic. Postgres ``EXTRACT(DOW)`` numbers Sunday=0; we
# remap to Monday=0 / Sunday=6 so labels read left-to-right.
_DOW_LABELS_TR: tuple[str, ...] = (
    "Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma",
    "Cumartesi", "Pazar",
)
_MONTH_LABELS_TR: tuple[str, ...] = (
    "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
)

_METRIC_LABELS_TR: dict[str, str] = {
    "count": "Yorum Sayısı",
    "avg_sentiment": "Ortalama Duygu",
    "avg_nps": "Ortalama NPS",
}


class HeatmapGenerator:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def generate(
        self,
        *,
        tenant_id: UUID,
        x_axis: HeatmapAxis,
        y_axis: HeatmapAxis,
        metric: HeatmapMetric,
        date_from: date | None = None,
        date_to: date | None = None,
        taxonomy_top_n: int = 12,
    ) -> dict[str, Any]:
        """Return the heatmap payload (cache-aware).

        ``taxonomy_top_n`` caps the y-axis row count when y_axis is
        ``taxonomy_code`` — without it a tenant with 200 distinct
        codes would render an unreadable wall. Other axes have
        bounded cardinality (24 hours, 7 days, 12 months, 53 weeks).
        """
        if x_axis not in ALLOWED_X_AXES:
            raise ValueError(
                f"x_axis must be one of {sorted(ALLOWED_X_AXES)}"
            )
        if y_axis not in ALLOWED_Y_AXES:
            raise ValueError(
                f"y_axis must be one of {sorted(ALLOWED_Y_AXES)}"
            )
        if x_axis == y_axis:
            raise ValueError("x_axis and y_axis must differ")
        if metric not in ALLOWED_METRICS:
            raise ValueError(
                f"metric must be one of {sorted(ALLOWED_METRICS)}"
            )

        cache_key = self._cache_key(
            tenant_id, x_axis, y_axis, metric,
            date_from, date_to, taxonomy_top_n,
        )

        async def _compute() -> dict[str, Any]:
            try:
                return await self._compute(
                    tenant_id=tenant_id,
                    x_axis=x_axis,
                    y_axis=y_axis,
                    metric=metric,
                    date_from=date_from,
                    date_to=date_to,
                    taxonomy_top_n=taxonomy_top_n,
                )
            except Exception:
                _logger.exception(
                    "heatmap_generator failed",
                    extra={
                        "tenant_id": str(tenant_id),
                        "x_axis": x_axis,
                        "y_axis": y_axis,
                        "metric": metric,
                    },
                )
                raise

        return await cache_get_or_compute(
            cache_key,
            ttl_seconds=CACHE_TTL_SECONDS,
            compute=_compute,
            label="heatmap",
        )

    async def _compute(
        self,
        *,
        tenant_id: UUID,
        x_axis: HeatmapAxis,
        y_axis: HeatmapAxis,
        metric: HeatmapMetric,
        date_from: date | None,
        date_to: date | None,
        taxonomy_top_n: int,
    ) -> dict[str, Any]:
        x_expr, x_resolver = self._axis_expr(x_axis)
        y_expr, y_resolver = self._axis_expr(y_axis)
        metric_expr = self._metric_expr(metric)

        stmt = (
            select(
                x_expr.label("x"),
                y_expr.label("y"),
                metric_expr.label("v"),
            )
            .where(Review.tenant_id == tenant_id)
            .where(Review.deleted_at.is_(None))
            .group_by("x", "y")
        )
        if date_from is not None:
            stmt = stmt.where(Review.created_at >= date_from)
        if date_to is not None:
            stmt = stmt.where(Review.created_at <= date_to)
        # NPS metric ignores rows where nps_score is NULL — without
        # this, the AVG produces NULL cells we'd then have to filter
        # client-side.
        if metric == "avg_nps":
            stmt = stmt.where(Review.nps_score.is_not(None))

        rows = (await self._session.execute(stmt)).all()

        # Resolve axis labels + raw → display index mapping.
        x_resolved = await self._resolve_axis_labels(
            x_axis, [r.x for r in rows], tenant_id, taxonomy_top_n,
            x_resolver,
        )
        y_resolved = await self._resolve_axis_labels(
            y_axis, [r.y for r in rows], tenant_id, taxonomy_top_n,
            y_resolver,
        )

        # Build the dense matrix.
        x_index = {raw: i for i, raw in enumerate(x_resolved.raw_values)}
        y_index = {raw: i for i, raw in enumerate(y_resolved.raw_values)}
        rows_count = len(y_resolved.raw_values)
        cols_count = len(x_resolved.raw_values)

        values: list[list[float | None]] = [
            [None for _ in range(cols_count)] for _ in range(rows_count)
        ]
        for r in rows:
            xi = x_index.get(r.x)
            yi = y_index.get(r.y)
            if xi is None or yi is None:
                continue
            values[yi][xi] = (
                round(float(r.v), 3) if r.v is not None else None
            )

        # Replace None with 0 only for ``count`` (sum-style metric);
        # avg metrics keep None so the frontend can render an empty
        # cell visually instead of a misleading 0.
        if metric == "count":
            values = [
                [(v if v is not None else 0) for v in row]
                for row in values
            ]

        # min/max from non-None values.
        flat = [
            v
            for row in values
            for v in row
            if v is not None
        ]
        metric_min = min(flat) if flat else 0
        metric_max = max(flat) if flat else 0

        return {
            "x_axis": x_axis,
            "y_axis": y_axis,
            "metric": metric,
            "metric_label": _METRIC_LABELS_TR[metric],
            "x_labels": x_resolved.labels,
            "y_labels": y_resolved.labels,
            "values": values,
            "metric_min": (
                round(float(metric_min), 3)
                if isinstance(metric_min, float)
                else metric_min
            ),
            "metric_max": (
                round(float(metric_max), 3)
                if isinstance(metric_max, float)
                else metric_max
            ),
        }

    @staticmethod
    def _axis_expr(axis: HeatmapAxis) -> tuple[Any, str]:
        """Return ``(SQL expression, resolver_kind)``. ``resolver_kind``
        tells _resolve_axis_labels which label table to use."""
        if axis == "hour_of_day":
            return func.extract("hour", Review.created_at), "hour"
        if axis == "day_of_week":
            return func.extract("dow", Review.created_at), "dow"
        if axis == "week_of_year":
            return func.extract("week", Review.created_at), "week"
        if axis == "month":
            return func.extract("month", Review.created_at), "month"
        if axis == "taxonomy_code":
            return Review.primary_category, "taxonomy"
        raise ValueError(f"unknown axis {axis!r}")

    @staticmethod
    def _metric_expr(metric: HeatmapMetric) -> Any:
        if metric == "count":
            return func.count()
        if metric == "avg_sentiment":
            return func.avg(Review.sentiment_score)
        if metric == "avg_nps":
            return func.avg(Review.nps_score)
        raise ValueError(f"unknown metric {metric!r}")

    async def _resolve_axis_labels(
        self,
        axis: HeatmapAxis,
        raw_values_seen: list[Any],
        tenant_id: UUID,
        taxonomy_top_n: int,
        resolver_kind: str,
    ) -> _AxisResolution:
        """Map raw axis values → ordered (raw, display) pairs.

        For calendar dimensions we always render the full axis (24
        hours / 7 days / 12 months / 53 weeks) even if some values
        had no rows; the frontend wants empty cells, not gaps. For
        taxonomy_code we restrict to the top-N codes by appearance.
        """
        del axis  # resolver_kind already encodes this
        if resolver_kind == "hour":
            return _AxisResolution(
                raw_values=[float(h) for h in range(24)],
                labels=[f"{h:02d}:00" for h in range(24)],
            )
        if resolver_kind == "dow":
            # Postgres EXTRACT(DOW): 0=Sunday..6=Saturday. We
            # remap to Monday=0..Sunday=6 for display order.
            return _AxisResolution(
                raw_values=[1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 0.0],
                labels=list(_DOW_LABELS_TR),
            )
        if resolver_kind == "month":
            return _AxisResolution(
                raw_values=[float(m) for m in range(1, 13)],
                labels=list(_MONTH_LABELS_TR),
            )
        if resolver_kind == "week":
            seen = sorted({int(v) for v in raw_values_seen if v is not None})
            return _AxisResolution(
                raw_values=[float(w) for w in seen],
                labels=[f"H{w}" for w in seen],
            )
        if resolver_kind == "taxonomy":
            # Take the top-N most-seen codes; resolve labels from
            # category_taxonomies. Order by count desc so the heatmap
            # reads top-to-bottom.
            counts = Counter(v for v in raw_values_seen if v is not None)
            top = [code for code, _ in counts.most_common(taxonomy_top_n)]
            label_stmt = (
                select(CategoryTaxonomy.code, CategoryTaxonomy.label_tr)
                .where(CategoryTaxonomy.tenant_id == tenant_id)
                .where(CategoryTaxonomy.code.in_(top))
            )
            label_rows = (await self._session.execute(label_stmt)).all()
            label_by_code = {r.code: r.label_tr for r in label_rows}
            return _AxisResolution(
                raw_values=list(top),
                labels=[label_by_code.get(c, c) for c in top],
            )
        raise ValueError(f"unknown resolver_kind {resolver_kind!r}")

    @staticmethod
    def _cache_key(
        tenant_id: UUID,
        x_axis: str,
        y_axis: str,
        metric: str,
        date_from: date | None,
        date_to: date | None,
        taxonomy_top_n: int,
    ) -> str:
        df = date_from.isoformat() if date_from else "all"
        dt = date_to.isoformat() if date_to else "all"
        return (
            f"heatmap:{tenant_id}:{x_axis}:{y_axis}:{metric}:"
            f"{df}:{dt}:{taxonomy_top_n}"
        )


__all__ = [
    "ALLOWED_METRICS",
    "ALLOWED_X_AXES",
    "ALLOWED_Y_AXES",
    "CACHE_TTL_SECONDS",
    "HeatmapAxis",
    "HeatmapGenerator",
    "HeatmapMetric",
]
