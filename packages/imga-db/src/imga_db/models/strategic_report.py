"""StrategicReport model — historical SWOT / OKR run.

Sprint 8.3.6 / Alt-Faz 8.3.6.1.F. Append-only audit + replay log of
every SWOT or OKR generation. ``input_stats`` is the JSONB analytics
snapshot the LLM was fed (date range, sentiment dist, top categories,
etc); ``output_payload`` is the structured response (matches the
prompt template's response_schema).

OKR rows that descend from a SWOT carry ``source_report_id`` pointing
at the SWOT row — the chain lets the UI render "this OKR was based on
the 2026-04 SWOT" without recomputing.

RLS+FORCE on tenant_id (migration 0019) — same convention every
tenant-scoped table since 0001.

``token_usage`` + ``generation_duration_ms`` give cheap cost / latency
observability without a separate metrics table; the rotator writes
them when the Gemini SDK returns usage data (some providers don't).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from imga_db.base import Base


class StrategicReport(Base):
    __tablename__ = "strategic_reports"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )

    # "swot" | "okr". Plain VARCHAR — adding a third type (e.g. "pestle"
    # in a future sprint) doesn't need a schema migration.
    report_type: Mapped[str] = mapped_column(String(16), nullable=False)

    # Date window the report covers. NULL when the trigger was tenant-
    # wide / all-time (Sprint 8.3.6 surfaces a date picker; defaulting
    # to NULL for "everything").
    date_from: Mapped[date | None] = mapped_column(Date(), nullable=True)
    date_to: Mapped[date | None] = mapped_column(Date(), nullable=True)

    # Analytics snapshot fed into the prompt. Stored as JSONB so a
    # follow-up query can join on key fields (e.g. find all SWOT runs
    # where total_reviews exceeded 1000).
    input_stats: Mapped[dict[str, Any]] = mapped_column(JSONB(), nullable=False)

    # Structured LLM response. Schema enforced by the prompt template's
    # response_schema (Sprint 8.3.6.3 / 8.3.6.4 finalises the shapes).
    output_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB(), nullable=False
    )

    # OKR rows that descended from a SWOT carry the parent SWOT id.
    # ON DELETE SET NULL — if the parent SWOT is later soft-deleted,
    # the OKR survives but loses the back-pointer.
    source_report_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("strategic_reports.id", ondelete="SET NULL"),
        nullable=True,
    )

    # "gemini-2.5-pro" / "gemini-2.0-flash" / etc. Plain VARCHAR.
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)

    # {"input": <int>, "output": <int>} — provider-dependent. NULL when
    # the SDK didn't return usage. Cheap observability; no quota
    # tracking in 8.3.6.
    token_usage: Mapped[dict[str, Any] | None] = mapped_column(
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
