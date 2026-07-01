"""ApiTenantConfig + ApiRequestLog — İmga v1 partner API (migration 0033).

``api_tenant_config`` 1:1 tenant partner ayarı (quota, contact, residency_locks).
``api_request_log`` her v1 analyze isteğinin usage/billing/KVKK kaydı — ham gövde
YOK, yalnız hash + 200-char özet. İkisi de RLS+FORCE tenant_isolation.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from imga_db.base import Base


class ApiTenantConfig(Base):
    """Partner tenant ayarı (quota + contact + residency_locks). 1:1 tenant."""

    __tablename__ = "api_tenant_config"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_api_tenant_config_tenant"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    contact_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    quota_tokens_per_day: Mapped[int] = mapped_column(
        BigInteger(), nullable=False, default=2_000_000
    )
    # Partial<Record<UseCase, "tr"|"outbound">> — §4A.1 (v1.3'te no-op).
    residency_locks: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ApiRequestLog(Base):
    """v1 analyze istek kaydı (usage/billing/export/erasure). Ham gövde YOK."""

    __tablename__ = "api_request_log"
    __table_args__ = (
        Index("ix_api_request_log_tenant_created", "tenant_id", "created_at"),
        Index("ix_api_request_log_session", "session_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    client_request_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    session_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    use_case: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    processed_in: Mapped[str] = mapped_column(String(16), nullable=False)
    tokens_prompt: Mapped[int] = mapped_column(Integer(), nullable=False, default=0)
    tokens_completion: Mapped[int] = mapped_column(
        Integer(), nullable=False, default=0
    )
    tokens_total: Mapped[int] = mapped_column(Integer(), nullable=False, default=0)
    cost_try: Mapped[Decimal] = mapped_column(
        Numeric(12, 4), nullable=False, default=Decimal("0")
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    # Ham gövde YOK — hash + özet (KVKK).
    context_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    response_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    response_summary: Mapped[str | None] = mapped_column(String(200), nullable=True)
