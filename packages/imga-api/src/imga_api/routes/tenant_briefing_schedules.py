"""Sprint 9.2 D — ``/tenants/me/briefing-schedules``.

Five endpoints:
  * GET    /                — list schedules for the active tenant
  * POST   /                — create a new schedule
  * PATCH  /{id}            — toggle enabled / change day-hour /
                              update recipients
  * DELETE /{id}            — remove the schedule
  * POST   /{id}/run-now    — manual trigger ("Send now" button on
                              the settings page; fires the same code
                              the cron uses, awaits inline)

logger.exception() on every catch path — Sprint 8.3.6.6 round-3 baseline.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from imga_db.models import BriefingSchedule, UserTenantRole
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import CurrentUser, bind_tenant, require_role
from imga_api.db_deps import get_app_session
from imga_api.services import (
    BriefingScheduleError,
    BriefingScheduleService,
    ScheduleNotFound,
)

_logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/tenants/me/briefing-schedules",
    tags=["Scheduled Briefings"],
)

_AnyMember = Depends(require_role(
    UserTenantRole.TENANT_ADMIN,
    UserTenantRole.ANALYST,
    UserTenantRole.VIEWER,
))
_WriteMember = Depends(require_role(
    UserTenantRole.TENANT_ADMIN,
    UserTenantRole.ANALYST,
))

ALLOWED_PERIODS = ("weekly", "monthly")


class ScheduleResponse(BaseModel):
    id: UUID
    period: str
    schedule_day: int
    schedule_hour: int
    timezone: str
    recipients: list[UUID]
    email_recipients: list[str]
    enabled: bool
    last_run_at: datetime | None
    last_run_briefing_id: UUID | None
    last_run_status: str | None
    last_run_error: str | None
    next_run_at: datetime
    created_at: datetime


class ScheduleCreateRequest(BaseModel):
    period: str
    schedule_day: int = Field(..., ge=0, le=27)
    schedule_hour: int = Field(default=9, ge=0, le=23)
    timezone: str = "Europe/Istanbul"
    recipients: list[UUID] = Field(default_factory=list)
    email_recipients: list[str] = Field(default_factory=list, max_length=20)
    enabled: bool = True

    @field_validator("period")
    @classmethod
    def _v_period(cls, v: str) -> str:
        if v not in ALLOWED_PERIODS:
            raise ValueError(
                f"period must be one of {list(ALLOWED_PERIODS)}"
            )
        return v


class ScheduleUpdateRequest(BaseModel):
    enabled: bool | None = None
    schedule_day: int | None = Field(default=None, ge=0, le=27)
    schedule_hour: int | None = Field(default=None, ge=0, le=23)
    recipients: list[UUID] | None = None
    email_recipients: list[str] | None = Field(default=None, max_length=20)


def _require_active_tenant(current: CurrentUser) -> UUID:
    if current.active_tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="active tenant context required",
        )
    return current.active_tenant_id


def _row_to_response(row: BriefingSchedule) -> ScheduleResponse:
    return ScheduleResponse(
        id=row.id,
        period=row.period,
        schedule_day=row.schedule_day,
        schedule_hour=row.schedule_hour,
        timezone=row.timezone,
        recipients=list(row.recipients or []),
        email_recipients=list(row.email_recipients or []),
        enabled=row.enabled,
        last_run_at=row.last_run_at,
        last_run_briefing_id=row.last_run_briefing_id,
        last_run_status=row.last_run_status,
        last_run_error=row.last_run_error,
        next_run_at=row.next_run_at,
        created_at=row.created_at,
    )


@router.get(
    "",
    response_model=list[ScheduleResponse],
    summary="List briefing schedules for the active tenant.",
)
async def list_schedules(
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> list[ScheduleResponse]:
    tenant_id = _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        service = BriefingScheduleService(app_session)
        rows = await service.list_for_tenant(tenant_id=tenant_id)
    return [_row_to_response(r) for r in rows]


@router.post(
    "",
    response_model=ScheduleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new scheduled briefing.",
)
async def create_schedule(
    body: ScheduleCreateRequest,
    current: Annotated[CurrentUser, _WriteMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> ScheduleResponse:
    tenant_id = _require_active_tenant(current)
    # Period-specific day check — the DB CHECK constraint enforces
    # the same rule, but we surface 400 before the round-trip.
    if body.period == "weekly" and not 0 <= body.schedule_day <= 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="weekly schedule_day must be 0..6 (Mon..Sun)",
        )
    if body.period == "monthly" and not 1 <= body.schedule_day <= 28:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="monthly schedule_day must be 1..28",
        )
    try:
        async with app_session.begin():
            await bind_tenant(app_session, current)
            service = BriefingScheduleService(app_session)
            row = await service.create(
                tenant_id=tenant_id,
                period=body.period,
                schedule_day=body.schedule_day,
                schedule_hour=body.schedule_hour,
                timezone=body.timezone,
                recipients=body.recipients,
                email_recipients=body.email_recipients,
                enabled=body.enabled,
            )
            response = _row_to_response(row)
        return response
    except BriefingScheduleError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except HTTPException:
        raise
    except Exception:
        _logger.exception(
            "create_schedule failed", extra={"tenant_id": str(tenant_id)}
        )
        raise


@router.patch(
    "/{schedule_id}",
    response_model=ScheduleResponse,
    summary="Update a scheduled briefing.",
)
async def update_schedule(
    schedule_id: UUID,
    body: ScheduleUpdateRequest,
    current: Annotated[CurrentUser, _WriteMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> ScheduleResponse:
    tenant_id = _require_active_tenant(current)
    try:
        async with app_session.begin():
            await bind_tenant(app_session, current)
            service = BriefingScheduleService(app_session)
            row = await service.update(
                schedule_id=schedule_id,
                tenant_id=tenant_id,
                enabled=body.enabled,
                schedule_day=body.schedule_day,
                schedule_hour=body.schedule_hour,
                recipients=body.recipients,
                email_recipients=body.email_recipients,
            )
            response = _row_to_response(row)
        return response
    except ScheduleNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="schedule bulunamadı"
        ) from exc
    except BriefingScheduleError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except HTTPException:
        raise
    except Exception:
        _logger.exception(
            "update_schedule failed",
            extra={
                "tenant_id": str(tenant_id),
                "schedule_id": str(schedule_id),
            },
        )
        raise


@router.delete(
    "/{schedule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a scheduled briefing.",
)
async def delete_schedule(
    schedule_id: UUID,
    current: Annotated[CurrentUser, _WriteMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> None:
    tenant_id = _require_active_tenant(current)
    try:
        async with app_session.begin():
            await bind_tenant(app_session, current)
            service = BriefingScheduleService(app_session)
            await service.delete(
                schedule_id=schedule_id, tenant_id=tenant_id
            )
    except ScheduleNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="schedule bulunamadı"
        ) from exc
    except HTTPException:
        raise
    except Exception:
        _logger.exception(
            "delete_schedule failed",
            extra={
                "tenant_id": str(tenant_id),
                "schedule_id": str(schedule_id),
            },
        )
        raise


@router.post(
    "/{schedule_id}/run-now",
    response_model=ScheduleResponse,
    summary=(
        "Manual trigger — generate a briefing for the schedule's "
        "period inline, persist it, and stamp the schedule's "
        "last_run_* audit columns. Used by the settings page's "
        "\"Send now\" button to verify a schedule without waiting "
        "for the next cron tick."
    ),
)
async def run_schedule_now(
    schedule_id: UUID,
    current: Annotated[CurrentUser, _WriteMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> ScheduleResponse:
    tenant_id = _require_active_tenant(current)
    from datetime import UTC, timedelta

    from imga_api.services.executive_briefing_service import (
        ExecutiveBriefingService,
    )

    period_days = {"weekly": 7, "monthly": 30}
    try:
        async with app_session.begin():
            await bind_tenant(app_session, current)
            row = await app_session.get(BriefingSchedule, schedule_id)
            if row is None or row.tenant_id != tenant_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="schedule bulunamadı",
                )
            today = datetime.now(UTC).date()
            window = period_days.get(row.period, 30)
            briefing_service = ExecutiveBriefingService(
                session=app_session,
                tenant_id=tenant_id,
                user_id=current.user_id,
            )
            ran_at = datetime.now(UTC)
            briefing_id: UUID | None = None
            status_label = "success"
            error_text: str | None = None
            try:
                payload = await briefing_service.generate(
                    period=row.period,
                    date_from=today - timedelta(days=window),
                    date_to=today,
                )
                raw_id = payload.get("id")
                if isinstance(raw_id, UUID):
                    briefing_id = raw_id
                elif isinstance(raw_id, str):
                    try:
                        briefing_id = UUID(raw_id)
                    except ValueError:
                        briefing_id = None
            except Exception as exc:
                status_label = "failed"
                error_text = str(exc)[:1024]
                _logger.exception(
                    "run-now: briefing generation failed",
                    extra={
                        "schedule_id": str(schedule_id),
                        "tenant_id": str(tenant_id),
                    },
                )
            schedule_service = BriefingScheduleService(app_session)
            await schedule_service.record_run(
                schedule=row,
                status=status_label,
                briefing_id=briefing_id,
                error=error_text,
                ran_at=ran_at,
            )
            response = _row_to_response(row)
        return response
    except HTTPException:
        raise
    except Exception:
        _logger.exception(
            "run-now route failed",
            extra={
                "schedule_id": str(schedule_id),
                "tenant_id": str(tenant_id),
            },
        )
        raise
