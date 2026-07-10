"""TicketRoutingRule model — kategori bazlı ticket yönlendirme kuralı.

Migration 0036. Tenant başına kategori kodu → bildirim e-postası +
opsiyonel assignee + opsiyonel SLA saati. Ticket mint eden üç yol
(tekil analiz, batch worker, manuel promote) ReviewService içindeki
routing hook'u üzerinden aktif kuralı uygular; SLA ihlal taraması
``sla_hours`` dolu kuralları okur.

UNIQUE(tenant_id, category_code) — kategori başına tek kural.
Tenant-scoped, RLS+FORCE — 0006 / 0022 konvansiyonu.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from imga_db.base import Base
from imga_db.models.mixins import TimestampMixin


class TicketRoutingRule(Base, TimestampMixin):
    __tablename__ = "ticket_routing_rules"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    category_code: Mapped[str] = mapped_column(String(64), nullable=False)
    notify_email: Mapped[str] = mapped_column(String(320), nullable=False)
    assignee_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    sla_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
