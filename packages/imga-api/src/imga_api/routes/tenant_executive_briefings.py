"""``/tenants/me/executive-briefings`` — LLM-authored executive summaries.

Sprint 8.3.10. Three endpoints:
  * POST   /generate     — fire generation (or fetch cached)
  * GET    /             — list past briefings
  * GET    /{id}         — fetch one briefing's full payload
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from imga_core.llm import (
    AllKeysExhaustedError,
    LLMError,
    LLMResponseBlockedError,
    LLMTokenLimitError,
)
from imga_db.models import ExecutiveBriefing, UserTenantRole
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import CurrentUser, bind_tenant, require_role
from imga_api.db_deps import get_app_session
from imga_api.services.executive_briefing_service import (
    BriefingResponseInvalidError,
    ExecutiveBriefingService,
    NoCredentialsError,
)

_logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/tenants/me/executive-briefings", tags=["Executive Briefings"]
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


class BriefingGenerateRequest(BaseModel):
    period: str = "month"
    date_from: date | None = None
    date_to: date | None = None
    batch_id: UUID | None = None
    force_refresh: bool = False

    @field_validator("period")
    @classmethod
    def _v_period(cls, v: str) -> str:
        if v not in {"week", "month", "quarter"}:
            raise ValueError("period must be week / month / quarter")
        return v


class BriefingResponse(BaseModel):
    id: UUID
    period: str
    date_from: date
    date_to: date
    batch_id: UUID | None
    headline: str
    kpi_changes: list[dict[str, Any]]
    critical_insights: list[str]
    top_actions: list[dict[str, Any]]
    model_name: str
    token_usage: dict[str, int] | None
    generated_at: datetime


class BriefingListItem(BaseModel):
    id: UUID
    period: str
    date_from: date
    date_to: date
    batch_id: UUID | None
    headline: str
    model_name: str
    generated_at: datetime


def _require_active_tenant(current: CurrentUser) -> UUID:
    if current.active_tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="active tenant context required for this endpoint",
        )
    return current.active_tenant_id


def _row_to_response(row: ExecutiveBriefing) -> BriefingResponse:
    return BriefingResponse(
        id=row.id,
        period=row.period,
        date_from=row.date_from,
        date_to=row.date_to,
        batch_id=row.batch_id,
        headline=row.headline,
        kpi_changes=list(row.kpi_changes),
        critical_insights=list(row.critical_insights),
        top_actions=list(row.top_actions),
        model_name=row.model_name,
        token_usage=dict(row.token_usage) if row.token_usage else None,
        generated_at=row.created_at,
    )


@router.post(
    "/generate",
    response_model=BriefingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate (or fetch cached) an executive briefing.",
    responses={
        503: {"description": "No active LLM credential / all keys exhausted."},
        502: {"description": "LLM response invalid."},
    },
)
async def generate_briefing(
    body: BriefingGenerateRequest,
    current: Annotated[CurrentUser, _WriteMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> BriefingResponse:
    tenant_id = _require_active_tenant(current)
    try:
        async with app_session.begin():
            await bind_tenant(app_session, current)
            service = ExecutiveBriefingService(
                app_session, tenant_id, user_id=current.user_id,
            )
            data = await service.generate(
                period=body.period,
                date_from=body.date_from,
                date_to=body.date_to,
                batch_id=body.batch_id,
                force_refresh=body.force_refresh,
            )
        # Fetch the freshly persisted row so response_model lines up.
        async with app_session.begin():
            await bind_tenant(app_session, current)
            row = await app_session.get(ExecutiveBriefing, UUID(data["id"]))
            if row is None:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="briefing kaydı bulunamadı",
                )
            response = _row_to_response(row)
        return response
    except NoCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="no_llm_credentials",
        ) from exc
    except AllKeysExhaustedError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="all_keys_exhausted",
        ) from exc
    except LLMTokenLimitError as exc:
        # Sprint 8.3.11 R2 — distinct surface for the truncation case
        # so the frontend can show a "tekrar deneyin / dönemi daraltın"
        # toast rather than a generic 502.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except LLMResponseBlockedError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except BriefingResponseInvalidError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"LLM yanıtı geçersiz: {exc}",
        ) from exc
    except LLMError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"LLM hatası: {exc}",
        ) from exc
    except HTTPException:
        raise
    except Exception:
        _logger.exception(
            "generate_briefing failed",
            extra={"tenant_id": str(tenant_id)},
        )
        raise


@router.get(
    "",
    response_model=list[BriefingListItem],
    summary="List past briefings (newest first).",
)
async def list_briefings(
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    limit: int = 50,
) -> list[BriefingListItem]:
    tenant_id = _require_active_tenant(current)
    if not 1 <= limit <= 200:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="limit 1..200 olmalı",
        )
    async with app_session.begin():
        await bind_tenant(app_session, current)
        stmt = (
            select(ExecutiveBriefing)
            .where(ExecutiveBriefing.tenant_id == tenant_id)
            .order_by(ExecutiveBriefing.created_at.desc())
            .limit(limit)
        )
        rows = (await app_session.execute(stmt)).scalars().all()
    return [
        BriefingListItem(
            id=r.id,
            period=r.period,
            date_from=r.date_from,
            date_to=r.date_to,
            batch_id=r.batch_id,
            headline=r.headline,
            model_name=r.model_name,
            generated_at=r.created_at,
        )
        for r in rows
    ]


@router.get(
    "/{briefing_id}",
    response_model=BriefingResponse,
    summary="Fetch one briefing's full payload.",
)
async def get_briefing(
    briefing_id: UUID,
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> BriefingResponse:
    tenant_id = _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        row = await app_session.get(ExecutiveBriefing, briefing_id)
        if row is None or row.tenant_id != tenant_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="briefing bulunamadı",
            )
        return _row_to_response(row)
