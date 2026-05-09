"""TenantKpiGoal — per-tenant target/period/value for a metric.

Sprint 9.2 B. RLS+FORCE; one goal per (tenant, metric, period,
period_start). Active rows (``period_end >= CURRENT_DATE``) are read
on every dashboard load; the partial index defined in Migration 0026
keeps that hot path narrow as historical goals accumulate.

The FK to ``metric_definitions.metric_key`` (text PK alternate) is
ON UPDATE CASCADE so renaming a metric (rare, but not unthinkable
for a new metric still finding its name) doesn't orphan goals.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from imga_db.base import Base


class TenantKpiGoal(Base):
    __tablename__ = "tenant_kpi_goals"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "metric_key",
            "target_period",
            "period_start",
            name="uq_tenant_kpi_goals_period",
        ),
        CheckConstraint(
            "target_period IN ('weekly', 'monthly', 'quarterly', 'yearly')",
            name="ck_tenant_kpi_goals_period",
        ),
        CheckConstraint(
            "period_end >= period_start",
            name="ck_tenant_kpi_goals_period_order",
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
    metric_key: Mapped[str] = mapped_column(
        Text(),
        ForeignKey(
            "metric_definitions.metric_key",
            ondelete="RESTRICT",
            onupdate="CASCADE",
        ),
        nullable=False,
    )
    target_value: Mapped[Decimal] = mapped_column(Numeric(), nullable=False)
    target_period: Mapped[str] = mapped_column(Text(), nullable=False)
    period_start: Mapped[date] = mapped_column(Date(), nullable=False)
    period_end: Mapped[date] = mapped_column(Date(), nullable=False)
    set_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    set_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    notes: Mapped[str | None] = mapped_column(Text(), nullable=True)
