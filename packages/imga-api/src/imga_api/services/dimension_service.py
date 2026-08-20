"""Sprint 9.3 B — business impact dimension config + analytics.

Every tenant can enable up to six review dimensions
(business_segment / product_line / channel / customer_tier /
entered_by / source — the last two added 2026-08-20, Dalga 3). The
config table tells the CSV uploader which header column maps to
which dimension and gives the dashboard the operator-facing
display label. ``allowed_values`` is an optional enum constraint
the route layer can enforce on top of the schema.

This service owns CRUD + read helpers; the analytics breakdown
helper that the dashboard binds to lives at the bottom of this
file (``compute_metric_by_dimension``) — it stays close to the
config so the metric_key + dimension validation path is in one
place.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from imga_db.models import Review, TenantBusinessDimension
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from imga_api.services.date_bounds import day_ceil, day_floor

_logger = logging.getLogger(__name__)


VALID_DIMENSIONS = (
    "business_segment",
    "product_line",
    "channel",
    "customer_tier",
    "entered_by",
    "source",
)


DIMENSION_COLUMNS = {
    "business_segment": Review.business_segment,
    "product_line": Review.product_line,
    "channel": Review.channel,
    "customer_tier": Review.customer_tier,
    "entered_by": Review.entered_by,
    "source": Review.source,
}


def fold_dimension_key(
    column: InstrumentedAttribute[str | None],
) -> ColumnElement[str | None]:
    """Bucket-folding key for a free-text dimension column.

    Upload sources spell the same value inconsistently across rows
    (``FEDEX`` / ``fedex`` / ``Fedex``); grouping on
    ``lower(trim(column))`` folds every spelling into one bucket.
    Shared by dimension_service, review_list_service (the
    dimension-values filter facet) and cohort_analyzer so the fold
    rule can't drift between the three call sites.
    """
    return func.lower(func.trim(column))


def dimension_value_present(
    column: InstrumentedAttribute[str | None],
) -> ColumnElement[bool]:
    """True when ``column`` carries a real value.

    NULL and an all-whitespace / empty string (after trim) both count
    as "no value" — a blank upload cell must not surface as a literal
    empty-string bucket.
    """
    return column.is_not(None) & (func.trim(column) != "")


class DimensionError(Exception):
    """Service-layer failure that maps to a 4xx in the route handler."""


class UnknownDimension(DimensionError):
    """``dimension`` arg is not one of the six valid keys."""


class DimensionConfigNotFound(DimensionError):
    """The config row doesn't exist in the active tenant scope."""


@dataclass(frozen=True, slots=True)
class DimensionBreakdown:
    """Wire-shape result for ``compute_metric_by_dimension``. The
    dashboard's ``DimensionBreakdown`` chart binds to ``buckets``
    directly; ``coverage_count`` is the share of reviews tagged
    with the dimension at all (vs. NULL)."""

    metric_key: str
    dimension: str
    buckets: list[dict[str, Any]]  # [{value, count, score}]
    total_count: int
    coverage_count: int


class DimensionService:
    """All public methods are session-bound; callers wrap them in
    their own ``async with session.begin():``. Every method
    validates the dimension key against the registry up-front so a
    typo from a route surfaces as a 400 before the round-trip."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def configure(
        self,
        *,
        tenant_id: UUID,
        dimension: str,
        display_label: str,
        enabled: bool = True,
        allowed_values: list[str] | None = None,
        csv_column_mapping: str | None = None,
    ) -> TenantBusinessDimension:
        """Upsert a dimension config row. The unique constraint on
        (tenant_id, dimension) makes this naturally idempotent —
        same key twice updates rather than inserts."""
        if dimension not in VALID_DIMENSIONS:
            raise UnknownDimension(
                f"unknown dimension {dimension!r}; "
                f"valid={list(VALID_DIMENSIONS)}"
            )
        existing = (
            await self._session.execute(
                select(TenantBusinessDimension).where(
                    TenantBusinessDimension.tenant_id == tenant_id,
                    TenantBusinessDimension.dimension == dimension,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing.display_label = display_label
            existing.enabled = enabled
            existing.allowed_values = list(allowed_values or [])
            existing.csv_column_mapping = csv_column_mapping
            await self._session.flush()
            return existing
        row = TenantBusinessDimension(
            tenant_id=tenant_id,
            dimension=dimension,
            display_label=display_label,
            enabled=enabled,
            allowed_values=list(allowed_values or []),
            csv_column_mapping=csv_column_mapping,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def list_for_tenant(
        self, *, tenant_id: UUID, enabled_only: bool = False
    ) -> list[TenantBusinessDimension]:
        stmt = select(TenantBusinessDimension).where(
            TenantBusinessDimension.tenant_id == tenant_id
        )
        if enabled_only:
            stmt = stmt.where(TenantBusinessDimension.enabled.is_(True))
        return list((await self._session.execute(stmt)).scalars().all())

    async def delete(
        self, *, tenant_id: UUID, dimension: str
    ) -> None:
        if dimension not in VALID_DIMENSIONS:
            raise UnknownDimension(
                f"unknown dimension {dimension!r}"
            )
        row = (
            await self._session.execute(
                select(TenantBusinessDimension).where(
                    TenantBusinessDimension.tenant_id == tenant_id,
                    TenantBusinessDimension.dimension == dimension,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise DimensionConfigNotFound(
                f"no config for {dimension} in tenant {tenant_id}"
            )
        await self._session.delete(row)
        await self._session.flush()

    async def csv_column_map(
        self, *, tenant_id: UUID
    ) -> dict[str, str]:
        """Return ``{csv_header: dimension_key}`` for the tenant's
        enabled dimensions. The batch worker reads this and looks up
        each row's value at upload time."""
        rows = await self.list_for_tenant(
            tenant_id=tenant_id, enabled_only=True
        )
        return {
            r.csv_column_mapping: r.dimension
            for r in rows
            if r.csv_column_mapping
        }


# ---------------------------------------------------------------------
# Analytics breakdown helper
# ---------------------------------------------------------------------
#
# This sits in the dimension service rather than analytics_service
# so the dimension-key validation + RLS-bound query are colocated.
# Callers (dashboard, insights, strategy) hit it via the route at
# /tenants/me/dimensions/{dimension}/breakdown?metric_key=nps.


async def compute_metric_by_dimension(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    dimension: str,
    metric_key: str,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    include_flagged: bool = False,
) -> DimensionBreakdown:
    """Compute ``metric_key`` grouped by ``dimension`` value.

    Sprint 9.3 / Dalga 3 — supported metric_keys:

      * ``review_volume`` — count(*) per bucket
      * ``sentiment_distribution`` — positive_pct per bucket
      * ``nps`` — score per bucket
      * ``negative_share`` — NEGATIF payı (%) per bucket
      * ``avg_sentiment`` — ortalama sentiment_score per bucket

    Other metric_keys raise ``DimensionError``; the routes layer
    surfaces them as 400. ``buckets`` is sorted by count desc so the
    dashboard chart shows the dominant segments first.

    Buckets fold on ``lower(trim(column))`` (``fold_dimension_key``) so
    "FEDEX" and "fedex" land in one bucket; the bucket's ``value`` is
    the most-frequent raw spelling within the fold (Postgres
    ``mode() WITHIN GROUP``), not the folded key itself.

    ``date_from``/``date_to`` accept a full datetime (not just a bare
    date) but always widen to whole-day bounds via the day_floor/
    day_ceil pattern (date_bounds.py) — ``datetime`` is a ``date``
    subtype so this works directly; the effect is that a supplied
    time-of-day is ignored and the end day is always fully included.
    ``include_flagged`` defaults to False, matching the
    quality_flag-excludes-by-default convention every other
    analytics/insights endpoint in this codebase uses.
    """
    if dimension not in VALID_DIMENSIONS:
        raise UnknownDimension(f"unknown dimension {dimension!r}")
    column = DIMENSION_COLUMNS[dimension]
    folded = fold_dimension_key(column)
    value_label = func.mode().within_group(func.trim(column)).label("bucket")

    base_conditions: list[ColumnElement[bool]] = [
        Review.tenant_id == tenant_id,
        Review.deleted_at.is_(None),
    ]
    if date_from is not None:
        base_conditions.append(Review.review_date >= day_floor(date_from))
    if date_to is not None:
        base_conditions.append(Review.review_date <= day_ceil(date_to))
    if not include_flagged:
        base_conditions.append(Review.quality_flag.is_(None))

    # Total + coverage count once (re-used as denominator for
    # percentage metrics).
    total_stmt = (
        select(func.count()).select_from(Review).where(*base_conditions)
    )
    total_count = (
        (await session.execute(total_stmt)).scalar_one() or 0
    )
    coverage_stmt = (
        select(func.count())
        .select_from(Review)
        .where(*base_conditions, dimension_value_present(column))
    )
    coverage_count = (
        (await session.execute(coverage_stmt)).scalar_one() or 0
    )

    if metric_key == "review_volume":
        stmt = (
            select(value_label, func.count().label("cnt"))
            .where(*base_conditions, dimension_value_present(column))
            .group_by(folded)
            .order_by(func.count().desc())
        )
        rows = (await session.execute(stmt)).all()
        buckets = [
            {
                "value": r.bucket,
                "count": int(r.cnt),
                "score": int(r.cnt),
            }
            for r in rows
        ]
    elif metric_key == "sentiment_distribution":
        # Positive percentage per bucket.
        stmt = (
            select(
                value_label,
                func.count().label("cnt"),
                func.sum(
                    case((Review.sentiment_label == "POZITIF", 1), else_=0)
                ).label("pos_cnt"),
            )
            .where(*base_conditions, dimension_value_present(column))
            .group_by(folded)
            .order_by(func.count().desc())
        )
        rows = (await session.execute(stmt)).all()
        buckets = []
        for r in rows:
            cnt = int(r.cnt or 0)
            pos = int(r.pos_cnt or 0)
            pct = round((pos / cnt) * 100.0, 2) if cnt else 0.0
            buckets.append(
                {
                    "value": r.bucket,
                    "count": cnt,
                    "score": pct,
                }
            )
    elif metric_key == "negative_share":
        # Negative percentage per bucket — mirror of
        # sentiment_distribution's positive_pct, for risk-ranked
        # dimension views (worst channel/segment first).
        stmt = (
            select(
                value_label,
                func.count().label("cnt"),
                func.sum(
                    case((Review.sentiment_label == "NEGATIF", 1), else_=0)
                ).label("neg_cnt"),
            )
            .where(*base_conditions, dimension_value_present(column))
            .group_by(folded)
            .order_by(func.count().desc())
        )
        rows = (await session.execute(stmt)).all()
        buckets = []
        for r in rows:
            cnt = int(r.cnt or 0)
            neg = int(r.neg_cnt or 0)
            pct = round((neg / cnt) * 100.0, 2) if cnt else 0.0
            buckets.append(
                {
                    "value": r.bucket,
                    "count": cnt,
                    "score": pct,
                }
            )
    elif metric_key == "avg_sentiment":
        stmt = (
            select(
                value_label,
                func.count().label("cnt"),
                func.avg(Review.sentiment_score).label("avg_sent"),
            )
            .where(*base_conditions, dimension_value_present(column))
            .group_by(folded)
            .order_by(func.count().desc())
        )
        rows = (await session.execute(stmt)).all()
        buckets = []
        for r in rows:
            cnt = int(r.cnt or 0)
            avg_sent = (
                round(float(r.avg_sent), 3) if r.avg_sent is not None else 0.0
            )
            buckets.append(
                {
                    "value": r.bucket,
                    "count": cnt,
                    "score": avg_sent,
                }
            )
    elif metric_key == "nps":
        # NPS per bucket from the generated nps_category column.
        stmt = (
            select(
                value_label,
                func.count().label("cnt"),
                func.sum(
                    case((Review.nps_category == "promoter", 1), else_=0)
                ).label("promoter"),
                func.sum(
                    case((Review.nps_category == "detractor", 1), else_=0)
                ).label("detractor"),
            )
            .where(
                *base_conditions,
                dimension_value_present(column),
                Review.nps_score.is_not(None),
            )
            .group_by(folded)
            .order_by(func.count().desc())
        )
        rows = (await session.execute(stmt)).all()
        buckets = []
        for r in rows:
            cnt = int(r.cnt or 0)
            promoter = int(r.promoter or 0)
            detractor = int(r.detractor or 0)
            score = (
                round(((promoter - detractor) / cnt) * 100.0, 2) if cnt else 0.0
            )
            buckets.append(
                {
                    "value": r.bucket,
                    "count": cnt,
                    "score": score,
                }
            )
    else:
        raise DimensionError(
            f"metric_key {metric_key!r} not supported by dimension breakdown; "
            f"supported: review_volume, sentiment_distribution, nps, "
            f"negative_share, avg_sentiment"
        )
    return DimensionBreakdown(
        metric_key=metric_key,
        dimension=dimension,
        buckets=buckets,
        total_count=total_count,
        coverage_count=coverage_count,
    )


__all__ = [
    "DIMENSION_COLUMNS",
    "VALID_DIMENSIONS",
    "DimensionBreakdown",
    "DimensionConfigNotFound",
    "DimensionError",
    "DimensionService",
    "UnknownDimension",
    "compute_metric_by_dimension",
    "dimension_value_present",
    "fold_dimension_key",
]
