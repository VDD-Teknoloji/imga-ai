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
from imga_db.models import ActionItem, ExecutiveBriefing, UserTenantRole
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
    # Sprint 9.0.5-B G — UUID list of ActionItem rows linked to
    # this briefing's top_actions. Frontend uses GET
    # /executive-briefings/{id}/top-actions to hydrate full
    # ActionItem records; this surface lets the briefing detail
    # page know up-front whether the section has any rows.
    top_action_item_ids: list[UUID] = []
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
        top_action_item_ids=list(row.top_action_item_ids or []),
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
    # Sprint 9.4.5 — deferred-raise pattern. The pre-9.4.5 shape
    # wrapped the LLM call in a try/except OUTSIDE the parent
    # ``async with app_session.begin():`` block; when the service
    # raised AllKeysExhaustedError (or any sibling), the exception
    # propagated out of the ``with``, the parent transaction rolled
    # back, and the SAVEPOINT audit row inserted by the auditor's
    # ``__aexit__`` went down with it. /admin/llm-audit then had no
    # row for the most operationally interesting failure path.
    #
    # The fix: catch the LLM-class exceptions INSIDE the ``async
    # with`` block, stash a deferred HTTPException, let the
    # ``async with`` exit cleanly so the parent transaction commits
    # (taking the audit row with it), then re-raise the HTTPException
    # afterward. /run-now already follows this shape — its try/except
    # is inside the begin() block, which is why /run-now never lost
    # an audit row on failure.
    deferred_exc: HTTPException | None = None
    data: dict[str, object] | None = None
    async with app_session.begin():
        await bind_tenant(app_session, current)
        service = ExecutiveBriefingService(
            app_session, tenant_id, user_id=current.user_id,
        )
        try:
            data = await service.generate(
                period=body.period,
                date_from=body.date_from,
                date_to=body.date_to,
                batch_id=body.batch_id,
                force_refresh=body.force_refresh,
            )
        except NoCredentialsError as exc:
            deferred_exc = HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="no_llm_credentials",
            )
            deferred_exc.__cause__ = exc
        except AllKeysExhaustedError as exc:
            deferred_exc = HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="all_keys_exhausted",
            )
            deferred_exc.__cause__ = exc
        except LLMTokenLimitError as exc:
            # Sprint 8.3.11 R2 — distinct surface for the truncation
            # case so the frontend can show a "tekrar deneyin /
            # dönemi daraltın" toast rather than a generic 502.
            deferred_exc = HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            )
            deferred_exc.__cause__ = exc
        except LLMResponseBlockedError as exc:
            deferred_exc = HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            )
            deferred_exc.__cause__ = exc
        except BriefingResponseInvalidError as exc:
            deferred_exc = HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"LLM yanıtı geçersiz: {exc}",
            )
            deferred_exc.__cause__ = exc
        except LLMError as exc:
            deferred_exc = HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"LLM hatası: {exc}",
            )
            deferred_exc.__cause__ = exc
    # ``async with app_session.begin()`` exited cleanly above — the
    # auditor's SAVEPOINT row is now part of the committed parent
    # transaction. Now we can safely raise the deferred HTTPException
    # for the operator-facing response.
    if deferred_exc is not None:
        raise deferred_exc

    # Success path — fetch the persisted briefing row so the response
    # model lines up.
    assert data is not None  # narrows the type after the deferred guard
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


class TopActionItemView(BaseModel):
    id: UUID
    title: str
    description: str
    rationale: str | None
    priority: str
    estimated_impact: str | None
    status: str
    due_date: date | None
    assignee_user_id: UUID | None


class TopActionsResponse(BaseModel):
    briefing_id: UUID
    items: list[TopActionItemView]


@router.get(
    "/{briefing_id}/top-actions",
    response_model=TopActionsResponse,
    summary="Sprint 9.0.5-B G — fetch ActionItem rows linked to a briefing.",
    description=(
        "Returns the ActionItems extracted from the briefing's "
        "``top_actions`` field. The frontend renders each as a "
        "clickable follow-up card with status / priority / "
        "assignee."
    ),
    responses={404: {"description": "Briefing not found or hidden by RLS."}},
)
async def get_briefing_top_actions(
    briefing_id: UUID,
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> TopActionsResponse:
    tenant_id = _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        briefing = await app_session.get(ExecutiveBriefing, briefing_id)
        if briefing is None or briefing.tenant_id != tenant_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="briefing bulunamadı",
            )
        ids = list(briefing.top_action_item_ids or [])
        if not ids:
            return TopActionsResponse(briefing_id=briefing_id, items=[])
        stmt = select(ActionItem).where(ActionItem.id.in_(ids))
        rows = (await app_session.execute(stmt)).scalars().all()
        # Preserve the briefing's array order (the LLM ranked them)
        # rather than ActionItem.id ordering.
        by_id = {r.id: r for r in rows}
        ordered = [by_id[i] for i in ids if i in by_id]
        return TopActionsResponse(
            briefing_id=briefing_id,
            items=[
                TopActionItemView(
                    id=r.id,
                    title=r.title,
                    description=r.description,
                    rationale=r.rationale,
                    priority=r.priority,
                    estimated_impact=r.estimated_impact,
                    status=r.status,
                    due_date=r.due_date,
                    assignee_user_id=r.assignee_user_id,
                )
                for r in ordered
            ],
        )
