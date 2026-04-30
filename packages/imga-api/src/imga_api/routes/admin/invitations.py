"""/admin/tenants/{tid}/invitations — invitation send + list + revoke.

Authorisation:

  * super_admin can act on any tenant.
  * tenant_admin can act ONLY on their own active tenant. Mismatch
    between path tenant_id and JWT active_tenant_id → 403.

Routes use the imga_admin DB role (BYPASSRLS) because invitations
straddle the auth boundary — a tenant_admin's session needs to write
into a tenant they're already an admin of, but the role check happens
at the API layer rather than via RLS so the path tenant_id is the
single source of truth.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from imga_db.models import UserTenantRole
from pydantic import BaseModel, ConfigDict, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import CurrentUser, get_current_user
from imga_api.db_deps import get_admin_session
from imga_api.services import (
    AuditService,
    InvitationService,
    UserService,
)

router = APIRouter(prefix="/admin/tenants", tags=["Admin: Users"])


def _require_actor_can_manage(current: CurrentUser, tenant_id: UUID) -> None:
    """Super-admin pass-through; otherwise the actor must be acting in
    that tenant's tenant_admin role. Plain analyst/viewer of the same
    tenant gets 403."""
    if current.is_super_admin:
        return
    if current.active_tenant_id != tenant_id or current.active_role != "tenant_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="tenant_admin yetkisi gerekli",
        )


# --- request / response models -----------------------------------------


class InvitationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    role: UserTenantRole


class InvitationCreateResponse(BaseModel):
    invitation_id: UUID
    token: str  # plaintext, returned exactly once
    email: str
    role: str
    expires_at: datetime


class InvitationView(BaseModel):
    id: UUID
    email: str
    role: str
    invited_by: UUID | None
    expires_at: datetime
    accepted_at: datetime | None
    created_at: datetime


class InvitationListResponse(BaseModel):
    invitations: list[InvitationView]


# --- endpoints ---------------------------------------------------------


@router.post(
    "/{tenant_id}/invitations",
    response_model=InvitationCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Issue an invitation. Plaintext token returned exactly once.",
)
async def create_invitation(
    tenant_id: UUID,
    body: InvitationCreateRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    admin_session: Annotated[AsyncSession, Depends(get_admin_session)],
) -> InvitationCreateResponse:
    _require_actor_can_manage(current, tenant_id)
    audit = AuditService(admin_session)
    users = UserService(admin_session, audit)
    invitations = InvitationService(admin_session, audit, users)

    invitation, token = await invitations.create_invitation(
        tenant_id=tenant_id,
        email=body.email,
        role=body.role,
        invited_by=current.user_id,
    )
    return InvitationCreateResponse(
        invitation_id=invitation.id,
        token=token,
        email=invitation.email,
        role=str(invitation.role),
        expires_at=invitation.expires_at,
    )


@router.get(
    "/{tenant_id}/invitations",
    response_model=InvitationListResponse,
    summary="List pending (and optionally accepted) invitations.",
)
async def list_invitations(
    tenant_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    admin_session: Annotated[AsyncSession, Depends(get_admin_session)],
    include_accepted: bool = False,
) -> InvitationListResponse:
    _require_actor_can_manage(current, tenant_id)
    audit = AuditService(admin_session)
    users = UserService(admin_session, audit)
    invitations = InvitationService(admin_session, audit, users)
    rows = await invitations.list_for_tenant(
        tenant_id, include_accepted=include_accepted
    )
    return InvitationListResponse(
        invitations=[
            InvitationView(
                id=r.id,
                email=r.email,
                role=str(r.role),
                invited_by=r.invited_by,
                expires_at=r.expires_at,
                accepted_at=r.accepted_at,
                created_at=r.created_at,
            )
            for r in rows
        ]
    )


@router.delete(
    "/{tenant_id}/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Revoke (hard delete) an invitation. Audit row preserves history.",
)
async def revoke_invitation(
    tenant_id: UUID,
    invitation_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    admin_session: Annotated[AsyncSession, Depends(get_admin_session)],
) -> None:
    _require_actor_can_manage(current, tenant_id)
    audit = AuditService(admin_session)
    users = UserService(admin_session, audit)
    invitations = InvitationService(admin_session, audit, users)
    try:
        await invitations.revoke(
            invitation_id, tenant_id=tenant_id, actor_user_id=current.user_id
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
