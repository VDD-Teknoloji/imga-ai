"""``/tenants/me/pending-webhooks`` — manual SLA webhook dispatch queue.

Sprint 9.0. Lists queued webhook events (when the tenant is on
``sla_webhook_dispatch_mode='manual'``) and lets the operator approve
or dismiss them. The approve path runs the dispatcher synchronously
so the operator gets immediate 502 / 200 feedback in-page.

logger.exception() in every catch path — Sprint 8.3.6.6 round-3
baseline note.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from imga_db.models import (
    PendingWebhookStatus,
    SlaWebhookDispatchMode,
    Tenant,
    UserTenantRole,
)
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import CurrentUser, bind_tenant, require_role
from imga_api.db_deps import get_app_session
from imga_api.services import AuditService
from imga_api.services.pending_webhook_service import (
    PendingWebhookNotActionableError,
    PendingWebhookNotFoundError,
    PendingWebhookService,
)
from imga_api.services.webhook_dispatcher import WebhookDispatchError

_logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/tenants/me/pending-webhooks",
    tags=["Pending Webhooks"],
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
_TenantAdmin = Depends(require_role(UserTenantRole.TENANT_ADMIN))


# --- response models ---------------------------------------------------


class PendingWebhookView(BaseModel):
    id: UUID
    sla_rule_id: UUID | None
    review_id: UUID | None
    webhook_target: str
    channel: str | None
    payload: dict[str, Any]
    status: str
    retry_count: int
    last_error: str | None
    created_at: datetime
    sent_at: datetime | None
    dismissed_at: datetime | None


class PendingWebhookListResponse(BaseModel):
    events: list[PendingWebhookView]
    # Sprint 9.0.5-B B — pagination metadata for the
    # /pending-webhooks page; ``total`` reflects the row count
    # under the same status_filter, not the whole table.
    total: int = 0
    page: int = 1
    page_size: int = 100


class DispatchModeResponse(BaseModel):
    sla_webhook_dispatch_mode: str


class DispatchModeUpdate(BaseModel):
    sla_webhook_dispatch_mode: SlaWebhookDispatchMode


# --- helpers -----------------------------------------------------------


def _require_active_tenant(current: CurrentUser) -> UUID:
    if current.active_tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="active tenant context required for this endpoint",
        )
    return current.active_tenant_id


def _to_view(row: Any) -> PendingWebhookView:
    return PendingWebhookView(
        id=row.id,
        sla_rule_id=row.sla_rule_id,
        review_id=row.review_id,
        webhook_target=str(row.webhook_target),
        channel=row.channel,
        payload=dict(row.payload or {}),
        status=str(row.status),
        retry_count=row.retry_count,
        last_error=row.last_error,
        created_at=row.created_at,
        sent_at=row.sent_at,
        dismissed_at=row.dismissed_at,
    )


def _client_ip(request: Request) -> str | None:
    if request.client is None:
        return None
    return request.client.host


# --- endpoints ---------------------------------------------------------


@router.get(
    "/dispatch-mode",
    response_model=DispatchModeResponse,
    summary="Get the tenant's SLA webhook dispatch mode.",
)
async def get_dispatch_mode(
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> DispatchModeResponse:
    tenant_id = _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        tenant = await app_session.get(Tenant, tenant_id)
        if tenant is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="tenant not found"
            )
        return DispatchModeResponse(
            sla_webhook_dispatch_mode=str(tenant.sla_webhook_dispatch_mode),
        )


@router.patch(
    "/dispatch-mode",
    response_model=DispatchModeResponse,
    summary="Update the tenant's SLA webhook dispatch mode (admin only).",
    description=(
        "automatic: SLA webhook hits fire httpx.post immediately on "
        "match (default).  manual: matches queue rows in pending_webhook_"
        "events; an operator approves / dismisses each one from this "
        "page."
    ),
)
async def update_dispatch_mode(
    body: DispatchModeUpdate,
    request: Request,
    current: Annotated[CurrentUser, _TenantAdmin],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> DispatchModeResponse:
    tenant_id = _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        tenant = await app_session.get(Tenant, tenant_id)
        if tenant is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="tenant not found"
            )
        prev = tenant.sla_webhook_dispatch_mode
        tenant.sla_webhook_dispatch_mode = body.sla_webhook_dispatch_mode
        audit = AuditService(app_session)
        await audit.log(
            action="tenant.sla_webhook_dispatch_mode.updated",
            resource_type="tenant",
            resource_id=tenant_id,
            tenant_id=tenant_id,
            actor_user_id=current.user_id,
            ip_address=_client_ip(request),
            details={
                "previous": str(prev),
                "next": str(body.sla_webhook_dispatch_mode),
            },
        )
    return DispatchModeResponse(
        sla_webhook_dispatch_mode=str(body.sla_webhook_dispatch_mode),
    )


@router.get(
    "",
    response_model=PendingWebhookListResponse,
    summary="List queued webhook events (newest first).",
)
async def list_pending_webhooks(
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    status_filter: str | None = None,
    limit: int = 100,
    page: int = 1,
) -> PendingWebhookListResponse:
    tenant_id = _require_active_tenant(current)
    if not 1 <= limit <= 500:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="limit 1..500 olmalı",
        )
    if page < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="page 1'den küçük olamaz",
        )
    parsed_status: PendingWebhookStatus | None = None
    if status_filter is not None:
        try:
            parsed_status = PendingWebhookStatus(status_filter)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"unknown status_filter={status_filter!r}",
            ) from exc

    offset = (page - 1) * limit
    async with app_session.begin():
        await bind_tenant(app_session, current)
        audit = AuditService(app_session)
        service = PendingWebhookService(app_session, audit)
        total = await service.count_events(
            tenant_id=tenant_id,
            status_filter=parsed_status,
        )
        rows = await service.list_events(
            tenant_id=tenant_id,
            status_filter=parsed_status,
            limit=limit,
            offset=offset,
        )
        views = [_to_view(r) for r in rows]
    return PendingWebhookListResponse(
        events=views,
        total=total,
        page=page,
        page_size=limit,
    )


@router.post(
    "/{event_id}/approve",
    response_model=PendingWebhookView,
    summary="Approve and dispatch a queued webhook.",
    description=(
        "Calls the dispatcher synchronously. Returns 502 when the "
        "destination (Slack / Teams) responds non-2xx; the row flips "
        "to ``failed`` with last_error populated so the operator can "
        "retry after fixing the upstream config."
    ),
    responses={
        404: {"description": "Pending webhook not found."},
        409: {"description": "Already in a terminal state."},
        502: {"description": "Webhook destination returned non-2xx."},
    },
)
async def approve_pending_webhook(
    event_id: UUID,
    request: Request,
    current: Annotated[CurrentUser, _WriteMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> PendingWebhookView:
    _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        audit = AuditService(app_session)
        service = PendingWebhookService(app_session, audit)
        try:
            event = await service.approve_event(
                event_id=event_id,
                actor_user_id=current.user_id,
                ip_address=_client_ip(request),
            )
        except PendingWebhookNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="pending webhook not found",
            ) from exc
        except PendingWebhookNotActionableError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=str(exc)
            ) from exc
        except WebhookDispatchError as exc:
            # Dispatcher already flipped the row to FAILED + persisted
            # last_error before raising; surface a 502 so the UI shows
            # the network-side issue.
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
            ) from exc
        return _to_view(event)


@router.post(
    "/{event_id}/dispatch",
    response_model=PendingWebhookView,
    summary="Sprint 9.0.5-B B alias for approve — dispatch a queued webhook.",
    description=(
        "Identical behaviour to ``/{id}/approve``. The frontend "
        "/pending-webhooks page uses this name because it matches "
        "the operator's mental model (\"dispatch this webhook\")."
    ),
    responses={
        404: {"description": "Pending webhook not found."},
        409: {"description": "Already in a terminal state."},
        502: {"description": "Webhook destination returned non-2xx."},
    },
)
async def dispatch_pending_webhook(
    event_id: UUID,
    request: Request,
    current: Annotated[CurrentUser, _WriteMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> PendingWebhookView:
    return await approve_pending_webhook(
        event_id, request, current, app_session,
    )


@router.post(
    "/{event_id}/cancel",
    response_model=PendingWebhookView,
    summary="Sprint 9.0.5-B B alias for dismiss — cancel a queued webhook.",
    responses={
        404: {"description": "Pending webhook not found."},
        409: {"description": "Already in a terminal state."},
    },
)
async def cancel_pending_webhook(
    event_id: UUID,
    request: Request,
    current: Annotated[CurrentUser, _WriteMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> PendingWebhookView:
    return await dismiss_pending_webhook(
        event_id, request, current, app_session,
    )


@router.post(
    "/{event_id}/dismiss",
    response_model=PendingWebhookView,
    summary="Dismiss a queued or failed webhook without dispatching.",
    responses={
        404: {"description": "Pending webhook not found."},
        409: {"description": "Already in a terminal state."},
    },
)
async def dismiss_pending_webhook(
    event_id: UUID,
    request: Request,
    current: Annotated[CurrentUser, _WriteMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> PendingWebhookView:
    _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        audit = AuditService(app_session)
        service = PendingWebhookService(app_session, audit)
        try:
            event = await service.dismiss_event(
                event_id=event_id,
                actor_user_id=current.user_id,
                ip_address=_client_ip(request),
            )
        except PendingWebhookNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="pending webhook not found",
            ) from exc
        except PendingWebhookNotActionableError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=str(exc)
            ) from exc
        return _to_view(event)
