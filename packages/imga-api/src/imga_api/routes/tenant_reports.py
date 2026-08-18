"""``/tenants/me/reports`` — multi-sheet Excel/CSV export pipeline.

Sprint 8.3.2. The 5 endpoints:

  POST   /tenants/me/reports/generate    queue a job (immediate validate)
  GET    /tenants/me/reports             list recent jobs (paginated)
  GET    /tenants/me/reports/{id}        poll status
  GET    /tenants/me/reports/{id}/download
                                          stream the file (410 past expiry)
  DELETE /tenants/me/reports/{id}        manual delete

Validation runs at request time (Sprint 8.3.2 / decision 16):
  * date_to - date_from <= 90 days
  * estimated row count <= 50K

Both surface as HTTP 400 with a Turkish detail message.
"""

from __future__ import annotations

import contextlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from imga_db.models import (
    ReportFormat,
    ReportStatus,
    ReportType,
    UserTenantRole,
)
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import CurrentUser, bind_tenant, require_role
from imga_api.db_deps import get_app_session
from imga_api.services import (
    AuditService,
    ReportFilters,
    ReportInvalidFiltersError,
    ReportNotFoundError,
    ReportService,
)
from imga_api.workers.scheduler import submit_report_job

log = logging.getLogger("imga-api.routes.report")

router = APIRouter(prefix="/tenants/me/reports", tags=["Analyze"])

_AnyMember = Depends(require_role(
    UserTenantRole.TENANT_ADMIN,
    UserTenantRole.ANALYST,
    UserTenantRole.VIEWER,
))
_WriteMember = Depends(require_role(
    UserTenantRole.TENANT_ADMIN,
    UserTenantRole.ANALYST,
))


# --- request / response models ---------------------------------------


class ReportFiltersRequest(BaseModel):
    date_from: datetime | None = None
    date_to: datetime | None = None
    category_ids: list[UUID] = Field(default_factory=list)
    sentiment_labels: list[str] = Field(default_factory=list)
    ticket_states: list[str] = Field(default_factory=list)
    batch_job_id: UUID | None = None
    # 2026-08-18 — WS2 veri kalitesi. ReportFilters zaten taşıyordu; bu
    # alan eksikti ve istek gövdesinden worker'a giden zincir kopuktu
    # (sessizce her zaman False'a düşüyordu). Varsayılan analytics_service
    # ile aynı: temiz veri.
    include_flagged: bool = False


class GenerateRequest(BaseModel):
    report_type: ReportType
    format: ReportFormat
    filters: ReportFiltersRequest = Field(default_factory=ReportFiltersRequest)


class GenerateResponse(BaseModel):
    report_id: UUID
    status: str
    estimated_seconds: int
    row_count_estimate: int


class EstimateResponse(BaseModel):
    """Dry-run estimate for the modal's Step 3 preview. No row inserted;
    same validation as /generate runs so the user sees the same 400
    they'd hit on submit."""

    row_count_estimate: int
    estimated_seconds: int
    review_rows: int
    ticket_rows: int


class ReportJobView(BaseModel):
    report_id: UUID
    status: str
    report_type: str
    format: str
    filters: dict[str, Any]
    row_count: int | None
    file_size_bytes: int | None
    error_message: str | None
    triggered_by_user_id: UUID | None
    started_at: str | None
    completed_at: str | None
    expires_at: str
    created_at: str


class ReportListResponse(BaseModel):
    reports: list[ReportJobView]
    total: int


# --- helpers ---------------------------------------------------------


def _require_active_tenant(current: CurrentUser) -> UUID:
    if current.active_tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="active tenant context required for this endpoint",
        )
    return current.active_tenant_id


def _client_ip(request: Request) -> str | None:
    if request.client is None:
        return None
    return request.client.host


def _job_view(job: Any) -> ReportJobView:
    return ReportJobView(
        report_id=job.id,
        status=str(job.status),
        report_type=str(job.report_type),
        format=str(job.format),
        filters=dict(job.filters or {}),
        row_count=job.row_count,
        file_size_bytes=job.file_size_bytes,
        error_message=job.error_message,
        triggered_by_user_id=job.triggered_by_user_id,
        started_at=job.started_at.isoformat() if job.started_at else None,
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
        expires_at=job.expires_at.isoformat(),
        created_at=job.created_at.isoformat(),
    )


def _filters_from_request(req: ReportFiltersRequest) -> ReportFilters:
    return ReportFilters(
        date_from=req.date_from,
        date_to=req.date_to,
        category_ids=tuple(req.category_ids),
        sentiment_labels=tuple(req.sentiment_labels),
        ticket_states=tuple(req.ticket_states),
        batch_job_id=req.batch_job_id,
        include_flagged=req.include_flagged,
    )


def _estimate_seconds(row_count: int) -> int:
    """Rule of thumb: ~5K rows/sec write throughput on commodity disk
    once the data is in memory. Floor at 5s so the UI doesn't show
    deceptively-quick estimates for tiny reports (overhead dominates)."""
    return max(5, row_count // 5_000 * 5 + 5)


# --- endpoints -------------------------------------------------------


@router.post(
    "/estimate",
    response_model=EstimateResponse,
    summary="Dry-run validation + row-count estimate (no row inserted).",
    description=(
        "Runs the same 90-day / 50K-row checks as /generate. The modal's "
        "Step 3 preview calls this so the user sees the projected row "
        "count and ETA before confirming."
    ),
    responses={
        400: {"description": "Filter validation failed (Turkish detail)."},
    },
)
async def estimate_report(
    body: GenerateRequest,
    request: Request,
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> EstimateResponse:
    tenant_id = _require_active_tenant(current)
    settings = request.app.state.settings.report
    filters = _filters_from_request(body.filters)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        audit = AuditService(app_session)
        service = ReportService(app_session, audit, settings)
        try:
            service.validate_filters(filters)
            estimate = await service.estimate_rows(
                tenant_id=tenant_id,
                report_type=body.report_type,
                filters=filters,
            )
            service.enforce_row_cap(estimate)
        except ReportInvalidFiltersError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc
    return EstimateResponse(
        row_count_estimate=estimate.total,
        estimated_seconds=_estimate_seconds(estimate.total),
        review_rows=estimate.review_rows,
        ticket_rows=estimate.ticket_rows,
    )


@router.post(
    "/generate",
    response_model=GenerateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Queue a multi-sheet Excel / CSV report.",
    description=(
        "Validation runs at request time: date span ≤ 90 days, "
        "estimated row count ≤ 50,000. Reports expire 24h after "
        "creation; the cleanup cron reaps the file (the row stays as "
        "audit trail with file_path = null)."
    ),
    responses={
        400: {"description": "Filter validation failed (Turkish detail)."},
    },
)
async def generate_report(
    body: GenerateRequest,
    request: Request,
    current: Annotated[CurrentUser, _WriteMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> GenerateResponse:
    tenant_id = _require_active_tenant(current)
    settings = request.app.state.settings.report
    filters = _filters_from_request(body.filters)

    async with app_session.begin():
        await bind_tenant(app_session, current)
        audit = AuditService(app_session)
        service = ReportService(app_session, audit, settings)
        try:
            service.validate_filters(filters)
            estimate = await service.estimate_rows(
                tenant_id=tenant_id,
                report_type=body.report_type,
                filters=filters,
            )
            service.enforce_row_cap(estimate)
        except ReportInvalidFiltersError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc

        job = await service.create_job(
            tenant_id=tenant_id,
            triggered_by_user_id=current.user_id,
            report_type=body.report_type,
            format_=body.format,
            filters=filters,
            ip_address=_client_ip(request),
        )
        report_id = job.id

    # Hand off to scheduler outside the transaction.
    scheduler = request.app.state.batch_scheduler
    report_context = request.app.state.report_worker_context
    submit_report_job(scheduler, job_id=report_id, context=report_context)

    return GenerateResponse(
        report_id=report_id,
        status=ReportStatus.QUEUED.value,
        estimated_seconds=_estimate_seconds(estimate.total),
        row_count_estimate=estimate.total,
    )


@router.get(
    "",
    response_model=ReportListResponse,
    summary="List the tenant's recent report jobs (newest first).",
)
async def list_reports(
    request: Request,
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    limit: int = 50,
    offset: int = 0,
) -> ReportListResponse:
    tenant_id = _require_active_tenant(current)
    settings = request.app.state.settings.report
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        audit = AuditService(app_session)
        service = ReportService(app_session, audit, settings)
        jobs = await service.list_jobs(
            tenant_id=tenant_id, limit=limit, offset=offset
        )
        views = [_job_view(j) for j in jobs]
    return ReportListResponse(reports=views, total=len(views))


@router.get(
    "/{report_id}",
    response_model=ReportJobView,
    summary="Get one report job's status (poll while generating).",
    responses={404: {"description": "Report not found or hidden by RLS."}},
)
async def get_report(
    report_id: UUID,
    request: Request,
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> ReportJobView:
    _require_active_tenant(current)
    settings = request.app.state.settings.report
    async with app_session.begin():
        await bind_tenant(app_session, current)
        audit = AuditService(app_session)
        service = ReportService(app_session, audit, settings)
        try:
            job = await service.get_job(report_id)
        except ReportNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="report not found"
            ) from exc
        return _job_view(job)


@router.get(
    "/{report_id}/download",
    summary="Download the generated report file.",
    responses={
        404: {"description": "Report not found."},
        409: {"description": "Report not yet completed."},
        410: {"description": "Report expired."},
    },
)
async def download_report(
    report_id: UUID,
    request: Request,
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> FileResponse:
    _require_active_tenant(current)
    settings = request.app.state.settings.report
    async with app_session.begin():
        await bind_tenant(app_session, current)
        audit = AuditService(app_session)
        service = ReportService(app_session, audit, settings)
        try:
            job = await service.get_job(report_id)
        except ReportNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="report not found"
            ) from exc

        if str(job.status) != ReportStatus.COMPLETED.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"report is in state {job.status}; not downloadable",
            )

        from datetime import UTC
        from datetime import datetime as _dt

        if job.expires_at < _dt.now(UTC):
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="rapor süresi doldu (24 saat)",
            )

        if not job.file_path:
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="rapor dosyası temizlik cron'u tarafından kaldırılmış",
            )
        file_path = Path(job.file_path)
        if not file_path.exists():
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="rapor dosyası diskte yok",
            )
        media_type = (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            if str(job.format) == ReportFormat.XLSX.value
            else "application/zip"
        )
        filename = f"imga-rapor-{report_id}.{job.format}"
        return FileResponse(
            path=str(file_path),
            media_type=media_type,
            filename=filename,
        )


@router.delete(
    "/{report_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a report (file + row).",
    responses={404: {"description": "Report not found."}},
)
async def delete_report(
    report_id: UUID,
    request: Request,
    current: Annotated[CurrentUser, _WriteMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> None:
    _require_active_tenant(current)
    settings = request.app.state.settings.report
    async with app_session.begin():
        await bind_tenant(app_session, current)
        audit = AuditService(app_session)
        service = ReportService(app_session, audit, settings)
        try:
            job = await service.get_job(report_id)
        except ReportNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="report not found"
            ) from exc
        file_path_str = job.file_path
        await service.delete_job(job_id=report_id, actor_user_id=current.user_id)

    # Unlink file outside the transaction; missing file is fine.
    if file_path_str:
        with contextlib.suppress(OSError):
            Path(file_path_str).unlink(missing_ok=True)
