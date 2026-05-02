"""BatchAnalyzeService — CRUD over analyze_batch_jobs.

Sprint 8.3.1. The route layer uses this for create / list / get / cancel;
the worker uses it for status transitions and progress updates. Service
keeps no per-instance state — it's just SQL behind a thin shape.

Why a separate service from ReviewService: the bridge logic
(``record_and_decide``) is the "one decision per text" entry point and
already deals with tenant config / dedup / ticket creation. The batch
worker calls into that for every row, but the *job lifecycle* (queued
→ processing → completed) is orthogonal — keeping it here means the
worker can tick progress without dragging the bridge in.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from imga_db.models import AnalyzeBatchJob, BatchJobStatus
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.services.audit_service import AuditService


class BatchServiceError(Exception):
    """Generic batch-service failure."""


class BatchJobNotFoundError(BatchServiceError):
    """Job missing or hidden by RLS."""


class BatchJobNotCancellableError(BatchServiceError):
    """Caller tried to cancel a job already in a terminal state."""


@dataclass(frozen=True, slots=True)
class BatchProgress:
    """Mutation payload for the worker's per-chunk progress update.

    Counts are *deltas* — service adds them onto the row to avoid
    losing concurrent ticket-bridge writes that race the chunk update.
    Use 0 for fields that didn't change in the current chunk.
    """

    processed_delta: int = 0
    succeeded_delta: int = 0
    failed_delta: int = 0
    tickets_created_delta: int = 0
    duplicates_skipped_delta: int = 0
    error_entries: list[dict[str, Any]] | None = None


class BatchAnalyzeService:
    """Job CRUD on the imga_app or imga_admin session, depending on the
    caller. Routes use the RLS-bound app session; the worker uses the
    admin session (which still calls ``set_current_tenant`` for FORCE-
    aware visibility) so cross-tenant scheduler queries work."""

    def __init__(self, session: AsyncSession, audit: AuditService) -> None:
        self._session = session
        self._audit = audit

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    async def create_job(
        self,
        *,
        tenant_id: UUID,
        triggered_by_user_id: UUID,
        file_name: str,
        file_size_bytes: int,
        file_path: str,
        text_column: str,
        source_column: str | None,
        auto_create_tickets: bool,
        total_rows: int,
        ip_address: str | None = None,
    ) -> AnalyzeBatchJob:
        now = datetime.now(UTC)
        job = AnalyzeBatchJob(
            tenant_id=tenant_id,
            triggered_by_user_id=triggered_by_user_id,
            status=BatchJobStatus.QUEUED,
            file_name=file_name,
            file_size_bytes=file_size_bytes,
            file_path=file_path,
            text_column=text_column,
            source_column=source_column,
            auto_create_tickets=auto_create_tickets,
            total_rows=total_rows,
            error_summary=[],
            created_at=now,
        )
        self._session.add(job)
        await self._session.flush()
        await self._audit.log(
            action="batch.created",
            resource_type="batch_job",
            resource_id=job.id,
            tenant_id=tenant_id,
            actor_user_id=triggered_by_user_id,
            ip_address=ip_address,
            details={
                "file_name": file_name,
                "total_rows": total_rows,
                "auto_create_tickets": auto_create_tickets,
            },
        )
        return job

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_job(self, job_id: UUID) -> AnalyzeBatchJob:
        job = await self._session.get(AnalyzeBatchJob, job_id)
        if job is None:
            raise BatchJobNotFoundError(f"batch job {job_id} not found")
        return job

    async def list_jobs(
        self,
        *,
        tenant_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AnalyzeBatchJob]:
        stmt = (
            select(AnalyzeBatchJob)
            .where(AnalyzeBatchJob.tenant_id == tenant_id)
            .order_by(desc(AnalyzeBatchJob.created_at))
            .limit(limit)
            .offset(offset)
        )
        return list((await self._session.execute(stmt)).scalars())

    async def has_active_job(self, *, tenant_id: UUID) -> bool:
        """True if the tenant already has a queued/processing job. The
        scheduler uses this to enforce per-tenant concurrency: incoming
        uploads still create their job row but wait on the in-memory
        lock."""
        stmt = (
            select(AnalyzeBatchJob.id)
            .where(AnalyzeBatchJob.tenant_id == tenant_id)
            .where(
                AnalyzeBatchJob.status.in_(
                    [BatchJobStatus.QUEUED, BatchJobStatus.PROCESSING]
                )
            )
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none() is not None

    # ------------------------------------------------------------------
    # Status transitions
    # ------------------------------------------------------------------

    async def mark_processing(self, job_id: UUID) -> AnalyzeBatchJob:
        job = await self.get_job(job_id)
        if job.status != BatchJobStatus.QUEUED:
            return job  # idempotent — worker may retry
        job.status = BatchJobStatus.PROCESSING
        job.started_at = datetime.now(UTC)
        await self._session.flush()
        await self._audit.log(
            action="batch.processing",
            resource_type="batch_job",
            resource_id=job.id,
            tenant_id=job.tenant_id,
        )
        return job

    async def mark_completed(self, job_id: UUID) -> AnalyzeBatchJob:
        job = await self.get_job(job_id)
        if job.status in (
            BatchJobStatus.COMPLETED,
            BatchJobStatus.FAILED,
            BatchJobStatus.CANCELLED,
        ):
            return job
        job.status = BatchJobStatus.COMPLETED
        job.completed_at = datetime.now(UTC)
        await self._session.flush()
        await self._audit.log(
            action="batch.completed",
            resource_type="batch_job",
            resource_id=job.id,
            tenant_id=job.tenant_id,
            details={
                "succeeded_rows": job.succeeded_rows,
                "failed_rows": job.failed_rows,
                "tickets_created": job.tickets_created,
                "duplicates_skipped": job.duplicates_skipped,
            },
        )
        return job

    async def mark_failed(self, job_id: UUID, *, reason: str) -> AnalyzeBatchJob:
        job = await self.get_job(job_id)
        if job.status in (BatchJobStatus.COMPLETED, BatchJobStatus.CANCELLED):
            return job
        job.status = BatchJobStatus.FAILED
        job.completed_at = datetime.now(UTC)
        # Append the catastrophic reason onto error_summary so the UI
        # can surface it without a separate column.
        existing = list(job.error_summary or [])
        existing.append({"row": None, "error": reason})
        job.error_summary = existing[:100]
        await self._session.flush()
        await self._audit.log(
            action="batch.failed",
            resource_type="batch_job",
            resource_id=job.id,
            tenant_id=job.tenant_id,
            details={"reason": reason},
        )
        return job

    async def cancel_job(
        self,
        *,
        job_id: UUID,
        actor_user_id: UUID,
        ip_address: str | None = None,
    ) -> AnalyzeBatchJob:
        """Flag the job as cancelled. The worker checks this at every
        chunk boundary and stops; if the job is already done the call
        raises BatchJobNotCancellableError so the API can return 409."""
        job = await self.get_job(job_id)
        if job.status not in (BatchJobStatus.QUEUED, BatchJobStatus.PROCESSING):
            raise BatchJobNotCancellableError(
                f"job {job_id} is in terminal state {job.status}"
            )
        job.status = BatchJobStatus.CANCELLED
        job.cancelled_at = datetime.now(UTC)
        job.completed_at = job.cancelled_at
        await self._session.flush()
        await self._audit.log(
            action="batch.cancelled",
            resource_type="batch_job",
            resource_id=job.id,
            tenant_id=job.tenant_id,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
        )
        return job

    # ------------------------------------------------------------------
    # Progress (worker-only)
    # ------------------------------------------------------------------

    async def apply_progress(
        self,
        *,
        job_id: UUID,
        progress: BatchProgress,
    ) -> AnalyzeBatchJob:
        job = await self.get_job(job_id)
        job.processed_rows += progress.processed_delta
        job.succeeded_rows += progress.succeeded_delta
        job.failed_rows += progress.failed_delta
        job.tickets_created += progress.tickets_created_delta
        job.duplicates_skipped += progress.duplicates_skipped_delta
        if progress.error_entries:
            current = list(job.error_summary or [])
            for entry in progress.error_entries:
                if len(current) >= 100:
                    break
                current.append(entry)
            job.error_summary = current
        await self._session.flush()
        return job

    async def is_cancelled(self, job_id: UUID) -> bool:
        """Worker checks this at every chunk boundary. Refreshes from
        DB so an out-of-band cancel from the cancel endpoint takes
        effect within at most one chunk."""
        await self._session.commit()  # release any prior snapshot
        job = await self._session.get(AnalyzeBatchJob, job_id)
        if job is None:
            return False
        return job.status == BatchJobStatus.CANCELLED


__all__ = [
    "BatchAnalyzeService",
    "BatchJobNotCancellableError",
    "BatchJobNotFoundError",
    "BatchProgress",
    "BatchServiceError",
]
