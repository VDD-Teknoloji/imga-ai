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
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

OrderField = Literal["created_at", "sentiment_score"]
OrderDir = Literal["asc", "desc"]


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
    # Sprint 9.5 B1 — time-extract filters for the /insights heatmap
    # cell-click drilldown. Each is an integer or None; non-None
    # values are compared against ``EXTRACT(<part> FROM created_at)``.
    # The heatmap_generator emits matching x_keys / y_keys on the
    # response so the frontend can wire the click without
    # re-deriving the axis numerics.
    hour_of_day: int | None = None  # 0..23
    day_of_week: int | None = None  # 0..6 (postgres DOW: 0=Sun..6=Sat)
    week_of_year: int | None = None  # 1..53
    month: int | None = None  # 1..12
    search: str | None = None  # ILIKE %term% over text
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


class ReviewListService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

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
        conditions = [Review.tenant_id == tenant_id, Review.deleted_at.is_(None)]
        if filters.date_from is not None:
            conditions.append(Review.analyzed_at >= filters.date_from)
        if filters.date_to is not None:
            conditions.append(Review.analyzed_at <= filters.date_to)
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
            real_codes = tuple(
                c for c in filters.perspective_codes if c != "__unmatched__"
            )
            include_unmatched = "__unmatched__" in filters.perspective_codes
            persp_clauses: list[ColumnElement[bool]] = []
            if real_codes:
                persp_clauses.append(
                    Review.company_perspective_code.in_(real_codes)
                )
            if include_unmatched:
                persp_clauses.append(Review.company_perspective_code.is_(None))
            if persp_clauses:
                conditions.append(or_(*persp_clauses))
        # Sprint 8.3.10 — cross-analysis heatmap drill-down lands here.
        if filters.primary_categories:
            conditions.append(
                Review.primary_category.in_(filters.primary_categories)
            )
        # Sprint 9.5 B1 — heatmap cell-click drilldown. The four
        # extract conditions mirror the heatmap_generator's axis
        # expressions (``_axis_expr``) so the cell's "rows in this
        # bucket" equation matches exactly. Created_at (not
        # analyzed_at) is the heatmap's source column.
        if filters.hour_of_day is not None:
            conditions.append(
                func.extract("hour", Review.created_at)
                == filters.hour_of_day
            )
        if filters.day_of_week is not None:
            conditions.append(
                func.extract("dow", Review.created_at)
                == filters.day_of_week
            )
        if filters.week_of_year is not None:
            conditions.append(
                func.extract("week", Review.created_at)
                == filters.week_of_year
            )
        if filters.month is not None:
            conditions.append(
                func.extract("month", Review.created_at)
                == filters.month
            )

        where_clause = and_(*conditions)

        count_stmt = select(func.count()).select_from(Review).where(where_clause)
        total: int = (await self._session.execute(count_stmt)).scalar_one()

        order_col = (
            Review.created_at
            if filters.order_by == "created_at"
            else Review.sentiment_score
        )
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
                submitted_by_user_id=r.Review.submitted_by_user_id,
                override_count=len(r.Review.overrides_applied)
                if r.Review.overrides_applied
                else 0,
                company_perspective_code=r.Review.company_perspective_code,
                company_perspective_label_tr=r.label_tr,
            )
            for r in rows
        ]
        return items, total

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


_ = Any  # keep mypy quiet about the imported name when callers don't use it.

__all__ = ["ReviewListFilters", "ReviewListItem", "ReviewListService"]
