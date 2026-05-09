"""MetricDefinition — registry of every KPI the platform reports.

Sprint 9.2 A. Tenant-agnostic; the same registry serves every tenant.
``canonical_implementation`` is a ``module:attr`` pointer (e.g.
``imga_core.metrics.nps:score_from_buckets``) that the service layer
agrees to dispatch through. The point of the table isn't dynamic
loading — Python code can import directly — it's a single source of
truth for "what does NPS mean here, what's its unit, what's the
range" so the dashboard, executive briefing, trend alerts, and
strategic reports never disagree on a definition again.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Numeric, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from imga_db.base import Base


class MetricDefinition(Base):
    __tablename__ = "metric_definitions"
    __table_args__ = (
        UniqueConstraint("metric_key", name="uq_metric_definitions_key"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    metric_key: Mapped[str] = mapped_column(Text(), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(Text(), nullable=False)
    description: Mapped[str] = mapped_column(Text(), nullable=False)
    formula: Mapped[str] = mapped_column(Text(), nullable=False)
    unit: Mapped[str] = mapped_column(Text(), nullable=False)
    range_min: Mapped[Decimal | None] = mapped_column(Numeric(), nullable=True)
    range_max: Mapped[Decimal | None] = mapped_column(Numeric(), nullable=True)
    higher_is_better: Mapped[bool] = mapped_column(
        Boolean(), nullable=False, default=True
    )
    aggregation: Mapped[str] = mapped_column(Text(), nullable=False)
    canonical_implementation: Mapped[str] = mapped_column(Text(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
