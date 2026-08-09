"""``/tenants/me/llm-credentials`` — kurumun LLM kimliklerini goruntule.

2026-08-09: yapay zeka modeli + API anahtari YONETIMI kurumdan
alinip super-admin'e tasindi. Yazma uclari (POST / PATCH / PUT
reorder / DELETE) bu router'dan kaldirildi; tek yazma yolu
``routes/admin/llm_credentials.py`` altindaki
``/admin/tenants/{tenant_id}/llm-credentials``.

Kurum tarafinda kalan iki salt-okur uc:

  * GET    liste — hangi saglayici/model/oncelik yapilandirilmis,
                   maskeli onizleme ile (son 4 karakter). Strateji ve
                   yonetici-ozeti sayfalari "kimlik var mi" kapisini
                   bu listeden okur.
  * GET    /openrouter-models — model katalogu (secici bos kalmasin
                   diye kuratorlu yedekli).

Guvenlik sozlesmesi: duz metin anahtar bu router'dan asla cikmaz;
``value_preview`` yalniz tanima yeter, kimlik olarak kullanilamaz.
RLS her sorguyu aktif kuruma filtreler; acik ``tenant_id ==``
predicate'i ikinci emniyet kemeridir.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from imga_db.models import UserTenantRole
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import CurrentUser, bind_tenant, require_role
from imga_api.db_deps import get_app_session
from imga_api.services.llm_credential_crud import (
    CredentialResponse,
    OpenRouterModelListResponse,
    fetch_openrouter_catalog,
    list_credential_rows,
    to_response,
)

router = APIRouter(
    prefix="/tenants/me/llm-credentials",
    tags=["Tenant Config"],
)

_AnyMember = Depends(require_role(
    UserTenantRole.TENANT_ADMIN,
    UserTenantRole.ANALYST,
    UserTenantRole.VIEWER,
))


def _require_active_tenant(current: CurrentUser) -> UUID:
    if current.active_tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="active tenant context required for this endpoint",
        )
    return current.active_tenant_id


@router.get(
    "",
    response_model=list[CredentialResponse],
    summary="Kurumun LLM kimliklerini listele (yalniz onizleme).",
)
async def list_credentials(
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> list[CredentialResponse]:
    tenant_id = _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        rows = await list_credential_rows(app_session, tenant_id)
    return [to_response(r) for r in rows]


@router.get(
    "/openrouter-models",
    response_model=OpenRouterModelListResponse,
    summary="OpenRouter model katalogu (1 saat onbellekli canli proxy).",
)
async def list_openrouter_models(
    current: Annotated[CurrentUser, _AnyMember],
) -> OpenRouterModelListResponse:
    _require_active_tenant(current)
    return await fetch_openrouter_catalog()
