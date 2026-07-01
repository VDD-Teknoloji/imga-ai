"""İmga v1 — Tenant + kota yönetimi (contract §4A.1/§4A.2/§3.2). opsBearer.

POST /v1/admin/tenants                    — tenant oluştur (§4A.1)
POST /v1/admin/tenants/{tenant_id}/quota  — kota güncelle (§3.2)
GET  /v1/admin/tenants/{tenant_id}/usage  — kullanım/fatura (§4A.2; opsBearer VEYA kendi tenant)

External ``tenant_id`` = Tenant.slug (ör. "asakai-prod"; name'den türetilir).
usage aggregation api_request_log üzerinden; ops BYPASSRLS + explicit tenant filtre.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, status
from imga_db.models import ApiRequestLog, ApiTenantConfig, Tenant
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.db_deps import get_admin_session
from imga_api.v1.auth import ApiPrincipal, get_partner_principal, require_ops
from imga_api.v1.errors import PartnerApiError

router = APIRouter(prefix="/v1/admin/tenants", tags=["v1-admin"])

_QUOTA_DEFAULT = 2_000_000  # §6


# --------------------------- schemas ---------------------------------
class TenantCreateRequest(BaseModel):
    name: str
    contact_email: str
    quota_tokens_per_day: int | None = None
    residency_locks: dict[str, str] | None = None


class TenantCreatedResponse(BaseModel):
    tenant_id: str
    created_at: datetime


class QuotaUpdateRequest(BaseModel):
    quota_tokens_per_day: int


class UsageTotals(BaseModel):
    requests: int
    tokens_in: int
    tokens_out: int
    cost_try: float


class UsageBucket(BaseModel):
    bucket: str
    requests: int
    tokens_in: int
    tokens_out: int
    cost_try: float


class UsageWindow(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    from_: str = Field(serialization_alias="from")
    to: str


class UsageResponse(BaseModel):
    tenant_id: str
    window: UsageWindow
    totals: UsageTotals
    breakdown: list[UsageBucket]


# --------------------------- helpers ---------------------------------
_TR_MAP = str.maketrans("çğıöşü", "cgiosu")


def _slugify(name: str) -> str:
    s = name.strip().lower().translate(_TR_MAP)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:64] or "tenant"


async def _tenant_uuid_by_slug(session: AsyncSession, slug: str) -> UUID:
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


# --------------------------- routes ----------------------------------
@router.post(
    "", response_model=TenantCreatedResponse, status_code=status.HTTP_201_CREATED
)
async def create_tenant(
    body: TenantCreateRequest,
    _ops: Annotated[ApiPrincipal, Depends(require_ops)],
    admin_session: Annotated[AsyncSession, Depends(get_admin_session)],
) -> TenantCreatedResponse:
    slug = _slugify(body.name)
    async with admin_session.begin_nested():
        exists = (
            await admin_session.execute(
                select(Tenant.id).where(Tenant.slug == slug)
            )
        ).scalar_one_or_none()
        if exists is not None:
            raise PartnerApiError(
                status_code=status.HTTP_400_BAD_REQUEST,
                code="invalid_input",
                message=f"tenant already exists: {slug}",
                details={"field": "name", "slug": slug},
            )
        tenant = Tenant(name=body.name, slug=slug)
        admin_session.add(tenant)
        await admin_session.flush()
        admin_session.add(
            ApiTenantConfig(
                tenant_id=tenant.id,
                contact_email=body.contact_email,
                quota_tokens_per_day=body.quota_tokens_per_day or _QUOTA_DEFAULT,
                residency_locks=body.residency_locks,
            )
        )
    return TenantCreatedResponse(tenant_id=slug, created_at=tenant.created_at)


@router.post("/{tenant_id}/quota", status_code=status.HTTP_200_OK)
async def update_quota(
    body: QuotaUpdateRequest,
    _ops: Annotated[ApiPrincipal, Depends(require_ops)],
    admin_session: Annotated[AsyncSession, Depends(get_admin_session)],
    tenant_id: Annotated[str, Path()],
) -> dict[str, str]:
    async with admin_session.begin_nested():
        tenant_uuid = await _tenant_uuid_by_slug(admin_session, tenant_id)
        cfg = (
            await admin_session.execute(
                select(ApiTenantConfig).where(
                    ApiTenantConfig.tenant_id == tenant_uuid
                )
            )
        ).scalar_one_or_none()
        if cfg is None:
            cfg = ApiTenantConfig(tenant_id=tenant_uuid)
            admin_session.add(cfg)
        cfg.quota_tokens_per_day = body.quota_tokens_per_day
    return {"tenant_id": tenant_id, "status": "updated"}


@router.get("/{tenant_id}/usage", response_model=UsageResponse)
async def tenant_usage(
    principal: Annotated[ApiPrincipal, Depends(get_partner_principal)],
    admin_session: Annotated[AsyncSession, Depends(get_admin_session)],
    tenant_id: Annotated[str, Path()],
    from_: Annotated[datetime, Query(alias="from")],
    to: Annotated[datetime, Query()],
    group_by: Annotated[str, Query()] = "day",
) -> UsageResponse:
    if group_by not in ("day", "week", "month", "use_case"):
        raise PartnerApiError(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="invalid_input",
            message="group_by must be day|week|month|use_case",
            details={"field": "group_by"},
        )
    async with admin_session.begin_nested():
        tenant_uuid = await _tenant_uuid_by_slug(admin_session, tenant_id)
        # opsBearer her tenant'ı görür; tenant Bearer yalnız kendi tenant'ını.
        if principal.kind == "tenant" and principal.tenant_id != tenant_uuid:
            raise PartnerApiError(
                status_code=status.HTTP_403_FORBIDDEN,
                code="auth_failed",
                message="tenant token cannot read another tenant's usage",
                details={"hint": "tenant_scope_cannot_access_admin"},
            )

        base_where = (
            (ApiRequestLog.tenant_id == tenant_uuid)
            & (ApiRequestLog.created_at >= from_)
            & (ApiRequestLog.created_at <= to)
        )
        totals = (
            await admin_session.execute(
                select(
                    func.count().label("requests"),
                    func.coalesce(func.sum(ApiRequestLog.tokens_prompt), 0),
                    func.coalesce(func.sum(ApiRequestLog.tokens_completion), 0),
                    func.coalesce(func.sum(ApiRequestLog.cost_try), 0),
                ).where(base_where)
            )
        ).one()

        if group_by == "use_case":
            bucket_col = ApiRequestLog.use_case
        else:
            bucket_col = func.to_char(
                func.date_trunc(group_by, ApiRequestLog.created_at),
                "YYYY-MM-DD",
            )
        rows = (
            await admin_session.execute(
                select(
                    bucket_col.label("bucket"),
                    func.count(),
                    func.coalesce(func.sum(ApiRequestLog.tokens_prompt), 0),
                    func.coalesce(func.sum(ApiRequestLog.tokens_completion), 0),
                    func.coalesce(func.sum(ApiRequestLog.cost_try), 0),
                )
                .where(base_where)
                .group_by(bucket_col)
                .order_by(bucket_col)
            )
        ).all()

    return UsageResponse(
        tenant_id=tenant_id,
        window=UsageWindow(from_=from_.isoformat(), to=to.isoformat()),
        totals=UsageTotals(
            requests=int(totals[0]),
            tokens_in=int(totals[1]),
            tokens_out=int(totals[2]),
            cost_try=float(totals[3]),
        ),
        breakdown=[
            UsageBucket(
                bucket=str(r[0]),
                requests=int(r[1]),
                tokens_in=int(r[2]),
                tokens_out=int(r[3]),
                cost_try=float(r[4]),
            )
            for r in rows
        ],
    )
