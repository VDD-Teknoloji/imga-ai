"""Sprint 9.2 B — ``/tenants/me/kpi-goals``.

Five endpoints:
  * GET    /                          — list (active or all by period)
  * POST   /                          — set new goal
  * GET    /{metric_key}/progress     — current vs target (for one
                                        active goal)
  * DELETE /{id}                      — remove goal
  * GET    /progress                  — bulk: every active goal's
                                        progress in one round-trip
                                        for the dashboard cards.

logger.exception() on every catch path — Sprint 8.3.6.6 round-3 baseline.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from imga_db.models import Review, TenantKpiGoal, UserTenantRole
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import CurrentUser, bind_tenant, require_role
from imga_api.db_deps import get_app_session
from imga_api.services import (
    AnalyticsService,
    GoalAlreadyExists,
    KpiGoalNotFound,
    KpiGoalService,
    UnknownMetricKey,
)
from imga_api.services.kpi_goal_service import GoalProgress

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tenants/me/kpi-goals", tags=["KPI Goals"])

_AnyMember = Depends(require_role(
    UserTenantRole.TENANT_ADMIN,
    UserTenantRole.ANALYST,
    UserTenantRole.VIEWER,
))
_WriteMember = Depends(require_role(
    UserTenantRole.TENANT_ADMIN,
    UserTenantRole.ANALYST,
))

ALLOWED_PERIODS = ("weekly", "monthly", "quarterly", "yearly")


class KpiGoalResponse(BaseModel):
    id: UUID
    metric_key: str
    target_value: float
    target_period: str
    period_start: date
    period_end: date
    set_by_user_id: UUID | None
    set_at: datetime
    notes: str | None


class KpiGoalCreateRequest(BaseModel):
    metric_key: str
    target_value: float
    target_period: str
    period_start: date
    period_end: date
    notes: str | None = Field(default=None, max_length=1024)

    @field_validator("target_period")
    @classmethod
    def _v_period(cls, v: str) -> str:
        if v not in ALLOWED_PERIODS:
            raise ValueError(
                f"target_period must be one of {list(ALLOWED_PERIODS)}"
            )
        return v


class GoalProgressResponse(BaseModel):
    metric_key: str
    target_value: float
    current_value: float | None
    achievement_pct: float | None
    on_track: bool
    period_start: date
    period_end: date
    target_period: str
    higher_is_better: bool


def _require_active_tenant(current: CurrentUser) -> UUID:
    if current.active_tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="active tenant context required",
        )
    return current.active_tenant_id


def _row_to_response(row: TenantKpiGoal) -> KpiGoalResponse:
    return KpiGoalResponse(
        id=row.id,
        metric_key=row.metric_key,
        target_value=float(row.target_value),
        target_period=row.target_period,
        period_start=row.period_start,
        period_end=row.period_end,
        set_by_user_id=row.set_by_user_id,
        set_at=row.set_at,
        notes=row.notes,
    )


def _progress_to_response(p: GoalProgress) -> GoalProgressResponse:
    return GoalProgressResponse(
        metric_key=p.metric_key,
        target_value=p.target_value,
        current_value=p.current_value,
        achievement_pct=p.achievement_pct,
        on_track=p.on_track,
        period_start=p.period_start,
        period_end=p.period_end,
        target_period=p.target_period,
        higher_is_better=p.higher_is_better,
    )


@router.get("", response_model=list[KpiGoalResponse], summary="List goals.")
async def list_goals(
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    period: str | None = None,
    active_only: bool = True,
) -> list[KpiGoalResponse]:
    if period is not None and period not in ALLOWED_PERIODS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"period must be one of {list(ALLOWED_PERIODS)}",
        )
    tenant_id = _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        service = KpiGoalService(app_session)
        rows = (
            await service.list_active(tenant_id=tenant_id)
            if active_only
            else await service.list_all(tenant_id=tenant_id, period=period)
        )
    return [_row_to_response(r) for r in rows]


@router.post(
    "",
    response_model=KpiGoalResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Set a KPI goal for the active tenant.",
)
async def set_goal(
    body: KpiGoalCreateRequest,
    request: Request,
    current: Annotated[CurrentUser, _WriteMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> KpiGoalResponse:
    tenant_id = _require_active_tenant(current)
    try:
        async with app_session.begin():
            await bind_tenant(app_session, current)
            service = KpiGoalService(app_session)
            row = await service.set_goal(
                tenant_id=tenant_id,
                metric_key=body.metric_key,
                target_value=body.target_value,
                target_period=body.target_period,
                period_start=body.period_start,
                period_end=body.period_end,
                set_by_user_id=current.user_id,
                notes=body.notes,
            )
            # Sprint 9.3 C — operator decision audit. Goal-setting is
            # the canonical "human committed to a number" action;
            # surfaces on /admin/decision-audit timeline.
            from imga_api.services import (
                DECISION_KPI_GOAL_SET,
                DecisionAuditService,
            )

            await DecisionAuditService(app_session).record_decision(
                tenant_id=tenant_id,
                decision_type=DECISION_KPI_GOAL_SET,
                related_entity_type="tenant_kpi_goal",
                related_entity_id=row.id,
                actor_user_id=current.user_id,
                payload={
                    "metric_key": body.metric_key,
                    "target_value": body.target_value,
                    "target_period": body.target_period,
                    "period_start": body.period_start.isoformat(),
                    "period_end": body.period_end.isoformat(),
                },
                rationale=body.notes,
                request_id=getattr(request.state, "request_id", None),
            )
            response = _row_to_response(row)
        return response
    except UnknownMetricKey as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except GoalAlreadyExists as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except HTTPException:
        raise
    except Exception:
        _logger.exception("set_goal failed", extra={"tenant_id": str(tenant_id)})
        raise


@router.delete(
    "/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a KPI goal.",
)
async def delete_goal(
    item_id: UUID,
    current: Annotated[CurrentUser, _WriteMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> None:
    tenant_id = _require_active_tenant(current)
    try:
        async with app_session.begin():
            await bind_tenant(app_session, current)
            service = KpiGoalService(app_session)
            await service.delete(item_id=item_id, tenant_id=tenant_id)
    except KpiGoalNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="goal bulunamadı"
        ) from exc
    except HTTPException:
        raise
    except Exception:
        _logger.exception(
            "delete_goal failed",
            extra={"tenant_id": str(tenant_id), "item_id": str(item_id)},
        )
        raise


@router.get(
    "/progress",
    response_model=list[GoalProgressResponse],
    summary=(
        "Bulk progress for every active goal — dashboard cards bind here."
    ),
)
async def bulk_progress(
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> list[GoalProgressResponse]:
    """Return ``GoalProgress`` for each active goal. The current value
    is taken from ``analytics_service`` (the same compute the
    dashboard uses elsewhere) so the cards never disagree with the
    main NPS card.

    Future: when the executive snapshot lands its bundle, this
    endpoint reads from the snapshot if the snapshot's cursor is
    fresh, falling back to a live compute otherwise. The shape
    doesn't change.
    """
    tenant_id = _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        service = KpiGoalService(app_session)
        goals = await service.list_active(tenant_id=tenant_id)
        if not goals:
            return []
        # Sprint 9.4 B — per-goal current value, computed in each
        # goal's own period window. Pre-9.4 every active goal shared
        # one all-time value, so a monthly target was compared to
        # an all-time number and the achievement % was nonsensical.
        currents = await _resolve_current_values(app_session, tenant_id, goals)
        results = [
            KpiGoalService.compute_progress(g, currents.get(g.id))
            for g in goals
        ]
    return [_progress_to_response(r) for r in results]


async def _resolve_current_values(
    session: AsyncSession,
    tenant_id: UUID,
    goals: list[TenantKpiGoal],
) -> dict[UUID, float]:
    """Sprint 9.4 B — bulk-fetch the headline value for each *goal*,
    using the goal's own ``period_start`` / ``period_end`` window.
    Returns ``{goal.id: current_value}`` so two goals on the same
    metric but different windows each get their own value.

    The compute path is metric-specific: NPS hits AnalyticsService
    (which already understands ``date_from`` / ``date_to``);
    review_volume + manual_review_rate run small inline queries
    that filter on ``Review.review_date`` (yorumun kendi tarihi)
    against the goal's window."""
    out: dict[UUID, float] = {}
    # Sprint 9.4 B — AnalyticsService.__init__ now takes (session,)
    # only (the second arg historically held an AuditService that the
    # service didn't actually consume). Pre-9.4 the helper passed it
    # anyway, but the bulk endpoint was never exercised with an
    # active NPS goal in tests so the TypeError never surfaced.
    analytics = AnalyticsService(session)
    for goal in goals:
        date_from = goal.period_start
        date_to = goal.period_end
        if goal.metric_key == "nps":
            summary = await analytics.compute_nps_summary(
                tenant_id=tenant_id,
                date_from=date_from,
                date_to=date_to,
            )
            out[goal.id] = (
                float(summary.score) if summary.score is not None else 0.0
            )
        elif goal.metric_key == "review_volume":
            total = (
                await session.execute(
                    select(func.count())
                    .select_from(Review)
                    .where(Review.tenant_id == tenant_id)
                    .where(Review.deleted_at.is_(None))
                    .where(func.date(Review.review_date) >= date_from)
                    .where(func.date(Review.review_date) <= date_to)
                )
            ).scalar_one() or 0
            out[goal.id] = float(total)
        elif goal.metric_key == "manual_review_rate":
            # Canonical proxy: rows the bridge couldn't auto-classify
            # and routed to manual review (low-confidence threshold +
            # the "belirsiz" unknown bucket). Both numerator + denom
            # filter on the same window so the rate is meaningful.
            manual = (
                await session.execute(
                    select(func.count())
                    .select_from(Review)
                    .where(Review.tenant_id == tenant_id)
                    .where(Review.deleted_at.is_(None))
                    .where(func.date(Review.review_date) >= date_from)
                    .where(func.date(Review.review_date) <= date_to)
                    .where(
                        Review.decision.in_(
                            ("skipped_threshold", "skipped_belirsiz")
                        )
                    )
                )
            ).scalar_one() or 0
            total = (
                await session.execute(
                    select(func.count())
                    .select_from(Review)
                    .where(Review.tenant_id == tenant_id)
                    .where(Review.deleted_at.is_(None))
                    .where(func.date(Review.review_date) >= date_from)
                    .where(func.date(Review.review_date) <= date_to)
                )
            ).scalar_one() or 0
            out[goal.id] = (
                (manual / total) * 100.0 if total else 0.0
            )
        # csat / category_concentration / sentiment_distribution —
        # when the snapshot service lands they fold in here. For now
        # the dashboard renders these as "no goal data yet" if a
        # tenant sets one, surfaced via current_value=None on the
        # response.
    return out
