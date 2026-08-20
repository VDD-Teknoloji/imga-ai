"""Sprint 9.3 A — ``/tenants/me/llm-audit``.

Admin-only read surface over the ``llm_call_audit`` table. The
list endpoint paginates + filters; a single ``/summary`` endpoint
folds the same filter bag into per-day token-usage + error-rate
totals so the dashboard can render the chart without a second
round-trip.

The route lives under ``/tenants/me`` (not ``/admin``) because the
data is tenant-scoped via RLS — a super-admin who wants
cross-tenant audit goes through the admin DB session directly.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from imga_db.models import LlmCallAudit, UserTenantRole
from pydantic import BaseModel
from sqlalchemy import Integer, case, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import CurrentUser, bind_tenant, require_role
from imga_api.db_deps import get_app_session

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tenants/me/llm-audit", tags=["LLM Audit"])

_AdminOnly = Depends(require_role(UserTenantRole.TENANT_ADMIN))


class LlmCallAuditResponse(BaseModel):
    id: UUID
    call_type: str
    related_entity_type: str | None
    related_entity_id: UUID | None
    prompt_template_key: str | None
    prompt_template_version: str | None
    prompt_hash: str
    model_name: str
    model_provider: str
    model_temperature: float | None
    model_max_tokens: int | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    duration_ms: int | None
    success: bool
    error_type: str | None
    error_message: str | None
    fallback_used: bool
    actor_user_id: UUID | None
    request_id: str | None
    created_at: datetime


class LlmAuditListResponse(BaseModel):
    items: list[LlmCallAuditResponse]
    total: int


class DailyUsagePoint(BaseModel):
    day: str  # YYYY-MM-DD
    call_count: int
    success_count: int
    failure_count: int
    total_tokens: int


class LlmAuditSummary(BaseModel):
    days: list[DailyUsagePoint]
    total_calls: int
    total_failures: int
    total_tokens: int
    # 2026-08-20 (B6, migration 0045) — bilinen maliyetlerin toplamı.
    # cost_usd NULL olan satırlar (fiyatı bilinmeyen model / token
    # sayısı yok) toplama KATILMAZ ve 0 sayılmaz; kaç tanesi
    # bilinmediğini ``unknown_cost_calls`` ayrı taşır.
    total_cost_usd: float
    unknown_cost_calls: int


def _require_active_tenant(current: CurrentUser) -> UUID:
    if current.active_tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="active tenant context required",
        )
    return current.active_tenant_id


def _row_to_response(row: LlmCallAudit) -> LlmCallAuditResponse:
    return LlmCallAuditResponse(
        id=row.id,
        call_type=row.call_type,
        related_entity_type=row.related_entity_type,
        related_entity_id=row.related_entity_id,
        prompt_template_key=row.prompt_template_key,
        prompt_template_version=row.prompt_template_version,
        prompt_hash=row.prompt_hash,
        model_name=row.model_name,
        model_provider=row.model_provider,
        model_temperature=(
            float(row.model_temperature) if row.model_temperature is not None else None
        ),
        model_max_tokens=row.model_max_tokens,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        total_tokens=row.total_tokens,
        duration_ms=row.duration_ms,
        success=row.success,
        error_type=row.error_type,
        error_message=row.error_message,
        fallback_used=row.fallback_used,
        actor_user_id=row.actor_user_id,
        request_id=row.request_id,
        created_at=row.created_at,
    )


@router.get(
    "",
    response_model=LlmAuditListResponse,
    summary="List LLM call audit rows for the active tenant.",
)
async def list_audit(
    current: Annotated[CurrentUser, _AdminOnly],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    call_type: str | None = None,
    success: bool | None = None,
    limit: int = 100,
    offset: int = 0,
) -> LlmAuditListResponse:
    tenant_id = _require_active_tenant(current)
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        base_filters = [LlmCallAudit.tenant_id == tenant_id]
        if call_type is not None:
            base_filters.append(LlmCallAudit.call_type == call_type)
        if success is not None:
            base_filters.append(LlmCallAudit.success.is_(success))
        count_stmt = select(func.count()).select_from(LlmCallAudit).where(*base_filters)
        total = (await app_session.execute(count_stmt)).scalar_one() or 0
        list_stmt = (
            select(LlmCallAudit)
            .where(*base_filters)
            .order_by(desc(LlmCallAudit.created_at))
            .limit(limit)
            .offset(offset)
        )
        rows = list((await app_session.execute(list_stmt)).scalars().all())
    return LlmAuditListResponse(
        items=[_row_to_response(r) for r in rows],
        total=total,
    )


@router.get(
    "/summary",
    response_model=LlmAuditSummary,
    summary="Per-day token usage + failure rate for the last 30 days.",
)
async def audit_summary(
    current: Annotated[CurrentUser, _AdminOnly],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> LlmAuditSummary:
    tenant_id = _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        # Sprint 9.4.2 hotfix — collapse the per-day rollup into a
        # single query with a CASE-driven failure counter. The pre-
        # 9.4.2 version ran two GROUP-BY queries and joined them in
        # Python; PostgreSQL rejected one of them on populated data
        # ("column created_at must appear in the GROUP BY clause")
        # the moment the Sprint 9.4.2 A fix let real rows land in
        # the table. A single query side-steps any dual-statement
        # consistency / aliasing subtlety and lets the dashboard's
        # chart render against the real audit data.
        day_col = func.date_trunc("day", LlmCallAudit.created_at)
        failure_marker = case(
            (LlmCallAudit.success.is_(False), 1),
            else_=0,
        )
        stmt = (
            select(
                day_col.label("day"),
                func.count().label("calls"),
                func.coalesce(
                    func.sum(func.cast(failure_marker, Integer)),
                    0,
                ).label("failures"),
                func.coalesce(func.sum(LlmCallAudit.total_tokens), 0).label("tokens"),
            )
            .where(LlmCallAudit.tenant_id == tenant_id)
            .group_by(day_col)
            .order_by(day_col)
        )
        rows = (await app_session.execute(stmt)).all()

        # 2026-08-20 (B6) — ayrı bir sorgu: cost_usd NULL'ları (SUM zaten
        # yok sayar) 0 sayılmaz, ayrıca kaç satırın maliyeti bilinmediği
        # ``unknown_cost_calls`` ile taşınır. Günlük seriyle birleştirmek
        # (call_type gibi) burada gereksiz — dashboard tek toplam kart
        # gösterir; ihtiyaç doğarsa günlük kırılım ayrı eklenir.
        unknown_cost_marker = case(
            (LlmCallAudit.cost_usd.is_(None), 1),
            else_=0,
        )
        cost_stmt = select(
            func.sum(LlmCallAudit.cost_usd).label("total_cost_usd"),
            func.coalesce(func.sum(func.cast(unknown_cost_marker, Integer)), 0).label(
                "unknown_cost_calls"
            ),
        ).where(LlmCallAudit.tenant_id == tenant_id)
        cost_row = (await app_session.execute(cost_stmt)).one()

        days: list[DailyUsagePoint] = []
        total_calls = 0
        total_failures = 0
        total_tokens = 0
        for r in rows:
            day_str = r.day.date().isoformat() if r.day is not None else ""
            calls = int(r.calls or 0)
            fails = int(r.failures or 0)
            tokens = int(r.tokens or 0)
            days.append(
                DailyUsagePoint(
                    day=day_str,
                    call_count=calls,
                    success_count=calls - fails,
                    failure_count=fails,
                    total_tokens=tokens,
                )
            )
            total_calls += calls
            total_failures += fails
            total_tokens += tokens

    return LlmAuditSummary(
        days=days,
        total_calls=total_calls,
        total_failures=total_failures,
        total_tokens=total_tokens,
        total_cost_usd=float(cost_row.total_cost_usd or 0),
        unknown_cost_calls=int(cost_row.unknown_cost_calls or 0),
    )
