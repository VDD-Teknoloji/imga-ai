"""AnalyticsService — read-only aggregations for the /insights page.

Sprint 8.3.3. Seven endpoints all sit under /tenants/me/analytics/* and
all run on the RLS-bound app session, so tenant isolation is implicit
(no manual ``WHERE tenant_id = :t`` needed inside the policy-protected
queries — the policy adds it). Every method returns a frozen dataclass
so the route layer can project to its Pydantic shape without leaking
SQLAlchemy types upstream.

Filter envelope is shared (``AnalyticsFilters``) — 95% of consumers
want at least date_from/date_to + source_types. Per-endpoint extras
(granularity, top_n, limit) live as method kwargs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from imga_db.models import Category, Review, Ticket, TicketState
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

Granularity = Literal["day", "week", "month"]


@dataclass(frozen=True, slots=True)
class AnalyticsFilters:
    """Common filter envelope. Endpoints that don't accept some fields
    just ignore them (e.g. sentiment_labels has no meaning for
    /ticket-resolution-time)."""

    date_from: datetime | None = None
    date_to: datetime | None = None
    sentiment_labels: tuple[str, ...] = ()
    category_ids: tuple[UUID, ...] = ()
    source_types: tuple[str, ...] = ()  # "manual" | "batch"
    batch_job_id: UUID | None = None


# --- response shapes (frozen, route projects to Pydantic) ---------------


@dataclass(frozen=True, slots=True)
class SentimentDistRow:
    label: str
    count: int
    percentage: float
    avg_score: float


@dataclass(frozen=True, slots=True)
class SentimentDist:
    total: int
    data: list[SentimentDistRow] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class CategoryDistRow:
    category: str
    category_label_tr: str
    count: int
    percentage: float


@dataclass(frozen=True, slots=True)
class CategoryDist:
    total: int
    data: list[CategoryDistRow] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class SentimentByCategory:
    categories: list[str] = field(default_factory=list)
    category_labels_tr: list[str] = field(default_factory=list)
    sentiments: list[str] = field(default_factory=list)
    matrix: list[list[int]] = field(default_factory=list)
    totals_by_category: list[int] = field(default_factory=list)
    totals_by_sentiment: list[int] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class OverrideStatsRow:
    layer: str
    layer_label_tr: str
    trigger_count: int
    trigger_percentage: float
    direction: str  # "boost" | "dampen" | "mixed" | "none"
    avg_impact: float
    max_impact: float


@dataclass(frozen=True, slots=True)
class OverrideStats:
    total_reviews: int
    data: list[OverrideStatsRow] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class TimelinePoint:
    date: str  # ISO date for day, "YYYY-Www" for week, "YYYY-MM" for month
    negatif: int
    nötr: int
    pozitif: int
    total: int
    avg_score: float


@dataclass(frozen=True, slots=True)
class SentimentTimeline:
    granularity: Granularity
    data: list[TimelinePoint] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ResolutionBucket:
    bucket: str
    count: int


@dataclass(frozen=True, slots=True)
class ResolutionByCategory:
    category: str
    avg_hours: float
    count: int


@dataclass(frozen=True, slots=True)
class TicketResolution:
    total_resolved_tickets: int
    avg_resolution_hours: float
    median_resolution_hours: float
    p95_resolution_hours: float
    distribution: list[ResolutionBucket] = field(default_factory=list)
    by_category: list[ResolutionByCategory] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class SensitivityBucket:
    range_start: float
    range_end: float
    count: int


@dataclass(frozen=True, slots=True)
class SensitivityStats:
    mean: float
    median: float
    std_dev: float


@dataclass(frozen=True, slots=True)
class SensitivityDistribution:
    total: int
    buckets: list[SensitivityBucket] = field(default_factory=list)
    stats: SensitivityStats = SensitivityStats(0.0, 0.0, 0.0)


# --- override layer Türkçe labels (Sprint 8.3 spec) ---------------------


_OVERRIDE_LABEL_TR: dict[str, str] = {
    "knowledge_base": "Bilgi Tabanı Kuralı",
    "critical": "Kritik Anahtar Kelime",
    "tier1": "Güçlü Negatif Sıfat",
    "sla": "SLA Tetikleyicisi",
    "tier2": "İkincil Tetikleyici",
}


# --- service ------------------------------------------------------------


class AnalyticsService:
    """Lives on the RLS-bound app session so tenant isolation is
    automatic via the row-level policies. Routes pass ``tenant_id`` for
    explicit equality where the planner can use indexes (the policy is
    a redundant belt-and-braces — both must agree)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # 1. Sentiment distribution
    # ------------------------------------------------------------------

    async def sentiment_distribution(
        self,
        *,
        tenant_id: UUID,
        filters: AnalyticsFilters,
    ) -> SentimentDist:
        stmt = (
            select(
                Review.sentiment_label,
                func.count().label("cnt"),
                func.avg(Review.sentiment_score).label("avg_score"),
            )
            .where(Review.tenant_id == tenant_id)
            .where(Review.deleted_at.is_(None))
            .group_by(Review.sentiment_label)
        )
        stmt = self._apply_review_filters(stmt, filters)
        rows = (await self._session.execute(stmt)).all()
        total = sum(r.cnt for r in rows)

        # Stable order: NEGATIF / NÖTR / POZITIF.
        order = {"NEGATIF": 0, "NÖTR": 1, "POZITIF": 2}
        rows_sorted = sorted(rows, key=lambda r: order.get(r.sentiment_label, 9))
        data = [
            SentimentDistRow(
                label=r.sentiment_label,
                count=r.cnt,
                percentage=round(100 * r.cnt / total, 2) if total else 0.0,
                avg_score=round(float(r.avg_score), 3) if r.avg_score is not None else 0.0,
            )
            for r in rows_sorted
        ]
        return SentimentDist(total=total, data=data)

    # ------------------------------------------------------------------
    # 2. Category distribution
    # ------------------------------------------------------------------

    async def category_distribution(
        self,
        *,
        tenant_id: UUID,
        filters: AnalyticsFilters,
        limit: int = 10,
    ) -> CategoryDist:
        # LEFT JOIN categories so codes that lack a label still appear.
        stmt = (
            select(
                Review.primary_category.label("code"),
                Category.label_tr.label("label_tr"),
                func.count().label("cnt"),
            )
            .select_from(Review)
            .outerjoin(Category, Category.code == Review.primary_category)
            .where(Review.tenant_id == tenant_id)
            .where(Review.deleted_at.is_(None))
            .group_by(Review.primary_category, Category.label_tr)
            .order_by(func.count().desc())
            .limit(limit)
        )
        stmt = self._apply_review_filters(stmt, filters)
        rows = (await self._session.execute(stmt)).all()

        # Total includes ALL reviews matching filters (not just top-N).
        total_stmt = (
            select(func.count())
            .select_from(Review)
            .where(Review.tenant_id == tenant_id)
            .where(Review.deleted_at.is_(None))
        )
        total_stmt = self._apply_review_filters(total_stmt, filters)
        total = (await self._session.execute(total_stmt)).scalar_one()

        data = [
            CategoryDistRow(
                category=r.code,
                category_label_tr=r.label_tr or r.code,
                count=r.cnt,
                percentage=round(100 * r.cnt / total, 2) if total else 0.0,
            )
            for r in rows
        ]
        return CategoryDist(total=total, data=data)

    # ------------------------------------------------------------------
    # 3. Sentiment-by-category heatmap
    # ------------------------------------------------------------------

    async def sentiment_by_category(
        self,
        *,
        tenant_id: UUID,
        filters: AnalyticsFilters,
        top_n_categories: int = 10,
    ) -> SentimentByCategory:
        # First pull the top N categories by total count.
        cat_stmt = (
            select(Review.primary_category, func.count().label("cnt"))
            .where(Review.tenant_id == tenant_id)
            .where(Review.deleted_at.is_(None))
            .group_by(Review.primary_category)
            .order_by(func.count().desc())
            .limit(top_n_categories)
        )
        cat_stmt = self._apply_review_filters(cat_stmt, filters)
        cat_rows = (await self._session.execute(cat_stmt)).all()
        if not cat_rows:
            return SentimentByCategory(sentiments=["NEGATIF", "NÖTR", "POZITIF"])
        top_codes = [r.primary_category for r in cat_rows]

        # Pull per-category-per-sentiment counts in one query.
        matrix_stmt = (
            select(
                Review.primary_category,
                Review.sentiment_label,
                func.count().label("cnt"),
            )
            .where(Review.tenant_id == tenant_id)
            .where(Review.deleted_at.is_(None))
            .where(Review.primary_category.in_(top_codes))
            .group_by(Review.primary_category, Review.sentiment_label)
        )
        matrix_stmt = self._apply_review_filters(matrix_stmt, filters)
        breakdown = (await self._session.execute(matrix_stmt)).all()

        # Resolve label_tr for the top categories.
        label_stmt = (
            select(Category.code, Category.label_tr)
            .where(Category.code.in_(top_codes))
            .where(Category.deleted_at.is_(None))
        )
        label_rows = (await self._session.execute(label_stmt)).all()
        label_map: dict[str, str] = {row[0]: row[1] for row in label_rows}

        sentiments = ["NEGATIF", "NÖTR", "POZITIF"]
        matrix: list[list[int]] = [[0, 0, 0] for _ in top_codes]
        cat_index = {code: i for i, code in enumerate(top_codes)}
        sent_index = {label: i for i, label in enumerate(sentiments)}
        for row in breakdown:
            i = cat_index.get(row.primary_category)
            j = sent_index.get(row.sentiment_label)
            if i is not None and j is not None:
                matrix[i][j] = row.cnt

        totals_by_category = [sum(row) for row in matrix]
        totals_by_sentiment = [sum(matrix[i][j] for i in range(len(matrix))) for j in range(3)]

        return SentimentByCategory(
            categories=top_codes,
            category_labels_tr=[label_map.get(c, c) for c in top_codes],
            sentiments=sentiments,
            matrix=matrix,
            totals_by_category=totals_by_category,
            totals_by_sentiment=totals_by_sentiment,
        )

    # ------------------------------------------------------------------
    # 4. Override stats — reads Review.overrides_applied JSONB (Sprint 8.3.4 fills it)
    # ------------------------------------------------------------------

    async def override_stats(
        self,
        *,
        tenant_id: UUID,
        filters: AnalyticsFilters,
    ) -> OverrideStats:
        """Group ``reviews.overrides_applied`` JSONB array by layer.

        Sprint 8.3.4 — replaces the 8.3.3 zero-count placeholder. We
        pull the JSONB column verbatim and aggregate in Python instead
        of unnesting in SQL: nested SRF expressions
        (``jsonb_array_elements`` inside ``jsonb_extract_path_text``)
        trip Postgres' planner on rows where the column is NULL,
        raising ``InvalidParameterValueError: cannot extract elements
        from a scalar`` even when a redundant ``IS NOT NULL`` filter
        precedes them. The dataset is already tenant-bounded by RLS,
        so the round trip cost is bounded by tenant size; aggregating
        in Python keeps the query trivial and the NULL semantics
        explicit.

        Layers that never fire still surface with zero counts so the
        UI's 5-row table doesn't shift around as data accumulates.
        """
        # Total review count drives the trigger_percentage denominator.
        total_stmt = (
            select(func.count())
            .select_from(Review)
            .where(Review.tenant_id == tenant_id)
            .where(Review.deleted_at.is_(None))
        )
        total_stmt = self._apply_review_filters(total_stmt, filters)
        total_reviews = (await self._session.execute(total_stmt)).scalar_one()

        # Pull the JSONB column for every matching review. NULL rows
        # (predating migration 0014) and empty arrays both contribute
        # zero hits below — no SRF acrobatics needed.
        col_stmt = (
            select(Review.overrides_applied)
            .where(Review.tenant_id == tenant_id)
            .where(Review.deleted_at.is_(None))
            .where(Review.overrides_applied.is_not(None))
        )
        col_stmt = self._apply_review_filters(col_stmt, filters)
        arrays = (await self._session.execute(col_stmt)).scalars().all()

        # Bucket per known layer. Forward-compat: any unexpected layer
        # code is silently dropped rather than crashing the dashboard.
        per_layer: dict[str, list[float]] = {code: [] for code in _OVERRIDE_LABEL_TR}
        for arr in arrays:
            if not isinstance(arr, list):
                continue
            for hit in arr:
                if not isinstance(hit, dict):
                    continue
                layer = hit.get("layer")
                score = hit.get("score")
                if (
                    isinstance(layer, str)
                    and layer in per_layer
                    and isinstance(score, (int, float))
                ):
                    per_layer[layer].append(float(score))

        data = []
        for code, scores in per_layer.items():
            count = len(scores)
            if count == 0:
                data.append(
                    OverrideStatsRow(
                        layer=code,
                        layer_label_tr=_OVERRIDE_LABEL_TR[code],
                        trigger_count=0,
                        trigger_percentage=0.0,
                        direction="none",
                        avg_impact=0.0,
                        max_impact=0.0,
                    )
                )
                continue
            avg_impact = sum(abs(s) for s in scores) / count
            max_impact = max(abs(s) for s in scores)
            positives = sum(1 for s in scores if s > 0)
            negatives = sum(1 for s in scores if s < 0)
            if positives > 0 and negatives == 0:
                direction = "boost"
            elif negatives > 0 and positives == 0:
                direction = "dampen"
            else:
                direction = "mixed"
            data.append(
                OverrideStatsRow(
                    layer=code,
                    layer_label_tr=_OVERRIDE_LABEL_TR[code],
                    trigger_count=count,
                    trigger_percentage=round(100 * count / total_reviews, 2)
                    if total_reviews
                    else 0.0,
                    direction=direction,
                    avg_impact=round(avg_impact, 3),
                    max_impact=round(max_impact, 3),
                )
            )

        return OverrideStats(total_reviews=total_reviews, data=data)

    # ------------------------------------------------------------------
    # 5. Sentiment timeline
    # ------------------------------------------------------------------

    async def sentiment_timeline(
        self,
        *,
        tenant_id: UUID,
        filters: AnalyticsFilters,
        granularity: Granularity,
    ) -> SentimentTimeline:
        bucket = self._date_bucket(granularity)
        stmt = (
            select(
                bucket.label("bucket"),
                Review.sentiment_label,
                func.count().label("cnt"),
                func.avg(Review.sentiment_score).label("avg_score"),
            )
            .where(Review.tenant_id == tenant_id)
            .where(Review.deleted_at.is_(None))
            .group_by(bucket, Review.sentiment_label)
            .order_by(bucket)
        )
        stmt = self._apply_review_filters(stmt, filters)
        rows = (await self._session.execute(stmt)).all()

        agg: dict[str, dict[str, Any]] = {}
        for row in rows:
            key = self._format_bucket(row.bucket, granularity)
            slot = agg.setdefault(
                key,
                {"negatif": 0, "nötr": 0, "pozitif": 0, "total": 0, "score_sum": 0.0},
            )
            label = row.sentiment_label.lower()
            count = row.cnt
            slot[label] = slot.get(label, 0) + count
            slot["total"] += count
            slot["score_sum"] += float(row.avg_score) * count

        ordered = sorted(agg.items(), key=lambda kv: kv[0])
        data = [
            TimelinePoint(
                date=key,
                negatif=int(v.get("negatif", 0)),
                nötr=int(v.get("nötr", 0)),
                pozitif=int(v.get("pozitif", 0)),
                total=int(v["total"]),
                avg_score=round(v["score_sum"] / v["total"], 3) if v["total"] else 0.0,
            )
            for key, v in ordered
        ]
        return SentimentTimeline(granularity=granularity, data=data)

    # ------------------------------------------------------------------
    # 6. Ticket resolution time
    # ------------------------------------------------------------------

    async def ticket_resolution_time(
        self,
        *,
        tenant_id: UUID,
        filters: AnalyticsFilters,
    ) -> TicketResolution:
        # Resolved tickets only, with resolved_at - opened_at in hours.
        secs_expr = (
            func.extract("epoch", Ticket.resolved_at - Ticket.opened_at)
        )
        hours_expr = (secs_expr / 3600.0).label("hours")

        stmt = (
            select(hours_expr)
            .where(Ticket.tenant_id == tenant_id)
            .where(Ticket.deleted_at.is_(None))
            .where(Ticket.state == TicketState.RESOLVED)
            .where(Ticket.resolved_at.is_not(None))
        )
        stmt = self._apply_ticket_filters(stmt, filters)
        rows = (await self._session.execute(stmt)).all()
        hours_list = sorted([float(r.hours) for r in rows if r.hours is not None])
        total = len(hours_list)
        if total == 0:
            return TicketResolution(
                total_resolved_tickets=0,
                avg_resolution_hours=0.0,
                median_resolution_hours=0.0,
                p95_resolution_hours=0.0,
            )
        avg = sum(hours_list) / total
        median = hours_list[total // 2]
        p95 = hours_list[min(total - 1, int(total * 0.95))]

        # Distribution buckets (same labels as the spec).
        buckets = [
            ("<1h", 0, 1),
            ("1-4h", 1, 4),
            ("4-24h", 4, 24),
            ("1-3 gün", 24, 72),
            (">3 gün", 72, float("inf")),
        ]
        bucket_counts = []
        for label, lo, hi in buckets:
            count = sum(1 for h in hours_list if lo <= h < hi)
            bucket_counts.append(ResolutionBucket(bucket=label, count=count))

        # By category — separate query for the breakdown.
        cat_stmt = (
            select(
                Category.code.label("code"),
                Category.label_tr.label("label_tr"),
                func.avg(secs_expr / 3600.0).label("avg_hours"),
                func.count().label("cnt"),
            )
            .select_from(Ticket)
            .join(Category, Category.id == Ticket.category_id)
            .where(Ticket.tenant_id == tenant_id)
            .where(Ticket.deleted_at.is_(None))
            .where(Ticket.state == TicketState.RESOLVED)
            .where(Ticket.resolved_at.is_not(None))
            .group_by(Category.code, Category.label_tr)
            .order_by(func.count().desc())
            .limit(10)
        )
        cat_stmt = self._apply_ticket_filters(cat_stmt, filters)
        cat_rows = (await self._session.execute(cat_stmt)).all()
        by_category = [
            ResolutionByCategory(
                category=r.label_tr or r.code,
                avg_hours=round(float(r.avg_hours), 2),
                count=r.cnt,
            )
            for r in cat_rows
        ]

        return TicketResolution(
            total_resolved_tickets=total,
            avg_resolution_hours=round(avg, 2),
            median_resolution_hours=round(median, 2),
            p95_resolution_hours=round(p95, 2),
            distribution=bucket_counts,
            by_category=by_category,
        )

    # ------------------------------------------------------------------
    # 7. Sensitivity distribution (sentiment_score histogram)
    # ------------------------------------------------------------------

    async def sensitivity_distribution(
        self,
        *,
        tenant_id: UUID,
        filters: AnalyticsFilters,
    ) -> SensitivityDistribution:
        stmt = (
            select(Review.sentiment_score)
            .where(Review.tenant_id == tenant_id)
            .where(Review.deleted_at.is_(None))
        )
        stmt = self._apply_review_filters(stmt, filters)
        rows = (await self._session.execute(stmt)).scalars().all()
        scores = [float(s) for s in rows]
        total = len(scores)
        if total == 0:
            return SensitivityDistribution(
                total=0,
                buckets=[],
                stats=SensitivityStats(0.0, 0.0, 0.0),
            )

        # 20 fixed buckets between -1.0 and 1.0 (width 0.1).
        bucket_counts = [0] * 20
        for s in scores:
            # Clamp to range and find bucket index.
            clamped = max(-1.0, min(1.0, s))
            idx = min(19, int((clamped + 1.0) * 10))
            bucket_counts[idx] += 1

        buckets = [
            SensitivityBucket(
                range_start=round(-1.0 + i * 0.1, 1),
                range_end=round(-1.0 + (i + 1) * 0.1, 1),
                count=bucket_counts[i],
            )
            for i in range(20)
        ]

        sorted_scores = sorted(scores)
        mean = sum(scores) / total
        median = sorted_scores[total // 2]
        variance = sum((s - mean) ** 2 for s in scores) / total
        std_dev = variance ** 0.5

        return SensitivityDistribution(
            total=total,
            buckets=buckets,
            stats=SensitivityStats(
                mean=round(mean, 3),
                median=round(median, 3),
                std_dev=round(std_dev, 3),
            ),
        )

    # ------------------------------------------------------------------
    # Filter helpers
    # ------------------------------------------------------------------

    def _apply_review_filters(self, stmt: Any, filters: AnalyticsFilters) -> Any:
        if filters.date_from is not None:
            stmt = stmt.where(Review.analyzed_at >= filters.date_from)
        if filters.date_to is not None:
            stmt = stmt.where(Review.analyzed_at <= filters.date_to)
        if filters.sentiment_labels:
            stmt = stmt.where(Review.sentiment_label.in_(filters.sentiment_labels))
        if filters.batch_job_id is not None:
            stmt = stmt.where(Review.batch_job_id == filters.batch_job_id)
        if filters.source_types:
            wanted = []
            if "batch" in filters.source_types:
                wanted.append(Review.batch_job_id.is_not(None))
            if "manual" in filters.source_types:
                wanted.append(Review.batch_job_id.is_(None))
            if wanted:
                stmt = stmt.where(or_(*wanted))
        return stmt

    def _apply_ticket_filters(self, stmt: Any, filters: AnalyticsFilters) -> Any:
        if filters.date_from is not None:
            stmt = stmt.where(Ticket.opened_at >= filters.date_from)
        if filters.date_to is not None:
            stmt = stmt.where(Ticket.opened_at <= filters.date_to)
        if filters.category_ids:
            stmt = stmt.where(Ticket.category_id.in_(filters.category_ids))
        return stmt

    def _date_bucket(self, granularity: Granularity) -> Any:
        return func.date_trunc(granularity, Review.analyzed_at)

    def _format_bucket(self, dt: datetime, granularity: Granularity) -> str:
        if granularity == "day":
            return dt.strftime("%Y-%m-%d")
        if granularity == "week":
            iso_year, iso_week, _ = dt.isocalendar()
            return f"{iso_year}-W{iso_week:02d}"
        return dt.strftime("%Y-%m")


# Silence unused-imports warnings (kept for forward use).
_ = (and_, case, JSONB, timedelta)


__all__ = [
    "AnalyticsFilters",
    "AnalyticsService",
    "CategoryDist",
    "CategoryDistRow",
    "Granularity",
    "OverrideStats",
    "OverrideStatsRow",
    "ResolutionBucket",
    "ResolutionByCategory",
    "SensitivityBucket",
    "SensitivityDistribution",
    "SensitivityStats",
    "SentimentByCategory",
    "SentimentDist",
    "SentimentDistRow",
    "SentimentTimeline",
    "TicketResolution",
    "TimelinePoint",
]
