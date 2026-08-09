"""Cohort analysis — aggregate reviews by period × dimension.

Sprint 8.3.9. Pure SQL aggregation against ``reviews`` (the dashboard
cohort tab fires this on every URL-state change, so we lean on
Postgres date_trunc + GROUP BY rather than Python iteration).

Three dimensions:

  * ``taxonomy``           — reviews.primary_category (BERT label)
  * ``company_perspective`` — reviews.company_perspective_code
                              (Sprint 8.3.5.6 heuristic match)
  * ``nps_bucket``         — reviews.nps_category (detractor / passive
                             / promoter), generated column

Three periods: ``week`` / ``month`` / ``quarter`` — passed straight
into ``date_trunc``. ``date_from`` / ``date_to`` filter the inclusive
window; the SQL uses ``created_at`` for the bucket boundary so the
cohort line aligns with the ingest time, not the review's own
``analyzed_at``.

Cache: 1 hour TTL. Key pattern: ``cohort:{tenant}:{period}:
{dimension}:{date_from}:{date_to}:{limit}``.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Literal
from uuid import UUID

from imga_db.models import CategoryTaxonomy, Review
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.services.date_bounds import day_ceil
from imga_api.services.insights_cache import cache_get_or_compute

_logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 3600

CohortPeriod = Literal["week", "month", "quarter"]
CohortDimension = Literal["taxonomy", "company_perspective", "nps_bucket"]

ALLOWED_PERIODS: frozenset[str] = frozenset({"week", "month", "quarter"})
ALLOWED_DIMENSIONS: frozenset[str] = frozenset(
    {"taxonomy", "company_perspective", "nps_bucket"}
)


class CohortAnalyzer:
    """Stateless aggregator. Reads the RLS-bound app session; the
    caller binds the tenant before calling ``aggregate``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def aggregate(
        self,
        *,
        tenant_id: UUID,
        period: CohortPeriod,
        dimension: CohortDimension,
        date_from: date | None = None,
        date_to: date | None = None,
        limit_cohorts: int = 10,
        batch_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Return the cohort payload (cache-aware).

        Top-level keys: ``period`` / ``dimension`` / ``cohorts``.
        Each cohort: ``key`` / ``label`` / ``data_points`` (a list of
        ``{period_start, count, avg_sentiment, avg_nps}``).
        """
        if period not in ALLOWED_PERIODS:
            raise ValueError(f"period must be one of {sorted(ALLOWED_PERIODS)}")
        if dimension not in ALLOWED_DIMENSIONS:
            raise ValueError(
                f"dimension must be one of {sorted(ALLOWED_DIMENSIONS)}"
            )
        if not 1 <= limit_cohorts <= 50:
            raise ValueError("limit_cohorts must be 1..50")

        cache_key = self._cache_key(
            tenant_id, period, dimension, date_from, date_to,
            limit_cohorts, batch_id,
        )

        async def _compute() -> dict[str, Any]:
            try:
                return await self._aggregate(
                    tenant_id=tenant_id,
                    period=period,
                    dimension=dimension,
                    date_from=date_from,
                    date_to=date_to,
                    limit_cohorts=limit_cohorts,
                    batch_id=batch_id,
                )
            except Exception:
                _logger.exception(
                    "cohort_analyzer aggregate failed",
                    extra={
                        "tenant_id": str(tenant_id),
                        "period": period,
                        "dimension": dimension,
                    },
                )
                raise

        return await cache_get_or_compute(
            cache_key,
            ttl_seconds=CACHE_TTL_SECONDS,
            compute=_compute,
            label="cohort",
        )

    async def _aggregate(
        self,
        *,
        tenant_id: UUID,
        period: CohortPeriod,
        dimension: CohortDimension,
        date_from: date | None,
        date_to: date | None,
        limit_cohorts: int,
        batch_id: UUID | None,
    ) -> dict[str, Any]:
        # 1. Resolve the dimension column on Review.
        dim_col = self._dimension_column(dimension)

        # 2. Identify the top-N cohorts by total review count over
        #    the entire window. Without this pre-filter, a
        #    long-tail dimension (e.g. 200 distinct taxonomy codes)
        #    would render an unreadable chart.
        period_expr = func.date_trunc(period, Review.created_at)

        cohort_totals_stmt = (
            select(dim_col.label("key"), func.count().label("cnt"))
            .where(Review.tenant_id == tenant_id)
            .where(Review.deleted_at.is_(None))
            .where(dim_col.is_not(None))
            .group_by(dim_col)
            .order_by(desc("cnt"))
            .limit(limit_cohorts)
        )
        if date_from is not None:
            cohort_totals_stmt = cohort_totals_stmt.where(
                Review.created_at >= date_from
            )
        if date_to is not None:
            # Gun sonu siniri — ciplak date geceyarisina cozulur ve
            # bitis gununu dusurur (bkz. services.date_bounds).
            cohort_totals_stmt = cohort_totals_stmt.where(
                Review.created_at <= day_ceil(date_to)
            )
        if batch_id is not None:
            cohort_totals_stmt = cohort_totals_stmt.where(
                Review.batch_job_id == batch_id
            )
        top_cohorts = (await self._session.execute(cohort_totals_stmt)).all()

        if not top_cohorts:
            return {
                "period": period,
                "dimension": dimension,
                "cohorts": [],
            }

        cohort_keys = [r.key for r in top_cohorts]

        # 3. Per-period aggregation, restricted to the top cohorts.
        per_period_stmt = (
            select(
                period_expr.label("period_start"),
                dim_col.label("key"),
                func.count().label("cnt"),
                func.avg(Review.sentiment_score).label("avg_sentiment"),
                func.avg(Review.nps_score).label("avg_nps"),
            )
            .where(Review.tenant_id == tenant_id)
            .where(Review.deleted_at.is_(None))
            .where(dim_col.in_(cohort_keys))
            .group_by(period_expr, dim_col)
            .order_by(period_expr, dim_col)
        )
        if date_from is not None:
            per_period_stmt = per_period_stmt.where(
                Review.created_at >= date_from
            )
        if date_to is not None:
            per_period_stmt = per_period_stmt.where(
                Review.created_at <= day_ceil(date_to)
            )
        if batch_id is not None:
            per_period_stmt = per_period_stmt.where(
                Review.batch_job_id == batch_id
            )
        rows = (await self._session.execute(per_period_stmt)).all()

        # 4. Resolve cohort labels (Türkçe) when dimension is
        #    company_perspective. Other dimensions surface the raw
        #    code as label.
        labels = await self._resolve_labels(tenant_id, dimension, cohort_keys)

        cohorts: list[dict[str, Any]] = []
        for key in cohort_keys:
            data_points = [
                {
                    "period_start": (
                        r.period_start.date().isoformat()
                        if hasattr(r.period_start, "date")
                        else str(r.period_start)
                    ),
                    "count": int(r.cnt),
                    "avg_sentiment": (
                        round(float(r.avg_sentiment), 3)
                        if r.avg_sentiment is not None
                        else None
                    ),
                    "avg_nps": (
                        round(float(r.avg_nps), 2)
                        if r.avg_nps is not None
                        else None
                    ),
                }
                for r in rows
                if r.key == key
            ]
            cohorts.append(
                {
                    "key": key,
                    "label": labels.get(key, key),
                    "data_points": data_points,
                }
            )

        return {
            "period": period,
            "dimension": dimension,
            "cohorts": cohorts,
        }

    async def _resolve_labels(
        self,
        tenant_id: UUID,
        dimension: CohortDimension,
        keys: list[str],
    ) -> dict[str, str]:
        """For ``company_perspective``, fetch the Türkçe labels from
        category_taxonomies. Other dimensions surface the raw code."""
        if dimension != "company_perspective" or not keys:
            return {}
        stmt = (
            select(CategoryTaxonomy.code, CategoryTaxonomy.label_tr)
            .where(CategoryTaxonomy.tenant_id == tenant_id)
            .where(CategoryTaxonomy.code.in_(keys))
        )
        rows = (await self._session.execute(stmt)).all()
        return {r.code: r.label_tr for r in rows}

    @staticmethod
    def _dimension_column(dimension: CohortDimension) -> Any:
        if dimension == "taxonomy":
            return Review.primary_category
        if dimension == "company_perspective":
            return Review.company_perspective_code
        if dimension == "nps_bucket":
            return Review.nps_category
        raise ValueError(f"unknown dimension {dimension!r}")

    @staticmethod
    def _cache_key(
        tenant_id: UUID,
        period: str,
        dimension: str,
        date_from: date | None,
        date_to: date | None,
        limit_cohorts: int,
        batch_id: UUID | None,
    ) -> str:
        df = date_from.isoformat() if date_from else "all"
        dt = date_to.isoformat() if date_to else "all"
        bid = str(batch_id) if batch_id else "all"
        return (
            f"cohort:{tenant_id}:{period}:{dimension}:"
            f"{df}:{dt}:{limit_cohorts}:{bid}"
        )


__all__ = [
    "ALLOWED_DIMENSIONS",
    "ALLOWED_PERIODS",
    "CACHE_TTL_SECONDS",
    "CohortAnalyzer",
    "CohortDimension",
    "CohortPeriod",
]
