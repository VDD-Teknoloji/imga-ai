"""EmailOutbox model — asenkron e-posta gönderim kuyruğu.

Migration 0036. Yönlendirme motoru ('ticket_opened') ve SLA ihlal
taraması ('sla_breach') satır ekler; arq cron dispatcher'ı
(``email_outbox_tick``) ``status='pending' AND next_attempt_at <=
now()`` satırlarını gönderir. Başarısızlıkta attempts artar ve
``next_attempt_at`` lineer backoff'la ilerler; 5. denemede ``failed``.

status/attempts/last_error/sent_at kalıbı pending_webhook_events
(0022) ile aynı. Tenant-scoped, RLS+FORCE.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from imga_db.base import Base


class EmailOutboxStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class EmailOutboxEventType(StrEnum):
    TICKET_OPENED = "ticket_opened"
    SLA_BREACH = "sla_breach"


class EmailOutbox(Base):
    """Kuyruğa alınmış tek bir e-posta. Konu + gövde enqueue anında
    render edilip snapshot'lanır — kaynak ticket/kural sonradan
    değişse de operatörün gördüğü içerik gönderilenle aynı kalır."""

    __tablename__ = "email_outbox"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    to_email: Mapped[str] = mapped_column(String(320), nullable=False)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[EmailOutboxEventType] = mapped_column(
        String(40), nullable=False
    )
    related_ticket_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tickets.id", ondelete="SET NULL"),
        nullable=True,
    )

    status: Mapped[EmailOutboxStatus] = mapped_column(
        String(20),
        default=EmailOutboxStatus.PENDING,
        nullable=False,
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
