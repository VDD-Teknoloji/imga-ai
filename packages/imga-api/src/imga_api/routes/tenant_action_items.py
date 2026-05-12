"""``/tenants/me/action-items`` — task tracking surface.

Sprint 8.3.10. Endpoints:

  * GET    /                        — list with filters; defaults to
                                      active rows only,
                                      ``?include_archived=true`` widens
                                      the scope (Sprint 9.1 A).
  * POST   /                        — manual create
  * PATCH  /{id}                    — edit (status/priority/assignee/due)
  * DELETE /{id}                    — Sprint 9.1 A: soft delete via
                                      ``ActionItemService.archive`` —
                                      the row stays for the audit trail
                                      and can be restored.
  * POST   /{id}/restore            — un-archive (Sprint 9.1 A).
  * GET    /{id}/events             — audit timeline (Sprint 9.1 A).
  * POST   /extract-from-report/{report_id}
                                    — pull strategic_recommendations
                                      from a SWOT row into action_items;
                                      emits ``created`` events with
                                      ``actor_type=llm_extraction``.

logger.exception() on every catch path — Sprint 8.3.6.6 round-3
baseline note.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Annotated, Any
from uuid import UUID

import json

from fastapi import APIRouter, Depends, Header, HTTPException, status
from imga_db.models import (
    ActionItem,
    ActionItemEvent,
    StrategicReport,
    UserTenantRole,
)
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import CurrentUser, bind_tenant, require_role
from imga_api.db_deps import get_app_session
from imga_api.services import (
    ACTOR_LLM_EXTRACTION,
    ActionItemAlreadyArchived,
    ActionItemNotArchived,
    ActionItemNotFound,
    ActionItemService,
)

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tenants/me/action-items", tags=["Action Items"])

_AnyMember = Depends(require_role(
    UserTenantRole.TENANT_ADMIN,
    UserTenantRole.ANALYST,
    UserTenantRole.VIEWER,
))
_WriteMember = Depends(require_role(
    UserTenantRole.TENANT_ADMIN,
    UserTenantRole.ANALYST,
))

ALLOWED_PRIORITIES = {"high", "medium", "low"}
ALLOWED_STATUSES = {"open", "in_progress", "done", "cancelled"}


class ActionItemResponse(BaseModel):
    id: UUID
    title: str
    description: str
    rationale: str | None
    priority: str
    estimated_impact: str | None
    status: str
    source_report_id: UUID | None
    source_briefing_id: UUID | None
    assignee_user_id: UUID | None
    due_date: date | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    # Sprint 9.1 A — soft-delete state. ``is_archived`` is the
    # derived bool the UI binds to; the timestamp lets the user see
    # *when* the archive happened on the timeline view.
    is_archived: bool
    archived_at: datetime | None
    archived_by: UUID | None


class ActionItemEventResponse(BaseModel):
    """Sprint 9.1 A — single audit-trail row, newest-first ordering."""

    id: UUID
    event_type: str
    actor_user_id: UUID | None
    actor_type: str
    payload: dict[str, Any]
    created_at: datetime


class ActionItemCreateRequest(BaseModel):
    title: str
    description: str
    rationale: str | None = None
    priority: str = "medium"
    estimated_impact: str | None = None
    assignee_user_id: UUID | None = None
    due_date: date | None = None

    @field_validator("title")
    @classmethod
    def _v_title(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > 256:
            raise ValueError("title must be 1-256 characters")
        return v

    @field_validator("description")
    @classmethod
    def _v_desc(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("description is required")
        return v

    @field_validator("priority")
    @classmethod
    def _v_priority(cls, v: str) -> str:
        if v not in ALLOWED_PRIORITIES:
            raise ValueError(
                f"priority must be one of {sorted(ALLOWED_PRIORITIES)}"
            )
        return v

    @field_validator("estimated_impact")
    @classmethod
    def _v_impact(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if v not in ALLOWED_PRIORITIES:
            raise ValueError(
                f"estimated_impact must be one of {sorted(ALLOWED_PRIORITIES)}"
            )
        return v


class ActionItemUpdateRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    rationale: str | None = None
    priority: str | None = None
    estimated_impact: str | None = None
    status: str | None = None
    assignee_user_id: UUID | None = Field(default=None)
    due_date: date | None = None

    @field_validator("status")
    @classmethod
    def _v_status(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if v not in ALLOWED_STATUSES:
            raise ValueError(
                f"status must be one of {sorted(ALLOWED_STATUSES)}"
            )
        return v

    @field_validator("priority")
    @classmethod
    def _v_priority(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if v not in ALLOWED_PRIORITIES:
            raise ValueError(
                f"priority must be one of {sorted(ALLOWED_PRIORITIES)}"
            )
        return v


def _require_active_tenant(current: CurrentUser) -> UUID:
    if current.active_tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="active tenant context required for this endpoint",
        )
    return current.active_tenant_id


def _row_to_response(row: ActionItem) -> ActionItemResponse:
    return ActionItemResponse(
        id=row.id,
        title=row.title,
        description=row.description,
        rationale=row.rationale,
        priority=row.priority,
        estimated_impact=row.estimated_impact,
        status=row.status,
        source_report_id=row.source_report_id,
        source_briefing_id=row.source_briefing_id,
        assignee_user_id=row.assignee_user_id,
        due_date=row.due_date,
        created_at=row.created_at,
        updated_at=row.updated_at,
        completed_at=row.completed_at,
        is_archived=row.archived_at is not None,
        archived_at=row.archived_at,
        archived_by=row.archived_by,
    )


def _event_to_response(row: ActionItemEvent) -> ActionItemEventResponse:
    return ActionItemEventResponse(
        id=row.id,
        event_type=row.event_type,
        actor_user_id=row.actor_user_id,
        actor_type=row.actor_type,
        payload=dict(row.payload or {}),
        created_at=row.created_at,
    )


@router.get(
    "",
    response_model=list[ActionItemResponse],
    summary="List action items with optional filters.",
)
async def list_action_items(
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    status_filter: str | None = None,
    priority: str | None = None,
    assignee_user_id: UUID | None = None,
    include_archived: bool = False,
) -> list[ActionItemResponse]:
    if status_filter is not None and status_filter not in ALLOWED_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"status must be one of {sorted(ALLOWED_STATUSES)}",
        )
    if priority is not None and priority not in ALLOWED_PRIORITIES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"priority must be one of {sorted(ALLOWED_PRIORITIES)}",
        )
    tenant_id = _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        stmt = select(ActionItem).where(ActionItem.tenant_id == tenant_id)
        if not include_archived:
            stmt = stmt.where(ActionItem.archived_at.is_(None))
        if status_filter is not None:
            stmt = stmt.where(ActionItem.status == status_filter)
        if priority is not None:
            stmt = stmt.where(ActionItem.priority == priority)
        if assignee_user_id is not None:
            stmt = stmt.where(ActionItem.assignee_user_id == assignee_user_id)
        stmt = stmt.order_by(ActionItem.created_at.desc())
        rows = (await app_session.execute(stmt)).scalars().all()
    return [_row_to_response(r) for r in rows]


@router.post(
    "",
    response_model=ActionItemResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a manual action item.",
)
async def create_action_item(
    body: ActionItemCreateRequest,
    current: Annotated[CurrentUser, _WriteMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description=(
                "Sprint 9.5 B2 — HTTP idempotency. When set, a retry "
                "with the same key + tenant returns the existing row "
                "instead of inserting a duplicate. Bounded to 128 "
                "chars; longer values are silently truncated by the "
                "DB constraint."
            ),
            max_length=128,
        ),
    ] = None,
) -> ActionItemResponse:
    """Create a manual action item.

    Sprint 9.5 B2 — supports an ``Idempotency-Key`` request header.
    When the header is set:
      * First call inserts the row + persists the key.
      * Retries with the SAME key + tenant short-circuit to the
        existing row (idempotent reply, 201 each time).
      * Different bodies under the same key DON'T diverge — the
        first body wins; the partial UNIQUE index on
        ``(tenant_id, idempotency_key) WHERE idempotency_key IS
        NOT NULL`` enforces this.

    Without the header (legacy / non-idempotent clients), behaviour
    is unchanged from Sprint 9.1 A: each call mints a fresh row.
    """
    tenant_id = _require_active_tenant(current)
    try:
        async with app_session.begin():
            await bind_tenant(app_session, current)
            # Idempotency check — only when key supplied. The cheap
            # SELECT is keyed on the partial UNIQUE index so a
            # hit is sub-millisecond.
            if idempotency_key is not None:
                existing = (
                    await app_session.execute(
                        select(ActionItem)
                        .where(ActionItem.tenant_id == tenant_id)
                        .where(
                            ActionItem.idempotency_key == idempotency_key
                        )
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    return _row_to_response(existing)

            row = ActionItem(
                tenant_id=tenant_id,
                title=body.title,
                description=body.description,
                rationale=body.rationale,
                priority=body.priority,
                estimated_impact=body.estimated_impact,
                status="open",
                assignee_user_id=body.assignee_user_id,
                due_date=body.due_date,
                idempotency_key=idempotency_key,
            )
            app_session.add(row)
            await app_session.flush()
            # Sprint 9.1 A — journal the creation. ActionItemService
            # writes the event row inside the same transaction.
            service = ActionItemService(app_session)
            await service.emit_created(
                row=row,
                actor_user_id=current.user_id,
                payload={"source": "manual"},
            )
            response = _row_to_response(row)
        return response
    except HTTPException:
        raise
    except Exception:
        _logger.exception(
            "create_action_item failed",
            extra={"tenant_id": str(tenant_id)},
        )
        raise


@router.patch(
    "/{item_id}",
    response_model=ActionItemResponse,
    summary="Edit fields on an action item.",
)
async def update_action_item(
    item_id: UUID,
    body: ActionItemUpdateRequest,
    current: Annotated[CurrentUser, _WriteMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> ActionItemResponse:
    tenant_id = _require_active_tenant(current)
    try:
        async with app_session.begin():
            await bind_tenant(app_session, current)
            service = ActionItemService(app_session)
            updates = body.model_dump(exclude_unset=True)
            row = await service.update(
                item_id=item_id,
                tenant_id=tenant_id,
                updates=updates,
                actor_user_id=current.user_id,
            )
            await app_session.refresh(row, ["updated_at"])
            response = _row_to_response(row)
        return response
    except ActionItemNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="action item bulunamadı",
        ) from exc
    except HTTPException:
        raise
    except Exception:
        _logger.exception(
            "update_action_item failed",
            extra={"tenant_id": str(tenant_id), "item_id": str(item_id)},
        )
        raise


@router.delete(
    "/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary=(
        "Archive an action item. Sprint 9.1 A — soft delete; the row "
        "stays for the audit trail and can be restored via "
        "POST /{id}/restore."
    ),
)
async def archive_action_item(
    item_id: UUID,
    current: Annotated[CurrentUser, _WriteMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> None:
    tenant_id = _require_active_tenant(current)
    try:
        async with app_session.begin():
            await bind_tenant(app_session, current)
            service = ActionItemService(app_session)
            await service.archive(
                item_id=item_id,
                tenant_id=tenant_id,
                actor_user_id=current.user_id,
            )
    except ActionItemNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="action item bulunamadı",
        ) from exc
    except ActionItemAlreadyArchived as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="action item zaten arşivde",
        ) from exc
    except HTTPException:
        raise
    except Exception:
        _logger.exception(
            "archive_action_item failed",
            extra={"tenant_id": str(tenant_id), "item_id": str(item_id)},
        )
        raise


@router.post(
    "/{item_id}/restore",
    response_model=ActionItemResponse,
    summary="Un-archive a previously soft-deleted action item.",
)
async def restore_action_item(
    item_id: UUID,
    current: Annotated[CurrentUser, _WriteMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> ActionItemResponse:
    tenant_id = _require_active_tenant(current)
    try:
        async with app_session.begin():
            await bind_tenant(app_session, current)
            service = ActionItemService(app_session)
            row = await service.restore(
                item_id=item_id,
                tenant_id=tenant_id,
                actor_user_id=current.user_id,
            )
            response = _row_to_response(row)
        return response
    except ActionItemNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="action item bulunamadı",
        ) from exc
    except ActionItemNotArchived as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="action item arşivde değil",
        ) from exc
    except HTTPException:
        raise
    except Exception:
        _logger.exception(
            "restore_action_item failed",
            extra={"tenant_id": str(tenant_id), "item_id": str(item_id)},
        )
        raise


@router.get(
    "/{item_id}/events",
    response_model=list[ActionItemEventResponse],
    summary="Audit timeline (newest first).",
)
async def list_action_item_events(
    item_id: UUID,
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> list[ActionItemEventResponse]:
    tenant_id = _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        # 404 if the item itself isn't visible — the events table
        # cascades on item delete so an empty list could mean either
        # "never seen" or "purged"; an explicit 404 disambiguates.
        item = await app_session.get(ActionItem, item_id)
        if item is None or item.tenant_id != tenant_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="action item bulunamadı",
            )
        stmt = (
            select(ActionItemEvent)
            .where(ActionItemEvent.action_item_id == item_id)
            .order_by(ActionItemEvent.created_at.desc())
        )
        rows = (await app_session.execute(stmt)).scalars().all()
    return [_event_to_response(r) for r in rows]


@router.post(
    "/extract-from-report/{report_id}",
    response_model=list[ActionItemResponse],
    status_code=status.HTTP_201_CREATED,
    summary=(
        "Extract action items from a SWOT report's "
        "strategic_recommendations."
    ),
)
async def extract_from_report(
    report_id: UUID,
    current: Annotated[CurrentUser, _WriteMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> list[ActionItemResponse]:
    """Read the SWOT row's ``strategic_recommendations`` array and
    return the action items extracted from it.

    Sprint 9.5 B2 — re-extracting the same SWOT used to mint
    duplicate ActionItem rows on every call. The route now routes
    through ``ActionExtractionService``, which fingerprint-dedups
    on ``(tenant_id, source_type, source_id, content_hash)``: the
    first call mints + persists, every subsequent call with the
    same SWOT content returns the same action_item_ids. A re-
    generated SWOT with edited recommendations gets a fresh
    fingerprint and a new extraction. Sprint 9.1 A's per-row
    ``created`` event with ``actor_type=llm_extraction`` is still
    emitted from inside the service.
    """
    from imga_api.services.action_extraction_service import (
        ActionExtractionService,
    )

    tenant_id = _require_active_tenant(current)
    try:
        async with app_session.begin():
            await bind_tenant(app_session, current)
            report = await app_session.get(StrategicReport, report_id)
            if report is None or report.tenant_id != tenant_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="rapor bulunamadı",
                )
            if report.report_type != "swot":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        "action items sadece SWOT raporlarından çıkarılabilir"
                    ),
                )
            recs = (report.output_payload or {}).get(
                "strategic_recommendations", []
            )
            # Build the payload list ActionExtractionService expects.
            # Normalisation mirrors the pre-9.5 inline logic so the
            # resulting rows look identical to a caller who didn't
            # know about the refactor.
            payloads: list[dict[str, Any]] = []
            for rec in recs:
                if not isinstance(rec, dict):
                    continue
                payloads.append(
                    {
                        "title": (
                            str(rec.get("title", "")).strip()[:256]
                            or "Öneri"
                        ),
                        "description": (
                            str(rec.get("description", "")).strip()
                            or "Açıklama yok."
                        ),
                        "rationale": None,
                        "priority": _normalise_priority(rec.get("priority")),
                        "estimated_impact": _normalise_priority(
                            rec.get("estimated_impact")
                        ),
                    }
                )
            if not payloads:
                return []

            # ``content_text`` is the dedup fingerprint anchor —
            # service hashes it with the extraction_version. Use the
            # canonical JSON of the normalised payloads so a SWOT
            # regenerated with the same recommendations produces the
            # same fingerprint regardless of cosmetic key ordering.
            content_text = _json_canonical(payloads)
            extractor = ActionExtractionService(app_session)
            item_ids = await extractor.extract(
                tenant_id=tenant_id,
                source_type="strategic_report",
                source_id=report.id,
                content_text=content_text,
                action_payloads=payloads,
            )

            # Re-fetch the rows to build the response. The service
            # returns ids only; we need ActionItem rows for
            # ``_row_to_response``.
            rows_stmt = (
                select(ActionItem)
                .where(ActionItem.tenant_id == tenant_id)
                .where(ActionItem.id.in_(item_ids))
            )
            rows = list(
                (await app_session.execute(rows_stmt)).scalars().all()
            )
            # Preserve service-returned order so the UI sees the
            # same priority sequence on every re-call.
            row_by_id = {r.id: r for r in rows}
            ordered = [row_by_id[i] for i in item_ids if i in row_by_id]
            response = [_row_to_response(r) for r in ordered]
        return response
    except HTTPException:
        raise
    except Exception:
        _logger.exception(
            "extract_from_report failed",
            extra={
                "tenant_id": str(tenant_id),
                "report_id": str(report_id),
            },
        )
        raise


def _json_canonical(payloads: list[dict[str, Any]]) -> str:
    """Stable JSON serialisation for the action_extraction
    fingerprint. ``sort_keys=True`` so a SWOT regenerated with the
    same recommendations produces the same fingerprint regardless
    of LLM-side key-ordering jitter."""
    return json.dumps(
        payloads, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )


def _normalise_priority(raw: Any) -> str:
    """Map SWOT recommendation priority ("yüksek" / "orta" / "düşük") to
    the action_item enum (high / medium / low). Other values default
    to medium."""
    if not isinstance(raw, str):
        return "medium"
    mapping = {
        "yüksek": "high",
        "high": "high",
        "orta": "medium",
        "medium": "medium",
        "düşük": "low",
        "low": "low",
    }
    return mapping.get(raw.strip().lower(), "medium")
