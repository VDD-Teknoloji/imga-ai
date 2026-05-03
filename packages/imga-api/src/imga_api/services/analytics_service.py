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
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from imga_core.config import CRISIS_SCORE_THRESHOLD
from imga_db.models import Category, CategoryTaxonomy, Review, Ticket, TicketState
from sqlalchemy import and_, case, func, or_, select, text
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


# --- Sprint 8.3.5 — NPS aggregation shapes ------------------------------


@dataclass(frozen=True, slots=True)
class NPSSummary:
    """Aggregate NPS view for a tenant + date/batch filter set.

    ``score`` is None when total_count == 0 — not 0, not -100. Frontend
    renders the empty state for None ("yeterli veri yok"). When
    total_count > 0:

        score = ((promoter_count - detractor_count) / total_count) * 100

    yielding -100..100 by definition. ``coverage_percent`` is the share
    of all (NPS-bearing or not) reviews that carry an nps_score in the
    same filter window — useful for "how reliable is this score?"
    callouts on the dashboard.
    """

    score: float | None
    detractor_count: int
    passive_count: int
    promoter_count: int
    total_count: int
    coverage_percent: float


@dataclass(frozen=True, slots=True)
class HeadlineMetrics:
    """Eight-field bundle for the dashboard's top row, served from a
    single endpoint so the page paints in one round-trip.

    Numeric fields default to 0 when the tenant has no qualifying rows.
    ``nps_score`` and ``avg_sentiment_score`` are ``None`` (not 0.0) on
    "no data" because 0 is a meaningful score in both metrics — the
    frontend renders an empty state for None.

    Date filter (``date_from`` / ``date_to``) applies to the review-side
    metrics only — total_reviews, crisis_count, nps_score / coverage,
    avg_sentiment_score, sensitive_topics_count. Tickets always reflect
    "right now" state (open + today's intake), independent of the
    review timeline filter; that matches the dashboard UX where
    reviewing yesterday's NPS doesn't pretend yesterday's open-ticket
    count.
    """

    total_reviews: int
    open_tickets: int
    today_new_tickets: int
    crisis_count: int
    nps_score: float | None
    nps_coverage_percent: float
    avg_sentiment_score: float | None
    sensitive_topics_count: int


@dataclass(frozen=True, slots=True)
class CompanyPerspectiveDistRow:
    """One row of the company-perspective distribution. ``code`` is the
    raw ``CategoryTaxonomy.code`` (or the placeholder for unmatched
    rows); ``label_tr`` falls back to the raw code when the taxonomy
    row has been pruned since the review was analyzed (8.3.7 edit UI
    can delete rows; we don't repair historical reviews).
    """

    code: str
    label_tr: str
    count: int
    percentage: float


@dataclass(frozen=True, slots=True)
class CompanyPerspectiveDist:
    """``unmatched_count`` is the share of reviews where the heuristic
    didn't fire (NULL company_perspective_code). It's reported alongside
    rather than mixed in so the dashboard can show "X reviews didn't
    match any taxonomy entry" as a separate signal."""

    total: int
    unmatched_count: int
    data: list[CompanyPerspectiveDistRow] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class NPSMonthlyPoint:
    """One row of the monthly trend list. ``month`` is the first day of
    the calendar month (UTC midnight) — the frontend formats from there.
    ``score`` is None when ``total_count == 0`` so a connectNulls=false
    line chart renders a real gap instead of dropping the point.
    """

    month: date
    score: float | None
    detractor_count: int
    passive_count: int
    promoter_count: int
    total_count: int


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
    # 8. NPS summary (Sprint 8.3.5)
    # ------------------------------------------------------------------

    async def compute_nps_summary(
        self,
        *,
        tenant_id: UUID,
        date_from: date | None = None,
        date_to: date | None = None,
        batch_job_id: UUID | None = None,
    ) -> NPSSummary:
        """Aggregate NPS bucket counts + score for the filter window.

        ``score`` is None when no NPS-bearing rows match the filter; the
        frontend renders the empty state instead of a confusing "0.0".
        Date filtering uses ``Review.created_at`` per the partial index
        ``ix_reviews_tenant_nps_created`` — semantically "when did we
        ingest this NPS feedback", which is the dimension dashboards
        track. The fold-down filter helper used by the other endpoints
        keys on ``analyzed_at`` so we deliberately don't reuse it here.

        Coverage = NPS-bearing rows / all-tenant-rows in the same window;
        the all-rows count uses the same created_at + batch_job_id
        filters so callers comparing it to total_count don't hit an
        apples-to-oranges denominator.
        """
        # Bucket aggregation — group by the GENERATED column. NULL rows
        # (no NPS) drop out of the GROUP BY because nps_category IS NULL
        # when nps_score IS NULL by construction.
        bucket_stmt = (
            select(Review.nps_category, func.count().label("cnt"))
            .where(Review.tenant_id == tenant_id)
            .where(Review.deleted_at.is_(None))
            .where(Review.nps_score.is_not(None))
            .group_by(Review.nps_category)
        )
        bucket_stmt = self._apply_nps_window(
            bucket_stmt, date_from=date_from, date_to=date_to, batch_job_id=batch_job_id
        )
        rows = (await self._session.execute(bucket_stmt)).all()

        per_bucket: dict[str, int] = {"detractor": 0, "passive": 0, "promoter": 0}
        for r in rows:
            if r.nps_category in per_bucket:
                per_bucket[r.nps_category] = r.cnt
        total = sum(per_bucket.values())

        score: float | None
        if total == 0:
            score = None
        else:
            score = round(
                ((per_bucket["promoter"] - per_bucket["detractor"]) / total) * 100,
                2,
            )

        # Coverage denominator — all non-deleted reviews in the same window.
        all_stmt = (
            select(func.count())
            .select_from(Review)
            .where(Review.tenant_id == tenant_id)
            .where(Review.deleted_at.is_(None))
        )
        all_stmt = self._apply_nps_window(
            all_stmt, date_from=date_from, date_to=date_to, batch_job_id=batch_job_id
        )
        all_total: int = (await self._session.execute(all_stmt)).scalar_one() or 0
        coverage = round(100 * total / all_total, 2) if all_total else 0.0

        return NPSSummary(
            score=score,
            detractor_count=per_bucket["detractor"],
            passive_count=per_bucket["passive"],
            promoter_count=per_bucket["promoter"],
            total_count=total,
            coverage_percent=coverage,
        )

    # ------------------------------------------------------------------
    # 9. NPS monthly trend (Sprint 8.3.5)
    # ------------------------------------------------------------------

    async def compute_monthly_nps_trend(
        self,
        *,
        tenant_id: UUID,
        months_back: int = 12,
        now: datetime | None = None,
    ) -> list[NPSMonthlyPoint]:
        """Return ``months_back`` calendar months of NPS, oldest first.

        Months without any NPS-bearing review still surface as a point
        with score=None — the frontend's connectNulls=false renders a
        gap, which is the truthful read of "we have no data this month",
        not a 0 that would smash the trend line.

        Now-anchored at the caller's ``now`` (or UTC now). Buckets are
        UTC calendar months (date_trunc('month', created_at)) — same
        timezone the partial index ``ix_reviews_tenant_nps_created``
        operates on, so the planner can stay on it.
        """
        anchor = (now or datetime.now(UTC)).date()
        target_months = _trailing_month_starts(anchor, months_back)
        # Window = oldest target month → next month after the newest.
        window_start = datetime.combine(target_months[0], datetime.min.time(), tzinfo=UTC)
        next_month_after_anchor = _next_month_start(target_months[-1])
        window_end_exclusive = datetime.combine(
            next_month_after_anchor, datetime.min.time(), tzinfo=UTC
        )

        bucket_expr = func.date_trunc("month", Review.created_at).label("bucket")
        stmt = (
            select(
                bucket_expr,
                Review.nps_category,
                func.count().label("cnt"),
            )
            .where(Review.tenant_id == tenant_id)
            .where(Review.deleted_at.is_(None))
            .where(Review.nps_score.is_not(None))
            .where(Review.created_at >= window_start)
            .where(Review.created_at < window_end_exclusive)
            .group_by(bucket_expr, Review.nps_category)
        )
        rows = (await self._session.execute(stmt)).all()

        # Pivot: month_start_date → bucket_label → count.
        agg: dict[date, dict[str, int]] = {
            m: {"detractor": 0, "passive": 0, "promoter": 0} for m in target_months
        }
        for r in rows:
            month_key = r.bucket.date() if isinstance(r.bucket, datetime) else r.bucket
            slot = agg.get(month_key)
            if slot is None or r.nps_category not in slot:
                continue
            slot[r.nps_category] = r.cnt

        points: list[NPSMonthlyPoint] = []
        for m in target_months:
            buckets = agg[m]
            total = sum(buckets.values())
            score: float | None
            if total == 0:
                score = None
            else:
                score = round(
                    ((buckets["promoter"] - buckets["detractor"]) / total) * 100,
                    2,
                )
            points.append(
                NPSMonthlyPoint(
                    month=m,
                    score=score,
                    detractor_count=buckets["detractor"],
                    passive_count=buckets["passive"],
                    promoter_count=buckets["promoter"],
                    total_count=total,
                )
            )
        return points

    # ------------------------------------------------------------------
    # 10. Headline metrics — dashboard top row, single-call (Sprint 8.3.5)
    # ------------------------------------------------------------------

    async def compute_headline_metrics(
        self,
        *,
        tenant_id: UUID,
        date_from: date | None = None,
        date_to: date | None = None,
        now: datetime | None = None,
    ) -> HeadlineMetrics:
        """Eight headline values for the dashboard's top row.

        The query plan: six small COUNTs / AVGs hitting indexes the
        previous sprints already laid down — partial NPS composite,
        sentiment_score (covered by ix_reviews_tenant_analyzed from
        Sprint 7), JSONB GIN on overrides_applied (Sprint 8.3.4),
        ticket state index (Sprint 7). On a 10K-row tenant the whole
        bundle should land under 100ms warm; that's the budget the
        dashboard pays on every page load.

        Date filter applies to *review* metrics only (created_at). The
        two ticket counts always reflect the live state — open
        tickets right now, today's intake from the Istanbul-local
        midnight boundary — so the dashboard doesn't pretend "Açık
        Bilet" is the count from a historical date range.
        """
        # --- review-side metrics ----------------------------------
        # 1. total_reviews (date-filtered)
        total_stmt = (
            select(func.count())
            .select_from(Review)
            .where(Review.tenant_id == tenant_id)
            .where(Review.deleted_at.is_(None))
        )
        total_stmt = self._apply_review_date_window(
            total_stmt, date_from=date_from, date_to=date_to
        )
        total_reviews: int = (await self._session.execute(total_stmt)).scalar_one() or 0

        # 2. crisis_count — sentiment_score <= -0.80
        crisis_stmt = (
            select(func.count())
            .select_from(Review)
            .where(Review.tenant_id == tenant_id)
            .where(Review.deleted_at.is_(None))
            .where(Review.sentiment_score <= CRISIS_SCORE_THRESHOLD)
        )
        crisis_stmt = self._apply_review_date_window(
            crisis_stmt, date_from=date_from, date_to=date_to
        )
        crisis_count: int = (await self._session.execute(crisis_stmt)).scalar_one() or 0

        # 3. avg_sentiment_score — None when no scored rows match.
        avg_stmt = (
            select(func.avg(Review.sentiment_score))
            .where(Review.tenant_id == tenant_id)
            .where(Review.deleted_at.is_(None))
            .where(Review.sentiment_score.is_not(None))
        )
        avg_stmt = self._apply_review_date_window(
            avg_stmt, date_from=date_from, date_to=date_to
        )
        avg_raw = (await self._session.execute(avg_stmt)).scalar_one_or_none()
        avg_sentiment_score: float | None = (
            round(float(avg_raw), 3) if avg_raw is not None else None
        )

        # 4. sensitive_topics_count — rows whose overrides_applied
        # contains a tier1 or tier2 hit. The JSONB ``@>`` containment
        # operator is NULL-safe (NULL @> anything → NULL → excluded by
        # WHERE) AND uses the GIN index from migration 0014 directly;
        # the obvious EXISTS-with-jsonb_array_elements path fails with
        # "cannot extract elements from a scalar" because the Postgres
        # planner can push the SRF past the row-level NULL filter even
        # with COALESCE wrapping (same quirk Sprint 8.3.4 round-1 hit
        # in override-stats — moved to Python-side aggregation there;
        # @> sidesteps it cleanly here).
        sensitive_stmt = (
            select(func.count())
            .select_from(Review)
            .where(Review.tenant_id == tenant_id)
            .where(Review.deleted_at.is_(None))
            .where(
                or_(
                    Review.overrides_applied.op("@>")(
                        text("'[{\"layer\": \"tier1\"}]'::jsonb")
                    ),
                    Review.overrides_applied.op("@>")(
                        text("'[{\"layer\": \"tier2\"}]'::jsonb")
                    ),
                )
            )
        )
        sensitive_stmt = self._apply_review_date_window(
            sensitive_stmt, date_from=date_from, date_to=date_to
        )
        sensitive_topics_count: int = (
            await self._session.execute(sensitive_stmt)
        ).scalar_one() or 0

        # 5 + 6. NPS via the existing summary aggregator (date-filtered).
        nps = await self.compute_nps_summary(
            tenant_id=tenant_id, date_from=date_from, date_to=date_to
        )

        # --- ticket-side metrics (no date filter) -----------------
        # 7. open_tickets — OPEN + IN_PROGRESS + PENDING_CUSTOMER.
        active_states = (
            TicketState.OPEN,
            TicketState.IN_PROGRESS,
            TicketState.PENDING_CUSTOMER,
        )
        open_stmt = (
            select(func.count())
            .select_from(Ticket)
            .where(Ticket.tenant_id == tenant_id)
            .where(Ticket.deleted_at.is_(None))
            .where(Ticket.state.in_(active_states))
        )
        open_tickets: int = (await self._session.execute(open_stmt)).scalar_one() or 0

        # 8. today_new_tickets — opened_at >= today_istanbul_start.
        today_start = _istanbul_today_start_utc(now)
        today_stmt = (
            select(func.count())
            .select_from(Ticket)
            .where(Ticket.tenant_id == tenant_id)
            .where(Ticket.deleted_at.is_(None))
            .where(Ticket.opened_at >= today_start)
        )
        today_new_tickets: int = (
            await self._session.execute(today_stmt)
        ).scalar_one() or 0

        return HeadlineMetrics(
            total_reviews=total_reviews,
            open_tickets=open_tickets,
            today_new_tickets=today_new_tickets,
            crisis_count=crisis_count,
            nps_score=nps.score,
            nps_coverage_percent=nps.coverage_percent,
            avg_sentiment_score=avg_sentiment_score,
            sensitive_topics_count=sensitive_topics_count,
        )

    # ------------------------------------------------------------------
    # 11. Company-perspective distribution (Sprint 8.3.5.6)
    # ------------------------------------------------------------------

    async def compute_company_perspective_distribution(
        self,
        *,
        tenant_id: UUID,
        filters: AnalyticsFilters,
        limit: int = 10,
    ) -> CompanyPerspectiveDist:
        """Top-N matched company-perspective codes plus the unmatched
        count. Joins ``CategoryTaxonomy`` per (tenant, code) for the
        Türkçe label; rows whose taxonomy entry has since been pruned
        (Sprint 8.3.7 will allow deletes) fall back to the raw code.

        Reviews with ``company_perspective_code IS NULL`` (the heuristic
        didn't match anything in the tenant's taxonomy) are reported via
        ``unmatched_count`` rather than mixed into ``data`` — the
        dashboard treats "didn't match" as a separate signal from "fell
        below the top-N tail".
        """
        # Total matching reviews after filters — denominator for percentage
        # and for unmatched_count = total - matched_total.
        total_stmt = (
            select(func.count())
            .select_from(Review)
            .where(Review.tenant_id == tenant_id)
            .where(Review.deleted_at.is_(None))
        )
        total_stmt = self._apply_review_filters(total_stmt, filters)
        total = (await self._session.execute(total_stmt)).scalar_one() or 0

        # Top-N codes by count, joined to taxonomy for label_tr. LEFT
        # JOIN on the (tenant_id, code) composite so a pruned taxonomy
        # entry still surfaces with the raw code.
        rows_stmt = (
            select(
                Review.company_perspective_code.label("code"),
                CategoryTaxonomy.label_tr.label("label_tr"),
                func.count().label("cnt"),
            )
            .select_from(Review)
            .outerjoin(
                CategoryTaxonomy,
                and_(
                    CategoryTaxonomy.tenant_id == Review.tenant_id,
                    CategoryTaxonomy.code == Review.company_perspective_code,
                ),
            )
            .where(Review.tenant_id == tenant_id)
            .where(Review.deleted_at.is_(None))
            .where(Review.company_perspective_code.is_not(None))
            .group_by(Review.company_perspective_code, CategoryTaxonomy.label_tr)
            .order_by(func.count().desc())
            .limit(limit)
        )
        rows_stmt = self._apply_review_filters(rows_stmt, filters)
        rows = (await self._session.execute(rows_stmt)).all()

        matched_total_stmt = (
            select(func.count())
            .select_from(Review)
            .where(Review.tenant_id == tenant_id)
            .where(Review.deleted_at.is_(None))
            .where(Review.company_perspective_code.is_not(None))
        )
        matched_total_stmt = self._apply_review_filters(matched_total_stmt, filters)
        matched_total = (
            await self._session.execute(matched_total_stmt)
        ).scalar_one() or 0
        unmatched_count = total - matched_total

        data = [
            CompanyPerspectiveDistRow(
                code=r.code,
                label_tr=r.label_tr or r.code,
                count=r.cnt,
                percentage=round(100 * r.cnt / total, 2) if total else 0.0,
            )
            for r in rows
        ]
        return CompanyPerspectiveDist(
            total=total, unmatched_count=unmatched_count, data=data
        )

    # ------------------------------------------------------------------
    # Filter helpers
    # ------------------------------------------------------------------

    def _apply_review_date_window(
        self,
        stmt: Any,
        *,
        date_from: date | None,
        date_to: date | None,
    ) -> Any:
        """Headline metrics + NPS endpoints filter reviews on
        ``created_at`` (when ingested), inclusive UTC midnight bounds.
        Same widening rule as ``_apply_nps_window``: pass a date and
        the upper bound becomes end-of-day so 2026-03-31 captures
        2026-03-31T23:59:59Z."""
        if date_from is not None:
            from_dt = datetime.combine(date_from, datetime.min.time(), tzinfo=UTC)
            stmt = stmt.where(Review.created_at >= from_dt)
        if date_to is not None:
            to_dt = datetime.combine(date_to, datetime.max.time(), tzinfo=UTC)
            stmt = stmt.where(Review.created_at <= to_dt)
        return stmt

    def _apply_nps_window(
        self,
        stmt: Any,
        *,
        date_from: date | None,
        date_to: date | None,
        batch_job_id: UUID | None,
    ) -> Any:
        """NPS-summary's filter envelope: review date window (shared
        with headline metrics, see ``_apply_review_date_window``) plus
        the batch_job_id filter that's NPS-specific to scope a single
        upload's score."""
        stmt = self._apply_review_date_window(
            stmt, date_from=date_from, date_to=date_to
        )
        if batch_job_id is not None:
            stmt = stmt.where(Review.batch_job_id == batch_job_id)
        return stmt

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


# --- Time helpers (Sprint 8.3.5 headline metrics) --------------------


_TR_TZ = ZoneInfo("Europe/Istanbul")


def _istanbul_today_start_utc(now: datetime | None = None) -> datetime:
    """First moment of *today* in the Europe/Istanbul timezone, returned
    as a UTC ``datetime`` for the DB comparison.

    "Bugün" semantics: dashboard's "Bugün Açılan" card is anchored to
    the user's calendar day, not UTC midnight (which is 03:00 in
    Istanbul). Caller passes ``now`` only in tests that need
    deterministic "today" boundaries; production calls leave it None.
    """
    moment = now or datetime.now(UTC)
    moment_tr = moment.astimezone(_TR_TZ)
    today_start_tr = datetime(
        moment_tr.year, moment_tr.month, moment_tr.day, tzinfo=_TR_TZ
    )
    return today_start_tr.astimezone(UTC)


# --- Month math helpers (Sprint 8.3.5 NPS trend) ---------------------


def _next_month_start(month_first: date) -> date:
    """Given the first day of a calendar month, return the first day of
    the next month. Handles December → January year roll without a
    timedelta hack."""
    if month_first.month == 12:
        return date(month_first.year + 1, 1, 1)
    return date(month_first.year, month_first.month + 1, 1)


def _trailing_month_starts(anchor: date, months_back: int) -> list[date]:
    """Return ``months_back`` first-of-month dates, oldest first,
    ending with the anchor's own month. ``months_back=12`` on
    2026-05-15 yields [2025-06-01, ..., 2026-05-01]."""
    first_of_anchor_month = date(anchor.year, anchor.month, 1)
    months: list[date] = []
    cursor = first_of_anchor_month
    for _ in range(months_back):
        months.append(cursor)
        # Walk backwards a month at a time.
        if cursor.month == 1:
            cursor = date(cursor.year - 1, 12, 1)
        else:
            cursor = date(cursor.year, cursor.month - 1, 1)
    months.reverse()
    return months


# Silence unused-imports warnings (kept for forward use).
_ = (and_, case, JSONB, timedelta)


__all__ = [
    "AnalyticsFilters",
    "AnalyticsService",
    "CategoryDist",
    "CategoryDistRow",
    "CompanyPerspectiveDist",
    "CompanyPerspectiveDistRow",
    "Granularity",
    "HeadlineMetrics",
    "NPSMonthlyPoint",
    "NPSSummary",
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
