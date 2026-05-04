"""``/tenants/me/llm-credentials`` — manage tenant Gemini API keys.

Sprint 8.3.6.5 / Alt-Faz 8.3.6.5.C. Encrypted storage,
priority-ordered for the multi-key rotator. Five endpoints (master
prompt's spec):

  * GET    list (preview only — last 4 chars; full plaintext never
                  leaves the server after the create call)
  * POST   create (auto-priority = max + 1)
  * PATCH  /{id} (label + is_active; priority changed via reorder)
  * PUT    reorder (full ordered list, priorities re-assigned 0..N)
  * DELETE /{id}

Security contract:

  * Plaintext key only ever lives in the create request body and the
    Fernet ciphertext lives in the DB. Other endpoints never expose
    the plaintext.
  * ``value_preview`` shows only the last 4 chars of the plaintext —
    enough for the user to recognise "yes that's the key I pasted"
    without exposing usable secret material.
  * RLS filters every query to the active tenant; the explicit
    ``tenant_id ==`` predicate is belt-and-braces.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from imga_core.security.encryption import EncryptionError, decrypt, encrypt
from imga_db.models import TenantLlmCredential, UserTenantRole
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import CurrentUser, bind_tenant, require_role
from imga_api.db_deps import get_app_session

router = APIRouter(
    prefix="/tenants/me/llm-credentials",
    tags=["Tenant Config"],
)

_AnyMember = Depends(require_role(
    UserTenantRole.TENANT_ADMIN,
    UserTenantRole.ANALYST,
    UserTenantRole.VIEWER,
))
_WriteMember = Depends(require_role(
    UserTenantRole.TENANT_ADMIN,
    UserTenantRole.ANALYST,
))


def _require_active_tenant(current: CurrentUser) -> UUID:
    if current.active_tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="active tenant context required for this endpoint",
        )
    return current.active_tenant_id


# --- response + request models -------------------------------------


class CredentialResponse(BaseModel):
    id: UUID
    label: str
    provider: str
    priority: int
    is_active: bool
    value_preview: str
    last_failed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CredentialCreateRequest(BaseModel):
    label: str = Field(min_length=1, max_length=64)
    api_key: str = Field(min_length=10, max_length=256)


class CredentialUpdateRequest(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=64)
    is_active: bool | None = None


class CredentialReorderRequest(BaseModel):
    ordered_ids: list[UUID] = Field(min_length=1)


# --- helpers -------------------------------------------------------


def _value_preview(plaintext: str) -> str:
    """Last 4 chars of the API key, prefixed with ``...``. Enough for
    recognition, useless as a credential."""
    if len(plaintext) <= 4:
        return "..."
    return f"...{plaintext[-4:]}"


def _to_response(
    row: TenantLlmCredential, *, plaintext: str | None = None
) -> CredentialResponse:
    """Materialise a credential row as the wire response. ``plaintext``
    is the just-decrypted value when the caller has it on hand
    (e.g. inside ``list``); when ``None``, decryption is attempted
    here and a placeholder preview surfaces on failure (corrupted
    ciphertext / master key mismatch).
    """
    if plaintext is None:
        try:
            plaintext = decrypt(row.encrypted_value)
            preview = _value_preview(plaintext)
        except EncryptionError:
            preview = "...?"
    else:
        preview = _value_preview(plaintext)
    return CredentialResponse(
        id=row.id,
        label=row.label,
        provider=row.provider,
        priority=row.priority,
        is_active=row.is_active,
        value_preview=preview,
        last_failed_at=row.last_failed_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


# --- endpoints -----------------------------------------------------


@router.get(
    "",
    response_model=list[CredentialResponse],
    summary="List tenant's Gemini API credentials (preview only).",
)
async def list_credentials(
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> list[CredentialResponse]:
    tenant_id = _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        rows = (
            await app_session.execute(
                select(TenantLlmCredential)
                .where(TenantLlmCredential.tenant_id == tenant_id)
                .where(TenantLlmCredential.provider == "gemini")
                .order_by(TenantLlmCredential.priority.asc())
            )
        ).scalars().all()
    return [_to_response(r) for r in rows]


@router.post(
    "",
    response_model=CredentialResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a new Gemini API credential. Auto-priority = max + 1.",
)
async def create_credential(
    body: CredentialCreateRequest,
    current: Annotated[CurrentUser, _WriteMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> CredentialResponse:
    tenant_id = _require_active_tenant(current)
    api_key = body.api_key.strip()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="api_key cannot be blank",
        )
    ciphertext = encrypt(api_key)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        # Auto-priority: max(existing) + 1, or 0 if first.
        max_pri = (
            await app_session.execute(
                select(func.max(TenantLlmCredential.priority))
                .where(TenantLlmCredential.tenant_id == tenant_id)
                .where(TenantLlmCredential.provider == "gemini")
            )
        ).scalar()
        next_priority = 0 if max_pri is None else max_pri + 1
        row = TenantLlmCredential(
            tenant_id=tenant_id,
            provider="gemini",
            label=body.label,
            encrypted_value=ciphertext,
            priority=next_priority,
            is_active=True,
        )
        app_session.add(row)
        await app_session.flush()
        return _to_response(row, plaintext=api_key)


@router.patch(
    "/{credential_id}",
    response_model=CredentialResponse,
    summary="Update a credential's label and/or active flag (priority via /reorder).",
)
async def update_credential(
    credential_id: UUID,
    body: CredentialUpdateRequest,
    current: Annotated[CurrentUser, _WriteMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> CredentialResponse:
    tenant_id = _require_active_tenant(current)
    payload = body.model_dump(exclude_unset=True)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="no updatable fields supplied",
        )
    async with app_session.begin():
        await bind_tenant(app_session, current)
        row = await app_session.get(TenantLlmCredential, credential_id)
        if row is None or row.tenant_id != tenant_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="credential not found",
            )
        for k, v in payload.items():
            setattr(row, k, v)
        await app_session.flush()
        return _to_response(row)


@router.put(
    "/reorder",
    response_model=list[CredentialResponse],
    summary="Reorder credentials by priority. Caller must include every active credential ID.",
)
async def reorder_credentials(
    body: CredentialReorderRequest,
    current: Annotated[CurrentUser, _WriteMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> list[CredentialResponse]:
    tenant_id = _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        # ID-only fetch first — we need to validate the request
        # against the existing set before any UPDATE. Avoids loading
        # ORM rows that would expire after the bulk UPDATE and
        # trigger MissingGreenlet on attribute access.
        existing_id_rows = (
            await app_session.execute(
                select(TenantLlmCredential.id)
                .where(TenantLlmCredential.tenant_id == tenant_id)
                .where(TenantLlmCredential.provider == "gemini")
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
        # Two-pass bulk UPDATE so the (tenant, provider, priority)
        # unique constraint stays satisfied mid-rewrite. Step 1
        # pushes every active credential into a high range; step 2
        # writes the final 0..N priorities. Pure SQL — no ORM
        # mutation, so no post-flush expire / MissingGreenlet
        # surprise on the subsequent decrypt path.
        await app_session.execute(
            update(TenantLlmCredential)
            .where(TenantLlmCredential.tenant_id == tenant_id)
            .where(TenantLlmCredential.provider == "gemini")
            .values(priority=TenantLlmCredential.priority + 10_000)
        )
        for new_priority, cid in enumerate(body.ordered_ids):
            await app_session.execute(
                update(TenantLlmCredential)
                .where(TenantLlmCredential.id == cid)
                .values(priority=new_priority)
            )
        # Re-fetch to surface the post-rewrite ordering.
        rows = (
            await app_session.execute(
                select(TenantLlmCredential)
                .where(TenantLlmCredential.tenant_id == tenant_id)
                .where(TenantLlmCredential.provider == "gemini")
                .order_by(TenantLlmCredential.priority.asc())
            )
        ).scalars().all()
        return [_to_response(r) for r in rows]


@router.delete(
    "/{credential_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a credential. Other priorities are NOT compacted automatically.",
)
async def delete_credential(
    credential_id: UUID,
    current: Annotated[CurrentUser, _WriteMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> None:
    tenant_id = _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        # Confirm ownership before delete; raw DELETE under RLS would
        # also work, but a 404 is friendlier than a silent no-op.
        row = await app_session.get(TenantLlmCredential, credential_id)
        if row is None or row.tenant_id != tenant_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="credential not found",
            )
        await app_session.execute(
            delete(TenantLlmCredential).where(
                TenantLlmCredential.id == credential_id
            )
        )


# Silence "imported but unused" hints when a future refactor drops
# the bulk update import.
_ = update
