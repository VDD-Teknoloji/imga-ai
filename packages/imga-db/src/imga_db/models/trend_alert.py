"""TrendAlert model — KPI deviation log.

Sprint 8.3.10. Threshold-based alerts emitted by TrendAlertService
when a metric crosses a documented bound vs the rolling baseline.
``evidence`` carries the metric snapshot (current value + baseline
+ delta) so the dashboard can render the alert without re-running
the SQL.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from imga_db.base import Base


class TrendAlert(Base):
    __tablename__ = "trend_alerts"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    alert_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text(), nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(
        JSONB(), nullable=False, default=dict
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active"
    )
    acknowledged_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Sprint 9.0.5-B I — dedupe support. ``fingerprint`` is a stable
    # hash of (alert_type, metric_breach_band, window_start,
    # window_end) so the same condition firing on the same day can
    # be ON CONFLICT DO NOTHING'd; ``evaluated_at`` anchors the
    # per-day uniqueness window. Empty fingerprint (legacy rows
    # pre-9.0.5-B + the partial-index WHERE clause) opts out of the
    # uniqueness so historical data isn't retroactively de-duped.
    fingerprint: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=""
    )
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
