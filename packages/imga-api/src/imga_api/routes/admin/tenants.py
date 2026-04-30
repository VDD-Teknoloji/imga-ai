"""/admin/tenants — super-admin tenant CRUD.

Tenant create supports an optional ``initial_admin`` block; when set
the same transaction also issues an invitation, so the response
returns the plaintext invitation token exactly once. The admin then
forwards that token to the new admin out-of-band (email link).

All five endpoints run on the ``imga_admin`` DB role (BYPASSRLS) —
there is no active tenant for super-admin context. Every mutation
hits ``audit_logs`` via the underlying services.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from imga_db.models import AutomationMode, TenantPlanTier, UserTenantRole
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import CurrentUser, require_super_admin
from imga_api.db_deps import get_admin_session
from imga_api.services import (
    AuditService,
    InvitationService,
    TenantNotFoundError,
    TenantService,
    TenantSlugTakenError,
    UserService,
)

router = APIRouter(prefix="/admin/tenants", tags=["Admin: Tenants"])


# --- request / response models ----------------------------------------


class InitialAdminInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    full_name: str = Field(..., min_length=1, max_length=255)


_SLUG_PATTERN = r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$"


class TenantCreateRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "name": "Acme Inc.",
                "slug": "acme",
                "plan_tier": "trial",
                "initial_admin": {
                    "email": "alice@acme.com",
                    "full_name": "Alice Smith",
                },
            }
        },
    )
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=64, pattern=_SLUG_PATTERN)
    plan_tier: TenantPlanTier = TenantPlanTier.TRIAL
    automation_mode: AutomationMode = AutomationMode.SEMI_AUTO
    initial_admin: InitialAdminInput | None = None


class TenantUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=255)
    plan_tier: TenantPlanTier | None = None
    automation_mode: AutomationMode | None = None
    settings: dict[str, Any] | None = None


class TenantSummary(BaseModel):
    id: UUID
    name: str
    slug: str
    plan_tier: str
    automation_mode: str
    created_at: datetime
    deleted_at: datetime | None


class TenantListResponse(BaseModel):
    tenants: list[TenantSummary]


class TenantCreateResponse(BaseModel):
    tenant: TenantSummary
    initial_invitation_token: str | None


# --- helpers ----------------------------------------------------------


def _to_summary(tenant: Any) -> TenantSummary:
    return TenantSummary(
        id=tenant.id,
        name=tenant.name,
        slug=tenant.slug,
        plan_tier=str(tenant.plan_tier),
        automation_mode=str(tenant.automation_mode),
        created_at=tenant.created_at,
        deleted_at=tenant.deleted_at,
    )


# --- endpoints --------------------------------------------------------


@router.post(
    "",
    response_model=TenantCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a tenant. Optionally seed an admin invitation.",
    description=(
        "When ``initial_admin`` is set, the same transaction issues a "
        "tenant_admin invitation and returns the plaintext token in "
        "``initial_invitation_token``. The token is shown exactly once — "
        "store / forward it immediately. Without ``initial_admin``, the "
        "tenant is created empty and the response token is null."
    ),
    responses={409: {"description": "Slug already in use."}},
)
async def create_tenant(
    body: TenantCreateRequest,
    current: Annotated[CurrentUser, Depends(require_super_admin)],
    admin_session: Annotated[AsyncSession, Depends(get_admin_session)],
) -> TenantCreateResponse:
    audit = AuditService(admin_session)
    tenants = TenantService(admin_session, audit)
    users = UserService(admin_session, audit)
    invitations = InvitationService(admin_session, audit, users)

    try:
        tenant = await tenants.create(
            name=body.name,
            slug=body.slug,
            plan_tier=body.plan_tier,
            automation_mode=body.automation_mode,
            actor_user_id=current.user_id,
        )
    except TenantSlugTakenError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc

    token: str | None = None
    if body.initial_admin is not None:
        _invitation, token = await invitations.create_invitation(
            tenant_id=tenant.id,
            email=body.initial_admin.email,
            role=UserTenantRole.TENANT_ADMIN,
            invited_by=current.user_id,
        )

    return TenantCreateResponse(
        tenant=_to_summary(tenant),
        initial_invitation_token=token,
    )


@router.get(
    "",
    response_model=TenantListResponse,
    summary="List every tenant in the system.",
)
async def list_tenants(
    _current: Annotated[CurrentUser, Depends(require_super_admin)],
    admin_session: Annotated[AsyncSession, Depends(get_admin_session)],
    include_deleted: bool = False,
) -> TenantListResponse:
    audit = AuditService(admin_session)
    tenants = TenantService(admin_session, audit)
    rows = await tenants.list(include_deleted=include_deleted)
    return TenantListResponse(tenants=[_to_summary(t) for t in rows])


@router.get(
    "/{tenant_id}",
    response_model=TenantSummary,
    summary="Fetch a single tenant by id.",
)
async def get_tenant(
    tenant_id: UUID,
    _current: Annotated[CurrentUser, Depends(require_super_admin)],
    admin_session: Annotated[AsyncSession, Depends(get_admin_session)],
) -> TenantSummary:
    audit = AuditService(admin_session)
    tenants = TenantService(admin_session, audit)
    tenant = await tenants.get(tenant_id)
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="tenant not found"
        )
    return _to_summary(tenant)


@router.patch(
    "/{tenant_id}",
    response_model=TenantSummary,
    summary="Update tenant name / plan / automation / settings.",
)
async def update_tenant(
    tenant_id: UUID,
    body: TenantUpdateRequest,
    current: Annotated[CurrentUser, Depends(require_super_admin)],
    admin_session: Annotated[AsyncSession, Depends(get_admin_session)],
) -> TenantSummary:
    audit = AuditService(admin_session)
    tenants = TenantService(admin_session, audit)
    try:
        tenant = await tenants.update_settings(
            tenant_id,
            name=body.name,
            plan_tier=body.plan_tier,
            automation_mode=body.automation_mode,
            settings=body.settings,
            actor_user_id=current.user_id,
        )
    except TenantNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return _to_summary(tenant)


@router.delete(
    "/{tenant_id}",
    response_model=TenantSummary,
    summary="Soft-delete (deleted_at = now). Tickets / users stay intact.",
)
async def delete_tenant(
    tenant_id: UUID,
    current: Annotated[CurrentUser, Depends(require_super_admin)],
    admin_session: Annotated[AsyncSession, Depends(get_admin_session)],
) -> TenantSummary:
    audit = AuditService(admin_session)
    tenants = TenantService(admin_session, audit)
    try:
        tenant = await tenants.soft_delete(tenant_id, actor_user_id=current.user_id)
    except TenantNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return _to_summary(tenant)
