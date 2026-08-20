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
from typing import Annotated, Any, Literal
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
from imga_api.services.tenant_service import TenantListRow

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
    # Kurum arayüz + AI çıktı dili — oluştururken seçilir (Sprint 12 i18n).
    language: Literal["tr", "en"] = "tr"
    initial_admin: InitialAdminInput | None = None
    # 2026-08-18 (WS1 onboarding, migration 0042) — opsiyonel: create
    # anında doldurulursa SWOT/OKR/brifing prompt bağlamı + AI kategori
    # önerisi (suggest-categories) daha isabetli başlar. Boş bırakılırsa
    # kurum eski davranışla (profil boş) oluşur, /settings/profile'dan
    # sonradan doldurulabilir (terminology hariç — bkz.
    # docs/analysis/2026-08-18-rag-mimari.md dışı, TenantService.create
    # docstring'i).
    industry: str | None = Field(default=None, max_length=64)
    industry_other_text: str | None = Field(default=None, max_length=128)
    company_size: str | None = Field(default=None, max_length=32)
    business_description: str | None = Field(default=None, max_length=500)
    # list[{"term": str, "note": str}] — terminology_directive'in ham
    # girdisi (strategic_constants.py). Şekil doğrulaması orada best-
    # effort yapılır (boş/eksik term'ler sessizce atlanır); burada
    # yalnız üst sınır (liste boyutu) kontrol edilir.
    terminology: list[dict[str, str]] | None = Field(default=None, max_length=200)


class TenantUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=255)
    plan_tier: TenantPlanTier | None = None
    automation_mode: AutomationMode | None = None
    language: Literal["tr", "en"] | None = None
    settings: dict[str, Any] | None = None


class TenantSummary(BaseModel):
    id: UUID
    name: str
    slug: str
    plan_tier: str
    automation_mode: str
    language: str
    created_at: datetime
    deleted_at: datetime | None
    # 2026-08-20 (C3+B7, süper-admin envanteri) — yalnız list_tenants
    # doldurur (tek ana sorgu + LEFT JOIN alt-sorgular, TenantService.list
    # bkz.). create/get/update/delete tek kurum döner ve bu toplu
    # metrikleri HESAPLAMAZ; None burada "bilinmiyor" değil "bu yanıtta
    # hesaplanmadı" demek — frontend'i yanlış sıfırla yanıltmamak için
    # 0 yerine None kullanılır.
    review_count: int | None = None
    last_upload_at: datetime | None = None
    tokens_30d: int | None = None
    cost_30d_usd: float | None = None
    engagement_band: str | None = None


class TenantListResponse(BaseModel):
    tenants: list[TenantSummary]


class TenantCreateResponse(BaseModel):
    tenant: TenantSummary
    initial_invitation_token: str | None


# --- helpers ----------------------------------------------------------


def _to_summary(tenant: Any, *, stats: TenantListRow | None = None) -> TenantSummary:
    return TenantSummary(
        id=tenant.id,
        name=tenant.name,
        slug=tenant.slug,
        plan_tier=str(tenant.plan_tier),
        automation_mode=str(tenant.automation_mode),
        language=getattr(tenant, "language", "tr"),
        created_at=tenant.created_at,
        deleted_at=tenant.deleted_at,
        review_count=stats.review_count if stats is not None else None,
        last_upload_at=stats.last_upload_at if stats is not None else None,
        tokens_30d=stats.tokens_30d if stats is not None else None,
        cost_30d_usd=(
            float(stats.cost_30d_usd)
            if stats is not None and stats.cost_30d_usd is not None
            else None
        ),
        engagement_band=stats.engagement_band if stats is not None else None,
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
            language=body.language,
            industry=body.industry,
            industry_other_text=body.industry_other_text,
            company_size=body.company_size,
            business_description=body.business_description,
            terminology=body.terminology,
            actor_user_id=current.user_id,
        )
    except TenantSlugTakenError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

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
    return TenantListResponse(tenants=[_to_summary(r.tenant, stats=r) for r in rows])


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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="tenant not found")
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
            language=body.language,
            actor_user_id=current.user_id,
        )
    except TenantNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _to_summary(tenant)
