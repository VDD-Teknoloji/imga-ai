"""Kategori bazlı ticket yönlendirme motoru.

Ticket mint eden üç yol da (tekil /analyze, batch worker, manuel
promote) ReviewService üzerinden geçer; ReviewService ticket create
sonrası buradaki ``resolve_rule`` + ``apply_routing`` çiftini çağırır.

``apply_routing`` iki iş yapar:

  1. Kuralda assignee varsa ve kullanıcı hâlâ kurum üyesiyse ticket'a
     atar (timeline'a ``TicketAssignmentEvent`` düşer). Üyelikten
     çıkmış assignee sessizce loglanıp atlanır — kural bayat diye
     ticket mint'i bozulmaz.
  2. ``email_outbox``'a 'ticket_opened' satırı enqueue eder; gönderim
     arq dispatcher'ında (workers/email_outbox_worker.py) asenkron.

E-posta içeriği tenant.language'e göre TR/EN üretilir ve enqueue
anında snapshot'lanır.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from uuid import UUID

from imga_db.models import (
    Category,
    EmailOutbox,
    EmailOutboxEventType,
    Tenant,
    Ticket,
    TicketAssignmentEvent,
    TicketRoutingRule,
    UserTenantLink,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.services.ticket_service import TicketService

_logger = logging.getLogger(__name__)

_SUBJECT_TITLE_MAX = 60
_BODY_EXCERPT_MAX = 300

_PRIORITY_LABELS_TR = {
    "low": "Düşük",
    "normal": "Normal",
    "high": "Yüksek",
    "urgent": "Acil",
}
_PRIORITY_LABELS_EN = {
    "low": "Low",
    "normal": "Normal",
    "high": "High",
    "urgent": "Urgent",
}


def _app_base_url() -> str:
    return (
        os.environ.get("IMGA_APP_BASE_URL", "").strip().rstrip("/")
        or "https://app.imga.ai"
    )


def _ticket_link(ticket_id: UUID) -> str:
    return f"{_app_base_url()}/tickets/{ticket_id}"


def _clip(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[:limit]


def build_ticket_opened_email(
    *,
    language: str,
    category_label: str,
    title: str,
    summary: str | None,
    priority: str,
    ticket_id: UUID,
) -> tuple[str, str]:
    """(subject, body_text) — 'ticket_opened' bildirimi."""
    short_title = _clip(title, _SUBJECT_TITLE_MAX)
    excerpt = _clip(summary or title, _BODY_EXCERPT_MAX)
    link = _ticket_link(ticket_id)
    if language == "en":
        subject = f"[İmga] New Ticket: {category_label} — {short_title}"
        body = (
            f"Category: {category_label}\n"
            f"Priority: {_PRIORITY_LABELS_EN.get(priority, priority)}\n"
            f"Summary: {excerpt}\n"
            f"\n"
            f"Ticket link: {link}\n"
        )
    else:
        subject = f"[İmga] Yeni Ticket: {category_label} — {short_title}"
        body = (
            f"Kategori: {category_label}\n"
            f"Öncelik: {_PRIORITY_LABELS_TR.get(priority, priority)}\n"
            f"Özet: {excerpt}\n"
            f"\n"
            f"Ticket bağlantısı: {link}\n"
        )
    return subject, body


def build_sla_breach_email(
    *,
    language: str,
    category_label: str,
    title: str,
    summary: str | None,
    priority: str,
    ticket_id: UUID,
    sla_hours: int,
) -> tuple[str, str]:
    """(subject, body_text) — 'sla_breach' bildirimi."""
    short_title = _clip(title, _SUBJECT_TITLE_MAX)
    excerpt = _clip(summary or title, _BODY_EXCERPT_MAX)
    link = _ticket_link(ticket_id)
    if language == "en":
        subject = f"[İmga] SLA Breach: {category_label} — {short_title}"
        body = (
            f"The ticket below has been open for more than "
            f"{sla_hours} hour(s) without resolution.\n"
            f"\n"
            f"Category: {category_label}\n"
            f"Priority: {_PRIORITY_LABELS_EN.get(priority, priority)}\n"
            f"Summary: {excerpt}\n"
            f"\n"
            f"Ticket link: {link}\n"
        )
    else:
        subject = f"[İmga] SLA Aşımı: {category_label} — {short_title}"
        body = (
            f"Aşağıdaki ticket {sla_hours} saatlik SLA eşiğini aşmasına "
            f"rağmen hâlâ çözülmedi.\n"
            f"\n"
            f"Kategori: {category_label}\n"
            f"Öncelik: {_PRIORITY_LABELS_TR.get(priority, priority)}\n"
            f"Özet: {excerpt}\n"
            f"\n"
            f"Ticket bağlantısı: {link}\n"
        )
    return subject, body


def category_label_for_language(
    category: Category | None, *, language: str, fallback: str
) -> str:
    if category is None:
        return fallback
    if language == "en" and category.label_en:
        return category.label_en
    return category.label_tr


async def resolve_rule(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    category_code: str,
) -> TicketRoutingRule | None:
    """Aktif yönlendirme kuralını döndür; yoksa None. RLS bağlı app
    session'da politika zaten filtreler; explicit tenant filtresi
    admin-session çağrıları için de doğru sonucu garantiler."""
    stmt = (
        select(TicketRoutingRule)
        .where(TicketRoutingRule.tenant_id == tenant_id)
        .where(TicketRoutingRule.category_code == category_code)
        .where(TicketRoutingRule.is_active.is_(True))
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def apply_routing(
    session: AsyncSession,
    *,
    tenant: Tenant,
    ticket: Ticket,
    category_code: str,
    rule: TicketRoutingRule,
    ticket_service: TicketService,
) -> None:
    """Kuralı yeni mint edilmiş ticket'a uygula: opsiyonel atama +
    'ticket_opened' outbox satırı. Çağıranın transaction'ı içinde
    koşar; commit sınırı route/worker'da kalır."""
    if rule.assignee_user_id is not None:
        membership = await session.get(
            UserTenantLink, (rule.assignee_user_id, tenant.id)
        )
        if membership is None:
            # Kural bayatlamış (assignee kurumdan çıkarılmış) —
            # atamayı atla, e-posta yine gitsin.
            _logger.info(
                "ticket routing: assignee %s is no longer a member of "
                "tenant %s; skipping assignment for ticket %s",
                rule.assignee_user_id,
                tenant.id,
                ticket.id,
            )
        elif ticket.created_by_user_id is not None:
            await ticket_service.assign(
                ticket_id=ticket.id,
                new_assignee_id=rule.assignee_user_id,
                actor_user_id=ticket.created_by_user_id,
            )
        else:
            # Sistem mint'i (created_by NULL): TicketService.assign
            # somut aktör ister; timeline event'ini aynı şekilde,
            # actor NULL ile elle yazıyoruz.
            moment = datetime.now(UTC)
            ticket.assigned_to_user_id = rule.assignee_user_id
            session.add(
                TicketAssignmentEvent(
                    tenant_id=tenant.id,
                    ticket_id=ticket.id,
                    from_user_id=None,
                    to_user_id=rule.assignee_user_id,
                    actor_user_id=None,
                    occurred_at=moment,
                    created_at=moment,
                )
            )

    category = await session.get(Category, ticket.category_id)
    label = category_label_for_language(
        category, language=tenant.language, fallback=category_code
    )
    subject, body = build_ticket_opened_email(
        language=tenant.language,
        category_label=label,
        title=ticket.title,
        summary=ticket.summary,
        priority=str(ticket.priority),
        ticket_id=ticket.id,
    )
    session.add(
        EmailOutbox(
            tenant_id=tenant.id,
            to_email=rule.notify_email,
            subject=subject,
            body_text=body,
            event_type=EmailOutboxEventType.TICKET_OPENED,
            related_ticket_id=ticket.id,
        )
    )
    await session.flush()


__all__ = [
    "apply_routing",
    "build_sla_breach_email",
    "build_ticket_opened_email",
    "category_label_for_language",
    "resolve_rule",
]
