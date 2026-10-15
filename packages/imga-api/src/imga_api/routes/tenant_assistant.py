"""Veri asistanı uçları — /tenants/me/assistant (2026-10-15).

Tüm kurum üyeleri soru sorabilir (yalnız okuma: kanıt paketi mevcut
yorum verisinden derlenir, hiçbir kayıt değişmez). LLM çağrısı
``llm_call_audit``'e ``assistant`` türüyle yazılır (migration 0053).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from imga_db.models import UserTenantRole
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import CurrentUser, bind_tenant, require_role
from imga_api.db_deps import get_app_session
from imga_api.services.data_assistant_service import (
    MAX_HISTORY_TURNS,
    MAX_QUESTION_LENGTH,
    DataAssistantService,
)

router = APIRouter(prefix="/tenants/me/assistant", tags=["Data Assistant"])
_AnyMember = Depends(
    require_role(UserTenantRole.TENANT_ADMIN, UserTenantRole.ANALYST, UserTenantRole.VIEWER)
)
Session = Annotated[AsyncSession, Depends(get_app_session)]


class HistoryTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str = Field(min_length=1, max_length=MAX_QUESTION_LENGTH)
    history: list[HistoryTurn] = Field(default_factory=list, max_length=MAX_HISTORY_TURNS)


class AskResponse(BaseModel):
    answer: str
    highlights: list[str]
    follow_ups: list[str]
    data_gaps: list[str]
    scope: dict[str, Any]
    evidence: dict[str, Any]
    llm_used: bool
    model: str | None
    provider: str | None
    warnings: list[str]


class SuggestionsResponse(BaseModel):
    items: list[str]


def _tenant(current: CurrentUser) -> Any:
    if current.active_tenant_id is None:
        raise HTTPException(400, "Aktif kurum gerekli.")
    return current.active_tenant_id


@router.post("/ask", response_model=AskResponse)
async def ask(
    body: AskRequest,
    current: Annotated[CurrentUser, _AnyMember],
    session: Session,
) -> AskResponse:
    tenant_id = _tenant(current)
    async with session.begin():
        await bind_tenant(session, current)
        service = DataAssistantService(session, tenant_id, current.user_id)
        try:
            result = await service.ask(
                body.question,
                history=[turn.model_dump() for turn in body.history],
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    return AskResponse(
        answer=result.answer,
        highlights=result.highlights,
        follow_ups=result.follow_ups,
        data_gaps=result.data_gaps,
        scope=result.scope,
        evidence=result.evidence,
        llm_used=result.llm_used,
        model=result.model,
        provider=result.provider,
        warnings=result.warnings,
    )


@router.get("/suggestions", response_model=SuggestionsResponse)
async def suggestions(
    current: Annotated[CurrentUser, _AnyMember],
    session: Session,
) -> SuggestionsResponse:
    tenant_id = _tenant(current)
    async with session.begin():
        await bind_tenant(session, current)
        items = await DataAssistantService(session, tenant_id, current.user_id).suggestions()
    return SuggestionsResponse(items=items)
