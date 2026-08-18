"""ReportService — CRUD over report_jobs.

Sprint 8.3.2. The route layer uses this for create/list/get/delete +
estimate; the worker uses it for status transitions and finalisation.

Validation lives at request time so we never queue a generation we
know we cannot deliver:

  * date_to - date_from <= 90 days (decision 16)
  * estimated row count <= 50,000   (decision 16)
  * format ∈ {xlsx, csv}, type ∈ {comprehensive, reviews_only, tickets_only}
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from imga_db.models import (
    ReportFormat,
    ReportJob,
    ReportStatus,
    ReportType,
    Review,
    Ticket,
)
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.services.audit_service import AuditService
from imga_api.settings import ReportSettings


class ReportServiceError(Exception):
    """Generic report-service failure."""


class ReportNotFoundError(ReportServiceError):
    """Report missing or hidden by RLS. Surfaces as 404."""


class ReportExpiredError(ReportServiceError):
    """Download requested past expires_at. Surfaces as 410 Gone."""


class ReportInvalidFiltersError(ReportServiceError):
    """Validation failed at request time. Caller maps to 400 with the
    Turkish message attached."""


@dataclass(frozen=True, slots=True)
class ReportFilters:
    """Validated filter envelope. Stored on report_jobs.filters as JSON."""

    date_from: datetime | None = None
    date_to: datetime | None = None
    category_ids: tuple[UUID, ...] = ()
    sentiment_labels: tuple[str, ...] = ()
    ticket_states: tuple[str, ...] = ()
    batch_job_id: UUID | None = None
    # 2026-08-18 — WS2 veri kalitesi. False (varsayılan) = quality_flag
    # IS NULL satırlarla sınırlı; rapor çıktısı analitikle aynı temiz-
    # veri varsayılanını paylaşır.
    include_flagged: bool = False

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "date_from": self.date_from.isoformat() if self.date_from else None,
            "date_to": self.date_to.isoformat() if self.date_to else None,
            "category_ids": [str(c) for c in self.category_ids],
            "sentiment_labels": list(self.sentiment_labels),
            "ticket_states": list(self.ticket_states),
            "batch_job_id": str(self.batch_job_id) if self.batch_job_id else None,
            "include_flagged": self.include_flagged,
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> ReportFilters:
        date_from = datetime.fromisoformat(raw["date_from"]) if raw.get("date_from") else None
        date_to = datetime.fromisoformat(raw["date_to"]) if raw.get("date_to") else None
        return cls(
            date_from=date_from,
            date_to=date_to,
            category_ids=tuple(UUID(c) for c in raw.get("category_ids") or []),
            sentiment_labels=tuple(raw.get("sentiment_labels") or []),
            ticket_states=tuple(raw.get("ticket_states") or []),
            batch_job_id=UUID(raw["batch_job_id"]) if raw.get("batch_job_id") else None,
            include_flagged=bool(raw.get("include_flagged", False)),
        )


@dataclass(frozen=True, slots=True)
class ReportEstimate:
    """Row-count estimate returned by ``estimate_rows`` and surfaced to
    the user before queue-ing. Drives the 50K limit check."""

    review_rows: int = 0
    ticket_rows: int = 0

    @property
    def total(self) -> int:
        return self.review_rows + self.ticket_rows


class ReportService:
    """Lives on whichever session the caller hands in:
      * RLS-bound app session for routes (tenant_isolation policy)
      * admin session for the worker (with set_current_tenant)
    """

    def __init__(
        self,
        session: AsyncSession,
        audit: AuditService,
        settings: ReportSettings,
    ) -> None:
        self._session = session
        self._audit = audit
        self._settings = settings

    # ------------------------------------------------------------------
    # Validation + estimate
    # ------------------------------------------------------------------

    def validate_filters(self, filters: ReportFilters) -> None:
        if filters.date_from and filters.date_to:
            if filters.date_to < filters.date_from:
                raise ReportInvalidFiltersError(
                    "Tarih aralığı geçersiz: bitiş başlangıçtan önce."
                )
            span = filters.date_to - filters.date_from
            if span > timedelta(days=self._settings.max_days):
                raise ReportInvalidFiltersError(
                    f"Tarih aralığı {self._settings.max_days} günü aşamaz."
                )

    async def estimate_rows(
        self,
        *,
        tenant_id: UUID,
        report_type: ReportType,
        filters: ReportFilters,
    ) -> ReportEstimate:
        """Cheap pre-flight count. Reviews + tickets queried separately
        so the 50K cap can short-circuit before the worker fires."""
        review_count = 0
        ticket_count = 0
        if report_type in (ReportType.COMPREHENSIVE, ReportType.REVIEWS_ONLY):
            stmt = select(func.count()).select_from(Review).where(
                Review.tenant_id == tenant_id,
                Review.deleted_at.is_(None),
            )
            stmt = self._apply_review_filters(stmt, filters)
            review_count = (await self._session.execute(stmt)).scalar_one()
        if report_type in (ReportType.COMPREHENSIVE, ReportType.TICKETS_ONLY):
            stmt = select(func.count()).select_from(Ticket).where(
                Ticket.tenant_id == tenant_id,
                Ticket.deleted_at.is_(None),
            )
            stmt = self._apply_ticket_filters(stmt, filters)
            ticket_count = (await self._session.execute(stmt)).scalar_one()
        return ReportEstimate(review_rows=review_count, ticket_rows=ticket_count)

    def enforce_row_cap(self, estimate: ReportEstimate) -> None:
        if estimate.total > self._settings.max_rows:
            raise ReportInvalidFiltersError(
                f"Sonuç {estimate.total} satır içeriyor; "
                f"{self._settings.max_rows:,} satır limitini aşıyor — "
                "tarih aralığını veya filtreleri daraltın."
            )

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def create_job(
        self,
        *,
        tenant_id: UUID,
        triggered_by_user_id: UUID,
        report_type: ReportType,
        format_: ReportFormat,
        filters: ReportFilters,
        ip_address: str | None = None,
    ) -> ReportJob:
        now = datetime.now(UTC)
        job = ReportJob(
            tenant_id=tenant_id,
            triggered_by_user_id=triggered_by_user_id,
            status=ReportStatus.QUEUED,
            report_type=report_type,
            format=format_,
            filters=filters.to_jsonable(),
            expires_at=now + timedelta(hours=self._settings.retention_hours),
            created_at=now,
        )
        self._session.add(job)
        await self._session.flush()
        await self._audit.log(
            action="report.created",
            resource_type="report_job",
            resource_id=job.id,
            tenant_id=tenant_id,
            actor_user_id=triggered_by_user_id,
            ip_address=ip_address,
            details={
                "report_type": str(report_type),
                "format": str(format_),
            },
        )
        return job

    async def get_job(self, job_id: UUID) -> ReportJob:
        job = await self._session.get(ReportJob, job_id)
        if job is None:
            raise ReportNotFoundError(f"report job {job_id} not found")
        return job

    async def list_jobs(
        self,
        *,
        tenant_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ReportJob]:
        stmt = (
            select(ReportJob)
            .where(ReportJob.tenant_id == tenant_id)
            .order_by(desc(ReportJob.created_at))
            .limit(limit)
            .offset(offset)
        )
        return list((await self._session.execute(stmt)).scalars())

    async def delete_job(
        self,
        *,
        job_id: UUID,
        actor_user_id: UUID,
    ) -> ReportJob:
        """Mark the job as deleted from the user's POV. We DELETE the row
        outright (not a soft-delete) so the cleanup cron can rely on the
        ``status`` index without having to filter ``deleted_at``. The
        on-disk file is unlinked separately by the route handler."""
        job = await self.get_job(job_id)
        await self._audit.log(
            action="report.deleted",
            resource_type="report_job",
            resource_id=job.id,
            tenant_id=job.tenant_id,
            actor_user_id=actor_user_id,
        )
        await self._session.delete(job)
        await self._session.flush()
        return job

    # ------------------------------------------------------------------
    # Worker transitions
    # ------------------------------------------------------------------

    async def mark_generating(self, job_id: UUID) -> ReportJob:
        job = await self.get_job(job_id)
        if job.status != ReportStatus.QUEUED:
            return job  # idempotent
        job.status = ReportStatus.GENERATING
        job.started_at = datetime.now(UTC)
        await self._session.flush()
        return job

    async def mark_completed(
        self,
        *,
        job_id: UUID,
        file_path: str,
        file_size_bytes: int,
        row_count: int,
    ) -> ReportJob:
        job = await self.get_job(job_id)
        if job.status in (ReportStatus.COMPLETED, ReportStatus.FAILED):
            return job
        job.status = ReportStatus.COMPLETED
        job.completed_at = datetime.now(UTC)
        job.file_path = file_path
        job.file_size_bytes = file_size_bytes
        job.row_count = row_count
        await self._session.flush()
        await self._audit.log(
            action="report.completed",
            resource_type="report_job",
            resource_id=job.id,
            tenant_id=job.tenant_id,
            details={
                "file_size_bytes": file_size_bytes,
                "row_count": row_count,
            },
        )
        return job

    async def mark_failed(
        self,
        *,
        job_id: UUID,
        reason: str,
    ) -> ReportJob:
        job = await self.get_job(job_id)
        if job.status in (ReportStatus.COMPLETED, ReportStatus.FAILED):
            return job
        job.status = ReportStatus.FAILED
        job.completed_at = datetime.now(UTC)
        job.error_message = reason
        await self._session.flush()
        await self._audit.log(
            action="report.failed",
            resource_type="report_job",
            resource_id=job.id,
            tenant_id=job.tenant_id,
            details={"reason": reason},
        )
        return job

    # ------------------------------------------------------------------
    # Filter helpers (worker reuses these for the actual query)
    # ------------------------------------------------------------------

    def _apply_review_filters(self, stmt: Any, filters: ReportFilters) -> Any:
        if filters.date_from is not None:
            stmt = stmt.where(Review.review_date >= filters.date_from)
        if filters.date_to is not None:
            stmt = stmt.where(Review.review_date <= filters.date_to)
        if filters.sentiment_labels:
            stmt = stmt.where(Review.sentiment_label.in_(filters.sentiment_labels))
        if filters.batch_job_id is not None:
            stmt = stmt.where(Review.batch_job_id == filters.batch_job_id)
        if not filters.include_flagged:
            stmt = stmt.where(Review.quality_flag.is_(None))
        # category_ids filter would need a JOIN through tickets/categories;
        # left for the worker to apply when fetching rows for the sheet.
        return stmt

    def _apply_ticket_filters(self, stmt: Any, filters: ReportFilters) -> Any:
        if filters.date_from is not None:
            stmt = stmt.where(Ticket.opened_at >= filters.date_from)
        if filters.date_to is not None:
            stmt = stmt.where(Ticket.opened_at <= filters.date_to)
        if filters.ticket_states:
            stmt = stmt.where(Ticket.state.in_(filters.ticket_states))
        if filters.category_ids:
            stmt = stmt.where(Ticket.category_id.in_(filters.category_ids))
        return stmt

    def apply_review_filters(self, stmt: Any, filters: ReportFilters) -> Any:
        """Public so the worker can reuse the same filter logic."""
        return self._apply_review_filters(stmt, filters)

    def apply_ticket_filters(self, stmt: Any, filters: ReportFilters) -> Any:
        return self._apply_ticket_filters(stmt, filters)


@dataclass(frozen=True, slots=True)
class ReportRequest:
    """Wire-shape, route validates / converts to ReportFilters before
    handing to ReportService.create_job."""

    report_type: ReportType
    format_: ReportFormat
    filters: ReportFilters = field(default_factory=ReportFilters)


__all__ = [
    "ReportEstimate",
    "ReportExpiredError",
    "ReportFilters",
    "ReportInvalidFiltersError",
    "ReportNotFoundError",
    "ReportRequest",
    "ReportService",
    "ReportServiceError",
]
