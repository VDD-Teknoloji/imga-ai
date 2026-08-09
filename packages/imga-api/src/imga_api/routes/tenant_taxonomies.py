"""``/tenants/me/taxonomies`` — company-perspective taxonomy CRUD.

Sprint 8.3.5 shipped GET; Sprint 8.3.7-A adds POST / PATCH / DELETE /
restore / reorder so each tenant can prune and extend the platform-
default 21-row seed.

Conventions worth flagging:

  * **system rows** (``is_default_seed=True``) — labels and keywords
    can be edited; the row CANNOT be hard-deleted via the API. Soft
    delete via the DELETE endpoint flips ``is_active`` to ``false``;
    POST /restore flips it back. Tenants who want a clean slate
    deactivate the system rows and add their own.
  * **audit log** — every write emits one ``taxonomy_edit_audit`` row
    with before/after JSONB snapshots, even when the action is
    initiated by a system path (user_id NULL).
  * **RLS** — every CRUD endpoint binds the tenant first; the explicit
    ``tenant_id ==`` predicate on UPDATE/DELETE statements is belt-
    and-braces (a row that slips past the policy still gets caught).
  * **logger.exception** — Sprint 8.3.6.6 round-3 baseline note.
    Every catch-block in this module logs with traceback so a 5xx
    surfaces in stdout.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from imga_core.categories.taxonomy import GLOBAL_CATEGORY_CODES
from imga_db.models import (
    CategoryTaxonomy,
    TaxonomyEditAudit,
    UserTenantRole,
)
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import CurrentUser, bind_tenant, require_role
from imga_api.db_deps import get_app_session

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tenants/me/taxonomies", tags=["Tenant Config"])

_AnyMember = Depends(require_role(
    UserTenantRole.TENANT_ADMIN,
    UserTenantRole.ANALYST,
    UserTenantRole.VIEWER,
))
_AdminOnly = Depends(require_role(UserTenantRole.TENANT_ADMIN))

# snake_case ASCII; one alpha lead, then alpha/digit/underscore.
_CODE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_CODE_MAX = 64
_LABEL_MAX = 128
_KEYWORD_MAX = 64
_KEYWORDS_LIMIT = 50


def _validate_primary_category_code(v: str | None) -> str | None:
    """Sprint 13.1 — ana kategori eşlemesi. NULL = eşlenmemiş; dolu
    ise ``reviews.primary_category`` ile aynı global kod uzayından
    olmak zorunda, aksi halde drill-down gruplaması sessizce boş
    kovalar üretir."""
    if v is None:
        return None
    v = v.strip()
    if not v:
        return None
    if v not in GLOBAL_CATEGORY_CODES:
        raise ValueError(
            "primary_category_code gecersiz; gecerli kodlar: "
            + ", ".join(sorted(GLOBAL_CATEGORY_CODES))
        )
    return v


# --------------------------------------------------------------------- #
# Pydantic schemas                                                      #
# --------------------------------------------------------------------- #


class TaxonomyEntryResponse(BaseModel):
    """Wire shape. Field names mirror the DB column names for one-to-
    one grep-ability; ``is_default_seed`` is what the user's master
    prompt called ``is_system`` (semantic match: platform-shipped row
    that can't be hard-deleted). The UI surfaces it as "Sistem"
    label-side rather than renaming the wire field, since the
    pre-existing /reviews and /insights consumers also read the same
    column under the same name."""

    id: UUID
    code: str
    label_tr: str
    keywords: list[str]
    priority: int
    parent_code: str | None
    primary_category_code: str | None
    is_default_seed: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime


class TaxonomyCreateRequest(BaseModel):
    code: str
    label_tr: str
    keywords: list[str] = Field(default_factory=list)
    priority: int = 100
    parent_code: str | None = None
    primary_category_code: str | None = None

    @field_validator("primary_category_code")
    @classmethod
    def _validate_primary(cls, v: str | None) -> str | None:
        return _validate_primary_category_code(v)

    @field_validator("code")
    @classmethod
    def _validate_code(cls, v: str) -> str:
        if not v or len(v) > _CODE_MAX:
            raise ValueError(f"code must be 1-{_CODE_MAX} characters")
        if not _CODE_RE.match(v):
            raise ValueError(
                "code must be snake_case (lowercase letters/digits/underscore, "
                "leading letter)"
            )
        return v

    @field_validator("label_tr")
    @classmethod
    def _validate_label(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > _LABEL_MAX:
            raise ValueError(f"label_tr must be 1-{_LABEL_MAX} characters")
        return v

    @field_validator("keywords")
    @classmethod
    def _validate_keywords(cls, v: list[str]) -> list[str]:
        return _normalise_keywords(v)

    @field_validator("priority")
    @classmethod
    def _validate_priority(cls, v: int) -> int:
        if not 0 <= v <= 9999:
            raise ValueError("priority must be 0-9999")
        return v


class TaxonomyUpdateRequest(BaseModel):
    label_tr: str | None = None
    keywords: list[str] | None = None
    priority: int | None = None
    parent_code: str | None = None
    primary_category_code: str | None = None

    @field_validator("primary_category_code")
    @classmethod
    def _validate_primary(cls, v: str | None) -> str | None:
        return _validate_primary_category_code(v)

    @field_validator("label_tr")
    @classmethod
    def _validate_label(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v or len(v) > _LABEL_MAX:
            raise ValueError(f"label_tr must be 1-{_LABEL_MAX} characters")
        return v

    @field_validator("keywords")
    @classmethod
    def _validate_keywords(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        return _normalise_keywords(v)

    @field_validator("priority")
    @classmethod
    def _validate_priority(cls, v: int | None) -> int | None:
        if v is None:
            return None
        if not 0 <= v <= 9999:
            raise ValueError("priority must be 0-9999")
        return v


class TaxonomyReorderRequest(BaseModel):
    """Bulk priority assignment. ``ordered_ids[0]`` becomes priority 0,
    the next priority 1, and so on. Cheap to reason about and matches
    the @dnd-kit drag-reorder UX on /settings/taxonomies."""

    ordered_ids: list[UUID]


# --------------------------------------------------------------------- #
# Helpers                                                               #
# --------------------------------------------------------------------- #


def _normalise_keywords(raw: list[str]) -> list[str]:
    if len(raw) > _KEYWORDS_LIMIT:
        raise ValueError(f"keywords list capped at {_KEYWORDS_LIMIT} entries")
    cleaned: list[str] = []
    seen: set[str] = set()
    for entry in raw:
        s = entry.strip().lower()
        if not s:
            continue
        if len(s) > _KEYWORD_MAX:
            raise ValueError(
                f"keyword too long: {s[:20]!r}... ({len(s)}>{_KEYWORD_MAX})"
            )
        if s in seen:
            continue
        seen.add(s)
        cleaned.append(s)
    return cleaned


def _require_active_tenant(current: CurrentUser) -> UUID:
    if current.active_tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="active tenant context required for this endpoint",
        )
    return current.active_tenant_id


def _row_to_response(row: CategoryTaxonomy) -> TaxonomyEntryResponse:
    return TaxonomyEntryResponse(
        id=row.id,
        code=row.code,
        label_tr=row.label_tr,
        keywords=list(row.keywords),
        priority=row.priority,
        parent_code=row.parent_code,
        primary_category_code=row.primary_category_code,
        is_default_seed=row.is_default_seed,
        is_active=row.is_active,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _row_to_audit_state(row: CategoryTaxonomy) -> dict[str, Any]:
    """JSONB-friendly dict snapshot for the audit log."""
    return {
        "id": str(row.id),
        "code": row.code,
        "label_tr": row.label_tr,
        "keywords": list(row.keywords),
        "priority": row.priority,
        "parent_code": row.parent_code,
        "primary_category_code": row.primary_category_code,
        "is_default_seed": row.is_default_seed,
        "is_active": row.is_active,
    }


def _emit_audit(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID | None,
    taxonomy_id: UUID,
    action: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> None:
    """Add one TaxonomyEditAudit row to the open transaction. Caller
    flushes via the surrounding ``async with session.begin()`` block."""
    session.add(
        TaxonomyEditAudit(
            tenant_id=tenant_id,
            user_id=user_id,
            taxonomy_id=taxonomy_id,
            action=action,
            before_state=before,
            after_state=after,
        )
    )


async def _load_for_tenant(
    session: AsyncSession, tenant_id: UUID, taxonomy_id: UUID
) -> CategoryTaxonomy:
    """Fetch one taxonomy or 404. RLS already constrains; the
    explicit tenant_id check is defence in depth."""
    row = await session.get(CategoryTaxonomy, taxonomy_id)
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="taksonomi bulunamadı",
        )
    return row


# --------------------------------------------------------------------- #
# Endpoints                                                             #
# --------------------------------------------------------------------- #


@router.get(
    "",
    response_model=list[TaxonomyEntryResponse],
    summary="List the active tenant's company-perspective taxonomy.",
)
async def list_taxonomies(
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    include_inactive: bool = False,
) -> list[TaxonomyEntryResponse]:
    """Read-only list ordered by priority (lower = higher precedence in
    the heuristic reranker). ``include_inactive=true`` surfaces soft-
    deleted rows for the /settings/taxonomies "show inactive" toggle."""
    tenant_id = _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        stmt = select(CategoryTaxonomy).where(
            CategoryTaxonomy.tenant_id == tenant_id
        )
        if not include_inactive:
            stmt = stmt.where(CategoryTaxonomy.is_active.is_(True))
        stmt = stmt.order_by(
            CategoryTaxonomy.priority, CategoryTaxonomy.code
        )
        rows = (await app_session.execute(stmt)).scalars().all()
    return [_row_to_response(r) for r in rows]


@router.post(
    "",
    response_model=TaxonomyEntryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a tenant-defined taxonomy entry.",
)
async def create_taxonomy(
    body: TaxonomyCreateRequest,
    current: Annotated[CurrentUser, _AdminOnly],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> TaxonomyEntryResponse:
    tenant_id = _require_active_tenant(current)
    try:
        async with app_session.begin():
            await bind_tenant(app_session, current)

            # Uniqueness check inside the transaction so the audit
            # row's tenant_id binding is consistent.
            existing = (
                await app_session.execute(
                    select(CategoryTaxonomy).where(
                        CategoryTaxonomy.tenant_id == tenant_id,
                        CategoryTaxonomy.code == body.code,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"code {body.code!r} bu tenant için zaten var",
                )

            if body.parent_code is not None:
                await _validate_parent_code(
                    app_session, tenant_id, body.parent_code, body.code
                )

            row = CategoryTaxonomy(
                tenant_id=tenant_id,
                code=body.code,
                label_tr=body.label_tr,
                keywords=body.keywords,
                priority=body.priority,
                parent_code=body.parent_code,
                primary_category_code=body.primary_category_code,
                is_default_seed=False,
                is_active=True,
            )
            app_session.add(row)
            await app_session.flush()

            _emit_audit(
                app_session,
                tenant_id=tenant_id,
                user_id=current.user_id,
                taxonomy_id=row.id,
                action="create",
                before=None,
                after=_row_to_audit_state(row),
            )
            response = _row_to_response(row)
        return response
    except HTTPException:
        raise
    except Exception:
        _logger.exception(
            "create_taxonomy failed",
            extra={"tenant_id": str(tenant_id), "code": body.code},
        )
        raise


@router.patch(
    "/{taxonomy_id}",
    response_model=TaxonomyEntryResponse,
    summary="Edit label / keywords / priority / parent_code / primary_category_code.",
)
async def update_taxonomy(
    taxonomy_id: UUID,
    body: TaxonomyUpdateRequest,
    current: Annotated[CurrentUser, _AdminOnly],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> TaxonomyEntryResponse:
    tenant_id = _require_active_tenant(current)
    try:
        async with app_session.begin():
            await bind_tenant(app_session, current)
            row = await _load_for_tenant(app_session, tenant_id, taxonomy_id)
            before = _row_to_audit_state(row)

            if body.label_tr is not None:
                row.label_tr = body.label_tr
            if body.keywords is not None:
                row.keywords = body.keywords
            if body.priority is not None:
                row.priority = body.priority
            if body.parent_code is not None and body.parent_code != row.code:
                await _validate_parent_code(
                    app_session, tenant_id, body.parent_code, row.code
                )
                row.parent_code = body.parent_code
            elif body.parent_code is None and "parent_code" in body.model_fields_set:
                # Explicit null clears the parent.
                row.parent_code = None
            # Ana kategori eşlemesi: acik null esleme'yi kaldirir.
            if "primary_category_code" in body.model_fields_set:
                row.primary_category_code = body.primary_category_code

            await app_session.flush()
            # Sprint 8.3.7-A — server-computed ``updated_at``
            # (onupdate=func.now()) gets expired after the UPDATE; an
            # implicit lazy reload during _row_to_response goes through
            # SQLAlchemy's sync path and crashes with MissingGreenlet.
            # Eagerly refresh inside the async context so the response
            # carries the fresh timestamp without the lazy round-trip.
            await app_session.refresh(row, ["updated_at"])
            _emit_audit(
                app_session,
                tenant_id=tenant_id,
                user_id=current.user_id,
                taxonomy_id=row.id,
                action="update",
                before=before,
                after=_row_to_audit_state(row),
            )
            response = _row_to_response(row)
        return response
    except HTTPException:
        raise
    except Exception:
        _logger.exception(
            "update_taxonomy failed",
            extra={
                "tenant_id": str(tenant_id),
                "taxonomy_id": str(taxonomy_id),
            },
        )
        raise


@router.delete(
    "/{taxonomy_id}",
    response_model=TaxonomyEntryResponse,
    summary="Soft delete (is_active=false). System rows allowed.",
)
async def delete_taxonomy(
    taxonomy_id: UUID,
    current: Annotated[CurrentUser, _AdminOnly],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> TaxonomyEntryResponse:
    """Soft delete via ``is_active=false``. Both system and tenant
    rows can be deactivated — system rows just can't be hard-deleted
    (this endpoint never hard-deletes anyway, so the protection is
    semantic for now). Restore via POST /{id}/restore."""
    tenant_id = _require_active_tenant(current)
    try:
        async with app_session.begin():
            await bind_tenant(app_session, current)
            row = await _load_for_tenant(app_session, tenant_id, taxonomy_id)
            if not row.is_active:
                # Idempotent — already deleted, just return the row.
                return _row_to_response(row)
            before = _row_to_audit_state(row)
            row.is_active = False
            await app_session.flush()
            await app_session.refresh(row, ["updated_at"])
            _emit_audit(
                app_session,
                tenant_id=tenant_id,
                user_id=current.user_id,
                taxonomy_id=row.id,
                action="delete",
                before=before,
                after=_row_to_audit_state(row),
            )
            response = _row_to_response(row)
        return response
    except HTTPException:
        raise
    except Exception:
        _logger.exception(
            "delete_taxonomy failed",
            extra={
                "tenant_id": str(tenant_id),
                "taxonomy_id": str(taxonomy_id),
            },
        )
        raise


@router.post(
    "/{taxonomy_id}/restore",
    response_model=TaxonomyEntryResponse,
    summary="Restore a soft-deleted taxonomy row.",
)
async def restore_taxonomy(
    taxonomy_id: UUID,
    current: Annotated[CurrentUser, _AdminOnly],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> TaxonomyEntryResponse:
    tenant_id = _require_active_tenant(current)
    try:
        async with app_session.begin():
            await bind_tenant(app_session, current)
            row = await _load_for_tenant(app_session, tenant_id, taxonomy_id)
            if row.is_active:
                return _row_to_response(row)
            before = _row_to_audit_state(row)
            row.is_active = True
            await app_session.flush()
            await app_session.refresh(row, ["updated_at"])
            _emit_audit(
                app_session,
                tenant_id=tenant_id,
                user_id=current.user_id,
                taxonomy_id=row.id,
                action="restore",
                before=before,
                after=_row_to_audit_state(row),
            )
            response = _row_to_response(row)
        return response
    except HTTPException:
        raise
    except Exception:
        _logger.exception(
            "restore_taxonomy failed",
            extra={
                "tenant_id": str(tenant_id),
                "taxonomy_id": str(taxonomy_id),
            },
        )
        raise


@router.put(
    "/reorder",
    response_model=list[TaxonomyEntryResponse],
    summary="Reassign priorities by full ordered ID list.",
)
async def reorder_taxonomies(
    body: TaxonomyReorderRequest,
    current: Annotated[CurrentUser, _AdminOnly],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> list[TaxonomyEntryResponse]:
    """The drag-reorder UI sends the full ordered list of IDs. We
    rewrite priorities in-place so they map 1:1 to list position. To
    avoid the unique-priority window (none today, but cheap to be
    safe) we apply in two passes — push everything to a high range
    first, then write final priorities. Pattern mirrors the
    LlmCredential reorder helper."""
    tenant_id = _require_active_tenant(current)
    if not body.ordered_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ordered_ids boş olamaz",
        )
    try:
        async with app_session.begin():
            await bind_tenant(app_session, current)
            stmt = select(CategoryTaxonomy).where(
                CategoryTaxonomy.tenant_id == tenant_id
            )
            existing = {
                row.id: row
                for row in (await app_session.execute(stmt)).scalars().all()
            }
            missing = [tid for tid in body.ordered_ids if tid not in existing]
            if missing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"taksonomi(ler) bulunamadı: {missing}",
                )
            # Pass 1: push out of the way.
            offset = 10000
            for tid in body.ordered_ids:
                existing[tid].priority = offset
                offset += 1
            await app_session.flush()
            # Pass 2: final priorities.
            for index, tid in enumerate(body.ordered_ids):
                existing[tid].priority = index
            await app_session.flush()
            # Refresh updated_at on every touched row so _row_to_response
            # doesn't trigger a lazy reload outside the async greenlet.
            for tid in body.ordered_ids:
                await app_session.refresh(existing[tid], ["updated_at"])

            ordered_rows = [existing[tid] for tid in body.ordered_ids]
            response = [_row_to_response(r) for r in ordered_rows]
        return response
    except HTTPException:
        raise
    except Exception:
        _logger.exception(
            "reorder_taxonomies failed",
            extra={"tenant_id": str(tenant_id)},
        )
        raise


async def _validate_parent_code(
    session: AsyncSession,
    tenant_id: UUID,
    parent_code: str,
    self_code: str,
) -> None:
    """parent_code must point at a sibling row in the same tenant and
    cannot point at the same row (no self-loops). One-level depth is
    fine — the API doesn't try to detect deeper cycles in this sprint;
    the UI is the user-facing validator and the heuristic reranker
    doesn't recurse on parent_code."""
    if parent_code == self_code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="parent_code kendi kodunu işaret edemez",
        )
    parent = (
        await session.execute(
            select(CategoryTaxonomy).where(
                CategoryTaxonomy.tenant_id == tenant_id,
                CategoryTaxonomy.code == parent_code,
            )
        )
    ).scalar_one_or_none()
    if parent is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"parent_code {parent_code!r} bu tenant'ta yok",
        )
