"""ExecutiveSnapshot — cached metric bundle for an executive briefing.

Sprint 9.2 C. RLS+FORCE; one row per (tenant, snapshot_date, period).
The cached payload lives in ``metrics`` (JSONB) so adding a new
metric to the briefing pipeline doesn't require a schema migration.

``last_review_id_at_snapshot`` is the cache cursor — the snapshot
service compares it against the tenant's most-recent review id; if
the upstream advanced the cursor stays behind, the cache is stale
and gets recomputed on the next ``get_or_compute`` call. Plain
``computed_at`` would also work as a freshness signal but the cursor
catches the case where the snapshot is "yesterday's", no new reviews
landed since, and a recompute would be exact-byte-equal — we skip
the work in that case.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from imga_db.base import Base


class ExecutiveSnapshot(Base):
    __tablename__ = "executive_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "snapshot_date",
            "period",
            name="uq_executive_snapshots_period",
        ),
        CheckConstraint(
            "period IN ('daily', 'weekly', 'monthly')",
            name="ck_executive_snapshots_period",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    snapshot_date: Mapped[date] = mapped_column(Date(), nullable=False)
    period: Mapped[str] = mapped_column(Text(), nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    review_count_at_snapshot: Mapped[int] = mapped_column(
        Integer(), nullable=False, default=0
    )
    last_review_id_at_snapshot: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    computation_duration_ms: Mapped[int | None] = mapped_column(
        Integer(), nullable=True
    )
