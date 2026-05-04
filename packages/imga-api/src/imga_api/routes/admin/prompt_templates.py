"""Read-only admin view of system-level prompt templates.

Sprint 8.3.6.5.E. Future-ready: Sprint 9.x lands a real admin role +
edit endpoints; today this is a list-only surface so an operator can
inspect which templates the LLM stack is using. No tenant override
yet — every tenant sees the same module-resident system prompts via
the SWOT/OKR services; the DB rows exist for the registry table to
have a place when overrides ship.

The ``response_schema`` JSONB column is bigger than what's useful in
a list view, so this endpoint surfaces the meta fields only. A future
detail endpoint can return the full row.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from imga_db.models import PromptTemplate, UserTenantRole
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import CurrentUser, require_role
from imga_api.db_deps import get_admin_session

router = APIRouter(prefix="/admin/prompt-templates", tags=["Admin"])

# No system-admin role yet. Sprint 9.x adds one; until then any
# tenant_admin from any tenant can read the system templates. The
# registry is non-sensitive (placeholders today, version metadata
# tomorrow).
_AnyTenantAdmin = Depends(require_role(UserTenantRole.TENANT_ADMIN))


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
    current: Annotated[CurrentUser, _AnyTenantAdmin],
    admin_session: Annotated[AsyncSession, Depends(get_admin_session)],
) -> list[PromptTemplateMeta]:
    """System-level — no RLS, no tenant scope. Tenant-admins from any
    tenant can read. Sprint 9.x replaces this with a proper admin role."""
    del current  # auth dependency only; no per-user filtering.
    async with admin_session.begin():
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
