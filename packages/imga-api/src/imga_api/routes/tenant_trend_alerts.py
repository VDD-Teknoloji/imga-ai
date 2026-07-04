"""``/tenants/me/trend-alerts`` — KPI deviation alert log.

Sprint 8.3.10. Three endpoints:

  * GET   /                  — list alerts (status filter)
  * PATCH /{id}              — acknowledge / dismiss
  * POST  /evaluate          — admin-triggered evaluation pass

The cron-driven evaluation lands in Sprint 8.6 alongside Prometheus;
this sprint ships the manual trigger so admins can fire on demand.

logger.exception() on every catch path.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from imga_db.models import TrendAlert, UserTenantRole
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import CurrentUser, bind_tenant, require_role
from imga_api.db_deps import get_app_session
from imga_api.services.trend_alert_service import TrendAlertService

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tenants/me/trend-alerts", tags=["Trend Alerts"])

_AnyMember = Depends(require_role(
    UserTenantRole.TENANT_ADMIN,
    UserTenantRole.ANALYST,
    UserTenantRole.VIEWER,
))
_AdminOnly = Depends(require_role(UserTenantRole.TENANT_ADMIN))
# Sprint 13 yetki denetimi: ack/dismiss durum mutasyonu — viewer
# salt-okuma kalır.
_WriteMember = Depends(require_role(
    UserTenantRole.TENANT_ADMIN,
    UserTenantRole.ANALYST,
))

ALLOWED_STATUSES = {"active", "acknowledged", "dismissed"}


class TrendAlertResponse(BaseModel):
    id: UUID
    alert_type: str
    severity: str
    title: str
    description: str
    evidence: dict[str, Any]
    status: str
    acknowledged_by_user_id: UUID | None
    acknowledged_at: datetime | None
    created_at: datetime


class TrendAlertUpdateRequest(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def _v_status(cls, v: str) -> str:
        if v not in ALLOWED_STATUSES:
            raise ValueError(
                f"status must be one of {sorted(ALLOWED_STATUSES)}"
            )
        return v


def _require_active_tenant(current: CurrentUser) -> UUID:
    if current.active_tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="active tenant context required for this endpoint",
        )
    return current.active_tenant_id


def _row_to_response(row: TrendAlert) -> TrendAlertResponse:
    return TrendAlertResponse(
        id=row.id,
        alert_type=row.alert_type,
        severity=row.severity,
        title=row.title,
        description=row.description,
        evidence=dict(row.evidence or {}),
        status=row.status,
        acknowledged_by_user_id=row.acknowledged_by_user_id,
        acknowledged_at=row.acknowledged_at,
        created_at=row.created_at,
    )


@router.get(
    "",
    response_model=list[TrendAlertResponse],
    summary="List trend alerts.",
)
async def list_trend_alerts(
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    status_filter: str | None = "active",
) -> list[TrendAlertResponse]:
    """Default ``status_filter=active`` so the dashboard surfaces
    only un-acknowledged alerts; pass ``all`` for the full log."""
    tenant_id = _require_active_tenant(current)
    if status_filter not in (None, "all", *ALLOWED_STATUSES):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"status must be one of {sorted(ALLOWED_STATUSES)} or 'all'",
        )
    async with app_session.begin():
        await bind_tenant(app_session, current)
        stmt = select(TrendAlert).where(TrendAlert.tenant_id == tenant_id)
        if status_filter and status_filter != "all":
            stmt = stmt.where(TrendAlert.status == status_filter)
        stmt = stmt.order_by(TrendAlert.created_at.desc())
        rows = (await app_session.execute(stmt)).scalars().all()
    return [_row_to_response(r) for r in rows]


@router.patch(
    "/{alert_id}",
    response_model=TrendAlertResponse,
    summary="Acknowledge or dismiss an alert.",
)
async def update_trend_alert(
    alert_id: UUID,
    body: TrendAlertUpdateRequest,
    current: Annotated[CurrentUser, _WriteMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> TrendAlertResponse:
    tenant_id = _require_active_tenant(current)
    try:
        async with app_session.begin():
            await bind_tenant(app_session, current)
            row = await app_session.get(TrendAlert, alert_id)
            if row is None or row.tenant_id != tenant_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="alert bulunamadı",
                )
            row.status = body.status
            if body.status in {"acknowledged", "dismissed"}:
                row.acknowledged_by_user_id = current.user_id
                row.acknowledged_at = datetime.now(UTC)
            await app_session.flush()
            response = _row_to_response(row)
        return response
    except HTTPException:
        raise
    except Exception:
        _logger.exception(
            "update_trend_alert failed",
            extra={
                "tenant_id": str(tenant_id),
                "alert_id": str(alert_id),
            },
        )
        raise


@router.post(
    "/evaluate",
    response_model=list[TrendAlertResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Run threshold-based evaluation; emit any new alerts.",
)
async def evaluate_trend_alerts(
    current: Annotated[CurrentUser, _AdminOnly],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> list[TrendAlertResponse]:
    """Admin-only manual trigger. Sprint 8.6 will wire a cron driver
    around the same TrendAlertService.evaluate."""
    tenant_id = _require_active_tenant(current)
    try:
        async with app_session.begin():
            await bind_tenant(app_session, current)
            service = TrendAlertService(app_session)
            new_alerts = await service.evaluate(tenant_id=tenant_id)
            for alert in new_alerts:
                app_session.add(alert)
            await app_session.flush()
            response = [_row_to_response(a) for a in new_alerts]
        return response
    except HTTPException:
        raise
    except Exception:
        _logger.exception(
            "evaluate_trend_alerts failed",
            extra={"tenant_id": str(tenant_id)},
        )
        raise
