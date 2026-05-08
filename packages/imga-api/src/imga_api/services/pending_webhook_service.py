"""PendingWebhookService — manual SLA webhook dispatch queue.

Sprint 9.0. When ``tenant.sla_webhook_dispatch_mode == 'manual'`` the
SLA engine routes matched rules through ``queue_event`` instead of
firing httpx.post directly. The /pending-webhooks page lists rows in
the ``pending`` status; the operator clicks Approve (``approve_event``
runs the dispatcher synchronously and flips the row to ``sent``) or
Dismiss (``dismiss_event`` flips it to ``dismissed`` without sending).

logger.exception() in every catch path — Sprint 8.3.6.6 round-3
baseline note.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from imga_db.models import (
    PendingWebhookEvent,
    PendingWebhookStatus,
    PendingWebhookTarget,
)
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.services.audit_service import AuditService
from imga_api.services.webhook_dispatcher import (
    SlaWebhookPayload,
    WebhookDispatcher,
    WebhookDispatchError,
)

_logger = logging.getLogger(__name__)


class PendingWebhookError(Exception):
    """Generic pending-webhook service failure."""


class PendingWebhookNotFoundError(PendingWebhookError):
    """Event missing or hidden by RLS."""


class PendingWebhookNotActionableError(PendingWebhookError):
    """Caller tried to approve / dismiss a row that's already in a
    terminal state (sent / dismissed)."""


class PendingWebhookService:
    """Queue + dispatch operations on ``pending_webhook_events``.

    Tenant-scoped via the same RLS+FORCE pattern as every other
    tenant-owned table; the caller binds ``app.current_tenant_id``
    before calling into the service. The dispatcher is injectable for
    tests so a respx mock transport can capture the actual POST.
    """

    def __init__(
        self,
        session: AsyncSession,
        audit: AuditService,
        dispatcher: WebhookDispatcher | None = None,
    ) -> None:
        self._session = session
        self._audit = audit
        self._dispatcher = dispatcher or WebhookDispatcher()

    # ------------------------------------------------------------------
    # Queue (called from the SLA engine)
    # ------------------------------------------------------------------

    async def queue_event(
        self,
        *,
        tenant_id: UUID,
        sla_rule_id: UUID | None,
        review_id: UUID | None,
        target: PendingWebhookTarget,
        webhook_url: str,
        channel: str | None,
        payload: SlaWebhookPayload,
    ) -> PendingWebhookEvent:
        """Persist a queued webhook hit. Returns the freshly inserted
        row so the caller can reference its id in audit logs.

        ``payload`` is snapshotted as a JSONB blob so the operator
        review survives later edits to the source review or rule.
        """
        event = PendingWebhookEvent(
            tenant_id=tenant_id,
            sla_rule_id=sla_rule_id,
            review_id=review_id,
            webhook_target=target,
            webhook_url=webhook_url,
            channel=channel,
            payload=_payload_to_dict(payload),
            status=PendingWebhookStatus.PENDING,
        )
        self._session.add(event)
        await self._session.flush()
        return event

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def list_events(
        self,
        *,
        tenant_id: UUID,
        status_filter: PendingWebhookStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[PendingWebhookEvent]:
        stmt = (
            select(PendingWebhookEvent)
            .where(PendingWebhookEvent.tenant_id == tenant_id)
            .order_by(desc(PendingWebhookEvent.created_at))
            .limit(limit)
            .offset(max(0, offset))
        )
        if status_filter is not None:
            stmt = stmt.where(PendingWebhookEvent.status == status_filter)
        return list((await self._session.execute(stmt)).scalars().all())

    async def count_events(
        self,
        *,
        tenant_id: UUID,
        status_filter: PendingWebhookStatus | None = None,
    ) -> int:
        """Sprint 9.0.5-B B — total count for pagination metadata.
        Same WHERE shape as list_events sans pagination."""
        from sqlalchemy import func

        stmt = (
            select(func.count())
            .select_from(PendingWebhookEvent)
            .where(PendingWebhookEvent.tenant_id == tenant_id)
        )
        if status_filter is not None:
            stmt = stmt.where(PendingWebhookEvent.status == status_filter)
        return int((await self._session.execute(stmt)).scalar_one() or 0)

    async def get_event(self, event_id: UUID) -> PendingWebhookEvent:
        row = await self._session.get(PendingWebhookEvent, event_id)
        if row is None:
            raise PendingWebhookNotFoundError(
                f"pending webhook {event_id} not found"
            )
        return row

    # ------------------------------------------------------------------
    # Operator actions
    # ------------------------------------------------------------------

    async def approve_event(
        self,
        *,
        event_id: UUID,
        actor_user_id: UUID,
        ip_address: str | None = None,
    ) -> PendingWebhookEvent:
        """Dispatch the queued webhook synchronously and mark sent.

        Raises PendingWebhookNotActionableError when the row is no
        longer pending (already sent / dismissed). On dispatcher
        failure the row flips to ``failed`` with ``last_error`` so
        the operator sees what went wrong; the exception is
        re-raised so the route returns 502.
        """
        event = await self.get_event(event_id)
        if event.status != PendingWebhookStatus.PENDING:
            raise PendingWebhookNotActionableError(
                f"pending webhook {event_id} already in state {event.status}"
            )
        payload = _payload_from_dict(dict(event.payload))
        try:
            if event.webhook_target == PendingWebhookTarget.SLACK:
                await self._dispatcher.dispatch_slack(
                    event.webhook_url, payload, channel=event.channel,
                )
            else:
                await self._dispatcher.dispatch_teams(
                    event.webhook_url, payload,
                )
        except WebhookDispatchError as exc:
            event.status = PendingWebhookStatus.FAILED
            event.retry_count = (event.retry_count or 0) + 1
            event.last_error = str(exc)[:2048]
            await self._session.flush()
            _logger.exception(
                "pending_webhook approve failed",
                extra={
                    "event_id": str(event.id),
                    "tenant_id": str(event.tenant_id),
                },
            )
            raise

        event.status = PendingWebhookStatus.SENT
        event.sent_at = datetime.now(UTC)
        event.last_error = None
        await self._session.flush()
        await self._audit.log(
            action="pending_webhook.approved",
            resource_type="pending_webhook",
            resource_id=event.id,
            tenant_id=event.tenant_id,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            details={
                "target": str(event.webhook_target),
                "rule_id": (
                    str(event.sla_rule_id)
                    if event.sla_rule_id is not None
                    else None
                ),
            },
        )
        return event

    async def dismiss_event(
        self,
        *,
        event_id: UUID,
        actor_user_id: UUID,
        ip_address: str | None = None,
    ) -> PendingWebhookEvent:
        event = await self.get_event(event_id)
        if event.status not in (
            PendingWebhookStatus.PENDING,
            PendingWebhookStatus.FAILED,
        ):
            raise PendingWebhookNotActionableError(
                f"pending webhook {event_id} already in state {event.status}"
            )
        event.status = PendingWebhookStatus.DISMISSED
        event.dismissed_at = datetime.now(UTC)
        event.dismissed_by_user_id = actor_user_id
        await self._session.flush()
        await self._audit.log(
            action="pending_webhook.dismissed",
            resource_type="pending_webhook",
            resource_id=event.id,
            tenant_id=event.tenant_id,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
        )
        return event


def _payload_to_dict(payload: SlaWebhookPayload) -> dict[str, Any]:
    """Snapshot the dataclass into a JSONB-safe dict."""
    return dict(asdict(payload))


def _payload_from_dict(data: dict[str, Any]) -> SlaWebhookPayload:
    """Re-hydrate a JSONB-stored payload back into the dispatcher's
    expected type. Defensive coercion: missing fields fall back to
    sane defaults so a partially-stored payload still dispatches."""
    return SlaWebhookPayload(
        rule_name=str(data.get("rule_name") or ""),
        review_text=str(data.get("review_text") or ""),
        review_id=str(data.get("review_id") or ""),
        taxonomy_label=data.get("taxonomy_label"),
        elapsed_minutes=data.get("elapsed_minutes"),
        threshold_minutes=data.get("threshold_minutes"),
        severity=str(data.get("severity") or "warning"),
    )


__all__ = [
    "PendingWebhookError",
    "PendingWebhookNotActionableError",
    "PendingWebhookNotFoundError",
    "PendingWebhookService",
]
