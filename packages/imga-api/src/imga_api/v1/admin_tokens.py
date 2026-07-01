"""İmga v1 — Admin token yönetimi (contract §4A.3-4A.5). opsBearer.

POST /v1/admin/tokens/rotate       — kesintisiz rotation (§4A.3)
POST /v1/admin/tokens/{id}/revoke  — iptal, ≤60s propagation (§4A.4/§8.5)
GET  /v1/admin/tokens?tenant_id=   — aktif token listesi, hash yok (§4A.5)

Hepsi ops-scope (require_ops); işlemler cross-tenant olduğu için admin_session
(BYPASSRLS). External ``tenant_id`` bir slug'dır (ör. "asakai-prod") →
internal Tenant.id (UUID) çözülür.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, status
from imga_db.models import Tenant
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import get_settings
from imga_api.db_deps import get_admin_session
from imga_api.settings import Settings
from imga_api.services.api_tokens import ApiTokenService
from imga_api.v1.auth import ApiPrincipal, require_ops
from imga_api.v1.errors import PartnerApiError

router = APIRouter(prefix="/v1/admin/tokens", tags=["v1-admin"])


class RotateRequest(BaseModel):
    tenant_id: str
    overlap_window_hours: int = 24


class RotateResponse(BaseModel):
    new_token: str
    new_token_id: UUID
    old_token_expires_at: datetime | None


class RevokeResponse(BaseModel):
    revoked_at: datetime
    propagation_deadline: datetime


class TokenInfo(BaseModel):
    token_id: UUID
    prefix: str
    label: str
    created_at: datetime
    expires_at: datetime
    last_used_at: datetime | None
    scope: str


class TokenListResponse(BaseModel):
    tokens: list[TokenInfo]


def _service(settings: Settings) -> ApiTokenService:
    if settings.token_pepper is None:
        raise PartnerApiError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="auth_failed",
            message="partner api not configured",
        )
    return ApiTokenService(
        pepper=settings.token_pepper, environment=settings.environment
    )


async def _resolve_tenant_uuid(session: AsyncSession, slug: str) -> UUID:
    """External tenant_id (slug) → internal Tenant.id. Bilinmezse 400."""
    row = (
        await session.execute(select(Tenant.id).where(Tenant.slug == slug))
    ).scalar_one_or_none()
    if row is None:
        raise PartnerApiError(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="invalid_input",
            message=f"unknown tenant_id: {slug}",
            details={"field": "tenant_id"},
        )
    return row


@router.post("/rotate", response_model=RotateResponse)
async def rotate_token(
    body: RotateRequest,
    _ops: Annotated[ApiPrincipal, Depends(require_ops)],
    settings: Annotated[Settings, Depends(get_settings)],
    admin_session: Annotated[AsyncSession, Depends(get_admin_session)],
) -> RotateResponse:
    service = _service(settings)
    async with admin_session.begin():
        tenant_uuid = await _resolve_tenant_uuid(admin_session, body.tenant_id)
        result = await service.rotate(
            admin_session,
            tenant_id=tenant_uuid,
            label=f"rotate:{body.tenant_id}",
            overlap_hours=body.overlap_window_hours,
        )
    # plaintext YALNIZ bu yanıtta.
    return RotateResponse(
        new_token=result.new.plaintext,
        new_token_id=result.new.token_id,
        old_token_expires_at=result.old_token_expires_at,
    )


@router.post("/{token_id}/revoke", response_model=RevokeResponse)
async def revoke_token(
    _ops: Annotated[ApiPrincipal, Depends(require_ops)],
    settings: Annotated[Settings, Depends(get_settings)],
    admin_session: Annotated[AsyncSession, Depends(get_admin_session)],
    token_id: Annotated[UUID, Path()],
) -> RevokeResponse:
    service = _service(settings)
    async with admin_session.begin():
        result = await service.revoke(admin_session, token_id, reason="admin_revoke")
    if result is None:
        raise PartnerApiError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="session_not_found",  # §5'te token-özel kod yok; en yakını
            message="token not found or already revoked",
        )
    return RevokeResponse(
        revoked_at=result.revoked_at,
        propagation_deadline=result.propagation_deadline,
    )


@router.get("", response_model=TokenListResponse)
async def list_tokens(
    _ops: Annotated[ApiPrincipal, Depends(require_ops)],
    settings: Annotated[Settings, Depends(get_settings)],
    admin_session: Annotated[AsyncSession, Depends(get_admin_session)],
    tenant_id: Annotated[str, Query()],
) -> TokenListResponse:
    service = _service(settings)
    async with admin_session.begin():
        tenant_uuid = await _resolve_tenant_uuid(admin_session, tenant_id)
        rows = await service.list_tenant_tokens(admin_session, tenant_uuid)
    return TokenListResponse(
        tokens=[
            TokenInfo(
                token_id=r.id,
                prefix=r.token_prefix,
                label=r.label,
                created_at=r.created_at,
                expires_at=r.expires_at,
                last_used_at=r.last_used_at,
                scope=r.scope,
            )
            for r in rows
        ]
    )
