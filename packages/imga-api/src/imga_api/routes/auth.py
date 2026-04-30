"""Auth endpoints — login, refresh w/ chain detection, logout, /me, switch-tenant, change-password."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from imga_db.models import User
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import (
    CurrentUser,
    get_auth_service,
    get_current_user,
)
from imga_api.db_deps import get_admin_session
from imga_api.services import AuthError, AuthService, TokenReuseDetected

router = APIRouter(prefix="/auth", tags=["auth"])


# --- request / response models ------------------------------------------


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=256)
    # Optional: choose tenant at login time. If omitted, the first
    # available tenant is selected (or None for super-admin with no link).
    active_tenant_id: UUID | None = None


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    refresh_token: str = Field(..., min_length=1)


class LogoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    refresh_token: str = Field(..., min_length=1)


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8, max_length=256)


class SwitchTenantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: UUID


class TokenPairResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"


class TenantSummary(BaseModel):
    id: UUID
    name: str
    slug: str
    role: str


class UserSummary(BaseModel):
    id: UUID
    email: str
    full_name: str
    is_super_admin: bool


class ActiveContext(BaseModel):
    tenant_id: UUID | None
    tenant_name: str | None
    tenant_slug: str | None
    role: str | None


class MeResponse(BaseModel):
    user: UserSummary
    active_context: ActiveContext
    available_tenants: list[TenantSummary]


# --- endpoints ----------------------------------------------------------


@router.post("/login", response_model=TokenPairResponse)
async def login(
    body: LoginRequest,
    request: Request,
    auth: AuthService = Depends(get_auth_service),
) -> TokenPairResponse:
    """Email + password login. Returns access + refresh token pair."""
    try:
        user, pair = await auth.login(
            email=body.email,
            password=body.password,
            ip_address=_client_ip(request),
        )
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc

    # Pick the active tenant: explicit > first available > None.
    chosen_tenant_id = body.active_tenant_id
    chosen_role: str | None = None
    if chosen_tenant_id is None:
        tenants = await auth.list_user_tenants(user.id)
        if tenants:
            chosen_tenant_id = tenants[0]["id"]  # type: ignore[assignment]
            chosen_role = str(tenants[0]["role"])
    else:
        # Verify the user is actually linked to the requested tenant.
        tenants = await auth.list_user_tenants(user.id)
        for t in tenants:
            if t["id"] == chosen_tenant_id:
                chosen_role = str(t["role"])
                break
        else:
            if not user.is_super_admin:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="user is not a member of the requested tenant",
                )

    # Re-issue tokens with the chosen tenant context (the first issuance
    # at AuthService.login had no tenant). Cheap: just re-encodes JWTs
    # and writes one extra refresh_token_records row.
    if chosen_tenant_id is not None:
        _user_again, pair = await auth.login(
            email=body.email,
            password=body.password,
            active_tenant_id=chosen_tenant_id,
            active_role=chosen_role,
            ip_address=_client_ip(request),
        )
    return TokenPairResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
    )


@router.post("/refresh", response_model=TokenPairResponse)
async def refresh(
    body: RefreshRequest,
    auth: AuthService = Depends(get_auth_service),
) -> TokenPairResponse:
    try:
        _user, pair = await auth.refresh(body.refresh_token)
    except TokenReuseDetected as exc:
        # Same status as a generic invalid token — don't leak detection.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid refresh token"
        ) from exc
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc
    return TokenPairResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def logout(
    body: LogoutRequest,
    auth: AuthService = Depends(get_auth_service),
) -> None:
    await auth.logout(body.refresh_token)


@router.post("/switch-tenant", response_model=TokenPairResponse)
async def switch_tenant(
    body: SwitchTenantRequest,
    current: CurrentUser = Depends(get_current_user),
    auth: AuthService = Depends(get_auth_service),
    admin_session: AsyncSession = Depends(get_admin_session),
) -> TokenPairResponse:
    """Re-issue tokens with a different active tenant. The user must
    already belong to the target tenant (or be a super-admin)."""
    tenants = await auth.list_user_tenants(current.user_id)
    role: str | None = None
    for t in tenants:
        if t["id"] == body.tenant_id:
            role = str(t["role"])
            break
    if role is None and not current.is_super_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="user is not a member of the requested tenant",
        )

    user = await admin_session.get(User, current.user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="user not found"
        )
    pair = await auth._issue_token_pair(  # type: ignore[attr-defined]
        user=user,
        active_tenant_id=body.tenant_id,
        active_role=role,
    )
    return TokenPairResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
    )


@router.get("/me", response_model=MeResponse)
async def me(
    current: CurrentUser = Depends(get_current_user),
    auth: AuthService = Depends(get_auth_service),
    admin_session: AsyncSession = Depends(get_admin_session),
) -> MeResponse:
    user = await admin_session.get(User, current.user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="user not found"
        )
    tenants = await auth.list_user_tenants(current.user_id)
    active_tenant_summary: dict[str, Any] | None = None
    if current.active_tenant_id is not None:
        for t in tenants:
            if t["id"] == current.active_tenant_id:
                active_tenant_summary = t
                break
    return MeResponse(
        user=UserSummary(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            is_super_admin=user.is_super_admin,
        ),
        active_context=ActiveContext(
            tenant_id=current.active_tenant_id,
            tenant_name=str(active_tenant_summary["name"]) if active_tenant_summary else None,
            tenant_slug=str(active_tenant_summary["slug"]) if active_tenant_summary else None,
            role=current.active_role,
        ),
        available_tenants=[
            TenantSummary(
                id=t["id"],  # type: ignore[arg-type]
                name=str(t["name"]),
                slug=str(t["slug"]),
                role=str(t["role"]),
            )
            for t in tenants
        ],
    )


@router.post(
    "/change-password",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def change_password(
    body: ChangePasswordRequest,
    current: CurrentUser = Depends(get_current_user),
    auth: AuthService = Depends(get_auth_service),
) -> None:
    try:
        await auth.change_password(
            user_id=current.user_id,
            current_password=body.current_password,
            new_password=body.new_password,
        )
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


# --- helpers ------------------------------------------------------------


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None
