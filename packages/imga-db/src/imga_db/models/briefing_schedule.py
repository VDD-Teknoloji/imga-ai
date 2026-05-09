"""BriefingSchedule — recurring weekly/monthly briefing trigger.

Sprint 9.2 D. RLS+FORCE; the arq cron worker scans
``WHERE enabled AND next_run_at <= NOW()`` every 5 minutes for due
rows. After each run the worker writes ``last_run_at`` /
``last_run_briefing_id`` / ``last_run_status`` (success or failed)
and advances ``next_run_at`` to the next valid slot in the schedule.

``recipients`` (UUIDs) drives the Generate-and-link delivery — the
dashboard's "Recent briefings" widget queries
``executive_briefings`` joined against the user's most recent
schedule run. ``email_recipients`` is a TEXT[] for external
addresses; the delivery service skips it gracefully when no SMTP
infra is configured (logs the would-be send, no-ops).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from imga_db.base import Base


class BriefingSchedule(Base):
    __tablename__ = "briefing_schedules"
    __table_args__ = (
        CheckConstraint(
            "period IN ('weekly', 'monthly')",
            name="ck_briefing_schedules_period",
        ),
        CheckConstraint(
            "schedule_hour BETWEEN 0 AND 23",
            name="ck_briefing_schedules_hour",
        ),
        CheckConstraint(
            "(period = 'weekly' AND schedule_day BETWEEN 0 AND 6) OR "
            "(period = 'monthly' AND schedule_day BETWEEN 1 AND 28)",
            name="ck_briefing_schedules_day",
        ),
        CheckConstraint(
            "last_run_status IS NULL OR last_run_status IN ('success', 'failed')",
            name="ck_briefing_schedules_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    period: Mapped[str] = mapped_column(Text(), nullable=False)
    schedule_day: Mapped[int] = mapped_column(Integer(), nullable=False)
    schedule_hour: Mapped[int] = mapped_column(
        Integer(), nullable=False, default=9
    )
    timezone: Mapped[str] = mapped_column(
        Text(), nullable=False, default="Europe/Istanbul"
    )
    recipients: Mapped[list[UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=False, default=list
    )
    email_recipients: Mapped[list[str]] = mapped_column(
        ARRAY(Text()), nullable=False, default=list
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean(), nullable=False, default=True
    )
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_run_briefing_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("executive_briefings.id", ondelete="SET NULL"),
        nullable=True,
    )
    last_run_status: Mapped[str | None] = mapped_column(Text(), nullable=True)
    last_run_error: Mapped[str | None] = mapped_column(Text(), nullable=True)
    next_run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
