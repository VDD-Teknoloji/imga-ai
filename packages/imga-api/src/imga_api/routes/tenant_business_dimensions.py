"""Sprint 9.3 B — ``/tenants/me/business-dimensions``.

Six endpoints:
  * GET    /                         — list dimension configs
  * PUT    /{dimension}              — upsert one dimension config
  * DELETE /{dimension}              — remove
  * GET    /{dimension}/breakdown    — analytics breakdown
                                       (?metric_key=nps|sentiment|volume)
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from imga_db.models import TenantBusinessDimension, UserTenantRole
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import CurrentUser, bind_tenant, require_role
from imga_api.db_deps import get_app_session
from imga_api.services.dimension_service import (
    DimensionConfigNotFound,
    DimensionError,
    DimensionService,
    UnknownDimension,
    compute_metric_by_dimension,
)

_logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/tenants/me/business-dimensions",
    tags=["Business Dimensions"],
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


class DimensionConfigResponse(BaseModel):
    id: UUID
    dimension: str
    display_label: str
    enabled: bool
    allowed_values: list[str]
    csv_column_mapping: str | None
    created_at: datetime
    updated_at: datetime


class DimensionConfigUpsertRequest(BaseModel):
    display_label: str = Field(..., min_length=1, max_length=128)
    enabled: bool = True
    allowed_values: list[str] = Field(default_factory=list, max_length=64)
    csv_column_mapping: str | None = None


class DimensionBreakdownResponse(BaseModel):
    metric_key: str
    dimension: str
    buckets: list[dict[str, Any]]
    total_count: int
    coverage_count: int


def _require_active_tenant(current: CurrentUser) -> UUID:
    if current.active_tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="active tenant context required",
        )
    return current.active_tenant_id


def _row_to_response(row: TenantBusinessDimension) -> DimensionConfigResponse:
    return DimensionConfigResponse(
        id=row.id,
        dimension=row.dimension,
        display_label=row.display_label,
        enabled=row.enabled,
        allowed_values=list(row.allowed_values or []),
        csv_column_mapping=row.csv_column_mapping,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get(
    "",
    response_model=list[DimensionConfigResponse],
    summary="List configured business dimensions.",
)
async def list_dimensions(
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> list[DimensionConfigResponse]:
    tenant_id = _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        service = DimensionService(app_session)
        rows = await service.list_for_tenant(tenant_id=tenant_id)
    return [_row_to_response(r) for r in rows]


@router.put(
    "/{dimension}",
    response_model=DimensionConfigResponse,
    summary="Configure (upsert) a business dimension.",
)
async def upsert_dimension(
    dimension: str,
    body: DimensionConfigUpsertRequest,
    current: Annotated[CurrentUser, _WriteMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> DimensionConfigResponse:
    tenant_id = _require_active_tenant(current)
    try:
        async with app_session.begin():
            await bind_tenant(app_session, current)
            service = DimensionService(app_session)
            row = await service.configure(
                tenant_id=tenant_id,
                dimension=dimension,
                display_label=body.display_label,
                enabled=body.enabled,
                allowed_values=body.allowed_values,
                csv_column_mapping=body.csv_column_mapping,
            )
            response = _row_to_response(row)
        return response
    except UnknownDimension as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except HTTPException:
        raise
    except Exception:
        _logger.exception(
            "upsert_dimension failed",
            extra={"tenant_id": str(tenant_id), "dimension": dimension},
        )
        raise


@router.delete(
    "/{dimension}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a business dimension config.",
)
async def delete_dimension(
    dimension: str,
    current: Annotated[CurrentUser, _WriteMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> None:
    tenant_id = _require_active_tenant(current)
    try:
        async with app_session.begin():
            await bind_tenant(app_session, current)
            service = DimensionService(app_session)
            await service.delete(tenant_id=tenant_id, dimension=dimension)
    except UnknownDimension as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except DimensionConfigNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except HTTPException:
        raise


@router.get(
    "/{dimension}/breakdown",
    response_model=DimensionBreakdownResponse,
    summary=(
        "Compute a metric grouped by the dimension. "
        "metric_key in (review_volume | sentiment_distribution | nps | "
        "negative_share | avg_sentiment)."
    ),
)
async def dimension_breakdown(
    dimension: str,
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    metric_key: str = "review_volume",
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    include_flagged: bool = False,
) -> DimensionBreakdownResponse:
    tenant_id = _require_active_tenant(current)
    try:
        async with app_session.begin():
            await bind_tenant(app_session, current)
            result = await compute_metric_by_dimension(
                app_session,
                tenant_id=tenant_id,
                dimension=dimension,
                metric_key=metric_key,
                date_from=date_from,
                date_to=date_to,
                include_flagged=include_flagged,
            )
        return DimensionBreakdownResponse(
            metric_key=result.metric_key,
            dimension=result.dimension,
            buckets=result.buckets,
            total_count=result.total_count,
            coverage_count=result.coverage_count,
        )
    except UnknownDimension as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except DimensionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except HTTPException:
        raise
    except Exception:
        _logger.exception(
            "dimension_breakdown failed",
            extra={"tenant_id": str(tenant_id), "dimension": dimension},
        )
        raise
