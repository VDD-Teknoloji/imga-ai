"""``/tenants/me/ticket-routing`` — kategori bazlı ticket yönlendirme.

CRUD over ``ticket_routing_rules`` + salt-okunur outbox penceresi.
Motor (kural eşleştirme + atama + e-posta enqueue) ayrı modülde —
``imga_api.services.ticket_routing_service``; bu router yalnız persist
eder. Kalıp tenant_sla_rules ile birebir: _AnyMember read / _AdminOnly
write, ``bind_tenant`` her handler'ın transaction'ında,
``refresh(["updated_at"])`` MissingGreenlet workaround'u, her
mutasyonda DecisionAudit.

logger.exception() on every catch — Sprint 8.3.6.6 round-3 baseline.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from imga_db.models import EmailOutbox, TicketRoutingRule, UserTenantRole
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import CurrentUser, bind_tenant, require_role
from imga_api.db_deps import get_app_session
from imga_api.services import (
    DECISION_TENANT_SETTING_CHANGED,
    DecisionAuditService,
)

_logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/tenants/me/ticket-routing", tags=["Tenant Config"]
)

_AnyMember = Depends(require_role(
    UserTenantRole.TENANT_ADMIN,
    UserTenantRole.ANALYST,
    UserTenantRole.VIEWER,
))
_AdminOnly = Depends(require_role(UserTenantRole.TENANT_ADMIN))

# 90 gün — sla_rules'daki dakika cap'inin saat karşılığı.
_MAX_SLA_HOURS = 24 * 90


# --------------------------------------------------------------------- #
# Pydantic schemas                                                      #
# --------------------------------------------------------------------- #


class RoutingRuleView(BaseModel):
    id: UUID
    category_code: str
    notify_email: str
    assignee_user_id: UUID | None
    sla_hours: int | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class RoutingRulesResponse(BaseModel):
    rules: list[RoutingRuleView]


def _clean_category_code(v: str) -> str:
    v = v.strip()
    if not v or len(v) > 64:
        raise ValueError("category_code must be 1-64 characters")
    return v


def _clean_notify_email(v: str) -> str:
    v = v.strip()
    if not v or len(v) > 320 or "@" not in v[1:-1]:
        raise ValueError("notify_email must be a valid email address")
    return v


def _clean_sla_hours(v: int | None) -> int | None:
    if v is None:
        return None
    if v < 1 or v > _MAX_SLA_HOURS:
        raise ValueError(f"sla_hours must be 1..{_MAX_SLA_HOURS}")
    return v


class RoutingRuleCreateRequest(BaseModel):
    category_code: str
    notify_email: str
    assignee_user_id: UUID | None = None
    sla_hours: int | None = None
    is_active: bool = True

    @field_validator("category_code")
    @classmethod
    def _validate_category_code(cls, v: str) -> str:
        return _clean_category_code(v)

    @field_validator("notify_email")
    @classmethod
    def _validate_notify_email(cls, v: str) -> str:
        return _clean_notify_email(v)

    @field_validator("sla_hours")
    @classmethod
    def _validate_sla_hours(cls, v: int | None) -> int | None:
        return _clean_sla_hours(v)


class RoutingRuleUpdateRequest(BaseModel):
    category_code: str | None = None
    notify_email: str | None = None
    assignee_user_id: UUID | None = None
    sla_hours: int | None = None
    is_active: bool | None = None

    @field_validator("category_code")
    @classmethod
    def _validate_category_code(cls, v: str | None) -> str | None:
        return None if v is None else _clean_category_code(v)

    @field_validator("notify_email")
    @classmethod
    def _validate_notify_email(cls, v: str | None) -> str | None:
        return None if v is None else _clean_notify_email(v)

    @field_validator("sla_hours")
    @classmethod
    def _validate_sla_hours(cls, v: int | None) -> int | None:
        return _clean_sla_hours(v)


class OutboxEmailView(BaseModel):
    id: UUID
    to_email: str
    subject: str
    event_type: str
    status: str
    attempts: int
    last_error: str | None
    related_ticket_id: UUID | None
    created_at: datetime
    sent_at: datetime | None


class OutboxResponse(BaseModel):
    emails: list[OutboxEmailView]


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


def _row_to_view(row: TicketRoutingRule) -> RoutingRuleView:
    return RoutingRuleView(
        id=row.id,
        category_code=row.category_code,
        notify_email=row.notify_email,
        assignee_user_id=row.assignee_user_id,
        sla_hours=row.sla_hours,
        is_active=row.is_active,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _load_for_tenant(
    session: AsyncSession, tenant_id: UUID, rule_id: UUID
) -> TicketRoutingRule:
    row = await session.get(TicketRoutingRule, rule_id)
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Yönlendirme kuralı bulunamadı",
        )
    return row


def _duplicate_conflict() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Bu kategori için zaten bir yönlendirme kuralı var",
    )


async def _record_rule_decision(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    rule: TicketRoutingRule,
    actor_user_id: UUID,
    action: str,
    request: Request,
    changed_fields: list[str] | None = None,
) -> None:
    # decision_audit_log.decision_type migration 0027 CHECK'ine bağlı —
    # yeni tip eklemek yerine tenant policy şemsiyesi altında loglanır;
    # entity_type ayrıştırmayı sağlar.
    payload: dict[str, object] = {
        "setting": "ticket_routing_rule",
        "action": action,
        "category_code": rule.category_code,
    }
    if changed_fields is not None:
        payload["changed_fields"] = sorted(changed_fields)
    await DecisionAuditService(session).record_decision(
        tenant_id=tenant_id,
        decision_type=DECISION_TENANT_SETTING_CHANGED,
        related_entity_type="ticket_routing_rule",
        related_entity_id=rule.id,
        actor_user_id=actor_user_id,
        payload=payload,
        request_id=getattr(request.state, "request_id", None),
    )


# --------------------------------------------------------------------- #
# Endpoints                                                             #
# --------------------------------------------------------------------- #


@router.get(
    "",
    response_model=RoutingRulesResponse,
    summary="List the active tenant's ticket routing rules.",
)
async def list_routing_rules(
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    include_inactive: bool = False,
) -> RoutingRulesResponse:
    tenant_id = _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        stmt = select(TicketRoutingRule).where(
            TicketRoutingRule.tenant_id == tenant_id
        )
        if not include_inactive:
            stmt = stmt.where(TicketRoutingRule.is_active.is_(True))
        stmt = stmt.order_by(TicketRoutingRule.created_at)
        rows = (await app_session.execute(stmt)).scalars().all()
    return RoutingRulesResponse(rules=[_row_to_view(r) for r in rows])


@router.post(
    "",
    response_model=RoutingRuleView,
    status_code=status.HTTP_201_CREATED,
    summary="Create a routing rule for a category.",
    responses={409: {"description": "Kategori için kural zaten var."}},
)
async def create_routing_rule(
    body: RoutingRuleCreateRequest,
    request: Request,
    current: Annotated[CurrentUser, _AdminOnly],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> RoutingRuleView:
    tenant_id = _require_active_tenant(current)
    try:
        async with app_session.begin():
            await bind_tenant(app_session, current)
            row = TicketRoutingRule(
                tenant_id=tenant_id,
                category_code=body.category_code,
                notify_email=body.notify_email,
                assignee_user_id=body.assignee_user_id,
                sla_hours=body.sla_hours,
                is_active=body.is_active,
            )
            app_session.add(row)
            await app_session.flush()
            # refresh server-computed ``updated_at`` inside the async
            # greenlet so _row_to_view doesn't trigger a lazy reload via
            # SQLAlchemy's sync path (MissingGreenlet).
            await app_session.refresh(row, ["updated_at"])
            await _record_rule_decision(
                app_session,
                tenant_id=tenant_id,
                rule=row,
                actor_user_id=current.user_id,
                action="created",
                request=request,
            )
            response = _row_to_view(row)
        return response
    except IntegrityError as exc:
        raise _duplicate_conflict() from exc
    except HTTPException:
        raise
    except Exception:
        _logger.exception(
            "create_routing_rule failed",
            extra={
                "tenant_id": str(tenant_id),
                "category_code": body.category_code,
            },
        )
        raise


@router.patch(
    "/{rule_id}",
    response_model=RoutingRuleView,
    summary="Edit fields on a routing rule.",
)
async def update_routing_rule(
    rule_id: UUID,
    body: RoutingRuleUpdateRequest,
    request: Request,
    current: Annotated[CurrentUser, _AdminOnly],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> RoutingRuleView:
    tenant_id = _require_active_tenant(current)
    try:
        async with app_session.begin():
            await bind_tenant(app_session, current)
            row = await _load_for_tenant(app_session, tenant_id, rule_id)
            data = body.model_dump(exclude_unset=True)
            for key, value in data.items():
                setattr(row, key, value)
            await app_session.flush()
            # refresh server-computed ``updated_at`` inside the async
            # greenlet — MissingGreenlet workaround (tenant_sla_rules).
            await app_session.refresh(row, ["updated_at"])
            await _record_rule_decision(
                app_session,
                tenant_id=tenant_id,
                rule=row,
                actor_user_id=current.user_id,
                action="updated",
                request=request,
                changed_fields=list(data.keys()),
            )
            response = _row_to_view(row)
        return response
    except IntegrityError as exc:
        raise _duplicate_conflict() from exc
    except HTTPException:
        raise
    except Exception:
        _logger.exception(
            "update_routing_rule failed",
            extra={"tenant_id": str(tenant_id), "rule_id": str(rule_id)},
        )
        raise


@router.delete(
    "/{rule_id}",
    response_model=RoutingRuleView,
    summary="Soft delete a routing rule (is_active=false).",
)
async def delete_routing_rule(
    rule_id: UUID,
    request: Request,
    current: Annotated[CurrentUser, _AdminOnly],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> RoutingRuleView:
    tenant_id = _require_active_tenant(current)
    try:
        async with app_session.begin():
            await bind_tenant(app_session, current)
            row = await _load_for_tenant(app_session, tenant_id, rule_id)
            row.is_active = False
            await app_session.flush()
            # refresh server-computed ``updated_at`` inside the async
            # greenlet — MissingGreenlet workaround (tenant_sla_rules).
            await app_session.refresh(row, ["updated_at"])
            await _record_rule_decision(
                app_session,
                tenant_id=tenant_id,
                rule=row,
                actor_user_id=current.user_id,
                action="deactivated",
                request=request,
            )
            response = _row_to_view(row)
        return response
    except HTTPException:
        raise
    except Exception:
        _logger.exception(
            "delete_routing_rule failed",
            extra={"tenant_id": str(tenant_id), "rule_id": str(rule_id)},
        )
        raise


@router.get(
    "/outbox",
    response_model=OutboxResponse,
    summary="Recent queued/sent notification emails (admin only).",
)
async def list_outbox(
    current: Annotated[CurrentUser, _AdminOnly],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    limit: int = 50,
) -> OutboxResponse:
    tenant_id = _require_active_tenant(current)
    limit = max(1, min(limit, 200))
    async with app_session.begin():
        await bind_tenant(app_session, current)
        stmt = (
            select(EmailOutbox)
            .where(EmailOutbox.tenant_id == tenant_id)
            .order_by(EmailOutbox.created_at.desc())
            .limit(limit)
        )
        rows = (await app_session.execute(stmt)).scalars().all()
    return OutboxResponse(
        emails=[
            OutboxEmailView(
                id=r.id,
                to_email=r.to_email,
                subject=r.subject,
                event_type=str(r.event_type),
                status=str(r.status),
                attempts=r.attempts,
                last_error=r.last_error,
                related_ticket_id=r.related_ticket_id,
                created_at=r.created_at,
                sent_at=r.sent_at,
            )
            for r in rows
        ]
    )
