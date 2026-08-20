"""``/admin/audit-logs`` — süper-admin çapraz-kurum denetim kaydı
görüntüleyici (C4+B2, 2026-08-20 süper-admin envanteri).

``audit_logs`` bugüne kadar yalnız yazılıyordu (``AuditService.log``,
her mutasyon endpoint'inden); okuma tarafı hiç yoktu — B2 bulgusu tam
bu: bir operatör "bu kurumda kim ne yaptı" sorusuna cevap bulamıyordu.
Bu uç yalnız okur; ``AuditService.list`` filtre + sayfalama + tenant/
actor isim JOIN'lerini taşır.

Diğer admin uçlarıyla aynı transaction sözleşmesi: burada
``async with admin_session.begin():`` YOK, bilerek (bkz.
admin/llm_credentials.py docstring'i).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import CurrentUser, require_super_admin
from imga_api.db_deps import get_admin_session
from imga_api.services.audit_service import AuditService

router = APIRouter(prefix="/admin/audit-logs", tags=["Admin: Audit Logs"])


class AuditLogItem(BaseModel):
    id: UUID
    tenant_id: UUID | None
    tenant_name: str | None
    actor_user_id: UUID | None
    actor_email: str | None
    action: str
    resource_type: str
    resource_id: UUID | None
    ip_address: str | None
    created_at: datetime


class AuditLogListResponse(BaseModel):
    items: list[AuditLogItem]
    total: int


@router.get(
    "",
    response_model=AuditLogListResponse,
    summary="Çapraz-kurum denetim kaydı listesi (filtre + sayfalama).",
)
async def list_audit_logs(
    _current: Annotated[CurrentUser, Depends(require_super_admin)],
    admin_session: Annotated[AsyncSession, Depends(get_admin_session)],
    tenant_id: UUID | None = None,
    action: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
) -> AuditLogListResponse:
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    audit = AuditService(admin_session)
    rows, total = await audit.list(
        tenant_id=tenant_id,
        action=action,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    return AuditLogListResponse(
        items=[
            AuditLogItem(
                id=r.id,
                tenant_id=r.tenant_id,
                tenant_name=r.tenant_name,
                actor_user_id=r.actor_user_id,
                actor_email=r.actor_email,
                action=r.action,
                resource_type=r.resource_type,
                resource_id=r.resource_id,
                ip_address=r.ip_address,
                created_at=r.created_at,
            )
            for r in rows
        ],
        total=total,
    )
