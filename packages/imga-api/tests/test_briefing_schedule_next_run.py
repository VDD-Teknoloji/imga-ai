"""Sprint 9.2 D — compute_next_run_at unit tests.

The cron worker scans ``briefing_schedules WHERE next_run_at <=
NOW()``; getting next_run_at wrong means a schedule fires every
tick (next_run_at stays in the past) or never fires (next_run_at
is in the wrong week / month).

Pure-function tests — Europe/Istanbul tz, deterministic ``after``
inputs.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from imga_api.services.briefing_schedule_service import (
    ScheduleSpec,
    compute_next_run_at,
)

_TR = ZoneInfo("Europe/Istanbul")


def _local(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=_TR).astimezone(UTC)


def test_weekly_advances_to_next_matching_weekday() -> None:
    # Monday 2026-05-04 at 14:00 TR → next Wed 09:00 TR.
    after = _local(2026, 5, 4, 14)
    spec = ScheduleSpec(
        period="weekly",
        schedule_day=2,  # Wednesday
        schedule_hour=9,
        timezone="Europe/Istanbul",
    )
    next_run = compute_next_run_at(spec, after=after)
    next_local = next_run.astimezone(_TR)
    assert next_local.weekday() == 2  # Wed
    assert next_local.hour == 9
    assert next_local.date().isoformat() == "2026-05-06"


def test_weekly_same_day_after_hour_advances_seven_days() -> None:
    """If today is the schedule_day but the hour has passed, the
    next run is one week from now."""
    # Wednesday 2026-05-06 at 10:00 TR (after 09:00 schedule hour).
    after = _local(2026, 5, 6, 10)
    spec = ScheduleSpec(
        period="weekly",
        schedule_day=2,  # Wednesday
        schedule_hour=9,
        timezone="Europe/Istanbul",
    )
    next_run = compute_next_run_at(spec, after=after)
    next_local = next_run.astimezone(_TR)
    assert next_local.date().isoformat() == "2026-05-13"  # next Wed


def test_weekly_same_day_before_hour_advances_today() -> None:
    """If today is the schedule_day and the hour hasn't passed, fire
    today."""
    after = _local(2026, 5, 6, 7)  # Wed 07:00 TR
    spec = ScheduleSpec(
        period="weekly",
        schedule_day=2,  # Wed
        schedule_hour=9,
        timezone="Europe/Istanbul",
    )
    next_run = compute_next_run_at(spec, after=after)
    next_local = next_run.astimezone(_TR)
    assert next_local.date().isoformat() == "2026-05-06"
    assert next_local.hour == 9


def test_monthly_advances_to_next_day_of_month() -> None:
    # 2026-05-10 14:00 TR with schedule_day=15 → 2026-05-15 09:00 TR.
    after = _local(2026, 5, 10, 14)
    spec = ScheduleSpec(
        period="monthly",
        schedule_day=15,
        schedule_hour=9,
        timezone="Europe/Istanbul",
    )
    next_run = compute_next_run_at(spec, after=after)
    next_local = next_run.astimezone(_TR)
    assert next_local.date().isoformat() == "2026-05-15"


def test_monthly_after_target_day_advances_next_month() -> None:
    # 2026-05-20 14:00 TR with schedule_day=15 → 2026-06-15 09:00 TR.
    after = _local(2026, 5, 20, 14)
    spec = ScheduleSpec(
        period="monthly",
        schedule_day=15,
        schedule_hour=9,
        timezone="Europe/Istanbul",
    )
    next_run = compute_next_run_at(spec, after=after)
    next_local = next_run.astimezone(_TR)
    assert next_local.date().isoformat() == "2026-06-15"


def test_unknown_period_raises() -> None:
    import pytest

    spec = ScheduleSpec(
        period="annually",  # not a valid value
        schedule_day=1,
        schedule_hour=9,
        timezone="Europe/Istanbul",
    )
    with pytest.raises(ValueError, match="unknown period"):
        compute_next_run_at(spec, after=_local(2026, 5, 1, 12))
