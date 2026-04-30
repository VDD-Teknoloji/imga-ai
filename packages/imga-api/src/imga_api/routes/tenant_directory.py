"""``GET /tenants/me/users`` — tenant member directory.

Sprint 7.5.5 / Alt-Faz 4 (A7). The ticket detail assignee picker and
the timeline's actor-id resolution both need to translate UUIDs back
to display names; this is the read endpoint they call.

Open to every tenant member (TENANT_ADMIN / ANALYST / VIEWER) so the
viewer-only UI can also show "who else is here". Optional ``search``
substring filters on case-insensitive email OR full_name match.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from imga_db.models import UserTenantRole
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import CurrentUser, bind_tenant, require_role
from imga_api.db_deps import get_app_session
from imga_api.services import AuditService, UserService

router = APIRouter(prefix="/tenants/me", tags=["Tenant Directory"])

_AnyMember = Depends(require_role(
    UserTenantRole.TENANT_ADMIN,
    UserTenantRole.ANALYST,
    UserTenantRole.VIEWER,
))


class TenantMemberView(BaseModel):
    user_id: UUID
    email: str
    full_name: str
    role: str
    is_active: bool
    last_login_at: datetime | None
    invitation_accepted_at: datetime | None


class TenantMembersResponse(BaseModel):
    """Envelope mirrors the rest of the API's list-shape convention."""

    members: list[TenantMemberView]


def _require_active_tenant(current: CurrentUser) -> UUID:
    if current.active_tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="active tenant context required for this endpoint",
        )
    return current.active_tenant_id


@router.get(
    "/users",
    response_model=TenantMembersResponse,
    summary="List active members of the active tenant.",
    description=(
        "Returns user_id + email + full_name + role + last_login_at + "
        "invitation_accepted_at for every active member. Soft-deleted "
        "users are excluded. Optional ``search`` substring filters on "
        "case-insensitive email OR full_name. Sorted by full_name."
    ),
)
async def list_tenant_members(
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    search: Annotated[str | None, Query(max_length=200)] = None,
) -> TenantMembersResponse:
    tenant_id = _require_active_tenant(current)
    audit = AuditService(app_session)
    users = UserService(app_session, audit)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        members = await users.list_for_tenant(tenant_id, search=search)
    return TenantMembersResponse(
        members=[
            TenantMemberView(
                user_id=m.user_id,
                email=m.email,
                full_name=m.full_name,
                role=str(m.role),
                is_active=m.is_active,
                last_login_at=m.last_login_at,
                invitation_accepted_at=m.invitation_accepted_at,
            )
            for m in members
        ]
    )
