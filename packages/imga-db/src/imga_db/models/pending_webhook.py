"""PendingWebhookEvent model — manual SLA webhook dispatch queue.

Sprint 9.0. When a tenant flips ``sla_webhook_dispatch_mode`` to
``manual``, the SLA engine stops firing httpx.post directly and
instead queues a row here. The /pending-webhooks page lists rows in
the ``pending`` status; an operator approves (status -> ``sent``,
synchronous dispatch) or dismisses (status -> ``dismissed``).

Tenant-scoped via RLS+FORCE — same convention as 0006 / 0019.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from imga_db.base import Base


class PendingWebhookStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    DISMISSED = "dismissed"


class PendingWebhookTarget(StrEnum):
    SLACK = "slack"
    TEAMS = "teams"


class PendingWebhookEvent(Base):
    """One queued webhook hit. Created when SLA engine fires a
    rule on a tenant in ``manual`` dispatch mode. Snapshot of the
    SlaWebhookPayload + the resolved URL is preserved at queue time
    so the operator review survives source edits."""

    __tablename__ = "pending_webhook_events"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    sla_rule_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("sla_rules.id", ondelete="SET NULL"),
        nullable=True,
    )
    review_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("reviews.id", ondelete="SET NULL"),
        nullable=True,
    )

    webhook_target: Mapped[PendingWebhookTarget] = mapped_column(
        String(16), nullable=False
    )
    webhook_url: Mapped[str] = mapped_column(String(512), nullable=False)
    channel: Mapped[str | None] = mapped_column(String(64), nullable=True)

    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, nullable=False
    )

    status: Mapped[PendingWebhookStatus] = mapped_column(
        String(16),
        default=PendingWebhookStatus.PENDING,
        nullable=False,
    )
    retry_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    dismissed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    dismissed_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
