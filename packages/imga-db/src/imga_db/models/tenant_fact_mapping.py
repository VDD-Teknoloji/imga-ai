"""TenantFactMapping — per-tenant CSV-column mapping for the 13
operational "facts" fields (SLA/CSAT/effort/compensation/delivery).

``tenant_business_dimensions``'ın (tenant_business_dimension.py)
kardeşi — aynı upsert/CRUD ruhu, ayrı tablo: dimensions yorumun iş
bağlamını taşırken, facts yorumun bağlı destek talebinin operasyonel
gerçekleşmesini taşır. ``csv_column_mapping`` burada NOT NULL —
dimensions'ın aksine bir mapping satırı haritasız var olamaz ("eşleme
yok" burada "satır yok" demektir, "harita boş" değil).

RLS+FORCE per the convention (migration 0046).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from imga_db.base import Base


class TenantFactMapping(Base):
    __tablename__ = "tenant_fact_mappings"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "fact_field", name="uq_tenant_fact_mappings_field"
        ),
        CheckConstraint(
            "fact_field IN ("
            "'sla_resolution_status', 'sla_first_response_status', "
            "'resolution_time', 'first_response_time', 'csat', "
            "'agent_interactions', 'customer_interactions', "
            "'compensation_status', 'freight_cost', 'goods_cost', "
            "'refund_reason', 'delivery_status', 'delivery_detail'"
            ")",
            name="ck_tenant_fact_mappings_field",
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
    fact_field: Mapped[str] = mapped_column(Text(), nullable=False)
    csv_column_mapping: Mapped[str] = mapped_column(Text(), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean(), nullable=False, default=True
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
