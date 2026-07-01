"""TenantDeletionAudit + DataPurgeAudit — İmga v1 KVKK (migration 0034).

tenant_deletion_audit: DELETE /v1/data/{session_id} kanıtı (RLS+FORCE tenant).
data_purge_audit: 30-gün retention purge kanıtı (deny-all RLS, sistem/ops).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from imga_db.base import Base


class TenantDeletionAudit(Base):
    """KVKK silme (§4.8) kanıt satırı."""

    __tablename__ = "tenant_deletion_audit"
    __table_args__ = (
        Index("ix_tenant_deletion_audit_tenant", "tenant_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    session_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    purge_job_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rows_deleted: Mapped[int | None] = mapped_column(Integer(), nullable=True)


class DataPurgeAudit(Base):
    """30-gün retention purge (§9) kanıt satırı. Deny-all RLS."""

    __tablename__ = "data_purge_audit"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    tenant_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    purged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    cutoff_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    rows_purged: Mapped[int] = mapped_column(Integer(), nullable=False, default=0)
