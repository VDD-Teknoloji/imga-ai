"""``/tenants/me/sla-rules`` — tenant-configurable SLA threshold rules.

Sprint 8.3.7-A. CRUD over ``sla_rules`` rows. The actual evaluator
that runs reviews against active rules lives in
``imga_api.services.sla_engine``; this router only persists.

Action wiring across sprints:

  * ``warn_only`` — live now (the engine logs / emits an event).
  * ``create_ticket`` — Sprint 8.3.9.
  * ``escalate`` — Sprint 8.3.9.
  * ``notify_email`` — Sprint 8.6 alongside Mailcow.

The DB CHECK accepts all four so configuration survives the
intervening sprints; the engine raises NotImplementedError on the
unwired actions until those sprints land. Tenants can therefore
draft rules now and have them activate automatically.

logger.exception() on every catch — Sprint 8.3.6.6 round-3 baseline.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from imga_db.models import SlaRule, UserTenantRole
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import CurrentUser, bind_tenant, require_role
from imga_api.db_deps import get_app_session

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tenants/me/sla-rules", tags=["Tenant Config"])

_AnyMember = Depends(require_role(
    UserTenantRole.TENANT_ADMIN,
    UserTenantRole.ANALYST,
    UserTenantRole.VIEWER,
))
_AdminOnly = Depends(require_role(UserTenantRole.TENANT_ADMIN))

ALLOWED_PRIORITIES = {"low", "normal", "high", "urgent"}
ALLOWED_ACTIONS = {"warn_only", "create_ticket", "escalate", "notify_email"}


# --------------------------------------------------------------------- #
# Pydantic schemas                                                      #
# --------------------------------------------------------------------- #


class SlaRuleResponse(BaseModel):
    id: UUID
    name: str
    match_priority: str | None
    match_taxonomy_codes: list[str] | None
    match_company_perspective_codes: list[str] | None
    match_nps_score_max: int | None
    response_sla_minutes: int | None
    resolution_sla_minutes: int | None
    action_type: str
    action_config: dict[str, Any]
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SlaRuleCreateRequest(BaseModel):
    name: str
    match_priority: str | None = None
    match_taxonomy_codes: list[str] | None = None
    match_company_perspective_codes: list[str] | None = None
    match_nps_score_max: int | None = None
    response_sla_minutes: int | None = None
    resolution_sla_minutes: int | None = None
    action_type: str = "warn_only"
    action_config: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > 128:
            raise ValueError("name must be 1-128 characters")
        return v

    @field_validator("match_priority")
    @classmethod
    def _validate_priority(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if v not in ALLOWED_PRIORITIES:
            raise ValueError(
                f"match_priority must be one of {sorted(ALLOWED_PRIORITIES)}"
            )
        return v

    @field_validator("action_type")
    @classmethod
    def _validate_action(cls, v: str) -> str:
        if v not in ALLOWED_ACTIONS:
            raise ValueError(
                f"action_type must be one of {sorted(ALLOWED_ACTIONS)}"
            )
        return v

    @field_validator("response_sla_minutes", "resolution_sla_minutes")
    @classmethod
    def _validate_minutes(cls, v: int | None) -> int | None:
        if v is None:
            return None
        if v < 1 or v > 60 * 24 * 90:  # cap at 90 days
            raise ValueError(
                "SLA minutes must be 1..129600 (90 days)"
            )
        return v

    @field_validator("match_nps_score_max")
    @classmethod
    def _validate_nps(cls, v: int | None) -> int | None:
        if v is None:
            return None
        if not 0 <= v <= 10:
            raise ValueError("match_nps_score_max must be 0..10")
        return v

    @field_validator(
        "match_taxonomy_codes",
        "match_company_perspective_codes",
    )
    @classmethod
    def _validate_codes(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        cleaned: list[str] = []
        seen: set[str] = set()
        for entry in v:
            s = entry.strip()
            if not s or len(s) > 64:
                raise ValueError("codes must be 1-64 characters")
            if s in seen:
                continue
            seen.add(s)
            cleaned.append(s)
        return cleaned or None

    @model_validator(mode="after")
    def _check_threshold_required(self) -> SlaRuleCreateRequest:
        if (
            self.response_sla_minutes is None
            and self.resolution_sla_minutes is None
        ):
            raise ValueError(
                "response_sla_minutes veya resolution_sla_minutes "
                "alanlarından en az biri ayarlanmalı"
            )
        return self


class SlaRuleUpdateRequest(BaseModel):
    name: str | None = None
    match_priority: str | None = None
    match_taxonomy_codes: list[str] | None = None
    match_company_perspective_codes: list[str] | None = None
    match_nps_score_max: int | None = None
    response_sla_minutes: int | None = None
    resolution_sla_minutes: int | None = None
    action_type: str | None = None
    action_config: dict[str, Any] | None = None
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v or len(v) > 128:
            raise ValueError("name must be 1-128 characters")
        return v

    @field_validator("match_priority")
    @classmethod
    def _validate_priority(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if v not in ALLOWED_PRIORITIES:
            raise ValueError(
                f"match_priority must be one of {sorted(ALLOWED_PRIORITIES)}"
            )
        return v

    @field_validator("action_type")
    @classmethod
    def _validate_action(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if v not in ALLOWED_ACTIONS:
            raise ValueError(
                f"action_type must be one of {sorted(ALLOWED_ACTIONS)}"
            )
        return v


# --------------------------------------------------------------------- #
# Helpers                                                               #
# --------------------------------------------------------------------- #


def _require_active_tenant(current: CurrentUser) -> UUID:
    if current.active_tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="active tenant context required for this endpoint",
        )
    return current.active_tenant_id


def _row_to_response(row: SlaRule) -> SlaRuleResponse:
    return SlaRuleResponse(
        id=row.id,
        name=row.name,
        match_priority=row.match_priority,
        match_taxonomy_codes=(
            list(row.match_taxonomy_codes)
            if row.match_taxonomy_codes is not None
            else None
        ),
        match_company_perspective_codes=(
            list(row.match_company_perspective_codes)
            if row.match_company_perspective_codes is not None
            else None
        ),
        match_nps_score_max=row.match_nps_score_max,
        response_sla_minutes=row.response_sla_minutes,
        resolution_sla_minutes=row.resolution_sla_minutes,
        action_type=row.action_type,
        action_config=dict(row.action_config or {}),
        is_active=row.is_active,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _load_for_tenant(
    session: AsyncSession, tenant_id: UUID, rule_id: UUID
) -> SlaRule:
    row = await session.get(SlaRule, rule_id)
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SLA kuralı bulunamadı",
        )
    return row


# --------------------------------------------------------------------- #
# Endpoints                                                             #
# --------------------------------------------------------------------- #


@router.get(
    "",
    response_model=list[SlaRuleResponse],
    summary="List the active tenant's SLA rules.",
)
async def list_sla_rules(
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    include_inactive: bool = False,
) -> list[SlaRuleResponse]:
    tenant_id = _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        stmt = select(SlaRule).where(SlaRule.tenant_id == tenant_id)
        if not include_inactive:
            stmt = stmt.where(SlaRule.is_active.is_(True))
        stmt = stmt.order_by(SlaRule.created_at)
        rows = (await app_session.execute(stmt)).scalars().all()
    return [_row_to_response(r) for r in rows]


@router.post(
    "",
    response_model=SlaRuleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new SLA rule.",
)
async def create_sla_rule(
    body: SlaRuleCreateRequest,
    current: Annotated[CurrentUser, _AdminOnly],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> SlaRuleResponse:
    tenant_id = _require_active_tenant(current)
    try:
        async with app_session.begin():
            await bind_tenant(app_session, current)
            row = SlaRule(
                tenant_id=tenant_id,
                name=body.name,
                match_priority=body.match_priority,
                match_taxonomy_codes=body.match_taxonomy_codes,
                match_company_perspective_codes=body.match_company_perspective_codes,
                match_nps_score_max=body.match_nps_score_max,
                response_sla_minutes=body.response_sla_minutes,
                resolution_sla_minutes=body.resolution_sla_minutes,
                action_type=body.action_type,
                action_config=body.action_config,
                is_active=body.is_active,
            )
            app_session.add(row)
            await app_session.flush()
            # Sprint 8.3.7-A — refresh server-computed ``updated_at``
            # inside the async greenlet so _row_to_response doesn't
            # trigger a lazy reload via SQLAlchemy's sync path
            # (MissingGreenlet).
            await app_session.refresh(row, ["updated_at"])
            response = _row_to_response(row)
        return response
    except HTTPException:
        raise
    except Exception:
        _logger.exception(
            "create_sla_rule failed",
            extra={"tenant_id": str(tenant_id), "name": body.name},
        )
        raise


@router.patch(
    "/{rule_id}",
    response_model=SlaRuleResponse,
    summary="Edit fields on an SLA rule.",
)
async def update_sla_rule(
    rule_id: UUID,
    body: SlaRuleUpdateRequest,
    current: Annotated[CurrentUser, _AdminOnly],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> SlaRuleResponse:
    tenant_id = _require_active_tenant(current)
    try:
        async with app_session.begin():
            await bind_tenant(app_session, current)
            row = await _load_for_tenant(app_session, tenant_id, rule_id)

            data = body.model_dump(exclude_unset=True)
            for key, value in data.items():
                setattr(row, key, value)

            # Re-validate the threshold guarantee after the partial
            # update — if the user clears both fields the row would
            # violate the DB CHECK at flush time, but we surface the
            # cleaner Pydantic-style 400 here.
            if (
                row.response_sla_minutes is None
                and row.resolution_sla_minutes is None
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        "response_sla_minutes veya resolution_sla_minutes "
                        "alanlarından en az biri ayarlanmalı"
                    ),
                )

            await app_session.flush()
            # Sprint 8.3.7-A — refresh server-computed ``updated_at``
            # inside the async greenlet so _row_to_response doesn't
            # trigger a lazy reload via SQLAlchemy's sync path
            # (MissingGreenlet).
            await app_session.refresh(row, ["updated_at"])
            response = _row_to_response(row)
        return response
    except HTTPException:
        raise
    except Exception:
        _logger.exception(
            "update_sla_rule failed",
            extra={"tenant_id": str(tenant_id), "rule_id": str(rule_id)},
        )
        raise


@router.delete(
    "/{rule_id}",
    response_model=SlaRuleResponse,
    summary="Soft delete an SLA rule (is_active=false).",
)
async def delete_sla_rule(
    rule_id: UUID,
    current: Annotated[CurrentUser, _AdminOnly],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> SlaRuleResponse:
    tenant_id = _require_active_tenant(current)
    try:
        async with app_session.begin():
            await bind_tenant(app_session, current)
            row = await _load_for_tenant(app_session, tenant_id, rule_id)
            row.is_active = False
            await app_session.flush()
            # Sprint 8.3.7-A — refresh server-computed ``updated_at``
            # inside the async greenlet so _row_to_response doesn't
            # trigger a lazy reload via SQLAlchemy's sync path
            # (MissingGreenlet).
            await app_session.refresh(row, ["updated_at"])
            response = _row_to_response(row)
        return response
    except HTTPException:
        raise
    except Exception:
        _logger.exception(
            "delete_sla_rule failed",
            extra={"tenant_id": str(tenant_id), "rule_id": str(rule_id)},
        )
        raise
