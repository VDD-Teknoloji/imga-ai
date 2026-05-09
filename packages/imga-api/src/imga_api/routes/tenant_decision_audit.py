"""Sprint 9.3 C — ``/tenants/me/decision-audit`` (read-only).

Operator decisions are recorded by the existing routes
(briefings, strategic, KPI goals, etc.) via
``DecisionAuditService.record_decision``. This module surfaces the
read side: the admin timeline page binds to ``GET /`` (paginated +
filtered) and the row-detail modal binds to ``GET /{id}``.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from imga_db.models import DecisionAuditLog, UserTenantRole
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import CurrentUser, bind_tenant, require_role
from imga_api.db_deps import get_app_session

_logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/tenants/me/decision-audit", tags=["Decision Audit"]
)

_AdminOnly = Depends(require_role(UserTenantRole.TENANT_ADMIN))


class DecisionAuditResponse(BaseModel):
    id: UUID
    decision_type: str
    related_entity_type: str
    related_entity_id: UUID
    actor_user_id: UUID | None
    payload: dict[str, Any]
    rationale: str | None
    request_id: str | None
    created_at: datetime


class DecisionAuditListResponse(BaseModel):
    items: list[DecisionAuditResponse]
    total: int


def _require_active_tenant(current: CurrentUser) -> UUID:
    if current.active_tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="active tenant context required",
        )
    return current.active_tenant_id


def _row_to_response(row: DecisionAuditLog) -> DecisionAuditResponse:
    return DecisionAuditResponse(
        id=row.id,
        decision_type=row.decision_type,
        related_entity_type=row.related_entity_type,
        related_entity_id=row.related_entity_id,
        actor_user_id=row.actor_user_id,
        payload=dict(row.payload or {}),
        rationale=row.rationale,
        request_id=row.request_id,
        created_at=row.created_at,
    )


@router.get(
    "",
    response_model=DecisionAuditListResponse,
    summary="List operator decisions for the active tenant.",
)
async def list_decisions(
    current: Annotated[CurrentUser, _AdminOnly],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    decision_type: str | None = None,
    related_entity_type: str | None = None,
    actor_user_id: UUID | None = None,
    limit: int = 100,
    offset: int = 0,
) -> DecisionAuditListResponse:
    tenant_id = _require_active_tenant(current)
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        filters = [DecisionAuditLog.tenant_id == tenant_id]
        if decision_type is not None:
            filters.append(DecisionAuditLog.decision_type == decision_type)
        if related_entity_type is not None:
            filters.append(
                DecisionAuditLog.related_entity_type == related_entity_type
            )
        if actor_user_id is not None:
            filters.append(DecisionAuditLog.actor_user_id == actor_user_id)
        count_stmt = (
            select(func.count())
            .select_from(DecisionAuditLog)
            .where(*filters)
        )
        total = (await app_session.execute(count_stmt)).scalar_one() or 0
        list_stmt = (
            select(DecisionAuditLog)
            .where(*filters)
            .order_by(desc(DecisionAuditLog.created_at))
            .limit(limit)
            .offset(offset)
        )
        rows = list((await app_session.execute(list_stmt)).scalars().all())
    return DecisionAuditListResponse(
        items=[_row_to_response(r) for r in rows],
        total=total,
    )
