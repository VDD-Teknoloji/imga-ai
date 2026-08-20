"""``/tenants/me/onboarding`` — AI kategori önerisi + uygulama (WS1).

İki adım:

  1. ``POST .../suggest-categories`` — tenant'ın profil alanları +
     (opsiyonel) son yorumlarından bir örneklem tek LLM çağrısına
     gönderilir; öneri PERSIST EDİLMEZ, yalnız döner.
  2. ``POST .../apply-categories`` — kullanıcının seçtiği alt küme tek
     transaction'da yazılır (custom Category + CategoryTaxonomy +
     global kapatma).

Rol/authz deseni ``routes/tenant_config.py`` ile aynı: her iki
endpoint de TENANT_ADMIN gerektirir (kategori/taksonomi mimarisini
değiştiren bir işlem — ANALYST/VIEWER salt-okunur kalır)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from imga_core.llm import AllKeysExhaustedError, LLMError
from imga_db.models import UserTenantRole
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import CurrentUser, bind_tenant, require_role
from imga_api.db_deps import get_app_session
from imga_api.dependencies import get_tenant_config_service
from imga_api.services.llm_credentials import NoCredentialsError
from imga_api.services.onboarding_service import (
    SAMPLE_LIMIT_DEFAULT,
    AppliedCategoriesResult,
    CategorySuggestion,
    OnboardingService,
    OnboardingServiceError,
)
from imga_api.services.tenant_config_service import (
    CategoryCodeArchivedError,
    TenantConfigService,
)

router = APIRouter(prefix="/tenants/me/onboarding", tags=["Tenant Onboarding"])

_TenantAdmin = Depends(require_role(UserTenantRole.TENANT_ADMIN))


def _require_active_tenant(current: CurrentUser) -> UUID:
    if current.active_tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="active tenant context required for this endpoint",
        )
    return current.active_tenant_id


def _onboarding_error_to_http(exc: Exception) -> HTTPException:
    """Servis katmanı hatalarını wire-shape HTTPException'a çevirir —
    tenant_strategic_reports.py'deki ``_llm_error_to_http`` ile aynı
    desen."""
    if isinstance(exc, NoCredentialsError):
        return HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail={
                "code": "no_llm_credentials",
                "message": (
                    "Aktif LLM API anahtarı tanımlanmamış. "
                    "Ayarlar > Entegrasyonlar üzerinden ekleyin."
                ),
            },
        )
    if isinstance(exc, AllKeysExhaustedError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "all_keys_exhausted",
                "message": (
                    "Tüm API anahtarları kotayı aştı veya geçersiz. "
                    "Ayarlar > Entegrasyonlar üzerinden kontrol edin."
                ),
            },
        )
    if isinstance(exc, LLMError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "llm_error",
                "message": "LLM sağlayıcı hatası, lütfen tekrar deneyin.",
            },
        )
    # 2026-08-18 (bulgu) — arşivli-kod çakışması: OnboardingServiceError
    # kontrolünden ÖNCE, kesin tip olarak yakalanır (CategoryCodeArchivedError
    # bir CategoryCodeConflictError alt sınıfı ama onboarding_service.
    # apply_categories bunu artık OnboardingServiceError'a SARMIYOR —
    # bkz. o dosyanın apply_categories yorumu). Temiz Türkçe mesaj + 409;
    # ham asyncpg IntegrityError metni asla buraya kadar gelmez.
    if isinstance(exc, CategoryCodeArchivedError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "category_code_archived", "message": str(exc)},
        )
    if isinstance(exc, OnboardingServiceError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        )
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"onboarding service failed: {exc}",
    )


# --- request / response models ------------------------------------------


class SuggestCategoriesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Tenant'ın son yorumlarından örnek boyutu — varsayılan 100,
    # tavan 300 (servis katmanı da tavanlar; burada kullanıcıya
    # anlamlı bir 400 mesajı için tekrarlanır).
    sample_limit: int = Field(default=SAMPLE_LIMIT_DEFAULT, ge=0, le=300)


class SuggestedCategoryView(BaseModel):
    code: str
    label_tr: str
    description: str


class SuggestedTaxonomyView(BaseModel):
    code: str
    label_tr: str
    primary_category_code: str


class SuggestCategoriesResponse(BaseModel):
    top_categories: list[SuggestedCategoryView]
    subcategories: list[SuggestedTaxonomyView]
    disable_global_codes: list[str]
    rationale: str


class ApplyTopCategoryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(..., min_length=1, max_length=64)
    label_tr: str = Field(..., min_length=1, max_length=128)
    description: str | None = None


class ApplySubcategoryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(..., min_length=1, max_length=64)
    label_tr: str = Field(..., min_length=1, max_length=128)
    primary_category_code: str | None = None


class ApplyCategoriesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    top_categories: list[ApplyTopCategoryInput] = Field(default_factory=list)
    subcategories: list[ApplySubcategoryInput] = Field(default_factory=list)
    disable_global_codes: list[str] = Field(default_factory=list)


class ApplyCategoriesResponse(BaseModel):
    created_categories: list[str]
    created_taxonomies: list[str]
    disabled_global_codes: list[str]


def _suggestion_to_response(s: CategorySuggestion) -> SuggestCategoriesResponse:
    return SuggestCategoriesResponse(
        top_categories=[
            SuggestedCategoryView(
                code=c.code, label_tr=c.label_tr, description=c.description
            )
            for c in s.top_categories
        ],
        subcategories=[
            SuggestedTaxonomyView(
                code=t.code,
                label_tr=t.label_tr,
                primary_category_code=t.primary_category_code,
            )
            for t in s.subcategories
        ],
        disable_global_codes=list(s.disable_global_codes),
        rationale=s.rationale,
    )


def _applied_to_response(r: AppliedCategoriesResult) -> ApplyCategoriesResponse:
    return ApplyCategoriesResponse(
        created_categories=list(r.created_categories),
        created_taxonomies=list(r.created_taxonomies),
        disabled_global_codes=list(r.disabled_global_codes),
    )


# --- endpoints ------------------------------------------------------------


@router.post(
    "/suggest-categories",
    response_model=SuggestCategoriesResponse,
    summary="AI kategori önerisi üret (persist edilmez).",
    description=(
        "Tenant'ın sektör/büyüklük/iş tanımı/terim sözlüğü + (varsa) son "
        "yorumlarından bir örneklemi TEK structured LLM çağrısına "
        "gönderir. Öneri yalnız döner — seçilen alt küme "
        "/apply-categories ile yazılır."
    ),
    responses={
        400: {"description": "Onboarding servis hatası (ör. tenant yok)."},
        412: {"description": "Tenant'ın aktif LLM anahtarı yok."},
        503: {"description": "LLM sağlayıcı hatası / tüm anahtarlar tükendi."},
    },
)
async def suggest_categories(
    body: SuggestCategoriesRequest,
    current: Annotated[CurrentUser, _TenantAdmin],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> SuggestCategoriesResponse:
    tenant_id = _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        service = OnboardingService(app_session, tenant_id)
        try:
            suggestion = await service.suggest_categories(
                sample_limit=body.sample_limit,
                actor_user_id=current.user_id,
            )
        except Exception as exc:
            raise _onboarding_error_to_http(exc) from exc
    return _suggestion_to_response(suggestion)


@router.post(
    "/apply-categories",
    response_model=ApplyCategoriesResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Seçilen kategori önerisini uygula (custom Category + CategoryTaxonomy + toggle).",
    description=(
        "Kullanıcının öneriden seçtiği alt küme tek transaction'da "
        "yazılır: her ``top_categories`` girdisi custom Category satırı, "
        "her ``subcategories`` girdisi CategoryTaxonomy satırı, her "
        "``disable_global_codes`` kodu global kategoriyi bu tenant için "
        "kapatır. Her adım kendi audit satırını yazar; ayrıca bir özet "
        "``tenant.onboarding.apply_categories`` audit satırı düşülür."
    ),
    responses={
        400: {"description": "Geçersiz/çakışan kod ya da kod zaten var."},
    },
)
async def apply_categories(
    body: ApplyCategoriesRequest,
    current: Annotated[CurrentUser, _TenantAdmin],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    config: Annotated[TenantConfigService, Depends(get_tenant_config_service)],
) -> ApplyCategoriesResponse:
    tenant_id = _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        service = OnboardingService(app_session, tenant_id)
        try:
            result = await service.apply_categories(
                config=config,
                top_categories=[c.model_dump() for c in body.top_categories],
                subcategories=[t.model_dump() for t in body.subcategories],
                disable_global_codes=body.disable_global_codes,
                actor_user_id=current.user_id,
            )
        except Exception as exc:
            raise _onboarding_error_to_http(exc) from exc
    return _applied_to_response(result)
