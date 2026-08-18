"""TenantBusinessDimension — per-tenant config for the five review
business-impact dimensions (segment / product / channel / tier /
entered_by).

Sprint 9.3 B. ``Review`` rows carry the four optional dimension
columns directly; this table is the per-tenant configuration that
tells the CSV uploader which CSV header maps to which dimension and
gives the dashboard the operator-facing display label.

2026-08-18 (migration 0042) added ``entered_by`` as the 5th dimension
key — ``Review.entered_by`` (the employee who logged the review) is
the corresponding column, same free-text-by-default treatment as the
original four.

RLS+FORCE per the convention.
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
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from imga_db.base import Base


class TenantBusinessDimension(Base):
    __tablename__ = "tenant_business_dimensions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "dimension", name="uq_tenant_business_dimensions_dim"
        ),
        CheckConstraint(
            "dimension IN ('business_segment', 'product_line', 'channel', "
            "'customer_tier', 'entered_by')",
            name="ck_tenant_business_dimensions_key",
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
    dimension: Mapped[str] = mapped_column(Text(), nullable=False)
    display_label: Mapped[str] = mapped_column(Text(), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean(), nullable=False, default=True
    )
    allowed_values: Mapped[list[str]] = mapped_column(
        ARRAY(Text()), nullable=False, default=list
    )
    csv_column_mapping: Mapped[str | None] = mapped_column(
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
