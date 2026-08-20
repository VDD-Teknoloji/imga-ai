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
    Response,
    UploadFile,
    status,
)
from imga_core.llm import AllKeysExhaustedError, LLMError
from imga_core.text_utils import normalize_turkish
from imga_db.models import AnalyzeBatchJob, BatchJobStatus, UserTenantRole
from pydantic import BaseModel, Field
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import CurrentUser, bind_tenant, require_role
from imga_api.db_deps import get_app_session
from imga_api.services import (
    AuditService,
    BatchAnalyzeService,
    BatchJobNotCancellableError,
    BatchJobNotFoundError,
    QualityReportResponseInvalidError,
    QualityReportService,
)
from imga_api.services.batch_template import (
    TEMPLATE_REQUIRED_COLUMNS,
    build_batch_template_xlsx,
)
from imga_api.services.llm_credentials import NoCredentialsError
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
from imga_api.workers.reanalyzer import (
    NoReanalysisCandidatesError,
    create_reanalysis_job,
    is_reanalysis_job,
)
from imga_api.workers.scheduler import enqueue_batch_job, enqueue_reanalysis_job
from imga_api.workers.upload_validation import (
    _effective_text_column,
    validate_upload,
)

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
    date_column: str | None = None
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
    # Sprint 9.0 — recovery surface.
    last_checkpoint_row: int = 0
    retry_count: int = 0
    last_error: str | None = None
    # Sprint 9.0.5-A — arq worker handle.
    worker_job_id: str | None = None
    queued_at: str | None = None
    # 2026-08-18 (migration 0042) WS2 — veri kalitesi bayrak sayaçları.
    # Alt küme succeeded_rows'un içinde; ayrı görünürlük kalite raporu
    # kartı + toggle'lar için (Dalga 3, frontend).
    quality_duplicate_rows: int = 0
    quality_empty_rows: int = 0
    quality_informational_rows: int = 0
    quality_meaningless_rows: int = 0


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


class ValidationIssueResponse(BaseModel):
    """Sprint 12 — tek bir ön-doğrulama bulgusu (satır numarası + ipucu)."""

    severity: str  # "error" (engelleyici) | "warning" (satır atlanır)
    code: str
    message: str
    row: int | None = None
    column: str | None = None
    hint: str | None = None


class ValidationReportResponse(BaseModel):
    ok: bool
    total_rows: int
    valid_rows: int
    error_count: int
    warning_count: int
    issues: list[ValidationIssueResponse] = Field(default_factory=list)


class PreviewResponse(BaseModel):
    headers: list[str]
    row_count: int
    detected: list[DetectedColumnResponse]
    pii_warnings: list[str]
    # Sprint 12 — yüklemeden önce yapısal + içerik doğrulama raporu.
    validation: ValidationReportResponse


# --- 2026-08-18 (migration 0042) — kalite raporu response modelleri --


class QualityFlagCountsResponse(BaseModel):
    duplicate: int
    empty: int
    informational: int
    meaningless: int


class RepeatedTextResponse(BaseModel):
    text_hash: str
    count: int
    sample_text: str


class EnteredByBreakdownResponse(BaseModel):
    entered_by: str | None
    total: int
    duplicate: int
    empty: int
    informational: int
    meaningless: int


class QualitySummaryResponse(BaseModel):
    assessment: str
    model_provider: str
    model_name: str
    generated_at: str


class QualityReportResponse(BaseModel):
    job_id: UUID
    total_rows: int
    succeeded_rows: int
    counts: QualityFlagCountsResponse
    top_repeated_texts: list[RepeatedTextResponse]
    entered_by_breakdown: list[EnteredByBreakdownResponse]
    # None = özet henüz üretilmedi (POST .../generate hiç çağrılmadı).
    summary: QualitySummaryResponse | None = None


def _quality_report_view(report: dict[str, Any]) -> QualityReportResponse:
    summary_payload = report.get("summary")
    return QualityReportResponse(
        job_id=UUID(report["job_id"]),
        total_rows=report["total_rows"],
        succeeded_rows=report["succeeded_rows"],
        counts=QualityFlagCountsResponse(**report["counts"]),
        top_repeated_texts=[
            RepeatedTextResponse(**r) for r in report["top_repeated_texts"]
        ],
        entered_by_breakdown=[
            EnteredByBreakdownResponse(**e)
            for e in report["entered_by_breakdown"]
        ],
        summary=(
            QualitySummaryResponse(**summary_payload)
            if summary_payload is not None
            else None
        ),
    )


# --- helpers ----------------------------------------------------------


def _require_active_tenant(current: CurrentUser) -> UUID:
    if current.active_tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="active tenant context required for this endpoint",
        )
    return current.active_tenant_id


def _ensure_template_compliance(header: list[str], file_path: Path) -> None:
    """Sprint 9.8 — yüklenen dosya şablona uymalı.

    OTAN feedback: "Kesinlikle kullanıcı bir formata zorlanmalı".
    Şablonun zorunlu kolonları (şu an: 'yorum') header'da yoksa,
    422 ile reddediyoruz ve kullanıcıyı 'Şablonu İndir' butonuna
    yönlendiriyoruz. Tek noktadan tek kontrat — yeni zorunlu
    kolon ekleneceğinde TEMPLATE_REQUIRED_COLUMNS güncellenir,
    burası otomatik korur.

    Karşılaştırma normalize_turkish ile yapılıyor — kullanıcı
    'Yorum' veya 'YORUM' yazmış olabilir, hepsi geçerli sayılır.
    Legacy 'text' header'ları için de bir tanıma kapısı bırakıldı
    (eski uploads geri uyumluluk).
    """
    normalized = {normalize_turkish(h).strip() for h in header}
    legacy_alias = {"text"}  # eski uploads için
    accepted = normalized | (normalized & legacy_alias)
    for required in TEMPLATE_REQUIRED_COLUMNS:
        if normalize_turkish(required) in accepted:
            return
        if normalized & legacy_alias:
            # Eski 'text' kolon adı bulundu — şablon uyumlu sayılır
            # ama Türkçe geçişe doğru itelersek iyi olur (uyarı
            # değil, sessiz kabul).
            return
    file_path.unlink(missing_ok=True)
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=(
            "Dosya İmga şablonuna uygun değil. Zorunlu 'yorum' "
            "kolonu bulunamadı. Lütfen 'Şablonu İndir' butonundan "
            "Excel şablonunu alın, yorumlarınızı 'yorum' kolonuna "
            "yapıştırın ve yeniden yükleyin. "
            f"Dosyadaki mevcut kolonlar: {', '.join(repr(h) for h in header)}."
        ),
    )


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
        date_column=getattr(job, "date_column", None),
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
        last_checkpoint_row=job.last_checkpoint_row,
        retry_count=job.retry_count,
        last_error=job.last_error,
        worker_job_id=getattr(job, "worker_job_id", None),
        queued_at=(
            job.queued_at.isoformat()
            if getattr(job, "queued_at", None) is not None
            else None
        ),
        quality_duplicate_rows=getattr(job, "quality_duplicate_rows", 0) or 0,
        quality_empty_rows=getattr(job, "quality_empty_rows", 0) or 0,
        quality_informational_rows=(
            getattr(job, "quality_informational_rows", 0) or 0
        ),
        quality_meaningless_rows=(
            getattr(job, "quality_meaningless_rows", 0) or 0
        ),
    )


# --- endpoints --------------------------------------------------------


@router.get(
    "/template",
    summary="İmga toplu yükleme şablonu (XLSX) indir.",
    description=(
        "Sprint 9.8 — OTAN feedback'i: kullanıcılar bir formata "
        "zorlanmalı. Bu endpoint operatör dostu bir Excel şablonu "
        "döner. Kolonlar: yorum (ZORUNLU), tarih, kaynak, nps. "
        "Şablon ayrı bir TALIMAT sayfası taşır — kolon kuralları, "
        "format kabulleri ve yaygın hatalar. Yüklenen dosya bu "
        "şablonun zorunlu kolonlarını taşımıyorsa /analyze/batch "
        "endpoint'i 422 ile reddeder."
    ),
    response_class=Response,
    responses={
        200: {
            "content": {
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {}
            },
            "description": "Hazır şablon dosyası.",
        },
    },
)
async def download_batch_template(
    current: Annotated[CurrentUser, _AnyMember],
) -> Response:
    """Şablonu binary indir. Auth, herhangi bir tenant üyesine açık —
    viewer rolündeki kullanıcı bile şablonu görüntüleyebilir (yükleme
    yetkisi olmayabilir ama "neyi nasıl dolduracağım" bilgisine
    erişebilir)."""
    _ = current  # auth dependency için, gövdede kullanılmıyor
    xlsx_bytes = build_batch_template_xlsx()
    return Response(
        content=xlsx_bytes,
        media_type=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
        headers={
            "Content-Disposition": (
                'attachment; filename="imga-toplu-yukleme-sablonu.xlsx"'
            ),
            "Cache-Control": "private, max-age=300",
        },
    )


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

        # Sprint 12 — analiz başlamadan tam doğrulama: zorunlu kolon,
        # boş dosya, satır limiti + satır-bazlı boş/kopya uyarıları.
        # Şablon standardı 'yorum' üzerinden doğrularız (strict).
        report = validate_upload(
            file_path,
            text_column="yorum",
            max_rows=batch_settings.max_rows,
            required_columns=TEMPLATE_REQUIRED_COLUMNS,
        )

        return PreviewResponse(
            headers=result.headers,
            row_count=result.row_count,
            validation=ValidationReportResponse(
                ok=report.ok,
                total_rows=report.total_rows,
                valid_rows=report.valid_rows,
                error_count=report.error_count,
                warning_count=report.warning_count,
                issues=[
                    ValidationIssueResponse(
                        severity=issue.severity,
                        code=issue.code,
                        message=issue.message,
                        row=issue.row,
                        column=issue.column,
                        hint=issue.hint,
                    )
                    for issue in report.issues
                ],
            ),
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
        # 'filename' LogRecord'un rezerve alanı — extra ile ezilmeye
        # çalışılınca logging KeyError atıp asıl hatayı maskeliyordu
        # (UAT HATA-01).
        log.exception(
            "preview_batch_columns failed",
            extra={"upload_filename": safe_name},
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
    text_column: Annotated[str, Form()] = "yorum",
    source_column: Annotated[str | None, Form()] = None,
    date_column: Annotated[str | None, Form()] = None,
    auto_create_tickets: Annotated[bool, Form()] = False,
) -> BatchJobResponse:
    # Sprint 9.8 — text_column default'u "yorum"a çekildi
    # (eski "text" değeri legacy_alias üzerinden hala kabul
    # edilir; bkz. _ensure_template_compliance).
    tenant_id = _require_active_tenant(current)
    settings: Settings = request.app.state.settings
    batch_settings = settings.batch

    if file.filename is None or not file.filename.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Dosya adı boş olamaz.",
        )
    safe_name = Path(file.filename).name  # strip any path components
    suffix = Path(safe_name).suffix.lower()
    if suffix not in (".csv", ".xlsx"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Desteklenmeyen dosya türü. Yalnızca .csv ve .xlsx "
                "kabul edilir. Lütfen 'Şablonu İndir' butonundan "
                "Excel şablonunu alıp kullanın."
            ),
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

    # Sprint 9.8 — OTAN feedback: yüklenen dosya İmga şablonuna
    # uymalı. Header'da zorunlu "yorum" kolonu (case + accent
    # insensitive) yoksa erken reddet. Eski "text" kolon adı da
    # tarihi yüklemeleri için tanıdık olmaya devam ediyor ama
    # yeni kullanıcı şablondan başlasın diye mesajda yorum'a
    # yönlendiriyoruz.
    _ensure_template_compliance(header, file_path)

    # FE artık text_column alanı göndermiyor — gerçek kolonu header'dan
    # çöz (istenen → şablon 'yorum' → legacy 'text') ve ÇÖZÜLMÜŞ değeri
    # job'a persist et; worker job.text_column'u olduğu gibi okur.
    text_column = _effective_text_column(
        header, text_column, TEMPLATE_REQUIRED_COLUMNS
    )

    if total_rows <= 0:
        file_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Dosya boş ya da yalnızca başlık satırı içeriyor. "
                "Yorumlarınızı 'yorum' kolonuna yazıp tekrar deneyin."
            ),
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
            date_column=date_column or None,
            auto_create_tickets=auto_create_tickets,
            total_rows=total_rows,
            ip_address=_client_ip(request),
        )

    # Sprint 9.0.5-A — enqueue via arq if the prod pool is wired,
    # else fall back to the in-process APScheduler (test stack +
    # legacy single-process deploys). The helper persists the
    # worker handle on a best-effort basis — failure to write the
    # handle doesn't fail the upload (the queue accepted the job
    # already; the column is just for observability + targeted
    # cancel later).
    worker_job_id, queued_at = await enqueue_batch_job(
        request.app, job_id=job.id, tenant_id=tenant_id,
    )
    if worker_job_id is not None or queued_at is not None:
        async with app_session.begin():
            await bind_tenant(app_session, current)
            await app_session.execute(
                update(AnalyzeBatchJob)
                .where(AnalyzeBatchJob.id == job.id)
                .values(
                    worker_job_id=worker_job_id,
                    queued_at=queued_at,
                )
            )
    async with app_session.begin():
        await bind_tenant(app_session, current)
        refreshed = await app_session.get(AnalyzeBatchJob, job.id)
        view = _job_view(refreshed if refreshed is not None else job)

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


@router.post(
    "/{job_id}/retry",
    response_model=BatchJobResponse,
    summary="Sprint 9.0 — re-queue a FAILED / CANCELLED job from its checkpoint.",
    description=(
        "Resumes processing from ``last_checkpoint_row`` so already-"
        "processed rows aren't double-counted. Counters (succeeded_rows, "
        "tickets_created, etc.) preserve their failure-time values; "
        "``retry_count`` increments. The worker picks up the re-queued "
        "job subject to the same per-tenant + global concurrency caps "
        "as the initial submission."
    ),
    responses={
        404: {"description": "Job not found."},
        409: {"description": "Job not in a retryable state."},
    },
)
async def retry_batch(
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
            job = await service.retry_job(
                job_id=job_id,
                actor_user_id=current.user_id,
                ip_address=_client_ip(request),
            )
        except BatchJobNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="batch job not found",
            ) from exc
        except BatchJobNotCancellableError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=str(exc)
            ) from exc
        tenant_id_for_dispatch = job.tenant_id
        retry_attempt = job.retry_count
        # 2026-08-10 — yeniden analiz işleri de bu endpoint'ten
        # sürdürülür (checkpoint = aday listesindeki indeks). Dosya
        # işçisine yollanırsa "upload file missing" ile ölürdü.
        dispatch_reanalysis = is_reanalysis_job(job.file_path)

    # Re-submit via the same dispatch path as create — arq if wired,
    # else in-process scheduler. Sprint 9.0.5-A. attempt: çöken önceki
    # denemenin Redis'te kalan arq kaydıyla kimlik çakışmasın (bkz.
    # enqueue_batch_job docstring).
    dispatch = (
        enqueue_reanalysis_job if dispatch_reanalysis else enqueue_batch_job
    )
    worker_job_id, queued_at = await dispatch(
        request.app,
        job_id=job.id,
        tenant_id=tenant_id_for_dispatch,
        attempt=retry_attempt,
    )
    if worker_job_id is not None or queued_at is not None:
        async with app_session.begin():
            await bind_tenant(app_session, current)
            await app_session.execute(
                update(AnalyzeBatchJob)
                .where(AnalyzeBatchJob.id == job.id)
                .values(
                    worker_job_id=worker_job_id,
                    queued_at=queued_at,
                )
            )
    async with app_session.begin():
        await bind_tenant(app_session, current)
        refreshed = await app_session.get(AnalyzeBatchJob, job.id)
        view = _job_view(refreshed if refreshed is not None else job)
    return view


@router.post(
    "/{job_id}/reanalyze",
    response_model=BatchJobResponse,
    status_code=status.HTTP_201_CREATED,
    summary="2026-08-10 — bu yüklemenin yorumlarını yeniden analiz et.",
    description=(
        "Kaynak yüklemenin ürettiği yorumları güncel sınıflandırma "
        "modelinden yeniden geçirir. YENİ bir iş satırı açılır "
        "(``yeniden-analiz: <kaynak>``) — kaynak iş olduğu gibi kalır, "
        "ilerleme aynı /batch endpoint'lerinden izlenir. Yorumlar "
        "YERİNDE güncellenir: duygu / kategori / alt kategori / "
        "deneyim tipi tazelenir; tarih, NPS, ticket bağlantısı ve "
        "otomasyon kararı korunur. İnsan düzeltmesi yapılmış yorumlar "
        "kapsam dışıdır. Yalnız kurum yöneticisi çalıştırabilir."
    ),
    responses={
        400: {"description": "Kapsamda yeniden analiz edilecek yorum yok."},
        403: {"description": "Kurum yöneticisi olmayan rol."},
        404: {"description": "Kaynak iş bulunamadı / RLS gizledi."},
        409: {"description": "Kaynak iş zaten bir yeniden analiz işi."},
    },
)
async def reanalyze_batch(
    job_id: UUID,
    request: Request,
    current: Annotated[CurrentUser, _TenantAdmin],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> BatchJobResponse:
    tenant_id = _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        audit = AuditService(app_session)
        service = BatchAnalyzeService(app_session, audit)
        try:
            source = await service.get_job(job_id)
        except BatchJobNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="batch job not found",
            ) from exc
        if is_reanalysis_job(source.file_path):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Bu iş zaten bir yeniden analiz işi; yeniden analizin "
                    "yeniden analizi yapılmaz."
                ),
            )
        try:
            new_job = await create_reanalysis_job(
                app_session,
                audit,
                tenant_id=tenant_id,
                triggered_by_user_id=current.user_id,
                source_batch_job_id=job_id,
                ip_address=_client_ip(request),
            )
        except NoReanalysisCandidatesError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc
        new_job_id = new_job.id

    return await dispatch_reanalysis(
        request, current, app_session, job_id=new_job_id, tenant_id=tenant_id
    )


async def dispatch_reanalysis(
    request: Request,
    current: CurrentUser,
    app_session: AsyncSession,
    *,
    job_id: UUID,
    tenant_id: UUID,
) -> BatchJobResponse:
    """Yeniden analiz işini kuyruğa ver + arq tutamacını satıra yaz.

    İki route (``/batch/{id}/reanalyze`` ve ``/reviews/reanalyze-all``)
    aynı kuyruklama + tazeleme adımını paylaşır."""
    worker_job_id, queued_at = await enqueue_reanalysis_job(
        request.app, job_id=job_id, tenant_id=tenant_id
    )
    if worker_job_id is not None or queued_at is not None:
        async with app_session.begin():
            await bind_tenant(app_session, current)
            await app_session.execute(
                update(AnalyzeBatchJob)
                .where(AnalyzeBatchJob.id == job_id)
                .values(worker_job_id=worker_job_id, queued_at=queued_at)
            )
    async with app_session.begin():
        await bind_tenant(app_session, current)
        refreshed = await app_session.get(AnalyzeBatchJob, job_id)
        if refreshed is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="batch job not found",
            )
        # update-then-serialize: refresh olmadan alanlar bayat kalır
        # (MissingGreenlet riski aynı oturumda lazy load tetiklerse).
        await app_session.refresh(refreshed)
        return _job_view(refreshed)


@router.get(
    "/{job_id}/quality-report",
    response_model=QualityReportResponse,
    summary="2026-08-18 — bu yüklemenin veri kalitesi raporu.",
    description=(
        "Bayrak sayaçları (job kolonlarından), bu job'un satırlarından "
        "en çok tekrarlanan metinler (top 10) + çalışan bazlı kırılım. "
        "LLM'e dokunmaz — özet (``summary``) yalnız daha önce "
        "``POST .../quality-report/generate`` çağrılmışsa dolu gelir."
    ),
    responses={404: {"description": "Job not found or hidden by RLS."}},
)
async def get_quality_report(
    job_id: UUID,
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> QualityReportResponse:
    _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        audit = AuditService(app_session)
        batch_service = BatchAnalyzeService(app_session, audit)
        try:
            job = await batch_service.get_job(job_id)
        except BatchJobNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="batch job not found",
            ) from exc
        report = await QualityReportService(app_session).build_report(job)
    return _quality_report_view(report)


@router.post(
    "/{job_id}/quality-report/generate",
    response_model=QualityReportResponse,
    summary="2026-08-18 — TEK LLM çağrısıyla kalite raporu özeti üretir.",
    description=(
        "``quality_summary`` NULL ise tenant'ın mevcut kazanan LLM "
        "kimliğiyle (SWOT/kök-neden ile aynı desen) kısa bir Türkçe "
        "değerlendirme üretir ve job satırına KALICI olarak cache'ler; "
        "doluysa LLM'e hiç dokunmadan mevcut özeti döner."
    ),
    responses={
        404: {"description": "Job not found or hidden by RLS."},
        412: {"description": "Kurumun aktif LLM anahtarı yok."},
        502: {"description": "LLM yanıtı beklenen şekilde değil."},
        503: {"description": "LLM sağlayıcısına ulaşılamadı."},
    },
)
async def generate_quality_report(
    job_id: UUID,
    current: Annotated[CurrentUser, _TenantMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> QualityReportResponse:
    tenant_id = _require_active_tenant(current)
    # Deferred raise: LLMCallAuditor'ın kendi savepoint'i normal
    # transaction kapanışıyla flush edilsin diye HTTP hatası
    # transaction bittikten SONRA yükselir (root_cause/briefing
    # servisleriyle aynı desen).
    deferred: HTTPException | None = None
    report: dict[str, Any] | None = None
    try:
        async with app_session.begin():
            await bind_tenant(app_session, current)
            audit = AuditService(app_session)
            batch_service = BatchAnalyzeService(app_session, audit)
            try:
                job = await batch_service.get_job(job_id)
            except BatchJobNotFoundError as exc:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="batch job not found",
                ) from exc
            service = QualityReportService(
                app_session, actor_user_id=current.user_id
            )
            try:
                report = await service.generate_summary(
                    job, tenant_id=tenant_id
                )
            except NoCredentialsError:
                deferred = HTTPException(
                    status_code=status.HTTP_412_PRECONDITION_FAILED,
                    detail=(
                        "LLM API anahtarı tanımlanmamış. Ayarlar > "
                        "Entegrasyonlar üzerinden ekleyin."
                    ),
                )
            except (AllKeysExhaustedError, LLMError) as exc:
                deferred = HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=f"LLM sağlayıcısına ulaşılamadı: {exc}",
                )
            except QualityReportResponseInvalidError as exc:
                deferred = HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"LLM yanıtı beklenen şekilde değil: {exc}",
                )
    except HTTPException:
        raise
    except Exception:
        log.exception(
            "quality report generate failed", extra={"job_id": str(job_id)}
        )
        raise
    if deferred is not None:
        raise deferred
    assert report is not None  # deferred is None => generate_summary returned
    return _quality_report_view(report)


def _client_ip(request: Request) -> str | None:
    if request.client is None:
        return None
    return request.client.host
