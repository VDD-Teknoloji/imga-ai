"""Sprint 9.4 A — schedule period → briefing-generator period mapping.

The DB CHECK constraint pins ``briefing_schedules.period`` to
``weekly``/``monthly`` but ``ExecutiveBriefingService.generate``
consumes ``week``/``month``/``quarter`` (the date-window keys).
Both run-now and the cron worker were passing the schedule value
straight through, hitting a ValueError every time and silently
flipping ``last_run_status='failed'`` while the route returned 200.

The fix is a one-line lookup; this module exists so both call
sites share the same mapping (and the same ValueError contract)
instead of duplicating the dict.
"""

from __future__ import annotations

SCHEDULE_PERIOD_TO_GENERATE_PERIOD: dict[str, str] = {
    "weekly": "week",
    "monthly": "month",
    # Reserved for the day we add quarterly schedules — the DB
    # CHECK rejects this today, but mapping it here means a future
    # migration that loosens the CHECK doesn't need to revisit
    # both call sites.
    "quarterly": "quarter",
}


def map_schedule_period_to_generate_period(schedule_period: str) -> str:
    """Translate a ``briefing_schedules.period`` value (DB-shape) to
    the ``ExecutiveBriefingService.generate(period=...)`` value
    (date-window-shape).

    Raises ``ValueError`` for unknown inputs. Callers should treat
    a raise as a programming error (the CHECK constraint should
    have caught it on insert), not as an expected branch."""
    try:
        return SCHEDULE_PERIOD_TO_GENERATE_PERIOD[schedule_period]
    except KeyError as exc:
        raise ValueError(
            f"unknown schedule period {schedule_period!r}; "
            f"expected one of {sorted(SCHEDULE_PERIOD_TO_GENERATE_PERIOD)}"
        ) from exc


__all__ = [
    "SCHEDULE_PERIOD_TO_GENERATE_PERIOD",
    "map_schedule_period_to_generate_period",
]
