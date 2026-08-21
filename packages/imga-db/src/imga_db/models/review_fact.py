"""ReviewFact — operasyonel "facts" katmanı, ``reviews`` ile 1:1.

SLA gerçekleşmeleri, CSAT, efor (temsilci/müşteri etkileşim sayısı),
tazmin ve teslimat verilerini taşır. Bir yorumun facts satırı yalnız
tenant CSV'de en az bir facts kolonu eşlemişse ve o satırda gerçekten
dolu bir hücre varsa yazılır (bkz. ``imga_api.services.fact_parsing.
build_fact_row``) — migration 0046.

PK = FK = ``review_id`` (1:1); ``tenant_id`` denormalize (RLS'in
JOIN'siz çalışması için, ``tickets``/``ticket_state_transitions``
kalıbıyla aynı gerekçe).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from imga_db.base import Base


class ReviewFact(Base):
    __tablename__ = "review_facts"
    __table_args__ = (
        CheckConstraint(
            "sla_resolution_status IS NULL OR "
            "sla_resolution_status IN ('within', 'violated')",
            name="ck_review_facts_sla_resolution_status",
        ),
        CheckConstraint(
            "sla_first_response_status IS NULL OR "
            "sla_first_response_status IN ('within', 'violated')",
            name="ck_review_facts_sla_first_response_status",
        ),
        CheckConstraint(
            "csat_score IS NULL OR (csat_score >= 1 AND csat_score <= 5)",
            name="ck_review_facts_csat_score_range",
        ),
    )

    review_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("reviews.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )

    sla_resolution_status: Mapped[str | None] = mapped_column(
        Text(), nullable=True
    )
    sla_first_response_status: Mapped[str | None] = mapped_column(
        Text(), nullable=True
    )
    resolution_time_minutes: Mapped[int | None] = mapped_column(
        Integer(), nullable=True
    )
    first_response_time_minutes: Mapped[int | None] = mapped_column(
        Integer(), nullable=True
    )
    csat_score: Mapped[int | None] = mapped_column(
        SmallInteger(), nullable=True
    )
    csat_raw: Mapped[str | None] = mapped_column(Text(), nullable=True)
    agent_interactions: Mapped[int | None] = mapped_column(
        Integer(), nullable=True
    )
    customer_interactions: Mapped[int | None] = mapped_column(
        Integer(), nullable=True
    )
    compensation_status: Mapped[str | None] = mapped_column(
        Text(), nullable=True
    )
    freight_cost: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    goods_cost: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    refund_reason: Mapped[str | None] = mapped_column(Text(), nullable=True)
    delivery_status: Mapped[str | None] = mapped_column(
        Text(), nullable=True
    )
    delivery_detail: Mapped[str | None] = mapped_column(
        Text(), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
