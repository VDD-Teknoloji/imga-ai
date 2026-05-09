"""Sprint 9.2 D — arq cron worker for scheduled briefings.

Wakes every 5 minutes (cron job ``minute={0,5,...,55}``), scans
``briefing_schedules WHERE enabled AND next_run_at <= now()``, and
runs each due schedule:

  1. Generate the briefing via ``ExecutiveBriefingService.generate(...)``.
     Best-effort — a failed generation marks the schedule
     ``last_run_status='failed'`` and advances ``next_run_at`` so the
     next tick doesn't keep retrying the same broken row forever.

  2. Persist the run audit + advance the cursor via
     ``BriefingScheduleService.record_run``.

  3. Optional email dispatch — guarded on ``IMGA_SMTP_HOST``. If the
     env var isn't set the service logs the would-be send (so an
     audit trail exists) and no-ops. Today's stack has no SMTP
     wired; a future sprint that adds it flips this branch on
     without code changes here.

The recipients column is the source of truth for who sees the
briefing in their dashboard's "Recent briefings" widget — that
filter happens at read time on the executive_briefings list
endpoint, not here.

logger.exception() in every catch path — Sprint 8.3.6.6 round-3
baseline note.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from imga_db import set_current_tenant
from imga_db.models import BriefingSchedule

from imga_api.services.briefing_period_mapper import (
    map_schedule_period_to_generate_period,
)
from imga_api.services.briefing_schedule_service import BriefingScheduleService
from imga_api.services.executive_briefing_service import (
    ExecutiveBriefingService,
)

_logger = logging.getLogger("imga-api.workers.scheduled_briefings")


_PERIOD_DAYS: dict[str, int] = {"weekly": 7, "monthly": 30}


async def scheduled_briefing_tick(ctx: dict[str, Any]) -> None:
    """arq cron entry — runs every 5 minutes from
    ``WorkerSettings.cron_jobs``. Idempotent: if the worker reaps
    the same row twice (rare; would only happen on a duplicate
    enqueue), the second pass sees ``next_run_at`` already advanced
    and the row drops out of the due-set.

    Pulls the worker context the batch task uses (admin engine pool
    + redis publisher etc.) so we don't reopen connections per run.
    """
    worker_context = ctx.get("worker_context")
    if worker_context is None:
        _logger.warning(
            "scheduled briefing tick: worker_context missing; "
            "the cron fired before startup completed"
        )
        return

    factory = worker_context.admin_session_factory
    async with factory() as session:
        async with session.begin():
            schedule_service = BriefingScheduleService(session)
            due = await schedule_service.fetch_due()
        if not due:
            return
        _logger.info(
            "scheduled briefing tick: %d schedule(s) due", len(due)
        )

    for schedule in due:
        try:
            await _run_schedule(factory, schedule)
        except Exception:
            # _run_schedule already records the failure on the row;
            # this catch is the outer safety net so one bad schedule
            # can't break the rest of the tick's batch.
            _logger.exception(
                "scheduled briefing failed", extra={
                    "schedule_id": str(schedule.id),
                    "tenant_id": str(schedule.tenant_id),
                },
            )


async def _run_schedule(
    factory: Any,
    schedule: BriefingSchedule,
) -> None:
    """Run one schedule end-to-end. Each schedule gets its own
    session so a transaction abort on the briefing path doesn't roll
    back another schedule's ``record_run``."""
    tenant_id = schedule.tenant_id
    period = schedule.period
    today = datetime.now(UTC).date()
    if period in _PERIOD_DAYS:
        date_to = today
        date_from = today - timedelta(days=_PERIOD_DAYS[period])
    else:
        # Defensive: the CHECK constraint enforces 'weekly' / 'monthly'.
        date_to = today
        date_from = today - timedelta(days=30)

    started = datetime.now(UTC)
    briefing_id: UUID | None = None
    status = "success"
    error: str | None = None

    try:
        async with factory() as session:
            async with session.begin():
                await set_current_tenant(session, tenant_id)
                briefing_service = ExecutiveBriefingService(
                    session=session,
                    tenant_id=tenant_id,
                    user_id=None,  # System-driven; no actor user.
                )
                # Sprint 9.4 A — schedule.period is weekly/monthly;
                # generate() expects week/month/quarter.
                generate_period = map_schedule_period_to_generate_period(
                    period
                )
                payload = await briefing_service.generate(
                    period=generate_period,
                    date_from=date_from,
                    date_to=date_to,
                )
                # ExecutiveBriefingService.generate persists the row
                # and returns its full payload including ``id``.
                raw_id = payload.get("id")
                if isinstance(raw_id, UUID):
                    briefing_id = raw_id
                elif isinstance(raw_id, str):
                    try:
                        briefing_id = UUID(raw_id)
                    except ValueError:
                        briefing_id = None
    except Exception as exc:
        status = "failed"
        error = str(exc)[:1024]
        _logger.exception(
            "scheduled briefing generation failed",
            extra={
                "schedule_id": str(schedule.id),
                "tenant_id": str(tenant_id),
                "period": period,
            },
        )

    # Email dispatch — Sprint 9.2 D ships the gate but no transport.
    # The branch logs would-be sends so an audit exists when SMTP
    # comes online.
    if (
        status == "success"
        and briefing_id is not None
        and schedule.email_recipients
    ):
        if not _smtp_configured():
            _logger.info(
                "scheduled briefing: SMTP not configured, skipping "
                "email dispatch (briefing %s, %d recipient(s))",
                briefing_id,
                len(schedule.email_recipients),
            )

    # Persist the run audit + advance next_run_at. Done in its own
    # session so the briefing transaction's commit/rollback doesn't
    # influence the audit row.
    async with factory() as session:
        async with session.begin():
            await set_current_tenant(session, tenant_id)
            schedule_service = BriefingScheduleService(session)
            # Re-fetch in this session so the ORM has a managed row.
            row = await session.get(BriefingSchedule, schedule.id)
            if row is None:
                _logger.warning(
                    "scheduled briefing: schedule %s vanished mid-run",
                    schedule.id,
                )
                return
            await schedule_service.record_run(
                schedule=row,
                status=status,
                briefing_id=briefing_id,
                error=error,
                ran_at=started,
            )

    if status == "success":
        _logger.info(
            "scheduled briefing run ok",
            extra={
                "schedule_id": str(schedule.id),
                "tenant_id": str(tenant_id),
                "period": period,
                "briefing_id": str(briefing_id) if briefing_id else None,
            },
        )


def _smtp_configured() -> bool:
    return bool(os.environ.get("IMGA_SMTP_HOST", "").strip())


__all__ = [
    "scheduled_briefing_tick",
]
