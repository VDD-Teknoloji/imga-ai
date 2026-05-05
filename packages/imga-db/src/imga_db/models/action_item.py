"""ActionItem model — trackable task extracted from a SWOT or briefing.

Sprint 8.3.10. Source can be a strategic_reports row (SWOT
recommendations), an executive_briefings row (top_actions), or
manual entry (both source FKs NULL). Status transitions are
free-form; the API enforces ``open → in_progress → done`` /
``open → cancelled`` linearly but the model accepts any of the
four documented states for simplicity.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import Date, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from imga_db.base import Base


class ActionItem(Base):
    __tablename__ = "action_items"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_report_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("strategic_reports.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_briefing_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("executive_briefings.id", ondelete="SET NULL"),
        nullable=True,
    )

    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text(), nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text(), nullable=True)

    priority: Mapped[str] = mapped_column(
        String(16), nullable=False, default="medium"
    )
    estimated_impact: Mapped[str | None] = mapped_column(
        String(16), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="open"
    )

    assignee_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    due_date: Mapped[date | None] = mapped_column(Date(), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
