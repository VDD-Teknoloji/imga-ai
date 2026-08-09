"""``/tenants/me/monthly-metrics`` + ``/tenants/me/engagement``.

Kurum aylık işlem adedini girer (payda); sistem o ayın yorum sayısını
``reviews.review_date`` üzerinden sayıp katılım oranını hesaplar ve
kuruma tanımlı bantlara göre değerlendirir. Bantları yalnızca süper
yönetici düzenler (bkz. ``routes/admin/engagement_bands.py``); buradaki
uçlar bantları yalnızca OKUR.

  * GET    /tenants/me/monthly-metrics   — liste (her üye)
  * PUT    /tenants/me/monthly-metrics   — ay bazlı upsert (admin+analist)
  * DELETE /tenants/me/monthly-metrics/{period_month} — sil (admin+analist)
  * GET    /tenants/me/engagement        — katılım tablosu (her üye)

Yazma yetkisi tenant_kpi_goals ile aynı: tenant_admin + analyst.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from imga_db.models import UserTenantRole
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import CurrentUser, bind_tenant, require_role
from imga_api.db_deps import get_app_session
from imga_api.services import EngagementService, MonthlyMetricNotFound
from imga_api.services.engagement_service import EngagementRow

_logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/tenants/me/monthly-metrics", tags=["Monthly Metrics"]
)
engagement_router = APIRouter(
    prefix="/tenants/me/engagement", tags=["Monthly Metrics"]
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


class MonthlyMetricResponse(BaseModel):
    id: UUID
    period_month: date
    transaction_count: int
    set_by_user_id: UUID | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class MonthlyMetricUpsertRequest(BaseModel):
    period_month: date
    transaction_count: int = Field(..., ge=0)
    notes: str | None = Field(default=None, max_length=1024)


class EngagementBand(BaseModel):
    min_pct: float
    label: str


class EngagementRowResponse(BaseModel):
    period_month: date
    transaction_count: int | None
    review_count: int
    engagement_pct: float | None
    band_label: str | None
    band_index: int | None


class EngagementResponse(BaseModel):
    rows: list[EngagementRowResponse]
    bands: list[EngagementBand]


def _require_active_tenant(current: CurrentUser) -> UUID:
    if current.active_tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="active tenant context required",
        )
    return current.active_tenant_id


def _row_to_response(row: Any) -> MonthlyMetricResponse:
    return MonthlyMetricResponse(
        id=row.id,
        period_month=row.period_month,
        transaction_count=int(row.transaction_count),
        set_by_user_id=row.set_by_user_id,
        notes=row.notes,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _engagement_to_response(row: EngagementRow) -> EngagementRowResponse:
    return EngagementRowResponse(
        period_month=row.period_month,
        transaction_count=row.transaction_count,
        review_count=row.review_count,
        engagement_pct=row.engagement_pct,
        band_label=row.band_label,
        band_index=row.band_index,
    )


@router.get(
    "",
    response_model=list[MonthlyMetricResponse],
    summary="Kurumun girdiği aylık işlem adetleri.",
)
async def list_monthly_metrics(
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[MonthlyMetricResponse]:
    tenant_id = _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        service = EngagementService(app_session)
        rows = await service.list_monthly_metrics(
            tenant_id=tenant_id, date_from=date_from, date_to=date_to
        )
        responses = [_row_to_response(r) for r in rows]
    return responses


@router.put(
    "",
    response_model=MonthlyMetricResponse,
    summary="Bir ayın işlem adedini yaz (varsa güncelle).",
)
async def upsert_monthly_metric(
    body: MonthlyMetricUpsertRequest,
    current: Annotated[CurrentUser, _WriteMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> MonthlyMetricResponse:
    tenant_id = _require_active_tenant(current)
    try:
        async with app_session.begin():
            await bind_tenant(app_session, current)
            service = EngagementService(app_session)
            row = await service.upsert_monthly_metric(
                tenant_id=tenant_id,
                period_month=body.period_month,
                transaction_count=body.transaction_count,
                set_by_user_id=current.user_id,
                notes=body.notes,
            )
            # Guncelleme yolunda onupdate=func.now() updated_at'i expire
            # eder; refresh olmadan senkron erisim MissingGreenlet atar.
            await app_session.refresh(row)
            response = _row_to_response(row)
        return response
    except HTTPException:
        raise
    except Exception:
        _logger.exception(
            "upsert_monthly_metric failed",
            extra={"tenant_id": str(tenant_id)},
        )
        raise


@router.delete(
    "/{period_month}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Bir ayın işlem adedi kaydını sil.",
)
async def delete_monthly_metric(
    period_month: date,
    current: Annotated[CurrentUser, _WriteMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> None:
    tenant_id = _require_active_tenant(current)
    try:
        async with app_session.begin():
            await bind_tenant(app_session, current)
            service = EngagementService(app_session)
            await service.delete_monthly_metric(
                tenant_id=tenant_id, period_month=period_month
            )
    except MonthlyMetricNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="ay kaydı bulunamadı"
        ) from exc
    except HTTPException:
        raise
    except Exception:
        _logger.exception(
            "delete_monthly_metric failed",
            extra={"tenant_id": str(tenant_id)},
        )
        raise


@engagement_router.get(
    "",
    response_model=EngagementResponse,
    summary="Aylık katılım oranı tablosu (varsayılan son 12 ay).",
)
async def get_engagement(
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    date_from: date | None = None,
    date_to: date | None = None,
) -> EngagementResponse:
    tenant_id = _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        service = EngagementService(app_session)
        rows, bands = await service.build_engagement_rows(
            tenant_id=tenant_id, date_from=date_from, date_to=date_to
        )
        response = EngagementResponse(
            rows=[_engagement_to_response(r) for r in rows],
            bands=[
                EngagementBand(
                    min_pct=float(b["min_pct"]), label=str(b["label"])
                )
                for b in bands
            ],
        )
    return response
