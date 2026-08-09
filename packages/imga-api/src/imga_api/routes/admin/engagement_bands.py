"""``/admin/tenants/{tenant_id}/engagement-bands`` — katılım eşikleri.

"%2 katılım iyi mi kötü mü" sorusunun cevabı sektöre göre değişir;
bu yüzden bantları kurum düzenlemez, süper yönetici düzenler. Kurum
tarafı bantları yalnızca okur (``GET /tenants/me/engagement``).

``imga_admin`` BYPASSRLS olduğu için her sorgu açık ``tenant_id``
taşır ve bilinmeyen kurum 404 döner. Handler gövdesi
``admin_session.begin()`` ile SARILMAZ — ``get_current_user`` paylaşılan
admin session'ında zaten bir transaction açmış oluyor; commit teardown'da
gerçekleşir (admin/tenants.py idiomu).
"""

from __future__ import annotations

from itertools import pairwise
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from imga_db.models import Tenant
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import CurrentUser, require_super_admin
from imga_api.db_deps import get_admin_session
from imga_api.services import EngagementService

router = APIRouter(
    prefix="/admin/tenants/{tenant_id}/engagement-bands",
    tags=["Admin: Engagement Bands"],
)

MAX_BANDS = 8


class BandInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    min_pct: float = Field(..., ge=0, le=100)
    label: str = Field(..., min_length=1, max_length=64)

    @field_validator("label")
    @classmethod
    def _v_label(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("label boş olamaz")
        return stripped


class BandsUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bands: list[BandInput] = Field(..., min_length=1, max_length=MAX_BANDS)

    @field_validator("bands")
    @classmethod
    def _v_bands(cls, v: list[BandInput]) -> list[BandInput]:
        """Bantlar 0'dan başlar ve kesin artan olur. Sıra iş kuralının
        kendisi: bir oran, ``min_pct <= pct`` sağlayan EN SON banda
        düşer — sıralama bozulursa değerlendirme sessizce yanlışlanır."""
        if v[0].min_pct != 0:
            raise ValueError("ilk bandın min_pct değeri 0 olmalı")
        for previous, current in pairwise(v):
            if current.min_pct <= previous.min_pct:
                raise ValueError("min_pct değerleri artan ve tekil olmalı")
        return v


class BandsResponse(BaseModel):
    tenant_id: UUID
    bands: list[BandInput]
    is_default: bool


async def _require_tenant(session: AsyncSession, tenant_id: UUID) -> None:
    """BYPASSRLS rolündeyiz — kurum var mı diye açıkça sormazsak
    bilinmeyen bir UUID sessizce boş bant listesi döndürürdü."""
    exists = (
        await session.execute(select(Tenant.id).where(Tenant.id == tenant_id))
    ).scalar_one_or_none()
    if exists is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="tenant not found"
        )


def _to_band_inputs(bands: list[dict[str, Any]]) -> list[BandInput]:
    return [
        BandInput(min_pct=float(b["min_pct"]), label=str(b["label"]))
        for b in bands
    ]


@router.get(
    "",
    response_model=BandsResponse,
    summary="Kurumun katılım oranı bantlarını oku (yoksa varsayılan).",
)
async def get_engagement_bands(
    tenant_id: UUID,
    _current: Annotated[CurrentUser, Depends(require_super_admin)],
    admin_session: Annotated[AsyncSession, Depends(get_admin_session)],
) -> BandsResponse:
    await _require_tenant(admin_session, tenant_id)
    service = EngagementService(admin_session)
    row = await service.get_settings_row(tenant_id=tenant_id)
    bands = await service.get_bands(tenant_id=tenant_id)
    return BandsResponse(
        tenant_id=tenant_id,
        bands=_to_band_inputs(bands),
        is_default=row is None or not row.bands,
    )


@router.put(
    "",
    response_model=BandsResponse,
    summary="Kurumun katılım oranı bantlarını değiştir.",
)
async def update_engagement_bands(
    tenant_id: UUID,
    body: BandsUpdateRequest,
    current: Annotated[CurrentUser, Depends(require_super_admin)],
    admin_session: Annotated[AsyncSession, Depends(get_admin_session)],
) -> BandsResponse:
    await _require_tenant(admin_session, tenant_id)
    service = EngagementService(admin_session)
    payload: list[dict[str, Any]] = [
        {"min_pct": b.min_pct, "label": b.label} for b in body.bands
    ]
    await service.set_bands(
        tenant_id=tenant_id,
        bands=payload,
        updated_by_user_id=current.user_id,
    )
    return BandsResponse(
        tenant_id=tenant_id,
        bands=_to_band_inputs(payload),
        is_default=False,
    )
