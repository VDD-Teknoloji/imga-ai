"""ReportJob model — Excel/CSV multi-sheet export pipeline.

Sprint 8.3.2. Each row is one ``POST /tenants/me/reports/generate``
call; APScheduler worker fills it (xlsxwriter or csv-zip), writes to
``/var/imga/reports/{tenant}/{id}.{ext}``, and the 24h cleanup cron
reaps the file via ``expires_at``. ``file_path`` survives the cron as
audit trail.

Lifecycle:
    queued     — request validated, awaiting worker
    generating — worker holds tenant lock; building the file
    completed  — file on disk, downloadable until expires_at
    failed     — ``error_message`` populated; row stays for forensics
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from imga_db.base import Base


class ReportStatus(StrEnum):
    QUEUED = "queued"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


class ReportType(StrEnum):
    COMPREHENSIVE = "comprehensive"
    REVIEWS_ONLY = "reviews_only"
    TICKETS_ONLY = "tickets_only"


class ReportFormat(StrEnum):
    XLSX = "xlsx"
    CSV = "csv"


class ReportJob(Base):
    """One row per report generation request. Tenant-scoped via RLS+FORCE
    (migration 0013). ``filters`` is the JSON envelope handed to the
    generator; ``file_path`` survives cleanup so audits show where a
    report lived even after the bytes are gone."""

    __tablename__ = "report_jobs"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    triggered_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    status: Mapped[ReportStatus] = mapped_column(
        String(16), default=ReportStatus.QUEUED, nullable=False
    )
    report_type: Mapped[ReportType] = mapped_column(String(32), nullable=False)
    format: Mapped[ReportFormat] = mapped_column(String(8), nullable=False)

    filters: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, nullable=False
    )

    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    error_message: Mapped[str | None] = mapped_column(Text(), nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
