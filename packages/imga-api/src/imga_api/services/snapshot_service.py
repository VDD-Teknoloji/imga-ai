"""Sprint 9.2 C — executive snapshot cache.

The executive briefing pipeline used to recompute every aggregate on
each generation, which on a 10K-row tenant was ~2 seconds of pure
SQL before the LLM call even started. The snapshot service caches
the metric bundle by (tenant_id, snapshot_date, period) so a same-
day re-render reads from one row instead of N aggregations.

Cache cursor: ``last_review_id_at_snapshot`` is the largest
``Review.id`` that contributed to the cached payload. The freshness
check compares it against the tenant's current MAX(id); if the
upstream advanced, the cache is stale and gets recomputed. This
beats a wall-clock TTL because:
  * a same-second re-render after a single batch upload would hit a
    stale TTL but a stale cursor; the cursor wins.
  * an idle tenant with no new reviews never recomputes a TTL'd
    cache it doesn't need; the cursor stays exact.

Invalidation triggers (worker hot paths) call ``invalidate(tenant,
date)`` after a state-changing operation (new batch processed,
manual review status change). The cache then misses on the next
read and recomputes — same behaviour as a stale cursor, just more
explicit.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from imga_db.models import ExecutiveSnapshot, Review
from imga_core.metrics import MetricScope, nps_score_from_buckets
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

_logger = logging.getLogger(__name__)


_PERIOD_DAYS: dict[str, int] = {
    "daily": 1,
    "weekly": 7,
    "monthly": 30,
}


@dataclass(frozen=True, slots=True)
class SnapshotPayload:
    """Wire shape returned to the briefing service. Mirrors the
    ``executive_snapshots.metrics`` JSONB column."""

    tenant_id: UUID
    snapshot_date: date
    period: str
    metrics: dict[str, Any]
    review_count: int
    cursor_review_id: UUID | None
    computed_at: datetime
    computation_duration_ms: int


class SnapshotService:
    """All public methods are session-bound; callers wrap them in
    their own transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_or_compute(
        self,
        *,
        tenant_id: UUID,
        period: str,
        snapshot_date: date | None = None,
    ) -> SnapshotPayload:
        """Read the cached snapshot for the day (or compute if miss /
        stale). Cold compute logs duration_ms; warm fetch reads the
        row directly."""
        if period not in _PERIOD_DAYS:
            raise ValueError(f"unknown period {period!r}")
        target_date = snapshot_date or datetime.now(UTC).date()
        cached = await self._read_existing(tenant_id, target_date, period)
        if cached is not None and not await self._is_stale(tenant_id, cached):
            return self._row_to_payload(cached)
        return await self._compute(tenant_id, target_date, period)

    async def invalidate(
        self,
        *,
        tenant_id: UUID,
        snapshot_date: date | None = None,
    ) -> int:
        """Drop every cached snapshot for the tenant on
        ``snapshot_date`` (default today). Worker hot paths call this
        after batch completion / manual review status change so the
        next briefing render recomputes from fresh data."""
        target_date = snapshot_date or datetime.now(UTC).date()
        result = await self._session.execute(
            select(ExecutiveSnapshot).where(
                ExecutiveSnapshot.tenant_id == tenant_id,
                ExecutiveSnapshot.snapshot_date == target_date,
            )
        )
        rows = list(result.scalars().all())
        for row in rows:
            await self._session.delete(row)
        await self._session.flush()
        return len(rows)

    # ---- internals ----

    async def _read_existing(
        self,
        tenant_id: UUID,
        snapshot_date: date,
        period: str,
    ) -> ExecutiveSnapshot | None:
        stmt = select(ExecutiveSnapshot).where(
            ExecutiveSnapshot.tenant_id == tenant_id,
            ExecutiveSnapshot.snapshot_date == snapshot_date,
            ExecutiveSnapshot.period == period,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def _is_stale(
        self,
        tenant_id: UUID,
        cached: ExecutiveSnapshot,
    ) -> bool:
        """Stale if a Review row newer than the cached cursor exists.
        Empty tenants stay fresh (cursor None, no upstream rows)."""
        stmt = (
            select(Review.id)
            .where(Review.tenant_id == tenant_id)
            .where(Review.deleted_at.is_(None))
            .order_by(Review.created_at.desc())
            .limit(1)
        )
        latest = (await self._session.execute(stmt)).scalar_one_or_none()
        if latest is None:
            return False
        if cached.last_review_id_at_snapshot is None:
            return True
        return latest != cached.last_review_id_at_snapshot

    async def _compute(
        self,
        tenant_id: UUID,
        snapshot_date: date,
        period: str,
    ) -> SnapshotPayload:
        started = time.monotonic()
        days = _PERIOD_DAYS[period]
        date_from = snapshot_date - timedelta(days=days)

        # NPS bucket counts via the same generated column the analytics
        # service reads. Sprint 9.2 routes the math through
        # imga_core.metrics.nps so the canonical formula is in one
        # place.
        bucket_stmt = (
            select(Review.nps_category, func.count().label("cnt"))
            .where(Review.tenant_id == tenant_id)
            .where(Review.deleted_at.is_(None))
            .where(Review.nps_score.is_not(None))
            .where(Review.created_at >= date_from)
            .where(Review.created_at <= snapshot_date)
            .group_by(Review.nps_category)
        )
        per_bucket = {"detractor": 0, "passive": 0, "promoter": 0}
        for row in (await self._session.execute(bucket_stmt)).all():
            if row.nps_category in per_bucket:
                per_bucket[row.nps_category] = row.cnt

        # Total review count + latest review id (cursor) for the
        # tenant, regardless of date — the cursor is "most recent
        # Review the tenant has seen", not "most recent in window".
        total_stmt = (
            select(func.count())
            .select_from(Review)
            .where(Review.tenant_id == tenant_id)
            .where(Review.deleted_at.is_(None))
        )
        total_count = (await self._session.execute(total_stmt)).scalar_one() or 0
        cursor_stmt = (
            select(Review.id)
            .where(Review.tenant_id == tenant_id)
            .where(Review.deleted_at.is_(None))
            .order_by(Review.created_at.desc())
            .limit(1)
        )
        cursor_id: UUID | None = (
            await self._session.execute(cursor_stmt)
        ).scalar_one_or_none()

        scope = MetricScope(
            tenant_id=str(tenant_id),
            date_from=datetime.combine(date_from, datetime.min.time(), tzinfo=UTC),
            date_to=datetime.combine(snapshot_date, datetime.max.time(), tzinfo=UTC),
        )
        nps = nps_score_from_buckets(
            promoter_count=per_bucket["promoter"],
            passive_count=per_bucket["passive"],
            detractor_count=per_bucket["detractor"],
            total_review_count=total_count,
            scope=scope,
        )

        metrics_payload = {
            "nps": nps.to_jsonable(),
            "review_volume": {
                "metric_key": "review_volume",
                "value": float(total_count),
                "unit": "count",
                "sample_count": total_count,
                "coverage_percent": 100.0,
                "computed_at": datetime.now(UTC).isoformat(),
            },
        }

        duration_ms = int((time.monotonic() - started) * 1000)

        # Upsert pattern via existing-row check + delete/insert. The
        # snapshot is keyed (tenant, date, period) UNIQUE, so we
        # delete any prior row before inserting (handles the stale-
        # cursor recompute case cleanly).
        existing = await self._read_existing(tenant_id, snapshot_date, period)
        if existing is not None:
            await self._session.delete(existing)
            await self._session.flush()
        row = ExecutiveSnapshot(
            tenant_id=tenant_id,
            snapshot_date=snapshot_date,
            period=period,
            metrics=metrics_payload,
            review_count_at_snapshot=total_count,
            last_review_id_at_snapshot=cursor_id,
            computed_at=datetime.now(UTC),
            computation_duration_ms=duration_ms,
        )
        self._session.add(row)
        await self._session.flush()
        _logger.info(
            "executive snapshot computed",
            extra={
                "tenant_id": str(tenant_id),
                "snapshot_date": snapshot_date.isoformat(),
                "period": period,
                "duration_ms": duration_ms,
                "review_count": total_count,
            },
        )
        return self._row_to_payload(row)

    @staticmethod
    def _row_to_payload(row: ExecutiveSnapshot) -> SnapshotPayload:
        return SnapshotPayload(
            tenant_id=row.tenant_id,
            snapshot_date=row.snapshot_date,
            period=row.period,
            metrics=dict(row.metrics or {}),
            review_count=row.review_count_at_snapshot,
            cursor_review_id=row.last_review_id_at_snapshot,
            computed_at=row.computed_at,
            computation_duration_ms=row.computation_duration_ms or 0,
        )


__all__ = [
    "SnapshotPayload",
    "SnapshotService",
]
