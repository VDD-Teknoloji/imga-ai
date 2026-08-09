"""``/admin/tenants/{tenant_id}/llm-credentials`` — super-admin LLM
kimlik yonetimi.

2026-08-09: yapay zeka modeli + API anahtari yonetimi kurumdan
alinip super-admin'e verildi. Yazma yolu artik yalniz burasi; kurum
tarafinda kalan tek sey maskeli okuma listesi
(``routes/tenant_llm_credentials.py``).

Her endpoint ``require_super_admin`` + imga_admin (BYPASSRLS)
oturumu kullanir. BYPASSRLS demek: RLS hicbir sorguyu filtrelemez,
kurum kapsamini yalniz yol parametresinden gelen ``tenant_id``
predicate'i saglar — her sorguda acikca yazilmasi zorunlu.

Transaction: burada ``async with admin_session.begin()`` YOK, bilerek.
``get_current_user`` ayni admin_session'i (FastAPI dependency cache)
bir SELECT icin kullaniyor ve AsyncSession autobegin ile transaction'i
acik birakiyor; handler ayrica ``begin()`` cagirirsa "A transaction is
already begun on this Session" 500'u patlar — prod C1/C2 bug'i,
bkz. tests/test_admin_session_regression.py. Sorgular autobegin'lenen
transaction'a katilir, ``get_admin_session`` cikista commit eder,
HTTPException'da rollback eder. admin/tenants.py ve admin/invitations.py
da ayni kalibi kullanir.

Model katalogu ``/admin/openrouter-models`` altinda; super-admin'in
aktif kurumu olmadigi icin kurum-tarafi katalog endpoint'i onun
baglaminda calismaz.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from imga_core.security.encryption import encrypt
from imga_db.models import Tenant, TenantLlmCredential
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import CurrentUser, require_super_admin
from imga_api.db_deps import get_admin_session
from imga_api.services.llm_credential_crud import (
    CredentialResponse,
    OpenRouterModelListResponse,
    fetch_openrouter_catalog,
    list_credential_rows,
    to_response,
)

router = APIRouter(prefix="/admin", tags=["Admin: LLM"])

_SuperAdmin = Depends(require_super_admin)

_CREDENTIALS = "/tenants/{tenant_id}/llm-credentials"


# --- request models ------------------------------------------------


class CredentialCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=64)
    api_key: str = Field(min_length=10, max_length=256)
    provider: str = Field(default="gemini", pattern="^(gemini|openrouter)$")
    # OpenRouter icin model kimligi (orn. "openai/gpt-5-mini");
    # NULL -> saglayici varsayilani.
    model: str | None = Field(default=None, min_length=1, max_length=128)


class CredentialUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str | None = Field(default=None, min_length=1, max_length=64)
    is_active: bool | None = None
    model: str | None = Field(default=None, min_length=1, max_length=128)


class CredentialReorderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ordered_ids: list[UUID] = Field(min_length=1)


# --- helpers -------------------------------------------------------


async def _ensure_tenant(session: AsyncSession, tenant_id: UUID) -> None:
    exists = (
        await session.execute(select(Tenant.id).where(Tenant.id == tenant_id))
    ).scalar_one_or_none()
    if exists is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="tenant not found"
        )


async def _get_owned_row(
    session: AsyncSession, tenant_id: UUID, credential_id: UUID
) -> TenantLlmCredential:
    row = await session.get(TenantLlmCredential, credential_id)
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="credential not found",
        )
    return row


# --- endpoints -----------------------------------------------------


@router.get(
    _CREDENTIALS,
    response_model=list[CredentialResponse],
    summary="Bir kurumun LLM kimliklerini listele (yalniz onizleme).",
)
async def admin_list_credentials(
    tenant_id: UUID,
    _current: Annotated[CurrentUser, _SuperAdmin],
    admin_session: Annotated[AsyncSession, Depends(get_admin_session)],
) -> list[CredentialResponse]:
    await _ensure_tenant(admin_session, tenant_id)
    rows = await list_credential_rows(admin_session, tenant_id)
    return [to_response(r) for r in rows]


@router.post(
    _CREDENTIALS,
    response_model=CredentialResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Kuruma yeni LLM kimligi ekle. Oto-oncelik = max + 1.",
)
async def admin_create_credential(
    tenant_id: UUID,
    body: CredentialCreateRequest,
    _current: Annotated[CurrentUser, _SuperAdmin],
    admin_session: Annotated[AsyncSession, Depends(get_admin_session)],
) -> CredentialResponse:
    api_key = body.api_key.strip()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="api_key cannot be blank",
        )
    ciphertext = encrypt(api_key)
    await _ensure_tenant(admin_session, tenant_id)
    max_pri = (
        await admin_session.execute(
            select(func.max(TenantLlmCredential.priority))
            .where(TenantLlmCredential.tenant_id == tenant_id)
        )
    ).scalar()
    next_priority = 0 if max_pri is None else max_pri + 1
    row = TenantLlmCredential(
        tenant_id=tenant_id,
        provider=body.provider,
        model=body.model,
        label=body.label,
        encrypted_value=ciphertext,
        priority=next_priority,
        is_active=True,
    )
    admin_session.add(row)
    await admin_session.flush()
    return to_response(row, plaintext=api_key)


@router.put(
    f"{_CREDENTIALS}/reorder",
    response_model=list[CredentialResponse],
    summary="Oncelik sirasini yeniden yaz. Govde her kimligi icermeli.",
)
async def admin_reorder_credentials(
    tenant_id: UUID,
    body: CredentialReorderRequest,
    _current: Annotated[CurrentUser, _SuperAdmin],
    admin_session: Annotated[AsyncSession, Depends(get_admin_session)],
) -> list[CredentialResponse]:
    await _ensure_tenant(admin_session, tenant_id)
    # ID-only fetch first — the request is validated against the
    # existing set before any UPDATE. Avoids loading ORM rows that
    # would expire after the bulk UPDATE and trigger MissingGreenlet
    # on attribute access.
    existing_id_rows = (
        await admin_session.execute(
            select(TenantLlmCredential.id)
            .where(TenantLlmCredential.tenant_id == tenant_id)
        )
    ).all()
    existing_ids = {r.id for r in existing_id_rows}
    requested_ids = set(body.ordered_ids)
    if requested_ids != existing_ids:
        missing = existing_ids - requested_ids
        extra = requested_ids - existing_ids
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "reorder_mismatch",
                "missing": sorted(str(m) for m in missing),
                "extra": sorted(str(e) for e in extra),
            },
        )
    # Two-pass bulk UPDATE so the (tenant, provider, priority) unique
    # constraint stays satisfied mid-rewrite. Step 1 pushes every row
    # into a high range; step 2 writes the final 0..N priorities. Both
    # passes share the request's single transaction, so a failure
    # mid-way rolls the whole rewrite back. Pure SQL — no ORM mutation,
    # so no post-flush expire / MissingGreenlet on the decrypt path.
    await admin_session.execute(
        update(TenantLlmCredential)
        .where(TenantLlmCredential.tenant_id == tenant_id)
        .values(priority=TenantLlmCredential.priority + 10_000)
    )
    for new_priority, cid in enumerate(body.ordered_ids):
        await admin_session.execute(
            update(TenantLlmCredential)
            .where(TenantLlmCredential.id == cid)
            .where(TenantLlmCredential.tenant_id == tenant_id)
            .values(priority=new_priority)
        )
    rows = await list_credential_rows(admin_session, tenant_id)
    return [to_response(r) for r in rows]


@router.patch(
    f"{_CREDENTIALS}/{{credential_id}}",
    response_model=CredentialResponse,
    summary="Etiket / model / aktiflik guncelle (oncelik: /reorder).",
)
async def admin_update_credential(
    tenant_id: UUID,
    credential_id: UUID,
    body: CredentialUpdateRequest,
    _current: Annotated[CurrentUser, _SuperAdmin],
    admin_session: Annotated[AsyncSession, Depends(get_admin_session)],
) -> CredentialResponse:
    payload = body.model_dump(exclude_unset=True)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="no updatable fields supplied",
        )
    await _ensure_tenant(admin_session, tenant_id)
    row = await _get_owned_row(admin_session, tenant_id, credential_id)
    for k, v in payload.items():
        setattr(row, k, v)
    await admin_session.flush()
    # onupdate=func.now() updated_at'i expire eder; refresh olmadan
    # to_response senkron lazy-load -> MissingGreenlet patlatir.
    await admin_session.refresh(row)
    return to_response(row)


@router.delete(
    f"{_CREDENTIALS}/{{credential_id}}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Kimligi sil. Kalan oncelikler otomatik sikistirilmaz.",
)
async def admin_delete_credential(
    tenant_id: UUID,
    credential_id: UUID,
    _current: Annotated[CurrentUser, _SuperAdmin],
    admin_session: Annotated[AsyncSession, Depends(get_admin_session)],
) -> None:
    await _ensure_tenant(admin_session, tenant_id)
    # Confirm ownership before delete — a 404 is friendlier than a
    # silent no-op, and on the BYPASSRLS session it is the only thing
    # standing between a typo'd id and a cross-tenant delete.
    await _get_owned_row(admin_session, tenant_id, credential_id)
    await admin_session.execute(
        delete(TenantLlmCredential)
        .where(TenantLlmCredential.id == credential_id)
        .where(TenantLlmCredential.tenant_id == tenant_id)
    )


@router.get(
    "/openrouter-models",
    response_model=OpenRouterModelListResponse,
    summary="OpenRouter model katalogu (1 saat onbellekli canli proxy).",
)
async def admin_list_openrouter_models(
    _current: Annotated[CurrentUser, _SuperAdmin],
) -> OpenRouterModelListResponse:
    return await fetch_openrouter_catalog()
