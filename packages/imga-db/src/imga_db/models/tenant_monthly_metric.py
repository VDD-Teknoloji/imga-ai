"""TenantMonthlyMetric — kurumun kendi girdiği aylık işlem adedi.

Katılım oranı (engagement) payda tarafı: kurum bir ayda kaç işlem
yaptığını buraya girer, sistem o ayın yorum sayısını ``reviews.review_date``
üzerinden sayıp oranı hesaplar. Yorum sayısı bu tablodan bağımsızdır —
işlem adedi girilmemiş ay da tabloda görünür (oran ``null``).

``period_month`` her zaman ayın ilk günü; servis katmanı normalize
eder, CheckConstraint ikinci savunma hattıdır. Tek satır / (kurum, ay).

RLS+FORCE — bkz. migration 0039.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from imga_db.base import Base


class TenantMonthlyMetric(Base):
    __tablename__ = "tenant_monthly_metrics"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "period_month",
            name="uq_tenant_monthly_metrics_period",
        ),
        CheckConstraint(
            "EXTRACT(DAY FROM period_month) = 1",
            name="ck_tenant_monthly_metrics_first_of_month",
        ),
        CheckConstraint(
            "transaction_count >= 0",
            name="ck_tenant_monthly_metrics_count_non_negative",
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
    period_month: Mapped[date] = mapped_column(Date(), nullable=False)
    transaction_count: Mapped[int] = mapped_column(BigInteger(), nullable=False)
    set_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    notes: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
