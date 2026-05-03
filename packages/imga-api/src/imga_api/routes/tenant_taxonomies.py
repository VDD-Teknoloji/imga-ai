"""``/tenants/me/taxonomies`` — read-only company-perspective taxonomy.

Sprint 8.3.5 / Alt-Faz 8.3.5.5. Lists the active tenant's
category_taxonomies rows ordered by priority. Edit UI (POST / PATCH /
DELETE) lands in 8.3.7; this sprint ships only the read path so the
frontend dashboard / settings pages can render the seeded 21 defaults.

RLS-bound — the row-level policy on category_taxonomies filters to
``app.current_tenant_id`` automatically; the explicit ``tenant_id ==``
predicate is belt-and-braces (any policy bug surfaces as zero rows
instead of a cross-tenant leak).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from imga_db.models import CategoryTaxonomy, UserTenantRole
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import CurrentUser, bind_tenant, require_role
from imga_api.db_deps import get_app_session

router = APIRouter(prefix="/tenants/me/taxonomies", tags=["Tenant Config"])

_AnyMember = Depends(require_role(
    UserTenantRole.TENANT_ADMIN,
    UserTenantRole.ANALYST,
    UserTenantRole.VIEWER,
))


class TaxonomyEntryResponse(BaseModel):
    id: UUID
    code: str
    label_tr: str
    keywords: list[str]
    priority: int
    is_default_seed: bool
    created_at: datetime
    updated_at: datetime


def _require_active_tenant(current: CurrentUser) -> UUID:
    if current.active_tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="active tenant context required for this endpoint",
        )
    return current.active_tenant_id


@router.get(
    "",
    response_model=list[TaxonomyEntryResponse],
    summary="Active tenant's company-perspective taxonomy (Sprint 8.3.5).",
)
async def list_taxonomies(
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> list[TaxonomyEntryResponse]:
    """Read-only list ordered by priority (lower = higher precedence in
    the heuristic reranker). Edit UI is Sprint 8.3.7."""
    tenant_id = _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        stmt = (
            select(CategoryTaxonomy)
            .where(CategoryTaxonomy.tenant_id == tenant_id)
            .order_by(CategoryTaxonomy.priority, CategoryTaxonomy.code)
        )
        rows = (await app_session.execute(stmt)).scalars().all()
    return [
        TaxonomyEntryResponse(
            id=row.id,
            code=row.code,
            label_tr=row.label_tr,
            keywords=list(row.keywords),
            priority=row.priority,
            is_default_seed=row.is_default_seed,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        for row in rows
    ]
