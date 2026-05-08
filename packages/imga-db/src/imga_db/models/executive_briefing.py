"""ExecutiveBriefing model — per-period executive summary.

Sprint 8.3.10. Same shape family as StrategicReport (LLM-generated +
input_stats + output payload) but a separate table because the
generation cadence + prompt context + cache TTL differ.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from imga_db.base import Base


class ExecutiveBriefing(Base):
    __tablename__ = "executive_briefings"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    period: Mapped[str] = mapped_column(String(16), nullable=False)
    date_from: Mapped[date] = mapped_column(Date(), nullable=False)
    date_to: Mapped[date] = mapped_column(Date(), nullable=False)
    batch_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("analyze_batch_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
    headline: Mapped[str] = mapped_column(Text(), nullable=False)
    kpi_changes: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB(), nullable=False, default=list
    )
    critical_insights: Mapped[list[str]] = mapped_column(
        JSONB(), nullable=False, default=list
    )
    top_actions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB(), nullable=False, default=list
    )
    input_stats: Mapped[dict[str, Any]] = mapped_column(
        JSONB(), nullable=False, default=dict
    )
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)
    token_usage: Mapped[dict[str, int] | None] = mapped_column(
        JSONB(), nullable=True
    )
    generation_duration_ms: Mapped[int | None] = mapped_column(
        Integer(), nullable=True
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Sprint 9.0.5-B G — top_actions linkage. ``top_actions`` JSONB
    # stays the LLM-authored prose payload; this column carries the
    # ActionItem row ids that the action-extraction pipeline
    # produced from that prose, so the frontend can JOIN to render
    # status/priority/assignee on each "follow up" card.
    top_action_item_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=False, default=list
    )
