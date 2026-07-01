"""İmga v1 — KVKK data lifecycle (contract §4.8/§4.9). tenant Bearer.

DELETE /v1/data/{session_id} — session verisini sil, 202 + purge_job_id.
GET  /v1/data/export         — NDJSON export, keyset pagination (≤31 gün).
Ham gövde zaten saklanmıyor (api_request_log yalnız hash+özet); export bunları verir.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Path, Query, Response, status
from imga_db.models import ApiRequestLog, TenantDeletionAudit, Tenant
from pydantic import BaseModel
from sqlalchemy import delete, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.db_deps import get_app_session
from imga_api.v1.auth import ApiPrincipal, bind_api_tenant, require_tenant
from imga_api.v1.errors import PartnerApiError

router = APIRouter(prefix="/v1/data", tags=["v1-data"])

_EXPORT_PAGE = 500
_MAX_WINDOW_DAYS = 31


class EraseResponse(BaseModel):
    ok: bool
    purge_job_id: UUID
    session_id: UUID
    eta_seconds: int


@router.delete(
    "/{session_id}", response_model=EraseResponse, status_code=status.HTTP_202_ACCEPTED
)
async def erase_session(
    principal: Annotated[ApiPrincipal, Depends(require_tenant)],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    session_id: Annotated[UUID, Path()],
) -> EraseResponse:
    purge_job_id = uuid4()
    async with app_session.begin():
        await bind_api_tenant(app_session, principal)
        # RLS-bound: yalnız kendi tenant'ının satırları silinir.
        result = await app_session.execute(
            delete(ApiRequestLog).where(ApiRequestLog.session_id == session_id)
        )
        rows_deleted = result.rowcount or 0
        if rows_deleted == 0:
            raise PartnerApiError(
                status_code=status.HTTP_404_NOT_FOUND,
                code="session_not_found",
                message="session not found",
            )
        app_session.add(
            TenantDeletionAudit(
                tenant_id=principal.tenant_id,
                session_id=session_id,
                purge_job_id=purge_job_id,
                completed_at=datetime.now(),  # senkron silme → hemen tamam
                rows_deleted=rows_deleted,
            )
        )
    return EraseResponse(
        ok=True, purge_job_id=purge_job_id, session_id=session_id, eta_seconds=0
    )


def _encode_cursor(created_at: datetime, row_id: UUID) -> str:
    raw = f"{created_at.isoformat()}|{row_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        created_str, id_str = raw.split("|", 1)
        return datetime.fromisoformat(created_str), UUID(id_str)
    except Exception as exc:  # noqa: BLE001
        raise PartnerApiError(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="invalid_input",
            message="invalid cursor",
            details={"field": "cursor"},
        ) from exc


@router.get("/export")
async def export_data(
    principal: Annotated[ApiPrincipal, Depends(require_tenant)],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    response: Response,
    from_: Annotated[datetime, Query(alias="from")],
    to: Annotated[datetime, Query()],
    use_case: Annotated[str | None, Query()] = None,
    cursor: Annotated[str | None, Query()] = None,
) -> Response:
    if (to - from_) > timedelta(days=_MAX_WINDOW_DAYS):
        raise PartnerApiError(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="export_window_too_large",
            message=f"window exceeds {_MAX_WINDOW_DAYS} days",
        )
    async with app_session.begin():
        await bind_api_tenant(app_session, principal)
        # Çağıranın tenant slug'ı (export tenant_id alanı için).
        slug = (
            await app_session.execute(
                select(Tenant.slug).where(Tenant.id == principal.tenant_id)
            )
        ).scalar_one_or_none() or str(principal.tenant_id)

        stmt = select(ApiRequestLog).where(
            ApiRequestLog.created_at >= from_,
            ApiRequestLog.created_at <= to,
        )
        if use_case is not None:
            stmt = stmt.where(ApiRequestLog.use_case == use_case)
        if cursor is not None:
            c_created, c_id = _decode_cursor(cursor)
            stmt = stmt.where(
                tuple_(ApiRequestLog.created_at, ApiRequestLog.id)
                > (c_created, c_id)
            )
        stmt = stmt.order_by(
            ApiRequestLog.created_at, ApiRequestLog.id
        ).limit(_EXPORT_PAGE)
        rows = (await app_session.execute(stmt)).scalars().all()

    lines: list[str] = []
    for r in rows:
        lines.append(
            json.dumps(
                {
                    "request_id": r.request_id,
                    "session_id": str(r.session_id) if r.session_id else None,
                    "tenant_id": slug,
                    "use_case": r.use_case,
                    "created_at": r.created_at.isoformat(),
                    "context_hash": r.context_sha256,
                    "response_summary": r.response_summary,
                    "processed_in": r.processed_in,
                    "tokens_total": r.tokens_total,
                    "cost_try": float(r.cost_try),
                },
                ensure_ascii=False,
            )
        )
    body = "\n".join(lines)
    resp = Response(content=body, media_type="application/x-ndjson")
    if len(rows) == _EXPORT_PAGE:
        last = rows[-1]
        resp.headers["X-Imga-Next-Cursor"] = _encode_cursor(last.created_at, last.id)
    return resp
