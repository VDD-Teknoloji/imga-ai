"""arq cron — email_outbox dispatcher + SLA ihlal taraması.

İki tick (arq_worker.py kayıtları):

  * ``email_outbox_tick`` (2 dk) — ``status='pending' AND
    next_attempt_at <= now()`` satırlarını (LIMIT 20) SMTP ile
    gönderir. Hata → attempts+1 + lineer backoff (5 dk * attempts);
    5. denemede ``failed``. SMTP yapılandırılmamışsa tek log + çıkış
    — satırlar pending kalır, SMTP gelince kendiliğinden akar.

  * ``sla_breach_tick`` (15 dk) — ``sla_hours`` dolu aktif yönlendirme
    kurallarının kategorisindeki OPEN / IN_PROGRESS ticket'lardan
    ``opened_at`` eşiği aşanları bulur ve ticket başına EN FAZLA BİR
    'sla_breach' outbox satırı enqueue eder (NOT EXISTS koruması —
    tick idempotent).

scheduled_briefings tick deseni: admin (BYPASSRLS) session ile
cross-tenant tarama, öğe başına ayrı session + ayrı try/except ki bir
tenant'ın hatası diğerlerini bozmasın.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from imga_db.models import (
    Category,
    EmailOutbox,
    EmailOutboxEventType,
    EmailOutboxStatus,
    Tenant,
    Ticket,
    TicketRoutingRule,
    TicketState,
)
from sqlalchemy import and_, exists, func, or_, select

from imga_api.services import email_sender
from imga_api.services.ticket_routing_service import build_sla_breach_email

_logger = logging.getLogger("imga-api.workers.email_outbox")

_DISPATCH_BATCH_LIMIT = 20
_MAX_ATTEMPTS = 5
_RETRY_BACKOFF = timedelta(minutes=5)


async def email_outbox_tick(ctx: dict[str, Any]) -> None:
    """arq cron entry — 2 dakikada bir pending e-postaları gönderir."""
    worker_context = ctx.get("worker_context")
    if worker_context is None:
        _logger.warning(
            "email outbox tick: worker_context missing; "
            "the cron fired before startup completed"
        )
        return
    if not email_sender.is_configured():
        _logger.info(
            "email outbox tick: SMTP not configured (IMGA_SMTP_HOST empty); "
            "leaving pending rows untouched"
        )
        return

    factory = worker_context.admin_session_factory
    async with factory() as session, session.begin():
        stmt = (
            select(EmailOutbox.id)
            .where(EmailOutbox.status == EmailOutboxStatus.PENDING)
            .where(EmailOutbox.next_attempt_at <= func.now())
            .order_by(EmailOutbox.next_attempt_at)
            .limit(_DISPATCH_BATCH_LIMIT)
        )
        due_ids = list((await session.execute(stmt)).scalars())
    if not due_ids:
        return
    _logger.info("email outbox tick: %d email(s) due", len(due_ids))

    for outbox_id in due_ids:
        try:
            await _dispatch_one(factory, outbox_id)
        except Exception:
            _logger.exception(
                "email outbox dispatch failed",
                extra={"outbox_id": str(outbox_id)},
            )


async def _dispatch_one(factory: Any, outbox_id: UUID) -> None:
    """Tek satırı kendi session'ında gönder — bir satırın DB hatası
    diğer satırların muhasebesini geri almasın."""
    async with factory() as session, session.begin():
        row = await session.get(EmailOutbox, outbox_id)
        if row is None or row.status != EmailOutboxStatus.PENDING:
            return
        try:
            await email_sender.send_email(
                to_email=row.to_email,
                subject=row.subject,
                body_text=row.body_text,
            )
        except Exception as exc:
            row.attempts += 1
            row.last_error = str(exc)[:2048]
            row.next_attempt_at = (
                datetime.now(UTC) + _RETRY_BACKOFF * row.attempts
            )
            if row.attempts >= _MAX_ATTEMPTS:
                row.status = EmailOutboxStatus.FAILED
            _logger.exception(
                "email outbox send failed",
                extra={
                    "outbox_id": str(row.id),
                    "tenant_id": str(row.tenant_id),
                    "attempts": row.attempts,
                },
            )
        else:
            row.status = EmailOutboxStatus.SENT
            row.sent_at = datetime.now(UTC)


async def sla_breach_tick(ctx: dict[str, Any]) -> None:
    """arq cron entry — 15 dakikada bir SLA eşiği aşılmış ticket'lara
    'sla_breach' outbox satırı enqueue eder (ticket başına tek satır)."""
    worker_context = ctx.get("worker_context")
    if worker_context is None:
        _logger.warning(
            "sla breach tick: worker_context missing; "
            "the cron fired before startup completed"
        )
        return

    factory = worker_context.admin_session_factory
    async with factory() as session, session.begin():
        breach_seen = (
            select(EmailOutbox.id)
            .where(EmailOutbox.related_ticket_id == Ticket.id)
            .where(
                EmailOutbox.event_type == EmailOutboxEventType.SLA_BREACH
            )
        )
        # Kategori eşleşmesi kod üzerinden: kural code saklar, ticket
        # id — global ya da kuralın tenant'ına ait custom kategori
        # satırı üzerinden join'lenir.
        stmt = (
            select(
                TicketRoutingRule.notify_email,
                TicketRoutingRule.sla_hours,
                Ticket.id.label("ticket_id"),
                Ticket.tenant_id,
                Ticket.title,
                Ticket.summary,
                Ticket.priority,
                Tenant.language,
                Category.label_tr,
                Category.label_en,
                Category.code,
            )
            .join(Tenant, Tenant.id == TicketRoutingRule.tenant_id)
            .join(
                Category,
                and_(
                    Category.code == TicketRoutingRule.category_code,
                    or_(
                        Category.tenant_id == TicketRoutingRule.tenant_id,
                        Category.tenant_id.is_(None),
                    ),
                ),
            )
            .join(
                Ticket,
                and_(
                    Ticket.tenant_id == TicketRoutingRule.tenant_id,
                    Ticket.category_id == Category.id,
                ),
            )
            .where(TicketRoutingRule.is_active.is_(True))
            .where(TicketRoutingRule.sla_hours.is_not(None))
            .where(
                Ticket.state.in_(
                    [TicketState.OPEN, TicketState.IN_PROGRESS]
                )
            )
            .where(Ticket.deleted_at.is_(None))
            .where(
                Ticket.opened_at
                <= func.now()
                - func.make_interval(
                    0, 0, 0, 0, TicketRoutingRule.sla_hours
                )
            )
            .where(~exists(breach_seen))
        )
        overdue = (await session.execute(stmt)).all()
    if not overdue:
        return
    _logger.info("sla breach tick: %d overdue ticket(s)", len(overdue))

    for hit in overdue:
        try:
            await _enqueue_breach(factory, hit)
        except Exception:
            _logger.exception(
                "sla breach enqueue failed",
                extra={
                    "ticket_id": str(hit.ticket_id),
                    "tenant_id": str(hit.tenant_id),
                },
            )


async def _enqueue_breach(factory: Any, hit: Any) -> None:
    sla_hours = int(hit.sla_hours)
    language = str(hit.language)
    label = (
        hit.label_en
        if language == "en" and hit.label_en
        else hit.label_tr
    ) or str(hit.code)
    subject, body = build_sla_breach_email(
        language=language,
        category_label=label,
        title=hit.title,
        summary=hit.summary,
        priority=str(hit.priority),
        ticket_id=hit.ticket_id,
        sla_hours=sla_hours,
    )
    async with factory() as session, session.begin():
        # Tarama ile enqueue arası yarışa karşı ikinci NOT EXISTS
        # kontrolü — tick üst üste binse de ticket başına tek satır.
        dupe = (
            await session.execute(
                select(EmailOutbox.id)
                .where(EmailOutbox.related_ticket_id == hit.ticket_id)
                .where(
                    EmailOutbox.event_type
                    == EmailOutboxEventType.SLA_BREACH
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if dupe is not None:
            return
        session.add(
            EmailOutbox(
                tenant_id=hit.tenant_id,
                to_email=hit.notify_email,
                subject=subject,
                body_text=body,
                event_type=EmailOutboxEventType.SLA_BREACH,
                related_ticket_id=hit.ticket_id,
            )
        )


__all__ = [
    "email_outbox_tick",
    "sla_breach_tick",
]
