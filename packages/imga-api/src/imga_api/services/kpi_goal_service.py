"""Sprint 9.2 B — per-tenant KPI goal/target lifecycle.

A goal is a target value for a registered metric over a specified
period. The service owns CRUD plus the progress computation that
the dashboard's KpiGoalCards section binds to. Progress maps the
metric's *current* value (taken from the executive snapshot or a
fresh compute) against the goal's target_value, factoring in
``higher_is_better`` from the registry: for NPS / CSAT the
percentage of target hit is straight ``current / target``; for
metrics where lower is better (manual_review_rate,
category_concentration) it inverts so the operator sees "you're
3pp under your concentration cap, on track" rather than "you're at
112% of your bound, alarmed".

The service does not manage transactions — callers wrap each public
method in their own ``async with session.begin():``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from imga_db.models import TenantKpiGoal
from imga_core.metrics import get_metric_definition
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class KpiGoalError(Exception):
    """Service-layer failure that maps to a 4xx in the route handler."""


class KpiGoalNotFound(KpiGoalError):
    """The id doesn't exist in the active tenant scope."""


class UnknownMetricKey(KpiGoalError):
    """The metric_key isn't in the registry — the route accepts it
    from the user, validate before insert."""


class GoalAlreadyExists(KpiGoalError):
    """A goal already exists for (metric, period, period_start). The
    UNIQUE constraint catches it at the DB layer; we surface a
    clean 409 here so the route doesn't need to parse asyncpg
    errors."""


@dataclass(frozen=True, slots=True)
class GoalProgress:
    """Wire shape the dashboard's KpiGoalCards binds to. ``on_track``
    is a derived bool: True when achievement_pct >= 90 (within 10%%
    of target), False otherwise. The frontend uses this for the
    badge colour; the raw achievement_pct goes on the progress bar."""

    metric_key: str
    target_value: float
    current_value: float | None
    achievement_pct: float | None
    on_track: bool
    period_start: date
    period_end: date
    target_period: str
    higher_is_better: bool


class KpiGoalService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def set_goal(
        self,
        *,
        tenant_id: UUID,
        metric_key: str,
        target_value: float,
        target_period: str,
        period_start: date,
        period_end: date,
        set_by_user_id: UUID | None,
        notes: str | None = None,
    ) -> TenantKpiGoal:
        """Insert a new goal. The DB UNIQUE constraint on
        (tenant_id, metric_key, target_period, period_start) is the
        canonical conflict signal; we pre-validate the metric_key
        against the in-process registry so a typo surfaces as a 400
        rather than a 500-from-FK."""
        try:
            get_metric_definition(metric_key)
        except KeyError as exc:
            raise UnknownMetricKey(str(exc)) from exc
        if period_end < period_start:
            raise KpiGoalError("period_end must be >= period_start")

        existing = await self._session.execute(
            select(TenantKpiGoal).where(
                TenantKpiGoal.tenant_id == tenant_id,
                TenantKpiGoal.metric_key == metric_key,
                TenantKpiGoal.target_period == target_period,
                TenantKpiGoal.period_start == period_start,
            )
        )
        if existing.scalar_one_or_none() is not None:
            raise GoalAlreadyExists(
                f"goal already exists for {metric_key}/{target_period} "
                f"starting {period_start}"
            )

        row = TenantKpiGoal(
            tenant_id=tenant_id,
            metric_key=metric_key,
            target_value=Decimal(str(target_value)),
            target_period=target_period,
            period_start=period_start,
            period_end=period_end,
            set_by_user_id=set_by_user_id,
            notes=notes,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def list_active(
        self,
        *,
        tenant_id: UUID,
        as_of: date | None = None,
    ) -> list[TenantKpiGoal]:
        """Goals whose period covers ``as_of`` (default: today). The
        partial index ``idx_tenant_kpi_goals_active`` serves this hot
        path; the dashboard reads it on every authenticated render."""
        cutoff = as_of or datetime.now(UTC).date()
        stmt = (
            select(TenantKpiGoal)
            .where(TenantKpiGoal.tenant_id == tenant_id)
            .where(TenantKpiGoal.period_end >= cutoff)
            .where(TenantKpiGoal.period_start <= cutoff)
            .order_by(TenantKpiGoal.period_end.asc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_all(
        self,
        *,
        tenant_id: UUID,
        period: str | None = None,
    ) -> list[TenantKpiGoal]:
        """Settings page reads this to show history (active + past)."""
        stmt = select(TenantKpiGoal).where(TenantKpiGoal.tenant_id == tenant_id)
        if period is not None:
            stmt = stmt.where(TenantKpiGoal.target_period == period)
        stmt = stmt.order_by(TenantKpiGoal.period_end.desc())
        return list((await self._session.execute(stmt)).scalars().all())

    async def delete(
        self,
        *,
        item_id: UUID,
        tenant_id: UUID,
    ) -> None:
        row = await self._session.get(TenantKpiGoal, item_id)
        if row is None or row.tenant_id != tenant_id:
            raise KpiGoalNotFound(f"goal {item_id} not in tenant {tenant_id}")
        await self._session.delete(row)
        await self._session.flush()

    @staticmethod
    def compute_progress(
        goal: TenantKpiGoal,
        current_value: float | None,
    ) -> GoalProgress:
        """Pure function — folds the metric registry's
        ``higher_is_better`` orientation into the achievement
        percentage. Static so the dashboard can call it without
        constructing the service (the dashboard has the goal row +
        the current value already)."""
        meta = get_metric_definition(goal.metric_key)
        target = float(goal.target_value)
        if current_value is None:
            achievement = None
            on_track = False
        elif meta.higher_is_better:
            # Higher is better (NPS, CSAT, etc.) — straightforward
            # current / target ratio. Cap display at 200% so a wild
            # outlier doesn't break chart axes; the raw value is
            # available in the response if the consumer wants it.
            achievement = min(round((current_value / target) * 100.0, 2), 200.0) if target else 0.0
            on_track = achievement >= 90.0
        else:
            # Lower is better (manual_review_rate, concentration) —
            # invert: target/current means "if current dropped to
            # target you'd be at 100%; if you're under target you're
            # over 100%, capped". Special-case current=0 (perfect):
            # render 200 to avoid div-by-zero and signal headroom.
            if current_value <= 0:
                achievement = 200.0
            else:
                achievement = min(round((target / current_value) * 100.0, 2), 200.0)
            on_track = achievement >= 90.0
        return GoalProgress(
            metric_key=goal.metric_key,
            target_value=target,
            current_value=current_value,
            achievement_pct=achievement,
            on_track=on_track,
            period_start=goal.period_start,
            period_end=goal.period_end,
            target_period=goal.target_period,
            higher_is_better=meta.higher_is_better,
        )


__all__ = [
    "GoalAlreadyExists",
    "GoalProgress",
    "KpiGoalError",
    "KpiGoalNotFound",
    "KpiGoalService",
    "UnknownMetricKey",
]
