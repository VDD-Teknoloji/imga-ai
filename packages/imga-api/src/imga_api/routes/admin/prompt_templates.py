"""Read-only admin view of system-level prompt templates.

Sprint 8.3.6.5.E. List-only surface so an operator can inspect which
templates the LLM stack is using. No tenant override yet — every
tenant sees the same module-resident system prompts via the SWOT/OKR
services; the DB rows exist for the registry table to have a place
when overrides ship.

2026-08-09: yetki super-admin'e daraltildi. Onceki hali sistem
genelindeki (tenant'siz) satirlari HERHANGI bir kurumun
tenant_admin'ine aciyordu — kurum sinirini asan bir okuma yoluydu.
Kurum-kapsamli sablon duzenleme yuzeyi ayri:
``/tenants/me/prompt-templates``.

The ``response_schema`` JSONB column is bigger than what's useful in
a list view, so this endpoint surfaces the meta fields only. A future
detail endpoint can return the full row.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from imga_db.models import PromptTemplate
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import CurrentUser, require_super_admin
from imga_api.db_deps import get_admin_session

router = APIRouter(prefix="/admin/prompt-templates", tags=["Admin"])

_SuperAdmin = Depends(require_super_admin)


class PromptTemplateMeta(BaseModel):
    id: UUID
    template_key: str
    model_name: str
    temperature: float
    top_p: float
    max_output_tokens: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


@router.get(
    "",
    response_model=list[PromptTemplateMeta],
    summary="List system-level prompt templates (read-only).",
)
async def list_prompt_templates(
    current: Annotated[CurrentUser, _SuperAdmin],
    admin_session: Annotated[AsyncSession, Depends(get_admin_session)],
) -> list[PromptTemplateMeta]:
    """System-level — no RLS, no tenant scope, super-admin only."""
    del current  # auth dependency only; no per-user filtering.
    # ``async with admin_session.begin()`` YOK: get_current_user ayni
    # session'da (FastAPI dependency cache) bir SELECT kosup autobegin
    # ile transaction'i acik birakiyor; ikinci bir begin() "A
    # transaction is already begun on this Session" 500'u verir —
    # bkz. tests/test_admin_session_regression.py.
    rows = (
        await admin_session.execute(
            select(PromptTemplate).order_by(PromptTemplate.template_key)
        )
    ).scalars().all()
    return [
        PromptTemplateMeta(
            id=row.id,
            template_key=row.template_key,
            model_name=row.model_name,
            temperature=row.temperature,
            top_p=row.top_p,
            max_output_tokens=row.max_output_tokens,
            is_active=row.is_active,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        for row in rows
    ]
