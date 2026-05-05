"""``/tenants/me/analyze/batch`` — bulk CSV/XLSX upload pipeline.

Sprint 8.3.1. This is the multipart-upload counterpart to
``/tenants/me/analyze``: the file lands on disk, a row is inserted into
``analyze_batch_jobs``, and the worker (``imga_api.workers.batch_analyzer``)
drains it asynchronously. Per spec, ``auto_create_tickets`` is opt-in
(default False) so a 1000-row upload doesn't accidentally mint 800
tickets.
"""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from imga_db.models import BatchJobStatus, UserTenantRole
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import CurrentUser, bind_tenant, require_role
from imga_api.db_deps import get_app_session
from imga_api.services import (
    AuditService,
    BatchAnalyzeService,
    BatchJobNotCancellableError,
    BatchJobNotFoundError,
)
from imga_api.services.smart_parser import SmartColumnDetector
from imga_api.services.smart_parser.sampler import sample_columns
from imga_api.settings import Settings
from imga_api.workers.file_parser import (
    FileParseError,
    UnknownColumnError,
    UnsupportedFormatError,
    count_rows,
    peek_header,
)
from imga_api.workers.scheduler import submit_batch_job

log = logging.getLogger("imga-api.routes.batch")

router = APIRouter(prefix="/tenants/me/analyze/batch", tags=["Analyze"])

_TenantMember = Depends(require_role(
    UserTenantRole.TENANT_ADMIN,
    UserTenantRole.ANALYST,
))
_TenantAdmin = Depends(require_role(UserTenantRole.TENANT_ADMIN))
_AnyMember = Depends(require_role(
    UserTenantRole.TENANT_ADMIN,
    UserTenantRole.ANALYST,
    UserTenantRole.VIEWER,
))


# --- response models ---------------------------------------------------


class BatchJobResponse(BaseModel):
    job_id: UUID
    status: str
    file_name: str
    file_size_bytes: int
    text_column: str
    source_column: str | None
    auto_create_tickets: bool
    total_rows: int
    processed_rows: int
    succeeded_rows: int
    failed_rows: int
    tickets_created: int
    duplicates_skipped: int
    error_summary: list[dict[str, Any]] = Field(default_factory=list)
    estimated_seconds: int | None = None
    triggered_by_user_id: UUID | None
    started_at: str | None
    completed_at: str | None
    cancelled_at: str | None
    created_at: str


class BatchJobListResponse(BaseModel):
    jobs: list[BatchJobResponse]
    total: int


# --- Sprint 8.3.8 — preview endpoint response models ----------------


class DetectorAlternative(BaseModel):
    """One non-winning detector verdict for a column. The UI surfaces
    these as dropdown options ("or it could be …") without re-running
    detection."""

    field_name: str
    confidence: float


class DetectedColumnResponse(BaseModel):
    column_name: str
    field_name: str | None
    confidence: float
    sample_values: list[str]
    alternatives: list[DetectorAlternative]
    metadata: dict[str, Any]


class PreviewResponse(BaseModel):
    headers: list[str]
    row_count: int
    detected: list[DetectedColumnResponse]
    pii_warnings: list[str]


# --- helpers ----------------------------------------------------------


def _require_active_tenant(current: CurrentUser) -> UUID:
    if current.active_tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="active tenant context required for this endpoint",
        )
    return current.active_tenant_id


def _job_view(job: Any) -> BatchJobResponse:
    """Project an AnalyzeBatchJob ORM row onto the wire shape. Status
    casts to its enum's value so JSON gets the lowercase string."""
    # Heuristic for estimated_seconds: ~150 ms / row at chunk_size=32 BERT
    # batches on a 2-vCPU CPU container. Updates to 0 once the job is
    # finished — UI shouldn't show ETA on a completed run.
    if job.status in (
        BatchJobStatus.COMPLETED,
        BatchJobStatus.FAILED,
        BatchJobStatus.CANCELLED,
    ):
        eta: int | None = 0
    else:
        remaining = max(0, job.total_rows - job.processed_rows)
        eta = max(1, int(remaining * 0.15))

    return BatchJobResponse(
        job_id=job.id,
        status=str(job.status),
        file_name=job.file_name,
        file_size_bytes=job.file_size_bytes,
        text_column=job.text_column,
        source_column=job.source_column,
        auto_create_tickets=job.auto_create_tickets,
        total_rows=job.total_rows,
        processed_rows=job.processed_rows,
        succeeded_rows=job.succeeded_rows,
        failed_rows=job.failed_rows,
        tickets_created=job.tickets_created,
        duplicates_skipped=job.duplicates_skipped,
        error_summary=list(job.error_summary or []),
        estimated_seconds=eta,
        triggered_by_user_id=job.triggered_by_user_id,
        started_at=job.started_at.isoformat() if job.started_at else None,
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
        cancelled_at=job.cancelled_at.isoformat() if job.cancelled_at else None,
        created_at=job.created_at.isoformat(),
    )


# --- endpoints --------------------------------------------------------


@router.post(
    "/preview",
    response_model=PreviewResponse,
    summary="Sprint 8.3.8 — detect column types from a sample upload.",
    description=(
        "Multipart upload that runs the smart_parser detector ensemble "
        "against the file's first 50 data rows and returns proposed "
        "column-to-field assignments + sample values + PII warnings. "
        "Does NOT persist the file or create a job — the response "
        "drives the /analyze/upload Step 2 preview UI; the user "
        "confirms / overrides and the actual upload happens via "
        "POST /tenants/me/analyze/batch."
    ),
)
async def preview_batch_columns(
    request: Request,
    current: Annotated[CurrentUser, _AnyMember],
    file: Annotated[UploadFile, File(...)],
) -> PreviewResponse:
    """Returns a preview snapshot — no DB writes, no job row.

    The file is streamed to a temp path inside the tenant's upload
    directory, sampled, then deleted. Same size/extension caps as
    the real upload endpoint apply (the user's first round of
    bytes-on-the-wire validation should be identical regardless of
    which path they hit)."""
    _ = _require_active_tenant(current)
    settings: Settings = request.app.state.settings
    batch_settings = settings.batch

    if file.filename is None or not file.filename.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="dosya adı boş olamaz",
        )
    safe_name = Path(file.filename).name
    suffix = Path(safe_name).suffix.lower()
    if suffix not in (".csv", ".xlsx"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="desteklenmeyen dosya türü; sadece .csv ve .xlsx kabul edilir",
        )

    # Temp path inside the tenant's upload dir so disk quotas + path
    # rules already configured for the real upload also apply here.
    tmp_dir = batch_settings.upload_dir / "preview" / str(uuid4())
    tmp_dir.mkdir(parents=True, exist_ok=True)
    file_path = tmp_dir / safe_name

    written = 0
    try:
        with file_path.open("wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > batch_settings.max_file_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=(
                            f"dosya boyutu "
                            f"{batch_settings.max_file_bytes // (1024 * 1024)} "
                            "MB sınırını aşıyor"
                        ),
                    )
                out.write(chunk)

        try:
            headers, samples, row_count = sample_columns(file_path)
        except (FileParseError, UnsupportedFormatError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc

        detector = SmartColumnDetector()
        result = detector.detect(headers, samples, row_count)

        return PreviewResponse(
            headers=result.headers,
            row_count=result.row_count,
            detected=[
                DetectedColumnResponse(
                    column_name=col.column_name,
                    field_name=(
                        col.field_name.value if col.field_name else None
                    ),
                    confidence=col.confidence,
                    sample_values=col.sample_values,
                    alternatives=[
                        DetectorAlternative(
                            field_name=alt.field_name.value,
                            confidence=alt.confidence,
                        )
                        for alt in col.alternatives
                    ],
                    metadata=col.metadata,
                )
                for col in result.detected
            ],
            pii_warnings=result.pii_warnings,
        )
    except HTTPException:
        raise
    except Exception:
        log.exception(
            "preview_batch_columns failed",
            extra={"filename": safe_name},
        )
        raise
    finally:
        # Best-effort cleanup — preview never persists the file.
        with contextlib.suppress(OSError):
            file_path.unlink(missing_ok=True)
            tmp_dir.rmdir()


@router.post(
    "",
    response_model=BatchJobResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a CSV/XLSX file for batch analysis.",
    description=(
        "Multipart upload. Returns immediately with the queued job "
        "row; the in-process worker picks it up subject to the "
        "concurrency caps (1 per tenant, 2 server-wide). Poll "
        "``GET /tenants/me/analyze/batch/{job_id}`` for progress."
    ),
)
async def create_batch(
    request: Request,
    current: Annotated[CurrentUser, _TenantMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    file: Annotated[UploadFile, File(...)],
    text_column: Annotated[str, Form()] = "text",
    source_column: Annotated[str | None, Form()] = None,
    auto_create_tickets: Annotated[bool, Form()] = False,
) -> BatchJobResponse:
    tenant_id = _require_active_tenant(current)
    settings: Settings = request.app.state.settings
    batch_settings = settings.batch

    if file.filename is None or not file.filename.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="dosya adı boş olamaz",
        )
    safe_name = Path(file.filename).name  # strip any path components
    suffix = Path(safe_name).suffix.lower()
    if suffix not in (".csv", ".xlsx"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="desteklenmeyen dosya türü; sadece .csv ve .xlsx kabul edilir",
        )

    # Allocate the job's storage path BEFORE writing — the file path
    # is part of the job row and a UUID directory avoids clashes
    # within the same tenant.
    job_id = uuid4()
    job_dir = batch_settings.upload_dir / str(tenant_id) / str(job_id)
    job_dir.mkdir(parents=True, exist_ok=True)
    file_path = job_dir / safe_name

    # Stream-write to disk while enforcing the size cap.
    written = 0
    with file_path.open("wb") as out:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            written += len(chunk)
            if written > batch_settings.max_file_bytes:
                out.close()
                file_path.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=(
                        f"dosya boyutu {batch_settings.max_file_bytes // (1024 * 1024)} "
                        "MB sınırını aşıyor"
                    ),
                )
            out.write(chunk)

    # Header + row-count probe. Errors here are the user's fault
    # (wrong column, empty file, malformed CSV) → 400.
    try:
        header = peek_header(file_path)
        total_rows = count_rows(file_path)
    except (FileParseError, UnsupportedFormatError) as exc:
        file_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    if total_rows <= 0:
        file_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="dosya boş ya da yalnızca başlık satırı içeriyor",
        )
    if total_rows > batch_settings.max_rows:
        file_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"satır sayısı {batch_settings.max_rows} sınırını aşıyor "
                f"(yüklenen dosyada {total_rows} satır var)"
            ),
        )

    # Validate the requested text/source columns exist in the header.
    # We don't need ParsedRow content here — peek_header is cheap and
    # the validation surfaces a clear error before the worker fires.
    try:
        from imga_api.workers.file_parser import _resolve_columns

        _resolve_columns(
            header, text_column=text_column, source_column=source_column
        )
    except UnknownColumnError as exc:
        file_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    # Create the job row inside the RLS-bound transaction.
    async with app_session.begin():
        await bind_tenant(app_session, current)
        audit = AuditService(app_session)
        service = BatchAnalyzeService(app_session, audit)
        job = await service.create_job(
            tenant_id=tenant_id,
            triggered_by_user_id=current.user_id,
            file_name=safe_name,
            file_size_bytes=written,
            file_path=str(file_path),
            text_column=text_column,
            source_column=source_column,
            auto_create_tickets=auto_create_tickets,
            total_rows=total_rows,
            ip_address=_client_ip(request),
        )
        view = _job_view(job)

    # Hand off to the scheduler. Keeping this OUTSIDE the transaction
    # is intentional — the scheduler may dispatch immediately.
    scheduler = request.app.state.batch_scheduler
    worker_context = request.app.state.batch_worker_context
    submit_batch_job(scheduler, job_id=view.job_id, context=worker_context)

    return view


@router.get(
    "",
    response_model=BatchJobListResponse,
    summary="List the tenant's recent batch jobs (newest first).",
)
async def list_batches(
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    limit: int = 50,
    offset: int = 0,
) -> BatchJobListResponse:
    tenant_id = _require_active_tenant(current)
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        audit = AuditService(app_session)
        service = BatchAnalyzeService(app_session, audit)
        jobs = await service.list_jobs(
            tenant_id=tenant_id, limit=limit, offset=offset
        )
        views = [_job_view(j) for j in jobs]
    return BatchJobListResponse(jobs=views, total=len(views))


@router.get(
    "/{job_id}",
    response_model=BatchJobResponse,
    summary="Get one batch job's status (poll while processing).",
    responses={404: {"description": "Job not found or hidden by RLS."}},
)
async def get_batch(
    job_id: UUID,
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> BatchJobResponse:
    _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        audit = AuditService(app_session)
        service = BatchAnalyzeService(app_session, audit)
        try:
            job = await service.get_job(job_id)
        except BatchJobNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="batch job not found"
            ) from exc
        return _job_view(job)


@router.delete(
    "/{job_id}",
    response_model=BatchJobResponse,
    summary="Cancel a queued or in-flight batch job.",
    responses={
        404: {"description": "Job not found."},
        409: {"description": "Job already in a terminal state."},
    },
)
async def cancel_batch(
    job_id: UUID,
    request: Request,
    current: Annotated[CurrentUser, _TenantMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> BatchJobResponse:
    _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        audit = AuditService(app_session)
        service = BatchAnalyzeService(app_session, audit)
        try:
            job = await service.cancel_job(
                job_id=job_id,
                actor_user_id=current.user_id,
                ip_address=_client_ip(request),
            )
        except BatchJobNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="batch job not found"
            ) from exc
        except BatchJobNotCancellableError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=str(exc)
            ) from exc
    # Best-effort: tell the scheduler we no longer need this job. The
    # worker will also discover the cancel via its chunk-boundary check.
    scheduler = request.app.state.batch_scheduler
    with contextlib.suppress(Exception):
        scheduler.remove_job(f"batch-{job_id}")
    return _job_view(job)


def _client_ip(request: Request) -> str | None:
    if request.client is None:
        return None
    return request.client.host
