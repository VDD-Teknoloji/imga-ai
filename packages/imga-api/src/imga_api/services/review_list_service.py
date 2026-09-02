"""ReviewListService — read-side queries over the ``reviews`` table.

Sprint 8.3.1. Separated from ReviewService (which owns the bridge logic
+ writes) so the read API stays a pure projection. Filters mirror the
ticket list filter pattern.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from imga_db.models import CategoryTaxonomy, Review
from sqlalchemy import Integer, and_, case, cast, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from imga_api.services.dimension_service import (
    DIMENSION_COLUMNS,
    UnknownDimension,
    dimension_value_present,
    fold_dimension_key,
)

OrderField = Literal["created_at", "sentiment_score", "engagement"]
OrderDir = Literal["asc", "desc"]

# B3 — bir NEGATİF şikayetin "viral" sayılması için gereken minimum
# etkileşim (like+retweet+reply toplamı, bkz. ``_engagement_expr``):
# 100+ etkileşim, şikayetin yazarın kendi takipçi kitlesinin ötesine
# yayıldığının kaba bir işareti. ``view_count`` bilerek hem bu eşiğin
# hem de ``_engagement_expr``'in dışında tutulur — platform tarafından
# şişirilir (otomatik oynatma/scroll-through sayımı), gerçek bir
# etkileşim sinyali değildir.
VIRAL_ENGAGEMENT_THRESHOLD = 100


@dataclass(frozen=True, slots=True)
class ReviewListFilters:
    """Validated filter set for GET /tenants/me/reviews."""

    date_from: datetime | None = None
    date_to: datetime | None = None
    sentiment_labels: tuple[str, ...] = ()
    has_ticket: bool | None = None
    batch_job_id: UUID | None = None
    source_types: tuple[str, ...] = ()  # manual | batch | api (mapped below)
    decisions: tuple[str, ...] = ()
    # Sprint 8.3.5.6. CSV of CategoryTaxonomy.code values from the
    # tenant's perspective list. The literal "__unmatched__" sentinel
    # filters to rows where the heuristic didn't fire (NULL column);
    # mixing it with real codes yields the union (matched in X, Y OR
    # unmatched).
    perspective_codes: tuple[str, ...] = ()
    # Sprint 8.3.10 — primary BERT category filter for the cross-
    # analysis heatmap drill-down. CSV of category codes
    # (Review.primary_category values). Empty tuple disables the
    # filter; one or more entries OR-match.
    primary_categories: tuple[str, ...] = ()
    # 2026-08-20 — Dalga 3. Business-dimension list filters over the
    # six free-text Review columns. Matching folds both sides via
    # lower(trim(...)) (fold_dimension_key) so "FEDEX"/"fedex" hit the
    # same rows regardless of which raw spelling the filter chip
    # carries — consistent with the dimension breakdown's bucketing.
    channels: tuple[str, ...] = ()
    business_segments: tuple[str, ...] = ()
    product_lines: tuple[str, ...] = ()
    customer_tiers: tuple[str, ...] = ()
    entered_bys: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    # Sprint 9.5 B1 — time-extract filters for the /insights heatmap
    # cell-click drilldown. Each is an integer or None; non-None
    # values are compared against ``EXTRACT(<part> FROM ...)`` on the
    # same column the heatmap axis uses (saat: created_at, gun/hafta/
    # ay: review_date). The heatmap_generator emits matching x_keys /
    # y_keys on the response so the frontend can wire the click
    # without re-deriving the axis numerics.
    hour_of_day: int | None = None  # 0..23
    day_of_week: int | None = None  # 0..6 (postgres DOW: 0=Sun..6=Sat)
    week_of_year: int | None = None  # 1..53
    month: int | None = None  # 1..12
    search: str | None = None  # ILIKE %term% over text
    # 2026-08-18 — WS2 veri kalitesi. CSV of quality_flag values
    # (duplicate/empty/informational/meaningless); non-empty means
    # "only these flags" — e.g. the list page's "sadece bilgilendirme
    # göster" view. Empty tuple disables this positive filter.
    quality_flags: tuple[str, ...] = ()
    # Liste bir arşiv: analitiğin aksine varsayılan HEPSİNİ gösterir
    # (bayraklı satırlar dahil). ``quality_flags`` doluysa bu alan
    # devre dışı kalır — kullanıcı zaten belirli bayrakları istemiştir.
    include_flagged: bool = True
    # W2-A — CSV of Review.content_type values. 2026-09-01 (migration
    # 0050) widened from just "question" to five: question, suggestion,
    # thanks, request, escalation. Empty tuple disables the filter.
    content_types: tuple[str, ...] = ()
    order_by: OrderField = "created_at"
    order: OrderDir = "desc"


@dataclass(frozen=True, slots=True)
class ReviewListItem:
    """Wire shape for one row in the list view."""

    id: UUID
    text: str
    sentiment_label: str
    sentiment_score: float
    primary_category: str
    primary_confidence: float
    decision: str
    decision_reason: str | None
    ticket_id: UUID | None
    batch_job_id: UUID | None
    source_type: str
    analyzed_at: datetime
    # Yorumun kendi tarihi — liste bu kolonu gösterir, analyzed_at
    # "ne zaman analiz edildi" olarak ikincil kalır.
    review_date: datetime
    submitted_by_user_id: UUID | None
    # Sprint 8.3.4 — count of override layers that fired during analysis.
    # The list view only needs the count for the chip; the full trace is
    # served by the detail endpoint to keep list responses small.
    override_count: int
    # Sprint 8.3.5.6 — heuristic company-perspective hit. Both fields are
    # None when the heuristic didn't match anything in the tenant's
    # taxonomy. ``label_tr`` is None (rather than falling back to the
    # raw code) when the taxonomy row was pruned after analyze; the UI
    # treats that case as "removed category" rather than re-rendering
    # the raw code as if it were the label.
    company_perspective_code: str | None
    company_perspective_label_tr: str | None
    # 2026-08-10 — LLM'in temas noktası kararı ("dijital" |
    # "operasyonel"). NULL = birleşik yol koşmamış eski satır.
    experience_type: str | None = None
    # 2026-08-26 (migration 0047) — kaynaktaki kalıcı bağlantı (tweet
    # URL'si vb.); kart "Tweeti aç / Kaynağı aç" düğmesi bunu kullanır.
    source_url: str | None = None
    # W2-A — içerik türü ("question" | "suggestion" | "thanks" |
    # "request" | "escalation" | None, migration 0050). NULL = normal
    # yorum.
    content_type: str | None = None


@dataclass(frozen=True, slots=True)
class DimensionValueCount:
    """One row of GET /tenants/me/reviews/dimension-values — the
    filter chip source. ``value`` is the fold's most-frequent raw
    spelling (see ``fold_dimension_key``), not the folded key."""

    value: str
    count: int


# --- W2-A — GET /tenants/me/reviews/summary --------------------------


@dataclass(frozen=True, slots=True)
class NpsSummary:
    promoter: int
    passive: int
    detractor: int
    with_nps: int
    # None when with_nps == 0 — dividing by zero has no meaningful score.
    score: float | None


@dataclass(frozen=True, slots=True)
class QualitySummary:
    """quality_flag bucket counts. ``clean`` is the NULL bucket (no
    flag at all), the other four mirror ``quality_flag``'s CHECK
    values."""

    clean: int
    duplicate: int
    empty: int
    informational: int
    meaningless: int


@dataclass(frozen=True, slots=True)
class CategoryCount:
    """Top primary_category buckets. ``code`` is the raw BERT category
    string — no CategoryTaxonomy join here, primary_category values
    aren't taxonomy codes."""

    code: str
    count: int
    negative_count: int


@dataclass(frozen=True, slots=True)
class EnteredByCount:
    """Per-``entered_by`` matrix row (folded like the dimension-values
    facet) — ``value`` is the fold's most-frequent raw spelling."""

    value: str
    total: int
    flagged: int
    question: int
    negative: int


@dataclass(frozen=True, slots=True)
class DailyCount:
    date: str  # YYYY-MM-DD
    count: int
    negative: int


@dataclass(frozen=True, slots=True)
class TopQuestion:
    """One content_type='question' text_hash bucket. ``text`` is a
    representative spelling (MIN over the bucket), not necessarily the
    most frequent one."""

    text: str
    count: int


@dataclass(frozen=True, slots=True)
class ReviewSummary:
    """Wire shape for GET /tenants/me/reviews/summary — one filter-
    reactive round trip over the same WHERE the list uses."""

    total: int
    sentiment: dict[str, int]
    avg_sentiment_score: float | None
    nps: NpsSummary
    sources: list[DimensionValueCount]
    categories: list[CategoryCount]
    quality: QualitySummary
    question_count: int
    # 2026-09-01 (migration 0050) — all five Review.content_type values,
    # 0-defaulted (question/suggestion/thanks/request/escalation).
    # ``question_count`` above is kept for backward compatibility and is
    # always equal to ``content_types["question"]``.
    content_types: dict[str, int]
    top_questions: list[TopQuestion]
    entered_by: list[EnteredByCount]
    daily: list[DailyCount]
    ticket_linked: int
    # B3 — NEGATİF + engagement >= VIRAL_ENGAGEMENT_THRESHOLD count.
    # Defaults to 0 so callers built before this field existed still
    # construct without it.
    viral_negative_count: int = 0


def _folded_in(
    column: InstrumentedAttribute[str | None], values: tuple[str, ...]
) -> ColumnElement[bool]:
    """``lower(trim(column)) IN (lowered values)`` — the list-filter
    counterpart to the dimension breakdown's bucket folding, so a
    filter chip built from one raw spelling still matches every other
    spelling folded into the same bucket."""
    lowered = tuple(v.strip().lower() for v in values)
    return fold_dimension_key(column).in_(lowered)


def _source_meta_int(key: str) -> ColumnElement[int]:
    """One integer counter out of ``Review.source_meta`` (JSONB,
    migration 0049), 0 when the column is NULL or the key is absent.
    ``->>`` extracts the raw JSON value as text (NULL either way, never
    an error) and ``::int`` casts it; COALESCE supplies the 0 floor."""
    return func.coalesce(cast(Review.source_meta.op("->>")(key), Integer), 0)


def _engagement_expr() -> ColumnElement[int]:
    """Engagement = like + retweet + reply counts from ``source_meta``.
    Twitter-only today (0 for every other source, not NULL) — shared by
    the ``order_by=engagement`` list ordering and ``summarize()``'s
    ``viral_negative_count`` so the two can't drift apart. Deliberately
    excludes ``view_count``: see ``VIRAL_ENGAGEMENT_THRESHOLD``."""
    return (
        _source_meta_int("like_count")
        + _source_meta_int("retweet_count")
        + _source_meta_int("reply_count")
    )


class ReviewListService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _build_conditions(
        self, *, tenant_id: UUID, filters: ReviewListFilters
    ) -> list[ColumnElement[bool]]:
        """Shared WHERE-condition builder for the list, the dimension-
        values facet's caller (indirectly, via list_reviews) and
        ``summarize`` — every aggregate the summary panel shows must
        answer to the exact same filter set as the list it sits above."""
        conditions: list[ColumnElement[bool]] = [
            Review.tenant_id == tenant_id,
            Review.deleted_at.is_(None),
        ]
        if filters.date_from is not None:
            conditions.append(Review.review_date >= filters.date_from)
        if filters.date_to is not None:
            conditions.append(Review.review_date <= filters.date_to)
        if filters.sentiment_labels:
            conditions.append(Review.sentiment_label.in_(filters.sentiment_labels))
        if filters.decisions:
            conditions.append(Review.decision.in_(filters.decisions))
        if filters.has_ticket is True:
            conditions.append(Review.ticket_id.is_not(None))
        elif filters.has_ticket is False:
            conditions.append(Review.ticket_id.is_(None))
        if filters.batch_job_id is not None:
            conditions.append(Review.batch_job_id == filters.batch_job_id)
        if filters.source_types:
            # source_type is derived: batch_job_id IS NOT NULL → "batch",
            # else → "manual" (the legacy /analyze path). "api" is
            # reserved for future SDK-tagged uploads.
            wanted: list[ColumnElement[bool]] = []
            if "batch" in filters.source_types:
                wanted.append(Review.batch_job_id.is_not(None))
            if "manual" in filters.source_types:
                wanted.append(Review.batch_job_id.is_(None))
            if wanted:
                conditions.append(or_(*wanted))
        if filters.search:
            term = f"%{filters.search.lower()}%"
            conditions.append(func.lower(Review.text).like(term))
        if filters.perspective_codes:
            real_codes = tuple(c for c in filters.perspective_codes if c != "__unmatched__")
            include_unmatched = "__unmatched__" in filters.perspective_codes
            persp_clauses: list[ColumnElement[bool]] = []
            if real_codes:
                persp_clauses.append(Review.company_perspective_code.in_(real_codes))
            if include_unmatched:
                persp_clauses.append(Review.company_perspective_code.is_(None))
            if persp_clauses:
                conditions.append(or_(*persp_clauses))
        # Sprint 8.3.10 — cross-analysis heatmap drill-down lands here.
        if filters.primary_categories:
            conditions.append(Review.primary_category.in_(filters.primary_categories))
        # 2026-08-20 — Dalga 3 business-dimension filters.
        if filters.channels:
            conditions.append(_folded_in(Review.channel, filters.channels))
        if filters.business_segments:
            conditions.append(_folded_in(Review.business_segment, filters.business_segments))
        if filters.product_lines:
            conditions.append(_folded_in(Review.product_line, filters.product_lines))
        if filters.customer_tiers:
            conditions.append(_folded_in(Review.customer_tier, filters.customer_tiers))
        if filters.entered_bys:
            conditions.append(_folded_in(Review.entered_by, filters.entered_bys))
        if filters.sources:
            conditions.append(_folded_in(Review.source, filters.sources))
        # Sprint 9.5 B1 — heatmap cell-click drilldown. The four
        # extract conditions mirror the heatmap_generator's axis
        # expressions (``_axis_expr``) so the cell's "rows in this
        # bucket" equation matches exactly — including its column
        # split: saat ``created_at``ten (yuklenen tarihler gun
        # hassasiyetinde, saat yok), gun/hafta/ay ``review_date``ten.
        if filters.hour_of_day is not None:
            conditions.append(func.extract("hour", Review.created_at) == filters.hour_of_day)
        if filters.day_of_week is not None:
            conditions.append(func.extract("dow", Review.review_date) == filters.day_of_week)
        if filters.week_of_year is not None:
            conditions.append(func.extract("week", Review.review_date) == filters.week_of_year)
        if filters.month is not None:
            conditions.append(func.extract("month", Review.review_date) == filters.month)
        if filters.quality_flags:
            conditions.append(Review.quality_flag.in_(filters.quality_flags))
        elif not filters.include_flagged:
            conditions.append(Review.quality_flag.is_(None))
        # W2-A — content_type filter (CSV, currently just "question").
        if filters.content_types:
            conditions.append(Review.content_type.in_(filters.content_types))
        return conditions

    async def list_reviews(
        self,
        *,
        tenant_id: UUID,
        filters: ReviewListFilters,
        limit: int,
        offset: int,
    ) -> tuple[list[ReviewListItem], int]:
        # Build the base WHERE first; reused for both COUNT(*) and the
        # paginated SELECT so they stay consistent.
        conditions = self._build_conditions(tenant_id=tenant_id, filters=filters)
        where_clause = and_(*conditions)

        count_stmt = select(func.count()).select_from(Review).where(where_clause)
        total: int = (await self._session.execute(count_stmt)).scalar_one()

        # "created_at" sıralaması artık review_date üzerinde: liste
        # yorumun kendi tarihini gösteriyor, ingest anına göre sıralamak
        # kullanıcıya sırasız görünürdü. Query-string adı geriye dönük
        # uyumluluk için korundu.
        order_col: ColumnElement[Any] | InstrumentedAttribute[Any]
        if filters.order_by == "created_at":
            order_col = Review.review_date
        elif filters.order_by == "sentiment_score":
            order_col = Review.sentiment_score
        else:  # "engagement"
            order_col = _engagement_expr()
        if filters.order_by == "engagement":
            # nulls_last is a no-op today (_engagement_expr always
            # COALESCEs to 0) but keeps "most engaged first" true even
            # if a future engagement key ever produced a real NULL.
            ordering = (
                order_col.desc().nulls_last()
                if filters.order == "desc"
                else order_col.asc().nulls_last()
            )
        else:
            ordering = order_col.asc() if filters.order == "asc" else order_col.desc()

        # Outer join CategoryTaxonomy on (tenant_id, code) for the label.
        # OUTER so a pruned taxonomy entry surfaces with label_tr=None
        # (the UI treats None as "removed category", distinct from "code
        # itself was the label").
        list_stmt = (
            select(Review, CategoryTaxonomy.label_tr)
            .select_from(Review)
            .outerjoin(
                CategoryTaxonomy,
                and_(
                    CategoryTaxonomy.tenant_id == Review.tenant_id,
                    CategoryTaxonomy.code == Review.company_perspective_code,
                ),
            )
            .where(where_clause)
            .order_by(ordering, desc(Review.id))
            .limit(limit)
            .offset(offset)
        )
        rows = list((await self._session.execute(list_stmt)).all())

        items = [
            ReviewListItem(
                id=r.Review.id,
                text=r.Review.text,
                sentiment_label=r.Review.sentiment_label,
                sentiment_score=float(r.Review.sentiment_score),
                primary_category=r.Review.primary_category,
                primary_confidence=float(r.Review.primary_confidence),
                decision=str(r.Review.decision),
                decision_reason=r.Review.decision_reason,
                ticket_id=r.Review.ticket_id,
                batch_job_id=r.Review.batch_job_id,
                source_type="batch" if r.Review.batch_job_id is not None else "manual",
                analyzed_at=r.Review.analyzed_at,
                review_date=r.Review.review_date,
                submitted_by_user_id=r.Review.submitted_by_user_id,
                # "reanalysis" izi kural katmanı değil — sayaca girerse
                # yeniden analiz sonrası her satır "+1" gösterir.
                override_count=sum(
                    1
                    for hit in (r.Review.overrides_applied or [])
                    if isinstance(hit, dict) and hit.get("layer") != "reanalysis"
                ),
                company_perspective_code=r.Review.company_perspective_code,
                company_perspective_label_tr=r.label_tr,
                experience_type=r.Review.experience_type,
                source_url=r.Review.source_url,
                content_type=r.Review.content_type,
            )
            for r in rows
        ]
        return items, total

    async def summarize(self, *, tenant_id: UUID, filters: ReviewListFilters) -> ReviewSummary:
        """Filter-reactive panel summary over the same rows the list
        would return — GET /tenants/me/reviews/summary. Every bucket
        below shares ``where_clause`` with ``list_reviews`` (built via
        the same ``_build_conditions``) so a filter chip narrows the
        summary exactly like it narrows the list, including
        ``include_flagged`` defaulting to True (the archive convention,
        not the analytics one)."""
        conditions = self._build_conditions(tenant_id=tenant_id, filters=filters)
        where_clause = and_(*conditions)

        # Query A — headline scalars in one round trip: total, average
        # score, NPS bucket counts, ticket-linked count and (B3)
        # viral_negative_count. content_type counts (incl.
        # question_count) come from Query I below — one GROUP BY covers
        # all five values instead of a per-value CASE column here.
        headline_stmt = select(
            func.count().label("total"),
            func.avg(Review.sentiment_score).label("avg_score"),
            func.sum(case((Review.ticket_id.is_not(None), 1), else_=0)).label("ticket_linked"),
            func.sum(case((Review.nps_score.is_not(None), 1), else_=0)).label("with_nps"),
            func.sum(case((Review.nps_category == "promoter", 1), else_=0)).label("promoter"),
            func.sum(case((Review.nps_category == "passive", 1), else_=0)).label("passive"),
            func.sum(case((Review.nps_category == "detractor", 1), else_=0)).label("detractor"),
            func.sum(
                case(
                    (
                        and_(
                            Review.sentiment_label == "NEGATIF",
                            _engagement_expr() >= VIRAL_ENGAGEMENT_THRESHOLD,
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("viral_negative"),
        ).where(where_clause)
        headline = (await self._session.execute(headline_stmt)).one()
        total = int(headline.total or 0)
        avg_sentiment_score = (
            round(float(headline.avg_score), 4) if headline.avg_score is not None else None
        )
        with_nps = int(headline.with_nps or 0)
        promoter = int(headline.promoter or 0)
        detractor = int(headline.detractor or 0)
        nps = NpsSummary(
            promoter=promoter,
            passive=int(headline.passive or 0),
            detractor=detractor,
            with_nps=with_nps,
            score=(round(((promoter - detractor) / with_nps) * 100.0, 1) if with_nps else None),
        )

        # Query B — sentiment distribution. Initialized with all three
        # labels so a bucket with zero rows still reports 0, not
        # "missing".
        sentiment_counts = {"NEGATIF": 0, "NÖTR": 0, "POZITIF": 0}
        sentiment_stmt = (
            select(Review.sentiment_label, func.count())
            .where(where_clause)
            .group_by(Review.sentiment_label)
        )
        for label, cnt in (await self._session.execute(sentiment_stmt)).all():
            sentiment_counts[label] = int(cnt)

        # Query C — top sources, folded like the dimension-values facet.
        sources_stmt = (
            select(
                func.mode().within_group(func.trim(Review.source)).label("value"),
                func.count().label("cnt"),
            )
            .where(and_(*conditions, dimension_value_present(Review.source)))
            .group_by(fold_dimension_key(Review.source))
            .order_by(func.count().desc())
            .limit(10)
        )
        sources = [
            DimensionValueCount(value=r.value, count=int(r.cnt))
            for r in (await self._session.execute(sources_stmt)).all()
        ]

        # Query D — top primary_category buckets. Raw string codes, no
        # taxonomy join (primary_category isn't a taxonomy code).
        categories_stmt = (
            select(
                Review.primary_category,
                func.count().label("cnt"),
                func.sum(case((Review.sentiment_label == "NEGATIF", 1), else_=0)).label("neg_cnt"),
            )
            .where(where_clause)
            .group_by(Review.primary_category)
            .order_by(func.count().desc())
            .limit(10)
        )
        categories = [
            CategoryCount(
                code=r.primary_category, count=int(r.cnt), negative_count=int(r.neg_cnt or 0)
            )
            for r in (await self._session.execute(categories_stmt)).all()
        ]

        # Query E — quality_flag buckets; NULL is the "clean" bucket.
        quality_counts = {
            "clean": 0,
            "duplicate": 0,
            "empty": 0,
            "informational": 0,
            "meaningless": 0,
        }
        quality_stmt = (
            select(Review.quality_flag, func.count())
            .where(where_clause)
            .group_by(Review.quality_flag)
        )
        for flag, cnt in (await self._session.execute(quality_stmt)).all():
            quality_counts["clean" if flag is None else flag] = int(cnt)
        quality = QualitySummary(**quality_counts)

        # Query F — top questions: text_hash buckets among
        # content_type='question' rows, count desc then latest first.
        questions_stmt = (
            select(
                Review.text_hash,
                func.min(Review.text).label("text"),
                func.count().label("cnt"),
                func.max(Review.review_date).label("latest"),
            )
            .where(and_(*conditions, Review.content_type == "question"))
            .group_by(Review.text_hash)
            .order_by(func.count().desc(), func.max(Review.review_date).desc())
            .limit(5)
        )
        top_questions = [
            TopQuestion(text=r.text, count=int(r.cnt))
            for r in (await self._session.execute(questions_stmt)).all()
        ]

        # Query G — per entered_by matrix, folded like the dimension-
        # values facet. Skips NULL/empty entered_by (no "unattributed"
        # bucket — dimension_value_present matches the facet's rule).
        entered_by_stmt = (
            select(
                func.mode().within_group(func.trim(Review.entered_by)).label("value"),
                func.count().label("total"),
                func.sum(case((Review.quality_flag.is_not(None), 1), else_=0)).label("flagged"),
                func.sum(case((Review.content_type == "question", 1), else_=0)).label("question"),
                func.sum(case((Review.sentiment_label == "NEGATIF", 1), else_=0)).label("negative"),
            )
            .where(and_(*conditions, dimension_value_present(Review.entered_by)))
            .group_by(fold_dimension_key(Review.entered_by))
            .order_by(func.count().desc())
            .limit(10)
        )
        entered_by = [
            EnteredByCount(
                value=r.value,
                total=int(r.total),
                flagged=int(r.flagged or 0),
                question=int(r.question or 0),
                negative=int(r.negative or 0),
            )
            for r in (await self._session.execute(entered_by_stmt)).all()
        ]

        # Query H — last 90 daily buckets. Ordered desc + capped inside
        # a subquery, then re-sorted ascending for the chart's x-axis.
        day_col = func.date_trunc("day", Review.review_date)
        daily_subq = (
            select(
                day_col.label("day"),
                func.count().label("cnt"),
                func.sum(case((Review.sentiment_label == "NEGATIF", 1), else_=0)).label("neg"),
            )
            .where(where_clause)
            .group_by(day_col)
            .order_by(day_col.desc())
            .limit(90)
        ).subquery()
        daily_stmt = select(daily_subq.c.day, daily_subq.c.cnt, daily_subq.c.neg).order_by(
            daily_subq.c.day.asc()
        )
        daily = [
            DailyCount(date=r.day.strftime("%Y-%m-%d"), count=int(r.cnt), negative=int(r.neg or 0))
            for r in (await self._session.execute(daily_stmt)).all()
        ]

        # Query I — content_type buckets. All five keys default to 0;
        # NULL (dominant, "plain review") rows are excluded via the
        # WHERE clause rather than left to fall through group_by, same
        # convention Query F uses for the question-only aggregate.
        content_type_counts: dict[str, int] = {
            "question": 0,
            "suggestion": 0,
            "thanks": 0,
            "request": 0,
            "escalation": 0,
        }
        content_type_stmt = (
            select(Review.content_type, func.count())
            .where(and_(*conditions, Review.content_type.is_not(None)))
            .group_by(Review.content_type)
        )
        for ctype, cnt in (await self._session.execute(content_type_stmt)).all():
            if ctype is not None:
                content_type_counts[ctype] = int(cnt)

        return ReviewSummary(
            total=total,
            sentiment=sentiment_counts,
            avg_sentiment_score=avg_sentiment_score,
            nps=nps,
            sources=sources,
            categories=categories,
            quality=quality,
            question_count=content_type_counts["question"],
            content_types=content_type_counts,
            top_questions=top_questions,
            entered_by=entered_by,
            daily=daily,
            ticket_linked=int(headline.ticket_linked or 0),
            viral_negative_count=int(headline.viral_negative or 0),
        )

    async def dimension_values(
        self,
        *,
        tenant_id: UUID,
        field: str,
        include_flagged: bool = True,
    ) -> list[DimensionValueCount]:
        """Distinct values for one business-dimension column — backs
        GET /tenants/me/reviews/dimension-values, the filter-chip
        source for the list UI.

        Folds on ``lower(trim(field))`` like the dimension breakdown
        (``dimension_service.compute_metric_by_dimension``); each
        returned ``value`` is the fold's most-frequent raw spelling.
        Ordered by count desc, capped at 100 — a filter dropdown has
        no use for a long tail. ``include_flagged`` defaults to True
        (unlike the analytics default of False) because this endpoint
        feeds the review list, which is an archive view, not a report.
        """
        if field not in DIMENSION_COLUMNS:
            raise UnknownDimension(f"unknown field {field!r}")
        column = DIMENSION_COLUMNS[field]
        conditions: list[ColumnElement[bool]] = [
            Review.tenant_id == tenant_id,
            Review.deleted_at.is_(None),
            dimension_value_present(column),
        ]
        if not include_flagged:
            conditions.append(Review.quality_flag.is_(None))
        stmt = (
            select(
                func.mode().within_group(func.trim(column)).label("value"),
                func.count().label("cnt"),
            )
            .where(and_(*conditions))
            .group_by(fold_dimension_key(column))
            .order_by(func.count().desc())
            .limit(100)
        )
        rows = (await self._session.execute(stmt)).all()
        return [DimensionValueCount(value=r.value, count=int(r.cnt)) for r in rows]

    async def get_review(
        self, *, tenant_id: UUID, review_id: UUID
    ) -> tuple[Review, str | None] | None:
        """Return ``(review, perspective_label_tr)`` or None on miss.

        ``perspective_label_tr`` is None when either the review's
        ``company_perspective_code`` is NULL (heuristic didn't fire) or
        the taxonomy row was pruned after analyze (Sprint 8.3.7 edits).
        Callers distinguish via ``review.company_perspective_code``.
        """
        stmt = (
            select(Review, CategoryTaxonomy.label_tr)
            .select_from(Review)
            .outerjoin(
                CategoryTaxonomy,
                and_(
                    CategoryTaxonomy.tenant_id == Review.tenant_id,
                    CategoryTaxonomy.code == Review.company_perspective_code,
                ),
            )
            .where(Review.tenant_id == tenant_id)
            .where(Review.id == review_id)
            .where(Review.deleted_at.is_(None))
        )
        row = (await self._session.execute(stmt)).first()
        if row is None:
            return None
        return row.Review, row.label_tr


__all__ = [
    "CategoryCount",
    "DailyCount",
    "DimensionValueCount",
    "EnteredByCount",
    "NpsSummary",
    "QualitySummary",
    "ReviewListFilters",
    "ReviewListItem",
    "ReviewListService",
    "ReviewSummary",
    "TopQuestion",
]
