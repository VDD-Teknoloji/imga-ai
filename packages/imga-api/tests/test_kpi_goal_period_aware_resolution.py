"""Sprint 9.4 B — _resolve_current_values period-aware regression tests.

Pre-9.4 every active goal shared a single all-time current value:

    keys = {g.metric_key for g in goals}
    currents = await _resolve_current_values(session, tenant_id, keys)

Result: a monthly NPS goal with target=70 was compared against
the tenant's all-time NPS — achievement_pct nonsense, on_track
unstable. The fix passes goals (not just keys) and computes one
value per goal in the goal's own ``period_start``/``period_end``
window.

These tests pin the contract: the resolver returns a dict keyed
by goal.id (so two goals on the same metric but different
windows each get their own value) and forwards each goal's
window to AnalyticsService.compute_nps_summary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from imga_api.routes.tenant_kpi_goals import _resolve_current_values


@dataclass(slots=True)
class _FakeGoal:
    id: UUID
    metric_key: str
    target_value: Decimal
    period_start: date
    period_end: date


@dataclass(slots=True)
class _FakeNpsSummary:
    score: float | None


@pytest.fixture
def fake_session() -> Any:
    """AsyncSession stand-in. Only ``execute`` is used by the
    review_volume / manual_review_rate branches; the NPS branch
    goes through AnalyticsService, which we patch separately."""
    s = MagicMock()
    s.execute = AsyncMock()
    return s


@pytest.mark.asyncio
async def test_resolver_returns_dict_keyed_by_goal_id(
    monkeypatch: pytest.MonkeyPatch,
    fake_session: Any,
) -> None:
    """Two goals on the same metric (review_volume) but different
    windows must each resolve to their own value, keyed by goal.id."""
    tenant_id = uuid4()
    goal_q1 = _FakeGoal(
        id=uuid4(),
        metric_key="review_volume",
        target_value=Decimal("100"),
        period_start=date(2026, 1, 1),
        period_end=date(2026, 3, 31),
    )
    goal_q2 = _FakeGoal(
        id=uuid4(),
        metric_key="review_volume",
        target_value=Decimal("150"),
        period_start=date(2026, 4, 1),
        period_end=date(2026, 6, 30),
    )

    # Each session.execute call returns a different scalar so we can
    # tell the two windows apart in the result dict.
    counts = iter([42, 88])

    def _scalar_one_factory() -> int:
        return next(counts)

    def _execute_side_effect(stmt: Any) -> Any:
        result = MagicMock()
        result.scalar_one = MagicMock(side_effect=_scalar_one_factory)
        return result

    fake_session.execute.side_effect = _execute_side_effect

    out = await _resolve_current_values(
        fake_session, tenant_id, [goal_q1, goal_q2]
    )

    assert set(out.keys()) == {goal_q1.id, goal_q2.id}
    assert out[goal_q1.id] == 42.0
    assert out[goal_q2.id] == 88.0


@pytest.mark.asyncio
async def test_resolver_forwards_goal_window_to_nps_compute(
    monkeypatch: pytest.MonkeyPatch,
    fake_session: Any,
) -> None:
    """NPS path must call AnalyticsService.compute_nps_summary with
    the goal's own ``date_from`` / ``date_to`` — not None, not the
    all-time window."""
    tenant_id = uuid4()
    goal = _FakeGoal(
        id=uuid4(),
        metric_key="nps",
        target_value=Decimal("70"),
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
    )

    captured: list[dict[str, Any]] = []

    async def _fake_nps(
        *, tenant_id: UUID, date_from: date | None = None,
        date_to: date | None = None, batch_job_id: UUID | None = None,
    ) -> _FakeNpsSummary:
        captured.append(
            {"tenant_id": tenant_id, "date_from": date_from, "date_to": date_to}
        )
        return _FakeNpsSummary(score=78.0)

    fake_analytics = MagicMock()
    fake_analytics.compute_nps_summary = _fake_nps

    monkeypatch.setattr(
        "imga_api.routes.tenant_kpi_goals.AnalyticsService",
        lambda *a, **kw: fake_analytics,
    )

    out = await _resolve_current_values(fake_session, tenant_id, [goal])

    assert len(captured) == 1
    assert captured[0]["date_from"] == goal.period_start
    assert captured[0]["date_to"] == goal.period_end
    assert out[goal.id] == 78.0


@pytest.mark.asyncio
async def test_resolver_handles_empty_goal_list(
    fake_session: Any,
) -> None:
    """Edge case — list_active() returned no rows. Resolver should
    return an empty dict without poking AnalyticsService at all."""
    out = await _resolve_current_values(fake_session, uuid4(), [])
    assert out == {}
    fake_session.execute.assert_not_called()
