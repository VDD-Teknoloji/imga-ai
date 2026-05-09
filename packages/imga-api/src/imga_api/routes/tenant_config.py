"""/tenants/me/* endpoints — taxonomy + automation-mode for the active tenant.

Routes here are tenant-scoped: they require an ``active_tenant_id`` on
the JWT and a TENANT_ADMIN role (or super-admin). The app DB session is
RLS-enforced; we bind the tenant inside each handler's transaction so
that ``categories`` and ``tenant_categories`` queries are policy-scoped.

Cache invalidation is handled by TenantConfigService — handlers stay
focused on validation, RLS binding, and serialization.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from imga_db.models import AutomationMode, UserTenantRole
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import CurrentUser, bind_tenant, require_role
from imga_api.db_deps import get_app_session
from imga_api.dependencies import get_tenant_config_service
from imga_api.services import (
    DECISION_TENANT_SETTING_CHANGED,
    CategoryCodeConflictError,
    CategoryNotFoundError,
    DecisionAuditService,
    TenantConfigError,
    TenantConfigService,
)

router = APIRouter(prefix="/tenants/me", tags=["Tenant Config"])


# --- request / response models ------------------------------------------


class CategoryView(BaseModel):
    id: UUID
    code: str
    label_tr: str
    label_en: str | None
    description: str | None
    is_global: bool
    is_enabled: bool
    is_archived: bool


class TenantConfigResponse(BaseModel):
    tenant_id: UUID
    automation_mode: str
    categories: list[CategoryView]


class CategoriesResponse(BaseModel):
    categories: list[CategoryView]


class AutomationModeUpdate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"example": {"automation_mode": "semi_auto"}},
    )
    automation_mode: AutomationMode


class CategoryToggleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_enabled: bool


class CustomCategoryCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "code": "vip_complaint",
                "label_tr": "VIP Müşteri Şikayeti",
                "label_en": "VIP Customer Complaint",
                "description": "Tickets opened from accounts on the VIP plan.",
            }
        },
    )
    code: str = Field(..., min_length=1, max_length=64)
    label_tr: str = Field(..., min_length=1, max_length=255)
    label_en: str | None = Field(default=None, max_length=255)
    description: str | None = None


class CustomCategoryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label_tr: str | None = Field(default=None, min_length=1, max_length=255)
    label_en: str | None = Field(default=None, max_length=255)
    description: str | None = None


# --- helpers ------------------------------------------------------------


def _require_active_tenant(current: CurrentUser) -> UUID:
    if current.active_tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="active tenant context required for this endpoint",
        )
    return current.active_tenant_id


def _categories_view(snapshot: dict[str, Any]) -> list[CategoryView]:
    return [CategoryView(**c) for c in snapshot["categories"]]


# Role guard reused across mutations: tenant_admin (or super-admin via
# require_role's built-in pass-through).
_TenantAdmin = Depends(require_role(UserTenantRole.TENANT_ADMIN))


# --- endpoints ----------------------------------------------------------


@router.get(
    "/config",
    response_model=TenantConfigResponse,
    summary="Full config snapshot for the active tenant.",
    description=(
        "Returns automation_mode + the complete category list (globals + "
        "this tenant's customs, including archived ones with "
        "is_archived=true). Cached server-side per tenant for 5 minutes; "
        "any mutation invalidates the entry."
    ),
)
async def get_config(
    current: Annotated[CurrentUser, Depends(require_role(
        UserTenantRole.TENANT_ADMIN,
        UserTenantRole.ANALYST,
        UserTenantRole.VIEWER,
    ))],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    config: Annotated[TenantConfigService, Depends(get_tenant_config_service)],
) -> TenantConfigResponse:
    """Full tenant-config snapshot (automation mode + categories).

    All tenant members can read the config; only TENANT_ADMIN can mutate.
    """
    tenant_id = _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        snapshot = await config.get_config(tenant_id)
    return TenantConfigResponse(
        tenant_id=snapshot["tenant_id"],
        automation_mode=snapshot["automation_mode"],
        categories=_categories_view(snapshot),
    )


@router.get(
    "/categories",
    response_model=CategoriesResponse,
    summary="List visible categories (globals + this tenant's customs).",
)
async def list_categories(
    current: Annotated[CurrentUser, Depends(require_role(
        UserTenantRole.TENANT_ADMIN,
        UserTenantRole.ANALYST,
        UserTenantRole.VIEWER,
    ))],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    config: Annotated[TenantConfigService, Depends(get_tenant_config_service)],
) -> CategoriesResponse:
    tenant_id = _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        snapshot = await config.get_config(tenant_id)
    return CategoriesResponse(categories=_categories_view(snapshot))


@router.patch(
    "/automation-mode",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Switch the tenant's auto-ticket policy.",
    description=(
        "Three modes: `manual` (no auto-create, only suggest), "
        "`semi_auto` (auto-create on confidence > 0.7 AND sentiment < -0.5), "
        "`full_auto` (every classified-NEGATIF complaint becomes a ticket)."
    ),
)
async def update_automation_mode(
    body: AutomationModeUpdate,
    request: Request,
    current: Annotated[CurrentUser, _TenantAdmin],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    config: Annotated[TenantConfigService, Depends(get_tenant_config_service)],
) -> None:
    tenant_id = _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        try:
            await config.set_automation_mode(
                tenant_id, body.automation_mode, actor_user_id=current.user_id
            )
        except TenantConfigError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
            ) from exc
        # Sprint 9.3 C — operator decision audit. Automation mode
        # gates whether complaint reviews auto-spawn tickets, so the
        # toggle is a load-bearing tenant policy decision; record it
        # on the timeline alongside SLA + dispatch-mode flips.
        await DecisionAuditService(app_session).record_decision(
            tenant_id=tenant_id,
            decision_type=DECISION_TENANT_SETTING_CHANGED,
            related_entity_type="tenant",
            related_entity_id=tenant_id,
            actor_user_id=current.user_id,
            payload={
                "setting": "automation_mode",
                "next": str(body.automation_mode),
            },
            request_id=getattr(request.state, "request_id", None),
        )


@router.patch(
    "/categories/{category_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Enable / disable a category for the active tenant.",
)
async def toggle_category(
    category_id: UUID,
    body: CategoryToggleRequest,
    current: Annotated[CurrentUser, _TenantAdmin],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    config: Annotated[TenantConfigService, Depends(get_tenant_config_service)],
) -> None:
    tenant_id = _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        try:
            await config.toggle_category(
                tenant_id,
                category_id,
                is_enabled=body.is_enabled,
                actor_user_id=current.user_id,
            )
        except CategoryNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
            ) from exc


@router.post(
    "/custom-categories",
    status_code=status.HTTP_201_CREATED,
    response_model=CategoryView,
    summary="Create a tenant-scoped custom category.",
    description=(
        "Code must not collide with a global (reserved) code or with an "
        "existing custom code for this tenant. The new row is enabled "
        "by default."
    ),
    responses={
        409: {"description": "Code collides with a global or an existing custom."},
    },
)
async def create_custom_category(
    body: CustomCategoryCreate,
    current: Annotated[CurrentUser, _TenantAdmin],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    config: Annotated[TenantConfigService, Depends(get_tenant_config_service)],
) -> CategoryView:
    tenant_id = _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        try:
            cat = await config.create_custom_category(
                tenant_id,
                code=body.code,
                label_tr=body.label_tr,
                label_en=body.label_en,
                description=body.description,
                actor_user_id=current.user_id,
            )
        except CategoryCodeConflictError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=str(exc)
            ) from exc
        except TenantConfigError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc
    return CategoryView(
        id=cat.id,
        code=cat.code,
        label_tr=cat.label_tr,
        label_en=cat.label_en,
        description=cat.description,
        is_global=False,
        is_enabled=True,
        is_archived=False,
    )


@router.patch(
    "/custom-categories/{category_id}",
    response_model=CategoryView,
    summary="Edit a custom category's labels / description.",
)
async def update_custom_category(
    category_id: UUID,
    body: CustomCategoryUpdate,
    current: Annotated[CurrentUser, _TenantAdmin],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    config: Annotated[TenantConfigService, Depends(get_tenant_config_service)],
) -> CategoryView:
    tenant_id = _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        try:
            cat = await config.update_custom_category(
                tenant_id,
                category_id,
                label_tr=body.label_tr,
                label_en=body.label_en,
                description=body.description,
                actor_user_id=current.user_id,
            )
        except CategoryNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
            ) from exc
    return CategoryView(
        id=cat.id,
        code=cat.code,
        label_tr=cat.label_tr,
        label_en=cat.label_en,
        description=cat.description,
        is_global=False,
        is_enabled=True,  # update doesn't touch enablement; UI re-reads /config for canonical state
        is_archived=cat.deleted_at is not None,
    )


@router.delete(
    "/custom-categories/{category_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Archive (soft-delete) a custom category.",
    description=(
        "The row stays so historic ticket views can still render the "
        "label, but is_archived flips to true and the category becomes "
        "ineligible for new tickets. Globals cannot be archived."
    ),
)
async def archive_custom_category(
    category_id: UUID,
    current: Annotated[CurrentUser, _TenantAdmin],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    config: Annotated[TenantConfigService, Depends(get_tenant_config_service)],
) -> None:
    """Soft-delete a custom category. Sprint 7.5 will add ON DELETE
    RESTRICT against tickets; today there are no tickets so a soft
    delete is enough — the row stays so historic ticket views can
    still render the label."""
    tenant_id = _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        try:
            await config.archive_custom_category(
                tenant_id, category_id, actor_user_id=current.user_id
            )
        except CategoryNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
            ) from exc
        except TenantConfigError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc
