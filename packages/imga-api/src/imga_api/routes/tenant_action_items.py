"""``/tenants/me/action-items`` — task tracking surface.

Sprint 8.3.10. Five endpoints:

  * GET    /                        — list with filters
  * POST   /                        — manual create
  * PATCH  /{id}                    — edit (status/priority/assignee/due)
  * DELETE /{id}                    — hard delete (no soft-delete this
                                      sprint; the kanban hides
                                      "cancelled" vs "deleted" from the
                                      user)
  * POST   /extract-from-report/{report_id}
                                    — pull strategic_recommendations
                                      from a SWOT row into action_items

logger.exception() on every catch path — Sprint 8.3.6.6 round-3
baseline note.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from imga_db.models import ActionItem, StrategicReport, UserTenantRole
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import CurrentUser, bind_tenant, require_role
from imga_api.db_deps import get_app_session

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
) -> ActionItemResponse:
    tenant_id = _require_active_tenant(current)
    try:
        async with app_session.begin():
            await bind_tenant(app_session, current)
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
            )
            app_session.add(row)
            await app_session.flush()
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
            row = await app_session.get(ActionItem, item_id)
            if row is None or row.tenant_id != tenant_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="action item bulunamadı",
                )
            data = body.model_dump(exclude_unset=True)
            for key, value in data.items():
                setattr(row, key, value)
            # Auto-stamp completed_at when transitioning to ``done``.
            if "status" in data and data["status"] == "done" and row.completed_at is None:
                row.completed_at = datetime.utcnow()
            elif "status" in data and data["status"] != "done":
                row.completed_at = None
            await app_session.flush()
            await app_session.refresh(row, ["updated_at"])
            response = _row_to_response(row)
        return response
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
    summary="Hard-delete an action item.",
)
async def delete_action_item(
    item_id: UUID,
    current: Annotated[CurrentUser, _WriteMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> None:
    tenant_id = _require_active_tenant(current)
    try:
        async with app_session.begin():
            await bind_tenant(app_session, current)
            row = await app_session.get(ActionItem, item_id)
            if row is None or row.tenant_id != tenant_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="action item bulunamadı",
                )
            await app_session.delete(row)
    except HTTPException:
        raise
    except Exception:
        _logger.exception(
            "delete_action_item failed",
            extra={"tenant_id": str(tenant_id), "item_id": str(item_id)},
        )
        raise


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
    insert one action_item per entry. Each new row carries
    ``source_report_id`` so the UI can link back. Existing items
    from the same report are NOT deduplicated — calling extract
    twice doubles the rows; the user can delete duplicates manually.
    """
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
            created: list[ActionItem] = []
            for rec in recs:
                if not isinstance(rec, dict):
                    continue
                priority = _normalise_priority(rec.get("priority"))
                impact = _normalise_priority(rec.get("estimated_impact"))
                row = ActionItem(
                    tenant_id=tenant_id,
                    source_report_id=report.id,
                    title=str(rec.get("title", "")).strip()[:256] or "Öneri",
                    description=str(rec.get("description", "")).strip()
                    or "Açıklama yok.",
                    rationale=None,
                    priority=priority,
                    estimated_impact=impact,
                    status="open",
                )
                app_session.add(row)
                created.append(row)
            await app_session.flush()
            response = [_row_to_response(r) for r in created]
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
