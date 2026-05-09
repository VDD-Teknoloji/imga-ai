"""Sprint 9.2 D — recurring briefing schedule lifecycle.

The arq cron worker scans ``WHERE enabled AND next_run_at <= NOW()``
every 5 minutes; this service owns the CRUD that creates / edits /
runs / reschedules those rows, plus the next-fire-time calculator
that's used at create + reschedule time.

Delivery is "Generate-and-link" (Sprint 9.2 D): the cron task calls
``ExecutiveBriefingService.generate(...)`` which inserts an
``executive_briefings`` row; the schedule's ``last_run_briefing_id``
points at that row so a recipient's dashboard can surface "Yeni
brifing geldi (2026-05-14, aylık)" without a separate notifications
table.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from imga_db.models import BriefingSchedule
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_logger = logging.getLogger(__name__)


class BriefingScheduleError(Exception):
    """Maps to a 4xx in the route handler."""


class ScheduleNotFound(BriefingScheduleError):
    """Schedule id missing in the active tenant scope."""


@dataclass(frozen=True, slots=True)
class ScheduleSpec:
    """Inputs for compute_next_run_at — pure function call site."""

    period: str  # 'weekly' | 'monthly'
    schedule_day: int  # weekly: 0-6 Mon-Sun, monthly: 1-28
    schedule_hour: int  # 0-23
    timezone: str  # IANA tz, e.g. 'Europe/Istanbul'


def compute_next_run_at(
    spec: ScheduleSpec,
    *,
    after: datetime | None = None,
) -> datetime:
    """Find the next instant matching the spec, strictly after
    ``after`` (default now). Returned in UTC for DB storage; the
    schedule's source-of-truth wall clock is the tenant's tz so a
    daylight-saving shift doesn't move the briefing's local time.
    """
    tz = ZoneInfo(spec.timezone)
    base = (after or datetime.now(UTC)).astimezone(tz)
    candidate = base.replace(
        hour=spec.schedule_hour, minute=0, second=0, microsecond=0
    )
    if candidate <= base:
        candidate += timedelta(days=1)
    if spec.period == "weekly":
        # Python: Mon=0..Sun=6 (matches our schedule_day convention).
        for _ in range(7):
            if candidate.weekday() == spec.schedule_day:
                break
            candidate += timedelta(days=1)
    elif spec.period == "monthly":
        # Walk forward one day at a time; max 28 iterations covers
        # every month including leap-Feb (schedule_day 1-28 cap is
        # enforced by the CHECK constraint).
        for _ in range(35):
            if candidate.day == spec.schedule_day:
                break
            candidate += timedelta(days=1)
    else:
        raise ValueError(f"unknown period {spec.period!r}")
    return candidate.astimezone(UTC)


class BriefingScheduleService:
    """All public methods are session-bound; callers wrap them in
    their own transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_tenant(
        self, *, tenant_id: UUID
    ) -> list[BriefingSchedule]:
        stmt = (
            select(BriefingSchedule)
            .where(BriefingSchedule.tenant_id == tenant_id)
            .order_by(BriefingSchedule.created_at.desc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def fetch_due(
        self,
        *,
        as_of: datetime | None = None,
        limit: int = 50,
    ) -> list[BriefingSchedule]:
        """Worker hot path — returns enabled rows whose next_run_at is
        in the past. Limit caps the per-tick batch so a one-time burst
        of due schedules doesn't lock the worker for too long."""
        cutoff = as_of or datetime.now(UTC)
        stmt = (
            select(BriefingSchedule)
            .where(BriefingSchedule.enabled.is_(True))
            .where(BriefingSchedule.next_run_at <= cutoff)
            .order_by(BriefingSchedule.next_run_at.asc())
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def create(
        self,
        *,
        tenant_id: UUID,
        period: str,
        schedule_day: int,
        schedule_hour: int = 9,
        timezone: str = "Europe/Istanbul",
        recipients: list[UUID] | None = None,
        email_recipients: list[str] | None = None,
        enabled: bool = True,
    ) -> BriefingSchedule:
        if period not in ("weekly", "monthly"):
            raise BriefingScheduleError(
                f"period must be 'weekly' or 'monthly', got {period!r}"
            )
        spec = ScheduleSpec(
            period=period,
            schedule_day=schedule_day,
            schedule_hour=schedule_hour,
            timezone=timezone,
        )
        try:
            next_run = compute_next_run_at(spec)
        except ValueError as exc:
            raise BriefingScheduleError(str(exc)) from exc
        row = BriefingSchedule(
            tenant_id=tenant_id,
            period=period,
            schedule_day=schedule_day,
            schedule_hour=schedule_hour,
            timezone=timezone,
            recipients=recipients or [],
            email_recipients=email_recipients or [],
            enabled=enabled,
            next_run_at=next_run,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def update(
        self,
        *,
        schedule_id: UUID,
        tenant_id: UUID,
        enabled: bool | None = None,
        schedule_day: int | None = None,
        schedule_hour: int | None = None,
        recipients: list[UUID] | None = None,
        email_recipients: list[str] | None = None,
    ) -> BriefingSchedule:
        row = await self._session.get(BriefingSchedule, schedule_id)
        if row is None or row.tenant_id != tenant_id:
            raise ScheduleNotFound(
                f"schedule {schedule_id} not in tenant {tenant_id}"
            )
        if enabled is not None:
            row.enabled = enabled
        day_changed = False
        if schedule_day is not None and schedule_day != row.schedule_day:
            row.schedule_day = schedule_day
            day_changed = True
        hour_changed = False
        if schedule_hour is not None and schedule_hour != row.schedule_hour:
            row.schedule_hour = schedule_hour
            hour_changed = True
        if recipients is not None:
            row.recipients = recipients
        if email_recipients is not None:
            row.email_recipients = email_recipients
        if day_changed or hour_changed:
            row.next_run_at = compute_next_run_at(
                ScheduleSpec(
                    period=row.period,
                    schedule_day=row.schedule_day,
                    schedule_hour=row.schedule_hour,
                    timezone=row.timezone,
                )
            )
        await self._session.flush()
        return row

    async def delete(
        self, *, schedule_id: UUID, tenant_id: UUID
    ) -> None:
        row = await self._session.get(BriefingSchedule, schedule_id)
        if row is None or row.tenant_id != tenant_id:
            raise ScheduleNotFound(
                f"schedule {schedule_id} not in tenant {tenant_id}"
            )
        await self._session.delete(row)
        await self._session.flush()

    async def record_run(
        self,
        *,
        schedule: BriefingSchedule,
        status: str,
        briefing_id: UUID | None = None,
        error: str | None = None,
        ran_at: datetime | None = None,
    ) -> None:
        """Worker calls this after each run (success OR failed). The
        method updates the audit columns and advances next_run_at to
        the next slot in the schedule."""
        if status not in ("success", "failed"):
            raise BriefingScheduleError(
                f"status must be 'success' or 'failed', got {status!r}"
            )
        schedule.last_run_at = ran_at or datetime.now(UTC)
        schedule.last_run_status = status
        schedule.last_run_briefing_id = briefing_id
        schedule.last_run_error = error
        schedule.next_run_at = compute_next_run_at(
            ScheduleSpec(
                period=schedule.period,
                schedule_day=schedule.schedule_day,
                schedule_hour=schedule.schedule_hour,
                timezone=schedule.timezone,
            ),
            after=schedule.last_run_at,
        )
        await self._session.flush()


__all__ = [
    "BriefingScheduleError",
    "BriefingScheduleService",
    "ScheduleNotFound",
    "ScheduleSpec",
    "compute_next_run_at",
]
