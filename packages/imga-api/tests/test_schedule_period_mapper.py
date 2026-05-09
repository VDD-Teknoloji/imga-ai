"""Sprint 9.4 A — schedule period mapper unit tests.

The DB CHECK constraint pins ``briefing_schedules.period`` to
``weekly`` / ``monthly`` and the briefing generator expects
``week`` / ``month`` / ``quarter``. Sprint 9.0.5 → 9.3 ran with
the unmapped value, silently flipping every scheduled run to
``failed`` while the run-now route returned 200.

These tests pin the mapping so a future provider swap or a typo
in the lookup dict surfaces here instead of in production logs.
"""

from __future__ import annotations

import pytest

from imga_api.services.briefing_period_mapper import (
    SCHEDULE_PERIOD_TO_GENERATE_PERIOD,
    map_schedule_period_to_generate_period,
)


def test_weekly_maps_to_week() -> None:
    assert map_schedule_period_to_generate_period("weekly") == "week"


def test_monthly_maps_to_month() -> None:
    assert map_schedule_period_to_generate_period("monthly") == "month"


def test_quarterly_maps_to_quarter_for_future_use() -> None:
    """Reserved key — DB CHECK rejects ``quarterly`` today, but the
    mapping is in place so a future CHECK loosening doesn't need a
    parallel patch in the run-now route + cron worker."""
    assert map_schedule_period_to_generate_period("quarterly") == "quarter"


def test_unknown_period_raises_value_error() -> None:
    with pytest.raises(ValueError, match="unknown schedule period"):
        map_schedule_period_to_generate_period("daily")


def test_lookup_table_is_complete_for_db_check_values() -> None:
    """If the DB CHECK constraint is ever extended to cover a new
    period, the mapping must be extended at the same time. This
    test pins the current key set so a forgotten update surfaces."""
    assert set(SCHEDULE_PERIOD_TO_GENERATE_PERIOD) == {
        "weekly",
        "monthly",
        "quarterly",
    }
