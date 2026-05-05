"""AnalyzeBatchJob model — bulk CSV/XLSX upload pipeline.

Sprint 8.3.1. Each ``POST /tenants/me/analyze/batch`` upload writes one
row here; the in-process APScheduler worker drains the file row-by-row
through ``AnalysisPipeline.analyze_batch`` and ``ReviewService``. Reviews
emitted by the job carry ``batch_job_id`` so the UI can filter "show
me everything from THIS upload" without a tickets join.

Lifecycle:
    queued     — uploaded, awaiting worker (bounded by concurrency policy:
                 1 paralel job per tenant, 2 server-wide)
    processing — worker holds tenant + global locks; progress columns
                 advance as chunks complete
    completed  — finished without crash (failed_rows may be > 0; row
                 errors don't fail the job, only worker crashes do)
    failed     — worker hit an unrecoverable error (file unreadable,
                 tenant config missing, BERT load failed, ...)
    cancelled  — user hit DELETE before worker finished. The worker
                 checks the cancel flag at every chunk boundary.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from imga_db.base import Base


class BatchJobStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AnalyzeBatchJob(Base):
    """One row per CSV/XLSX upload. Tenant-scoped via RLS+FORCE
    (migration 0012). No soft-delete — completed jobs stay in the
    history table forever; the on-disk file is reaped after 24h by
    a separate cron, but ``file_path`` survives as audit trail."""

    __tablename__ = "analyze_batch_jobs"

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

    status: Mapped[BatchJobStatus] = mapped_column(
        String(16), default=BatchJobStatus.QUEUED, nullable=False
    )

    # Original upload metadata. file_path never gets nulled — even after
    # the cleanup cron reaps the on-disk blob, the column lives on so
    # audit reports can reconstruct what was uploaded where.
    file_name: Mapped[str] = mapped_column(String(256), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    text_column: Mapped[str] = mapped_column(String(64), nullable=False)
    source_column: Mapped[str | None] = mapped_column(String(64), nullable=True)
    auto_create_tickets: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    total_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    processed_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    succeeded_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tickets_created: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duplicates_skipped: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )

    # First 100 row-level errors. Worker truncates beyond that —
    # past 100 errors, the failure rate itself is the signal, not the
    # individual row payloads.
    error_summary: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, nullable=False
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    # Sprint 8.3.5. NPS auto-detection results, populated by the worker
    # at job start (detected_nps_column) and incremented as rows persist
    # (rows_with_nps). NULL detected_nps_column == "no recognizable NPS
    # header in the upload"; rows_with_nps stays at 0 when no column
    # was detected and counts NPS-bearing rows otherwise.
    detected_nps_column: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    rows_with_nps: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )

    # Sprint 9.0 — recovery + retry. last_checkpoint_row advances on
    # every chunk commit so a worker restart can resume from the next
    # row instead of replaying from the start. retry_count counts
    # operator-initiated retries from /batches/{id}/retry. last_error
    # is the human-readable failure message (job-level summary
    # complementing error_summary's per-row entries).
    last_checkpoint_row: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    retry_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    last_error: Mapped[str | None] = mapped_column(
        String(2048), nullable=True
    )
