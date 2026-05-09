"""Sprint 9.3 B — business impact dimension config + analytics.

Every tenant can enable up to four review dimensions
(business_segment / product_line / channel / customer_tier). The
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
from typing import Any
from uuid import UUID

from imga_db.models import Review, TenantBusinessDimension
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

_logger = logging.getLogger(__name__)


_VALID_DIMENSIONS = (
    "business_segment",
    "product_line",
    "channel",
    "customer_tier",
)


_DIMENSION_COLUMNS = {
    "business_segment": Review.business_segment,
    "product_line": Review.product_line,
    "channel": Review.channel,
    "customer_tier": Review.customer_tier,
}


class DimensionError(Exception):
    """Service-layer failure that maps to a 4xx in the route handler."""


class UnknownDimension(DimensionError):
    """``dimension`` arg is not one of the four valid keys."""


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
        if dimension not in _VALID_DIMENSIONS:
            raise UnknownDimension(
                f"unknown dimension {dimension!r}; "
                f"valid={list(_VALID_DIMENSIONS)}"
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
        if dimension not in _VALID_DIMENSIONS:
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
) -> DimensionBreakdown:
    """Compute ``metric_key`` grouped by ``dimension`` value.

    Sprint 9.3 — supported metric_keys (the most-asked-for slice
    of the registry):

      * ``review_volume`` — count(*) per bucket
      * ``sentiment_distribution`` — positive_pct per bucket
      * ``nps`` — score per bucket

    Other metric_keys raise ``DimensionError``; the routes layer
    surfaces them as 400. ``buckets`` is sorted by count desc so the
    dashboard chart shows the dominant segments first.
    """
    if dimension not in _VALID_DIMENSIONS:
        raise UnknownDimension(f"unknown dimension {dimension!r}")
    column = _DIMENSION_COLUMNS[dimension]

    # Total + coverage count once (re-used as denominator for
    # percentage metrics).
    total_stmt = (
        select(func.count())
        .select_from(Review)
        .where(Review.tenant_id == tenant_id)
        .where(Review.deleted_at.is_(None))
    )
    total_count = (
        (await session.execute(total_stmt)).scalar_one() or 0
    )
    coverage_stmt = (
        select(func.count())
        .select_from(Review)
        .where(Review.tenant_id == tenant_id)
        .where(Review.deleted_at.is_(None))
        .where(column.is_not(None))
    )
    coverage_count = (
        (await session.execute(coverage_stmt)).scalar_one() or 0
    )

    if metric_key == "review_volume":
        stmt = (
            select(column.label("bucket"), func.count().label("cnt"))
            .where(Review.tenant_id == tenant_id)
            .where(Review.deleted_at.is_(None))
            .where(column.is_not(None))
            .group_by(column)
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
                column.label("bucket"),
                func.count().label("cnt"),
                func.sum(
                    case((Review.sentiment_label == "POZITIF", 1), else_=0)
                ).label("pos_cnt"),
            )
            .where(Review.tenant_id == tenant_id)
            .where(Review.deleted_at.is_(None))
            .where(column.is_not(None))
            .group_by(column)
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
    elif metric_key == "nps":
        # NPS per bucket from the generated nps_category column.
        stmt = (
            select(
                column.label("bucket"),
                func.count().label("cnt"),
                func.sum(
                    case((Review.nps_category == "promoter", 1), else_=0)
                ).label("promoter"),
                func.sum(
                    case((Review.nps_category == "detractor", 1), else_=0)
                ).label("detractor"),
            )
            .where(Review.tenant_id == tenant_id)
            .where(Review.deleted_at.is_(None))
            .where(column.is_not(None))
            .where(Review.nps_score.is_not(None))
            .group_by(column)
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
            f"supported: review_volume, sentiment_distribution, nps"
        )
    return DimensionBreakdown(
        metric_key=metric_key,
        dimension=dimension,
        buckets=buckets,
        total_count=total_count,
        coverage_count=coverage_count,
    )


__all__ = [
    "DimensionBreakdown",
    "DimensionConfigNotFound",
    "DimensionError",
    "DimensionService",
    "UnknownDimension",
    "compute_metric_by_dimension",
]
