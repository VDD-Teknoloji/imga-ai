"""``/admin/llm-usage`` — süper-admin platform genelinde LLM kullanım +
maliyet raporu (C1, 2026-08-20 süper-admin envanteri).

Kurum başına ve call_type başına kırılım + platform toplamı, tek
tarih aralığı üzerinden (varsayılan son 30 gün). ``llm_call_audit``
tablosu RLS+FORCE altında (bkz. model docstring'i); bu uç çapraz-kurum
görünüm gerektirdiği için ``imga_admin`` (BYPASSRLS) oturumu kullanır.

Diğer admin uçlarıyla aynı transaction sözleşmesi: burada
``async with admin_session.begin():`` YOK, bilerek — ``get_current_user``
(require_super_admin zincirinin bir parçası) admin_session'ı zaten
autobegin'ler; ikinci bir ``begin()`` "A transaction is already begun on
this Session" 500'üne düşer (bkz. admin/llm_credentials.py docstring'i,
tests/test_admin_session_regression.py).

Maliyet: ``cost_usd`` NULL olan satırlar SUM'a hiç girmez (SQL SUM NULL'ı
yok sayar) VE ayrıca 0 sayılmaz — ``unknown_cost_calls`` bu satırları
ayrı taşır. Tüm satırlar bilinmeyen fiyatlıysa ``total_cost_usd`` None
döner (0.0 DEĞİL — "bilinmiyor" ile "gerçekten sıfır" karışmasın).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from imga_db.models import LlmCallAudit, Tenant
from pydantic import BaseModel
from sqlalchemy import Integer, case, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import CurrentUser, require_super_admin
from imga_api.db_deps import get_admin_session

router = APIRouter(prefix="/admin/llm-usage", tags=["Admin: LLM Usage"])

_DEFAULT_WINDOW_DAYS = 30


class LlmUsageByTenant(BaseModel):
    tenant_id: UUID
    tenant_name: str
    calls: int
    input_tokens: int
    output_tokens: int
    total_cost_usd: float | None
    unknown_cost_calls: int
    error_rate: float


class LlmUsageByCallType(BaseModel):
    call_type: str
    calls: int
    input_tokens: int
    output_tokens: int
    total_cost_usd: float | None


class LlmUsagePlatformTotals(BaseModel):
    calls: int
    input_tokens: int
    output_tokens: int
    total_cost_usd: float | None
    unknown_cost_calls: int
    error_rate: float


class LlmUsageResponse(BaseModel):
    date_from: date
    date_to: date
    tenants: list[LlmUsageByTenant]
    call_types: list[LlmUsageByCallType]
    platform: LlmUsagePlatformTotals


def _day_bounds(
    date_from: date | None, date_to: date | None
) -> tuple[date, date, datetime, datetime]:
    """Varsayılan pencere: son 30 gün (bugün dahil). Üst sınır ertesi
    günün başlangıcı olarak ele alınır (``<`` ile karşılaştırılır) ki
    ``date_to``nun tüm günü dahil olsun — 0039/engagement_service'teki
    ay-aritmetiği deseniyle aynı fikir, gün ölçeğinde."""
    effective_to = date_to or datetime.now(UTC).date()
    effective_from = date_from or (effective_to - timedelta(days=_DEFAULT_WINDOW_DAYS))
    dt_from = datetime(effective_from.year, effective_from.month, effective_from.day, tzinfo=UTC)
    dt_to_exclusive = datetime(
        effective_to.year, effective_to.month, effective_to.day, tzinfo=UTC
    ) + timedelta(days=1)
    return effective_from, effective_to, dt_from, dt_to_exclusive


def _sum_known_cost(values: list[float | None]) -> float | None:
    known = [v for v in values if v is not None]
    if not known:
        return None
    return sum(known)


@router.get(
    "",
    response_model=LlmUsageResponse,
    summary="Platform genelinde LLM kullanım + maliyet raporu (kurum + call_type kırılımı).",
)
async def llm_usage(
    _current: Annotated[CurrentUser, Depends(require_super_admin)],
    admin_session: Annotated[AsyncSession, Depends(get_admin_session)],
    date_from: date | None = None,
    date_to: date | None = None,
) -> LlmUsageResponse:
    eff_from, eff_to, dt_from, dt_to_exclusive = _day_bounds(date_from, date_to)
    window = (
        LlmCallAudit.created_at >= dt_from,
        LlmCallAudit.created_at < dt_to_exclusive,
    )
    failure_marker = case((LlmCallAudit.success.is_(False), 1), else_=0)
    unknown_cost_marker = case((LlmCallAudit.cost_usd.is_(None), 1), else_=0)

    tenant_stmt = (
        select(
            LlmCallAudit.tenant_id,
            Tenant.name,
            func.count().label("calls"),
            func.coalesce(func.sum(LlmCallAudit.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(LlmCallAudit.output_tokens), 0).label("output_tokens"),
            func.sum(LlmCallAudit.cost_usd).label("total_cost_usd"),
            func.coalesce(func.sum(func.cast(unknown_cost_marker, Integer)), 0).label(
                "unknown_cost_calls"
            ),
            func.coalesce(func.sum(func.cast(failure_marker, Integer)), 0).label("failures"),
        )
        .join(Tenant, Tenant.id == LlmCallAudit.tenant_id)
        .where(*window)
        .group_by(LlmCallAudit.tenant_id, Tenant.name)
        .order_by(desc("calls"))
    )
    tenant_rows = (await admin_session.execute(tenant_stmt)).all()

    tenants: list[LlmUsageByTenant] = []
    platform_calls = 0
    platform_input = 0
    platform_output = 0
    platform_unknown = 0
    platform_failures = 0
    platform_known_costs: list[float | None] = []
    for row in tenant_rows:
        calls = int(row.calls or 0)
        failures = int(row.failures or 0)
        cost = float(row.total_cost_usd) if row.total_cost_usd is not None else None
        tenants.append(
            LlmUsageByTenant(
                tenant_id=row.tenant_id,
                tenant_name=row.name,
                calls=calls,
                input_tokens=int(row.input_tokens or 0),
                output_tokens=int(row.output_tokens or 0),
                total_cost_usd=cost,
                unknown_cost_calls=int(row.unknown_cost_calls or 0),
                error_rate=(failures / calls) if calls else 0.0,
            )
        )
        platform_calls += calls
        platform_input += int(row.input_tokens or 0)
        platform_output += int(row.output_tokens or 0)
        platform_unknown += int(row.unknown_cost_calls or 0)
        platform_failures += failures
        platform_known_costs.append(cost)

    call_type_stmt = (
        select(
            LlmCallAudit.call_type,
            func.count().label("calls"),
            func.coalesce(func.sum(LlmCallAudit.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(LlmCallAudit.output_tokens), 0).label("output_tokens"),
            func.sum(LlmCallAudit.cost_usd).label("total_cost_usd"),
        )
        .where(*window)
        .group_by(LlmCallAudit.call_type)
        .order_by(desc("calls"))
    )
    call_type_rows = (await admin_session.execute(call_type_stmt)).all()
    call_types = [
        LlmUsageByCallType(
            call_type=row.call_type,
            calls=int(row.calls or 0),
            input_tokens=int(row.input_tokens or 0),
            output_tokens=int(row.output_tokens or 0),
            total_cost_usd=(float(row.total_cost_usd) if row.total_cost_usd is not None else None),
        )
        for row in call_type_rows
    ]

    platform = LlmUsagePlatformTotals(
        calls=platform_calls,
        input_tokens=platform_input,
        output_tokens=platform_output,
        total_cost_usd=_sum_known_cost(platform_known_costs),
        unknown_cost_calls=platform_unknown,
        error_rate=(platform_failures / platform_calls) if platform_calls else 0.0,
    )

    return LlmUsageResponse(
        date_from=eff_from,
        date_to=eff_to,
        tenants=tenants,
        call_types=call_types,
        platform=platform,
    )
