"""``/tenants/me/strategic-reports`` — SWOT/OKR generation + history.

Sprint 8.3.6.5 / Alt-Faz 8.3.6.5.B. Five endpoints:

  * POST /swot/generate         — SwotService driver (cache-aware).
  * POST /okr/generate          — OkrService driver (no cache).
  * GET  /                      — paginated history (filter by type).
  * GET  /{id}                  — full detail view.
  * GET  /{id}/download.pdf     — WeasyPrint render, attachment stream.

All routes are RLS-bound via ``bind_tenant``; the explicit tenant_id
checks on the FK are belt-and-braces. Service errors map to HTTP:

  * NoCredentialsError → 503 + "no_llm_credentials" code (front-end
    redirects to /settings/integrations).
  * AllKeysExhaustedError → 503 + "all_keys_exhausted".
  * SourceReportNotFoundError → 404.
  * SwotResponseInvalidError / OkrResponseInvalidError → 502 ("LLM
    yanıtı geçersiz, lütfen tekrar deneyin").
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from imga_core.llm.errors import AllKeysExhaustedError
from imga_db.models import StrategicReport, UserTenantRole
from pydantic import BaseModel, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import CurrentUser, bind_tenant, require_role
from imga_api.db_deps import get_app_session
from imga_api.services.llm_credentials import NoCredentialsError
from imga_api.services.okr_service import (
    OkrResponseInvalidError,
    OkrService,
    SourceReportNotFoundError,
)
from imga_api.services.pdf_render import PdfRenderError, PdfRenderService
from imga_api.services.swot_service import (
    SwotResponseInvalidError,
    SwotService,
)

router = APIRouter(
    prefix="/tenants/me/strategic-reports",
    tags=["Strategic Reports"],
)

_AnyMember = Depends(require_role(
    UserTenantRole.TENANT_ADMIN,
    UserTenantRole.ANALYST,
    UserTenantRole.VIEWER,
))
_WriteMember = Depends(require_role(
    UserTenantRole.TENANT_ADMIN,
    UserTenantRole.ANALYST,
))


def _require_active_tenant(current: CurrentUser) -> UUID:
    if current.active_tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="active tenant context required for this endpoint",
        )
    return current.active_tenant_id


# --- request + response models --------------------------------------


class SwotGenerateRequest(BaseModel):
    date_from: date | None = None
    date_to: date | None = None
    force_refresh: bool = False
    # Sprint 8.3.11 — optional batch scope. When set, every stats
    # call inside SwotService filters to ``Review.batch_job_id ==
    # batch_id`` so the SWOT reflects a single upload's data.
    batch_id: UUID | None = None

    @model_validator(mode="after")
    def _date_range(self) -> SwotGenerateRequest:
        if (
            self.date_from is not None
            and self.date_to is not None
            and self.date_to < self.date_from
        ):
            raise ValueError("date_to must be >= date_from")
        return self


class OkrGenerateRequest(BaseModel):
    source_report_id: UUID


class StrategicReportSummary(BaseModel):
    id: UUID
    report_type: str
    date_from: date | None
    date_to: date | None
    source_report_id: UUID | None
    model_name: str
    generation_duration_ms: int | None
    created_at: datetime


class StrategicReportDetail(BaseModel):
    id: UUID
    report_type: str
    date_from: date | None
    date_to: date | None
    source_report_id: UUID | None
    input_stats: dict[str, Any]
    output_payload: dict[str, Any]
    model_name: str
    token_usage: dict[str, int] | None
    generation_duration_ms: int | None
    created_at: datetime
    created_by_user_id: UUID | None


class StrategicReportListResponse(BaseModel):
    items: list[StrategicReportSummary]
    total: int
    has_more: bool


# --- helpers --------------------------------------------------------


def _llm_error_to_http(exc: Exception) -> HTTPException:
    """Map service-layer errors to wire-shape HTTP exceptions. Used
    by both POST endpoints to keep the mapping in one place."""
    if isinstance(exc, NoCredentialsError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "no_llm_credentials",
                "message": (
                    "LLM anahtarı tanımlanmamış. "
                    "Ayarlar > Entegrasyonlar üzerinden ekleyin."
                ),
            },
        )
    if isinstance(exc, AllKeysExhaustedError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "all_keys_exhausted",
                "message": (
                    "Tüm API anahtarları kotayı aştı veya geçersiz. "
                    "Ayarlar > Entegrasyonlar üzerinden kontrol edin."
                ),
            },
        )
    if isinstance(exc, SourceReportNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="kaynak SWOT raporu bulunamadı",
        )
    if isinstance(exc, SwotResponseInvalidError | OkrResponseInvalidError):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "llm_response_invalid",
                "message": "LLM yanıtı geçersiz, lütfen tekrar deneyin.",
            },
        )
    # Default — re-raise as 500 with a Türkçe message; the route
    # decorator's logging picks up the traceback.
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"strategic report generator failed: {exc}",
    )


def _row_to_summary(row: StrategicReport) -> StrategicReportSummary:
    return StrategicReportSummary(
        id=row.id,
        report_type=row.report_type,
        date_from=row.date_from,
        date_to=row.date_to,
        source_report_id=row.source_report_id,
        model_name=row.model_name,
        generation_duration_ms=row.generation_duration_ms,
        created_at=row.created_at,
    )


def _row_to_detail(row: StrategicReport) -> StrategicReportDetail:
    return StrategicReportDetail(
        id=row.id,
        report_type=row.report_type,
        date_from=row.date_from,
        date_to=row.date_to,
        source_report_id=row.source_report_id,
        input_stats=row.input_stats,
        output_payload=row.output_payload,
        model_name=row.model_name,
        token_usage=row.token_usage,
        generation_duration_ms=row.generation_duration_ms,
        created_at=row.created_at,
        created_by_user_id=row.created_by_user_id,
    )


# --- endpoints ------------------------------------------------------


@router.post(
    "/swot/generate",
    response_model=StrategicReportDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Generate (or fetch from cache) a SWOT analysis.",
)
async def generate_swot(
    body: SwotGenerateRequest,
    current: Annotated[CurrentUser, _WriteMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> StrategicReportDetail:
    tenant_id = _require_active_tenant(current)
    user_id = current.user_id
    async with app_session.begin():
        await bind_tenant(app_session, current)
        service = SwotService(app_session, tenant_id, user_id)
        try:
            result = await service.generate(
                date_from=body.date_from,
                date_to=body.date_to,
                force_refresh=body.force_refresh,
                batch_id=body.batch_id,
            )
        except Exception as exc:
            raise _llm_error_to_http(exc) from exc
        # Reload the row to populate created_at + the model_name we
        # just persisted; service returns a serialised dict but the
        # response model expects the DB-shaped fields too.
        row = await app_session.get(StrategicReport, UUID(result["id"]))
        if row is None:
            raise HTTPException(  # pragma: no cover — flush + read in same tx
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="SWOT row vanished post-flush",
            )
        return _row_to_detail(row)


@router.post(
    "/okr/generate",
    response_model=StrategicReportDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Generate OKR proposals from a parent SWOT report.",
)
async def generate_okr(
    body: OkrGenerateRequest,
    current: Annotated[CurrentUser, _WriteMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> StrategicReportDetail:
    tenant_id = _require_active_tenant(current)
    user_id = current.user_id
    async with app_session.begin():
        await bind_tenant(app_session, current)
        service = OkrService(app_session, tenant_id, user_id)
        try:
            result = await service.generate(body.source_report_id)
        except Exception as exc:
            raise _llm_error_to_http(exc) from exc
        row = await app_session.get(StrategicReport, UUID(result["id"]))
        if row is None:
            raise HTTPException(  # pragma: no cover
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="OKR row vanished post-flush",
            )
        return _row_to_detail(row)


@router.get(
    "",
    response_model=StrategicReportListResponse,
    summary="List the active tenant's strategic reports, newest first.",
)
async def list_strategic_reports(
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    report_type: Annotated[
        str | None, Query(pattern="^(swot|okr)$")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> StrategicReportListResponse:
    tenant_id = _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        base = (
            select(StrategicReport)
            .where(StrategicReport.tenant_id == tenant_id)
            .order_by(StrategicReport.created_at.desc())
        )
        if report_type:
            base = base.where(StrategicReport.report_type == report_type)
        # Total count: RLS-filtered, type-filtered.
        count_stmt = select(func.count()).select_from(base.subquery())
        total: int = (await app_session.execute(count_stmt)).scalar_one() or 0
        rows = (
            await app_session.execute(base.limit(limit).offset(offset))
        ).scalars().all()
        items = [_row_to_summary(r) for r in rows]
    return StrategicReportListResponse(
        items=items,
        total=total,
        has_more=offset + len(items) < total,
    )


@router.get(
    "/{report_id}",
    response_model=StrategicReportDetail,
    responses={404: {"description": "Report not found / hidden by RLS."}},
    summary="Single-report detail.",
)
async def get_strategic_report(
    report_id: UUID,
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> StrategicReportDetail:
    tenant_id = _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        row = await app_session.get(StrategicReport, report_id)
        if row is None or row.tenant_id != tenant_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="rapor bulunamadı",
            )
        return _row_to_detail(row)


@router.get(
    "/{report_id}/download.pdf",
    summary="Download the report as a PDF (executive deliverable).",
    responses={
        404: {"description": "Report not found / hidden by RLS."},
        500: {"description": "PDF render failed."},
    },
)
async def download_strategic_report_pdf(
    report_id: UUID,
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> Response:
    tenant_id = _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        row = await app_session.get(StrategicReport, report_id)
        if row is None or row.tenant_id != tenant_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="rapor bulunamadı",
            )
        report_dict = _row_to_detail(row).model_dump(mode="json")
        source_dict: dict[str, Any] | None = None
        if row.report_type == "okr" and row.source_report_id is not None:
            parent = await app_session.get(
                StrategicReport, row.source_report_id
            )
            if parent is not None and parent.tenant_id == tenant_id:
                source_dict = _row_to_detail(parent).model_dump(mode="json")

    renderer = PdfRenderService()
    try:
        if row.report_type == "swot":
            pdf_bytes = renderer.render_swot(report_dict)
        elif row.report_type == "okr":
            pdf_bytes = renderer.render_okr(report_dict, source_dict)
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"unsupported report_type: {row.report_type}",
            )
    except PdfRenderError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"PDF render failed: {exc}",
        ) from exc

    filename = f"{row.report_type}-{str(row.id)[:8]}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
