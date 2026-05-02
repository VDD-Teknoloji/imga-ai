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

from imga_db.models import Review
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

        where_clause = and_(*conditions)

        count_stmt = select(func.count()).select_from(Review).where(where_clause)
        total: int = (await self._session.execute(count_stmt)).scalar_one()

        order_col = (
            Review.created_at
            if filters.order_by == "created_at"
            else Review.sentiment_score
        )
        ordering = order_col.asc() if filters.order == "asc" else order_col.desc()

        list_stmt = (
            select(Review)
            .where(where_clause)
            .order_by(ordering, desc(Review.id))
            .limit(limit)
            .offset(offset)
        )
        rows = list((await self._session.execute(list_stmt)).scalars())

        items = [
            ReviewListItem(
                id=r.id,
                text=r.text,
                sentiment_label=r.sentiment_label,
                sentiment_score=float(r.sentiment_score),
                primary_category=r.primary_category,
                primary_confidence=float(r.primary_confidence),
                decision=str(r.decision),
                decision_reason=r.decision_reason,
                ticket_id=r.ticket_id,
                batch_job_id=r.batch_job_id,
                source_type="batch" if r.batch_job_id is not None else "manual",
                analyzed_at=r.analyzed_at,
                submitted_by_user_id=r.submitted_by_user_id,
                override_count=len(r.overrides_applied) if r.overrides_applied else 0,
            )
            for r in rows
        ]
        return items, total

    async def get_review(
        self, *, tenant_id: UUID, review_id: UUID
    ) -> Review | None:
        stmt = (
            select(Review)
            .where(Review.tenant_id == tenant_id)
            .where(Review.id == review_id)
            .where(Review.deleted_at.is_(None))
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()


_ = Any  # keep mypy quiet about the imported name when callers don't use it.

__all__ = ["ReviewListFilters", "ReviewListItem", "ReviewListService"]
