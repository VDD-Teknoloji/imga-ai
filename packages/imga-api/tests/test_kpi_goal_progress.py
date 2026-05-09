"""Sprint 9.2 B — KpiGoalService.compute_progress unit tests.

The progress math is direction-aware: NPS / CSAT use straight
``current / target``; lower-is-better metrics
(manual_review_rate, category_concentration) invert. The route
layer's bulk endpoint binds these results to the dashboard cards,
so a regression here flips the wrong card to "yolda" and an
operator misreads their KPI status.

Pure-function tests — no DB, no fixtures.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

from imga_api.services.kpi_goal_service import KpiGoalService


class _FakeGoal:
    """Stand-in for ``TenantKpiGoal`` — only the fields
    ``compute_progress`` reads."""

    def __init__(
        self,
        metric_key: str,
        target_value: float,
    ) -> None:
        self.metric_key = metric_key
        self.target_value = Decimal(str(target_value))
        self.target_period = "monthly"
        self.period_start = date(2026, 5, 1)
        self.period_end = date(2026, 5, 31)
        self.tenant_id = uuid4()
        self.id = uuid4()
        self.set_at = datetime.now(UTC)


# --- higher_is_better metrics ---


def test_progress_higher_is_better_on_track_at_92pct() -> None:
    goal = _FakeGoal("nps", target_value=70.0)
    p = KpiGoalService.compute_progress(goal, current_value=65.0)
    # 65/70 = 92.86% — above the 90% on-track threshold.
    assert p.achievement_pct == 92.86
    assert p.on_track is True
    assert p.higher_is_better is True


def test_progress_higher_is_better_below_threshold_off_track() -> None:
    goal = _FakeGoal("nps", target_value=70.0)
    p = KpiGoalService.compute_progress(goal, current_value=50.0)
    # 50/70 = 71% — under threshold.
    assert p.on_track is False


def test_progress_higher_is_better_caps_at_200pct() -> None:
    """A wild outlier (current double the target) shouldn't break
    chart axes — the display cap is 200%."""
    goal = _FakeGoal("nps", target_value=10.0)
    p = KpiGoalService.compute_progress(goal, current_value=50.0)
    assert p.achievement_pct == 200.0
    assert p.on_track is True


def test_progress_unknown_current_returns_none() -> None:
    goal = _FakeGoal("nps", target_value=70.0)
    p = KpiGoalService.compute_progress(goal, current_value=None)
    assert p.achievement_pct is None
    assert p.current_value is None
    assert p.on_track is False


# --- lower_is_better metrics ---


def test_progress_lower_is_better_inverts_ratio() -> None:
    """manual_review_rate target=20%, current=15%. Operator beat
    the target so achievement should be > 100%, on-track."""
    goal = _FakeGoal("manual_review_rate", target_value=20.0)
    p = KpiGoalService.compute_progress(goal, current_value=15.0)
    # target/current = 20/15 = 133.33% — operator beat the cap.
    assert p.achievement_pct == 133.33
    assert p.on_track is True
    assert p.higher_is_better is False


def test_progress_lower_is_better_at_target_is_100pct() -> None:
    goal = _FakeGoal("manual_review_rate", target_value=20.0)
    p = KpiGoalService.compute_progress(goal, current_value=20.0)
    assert p.achievement_pct == 100.0
    assert p.on_track is True


def test_progress_lower_is_better_above_target_is_off_track() -> None:
    goal = _FakeGoal("manual_review_rate", target_value=20.0)
    p = KpiGoalService.compute_progress(goal, current_value=40.0)
    # target/current = 20/40 = 50% — operator way over the cap.
    assert p.achievement_pct == 50.0
    assert p.on_track is False


def test_progress_lower_is_better_zero_current_renders_max() -> None:
    """Manual review rate at 0% is operator perfection — render 200
    so the bar shows full headroom; avoids div-by-zero."""
    goal = _FakeGoal("category_concentration", target_value=0.5)
    p = KpiGoalService.compute_progress(goal, current_value=0.0)
    assert p.achievement_pct == 200.0
    assert p.on_track is True
