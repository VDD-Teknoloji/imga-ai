"""``/public/trial/*`` — public-internet trial endpoint for imga.ai.

Sprint 9.7. The marketing site at https://imga.ai proxies email-
verified visitors here with a server-to-server bearer token. We
run a ≤100-row analysis using the production pipeline and return a
small aggregate teaser (sentiment dist, top categories, sample
excerpts, NPS estimate). Detailed reports require a sales contact
— this endpoint exists to convert visitors, not to give them the
full SaaS for free.

This is the ONLY route in the API that doesn't sit under
``/tenants/me/*`` — by design. There's no end-user JWT here; the
marketing backend authenticates with a shared bearer key
(IMGA_API_TRIAL_KEY). hmac.compare_digest on the header keeps the
check constant-time. The route reads + writes via the imga_admin
role (RLS bypass) because the trial tenant context is set inline
by the route, not via the normal CurrentUser dependency.

KVKK / cookie / RLS notes live alongside the relevant code, but
the load-bearing posture is: nothing about a trial visitor's data
survives outside the 24h idempotency window. See
imga_api.services.trial_analysis_service for the aggregation +
storage details.
"""

from __future__ import annotations

import hmac
import logging
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Header,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.db_deps import get_admin_session
from imga_api.dependencies import get_pipeline
from imga_api.services.trial_analysis_service import (
    TRIAL_ROW_CAP,
    TRIAL_TENANT_ID,
    TrialEmptyError,
    TrialNoTextColumnError,
    TrialRowCapError,
    gc_expired,
    get_cached_analysis,
    run_trial_analysis,
    serialize_for_response,
    temp_upload_dir,
)

from imga_core import AnalysisPipeline

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/public/trial", tags=["Public Trial"])

# Defense-in-depth file-size cap. The marketing site rejects >1 MB
# upstream; we re-check here so a misconfigured client (or someone
# probing directly) doesn't drag the server through a 100 MB CSV.
TRIAL_MAX_FILE_BYTES = 1 * 1024 * 1024


class TrialAnalyzeResponse(BaseModel):
    """On-the-wire shape consumed by the imga.ai marketing trial
    dashboard. Mirrors the marketing repo's TrialResults type 1:1."""

    sentiment_distribution: dict[str, int]
    top_categories: list[dict[str, object]]
    sample_reviews: list[dict[str, object]]
    nps_estimate: int | None
    request_id: str
    processing_time_ms: int | None


def _require_trial_api_key(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """Authenticate the marketing-site → api proxy bearer.

    hmac.compare_digest dodges timing attacks; ``startswith("Bearer ")``
    + slice keeps the header parser tight. Settings.imga_api_trial_key
    == None means the operator hasn't provisioned the trial endpoint
    yet — we surface 503 (rather than 401) so the marketing site can
    keep its local-mock fallback engaged.
    """
    settings = request.app.state.settings
    configured = settings.imga_api_trial_key
    if not configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="trial endpoint disabled (IMGA_API_TRIAL_KEY not set)",
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing or malformed Authorization header",
        )
    token = authorization[len("Bearer ") :]
    if not hmac.compare_digest(token.encode("utf-8"), configured.encode("utf-8")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid bearer token",
        )


@router.post(
    "/analyze",
    response_model=TrialAnalyzeResponse,
    status_code=status.HTTP_200_OK,
    summary="Run an imga.ai marketing-site trial analysis (≤100 rows).",
    description=(
        "Server-to-server endpoint called by the imga.ai marketing "
        "backend after a visitor verifies their email and uploads a "
        "CSV/XLSX. Runs the production analysis pipeline against "
        "the (capped) row set and returns a teaser payload. "
        "Idempotency: a second call from the same X-Trial-User-Email "
        "within 24h returns the cached aggregate without re-running "
        "the pipeline. RLS-isolated to the singleton trial tenant; "
        "no rows reach the live reviews/tickets/strategic_reports "
        "tables."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Bearer missing/invalid."},
        status.HTTP_413_REQUEST_ENTITY_TOO_LARGE: {
            "description": f"Upload exceeded {TRIAL_MAX_FILE_BYTES // 1024} KB."
        },
        status.HTTP_422_UNPROCESSABLE_ENTITY: {
            "description": (
                f"More than {TRIAL_ROW_CAP} rows, empty file, or no "
                "review-text column detected."
            )
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": "Trial endpoint disabled — IMGA_API_TRIAL_KEY unset."
        },
    },
    dependencies=[Depends(_require_trial_api_key)],
)
async def analyze_trial(
    request: Request,
    file: Annotated[UploadFile, File(...)],
    admin_session: Annotated[AsyncSession, Depends(get_admin_session)],
    pipeline: Annotated[AnalysisPipeline, Depends(get_pipeline)],
    x_trial_user_id: Annotated[str | None, Header()] = None,
    x_trial_user_email: Annotated[str | None, Header()] = None,
) -> TrialAnalyzeResponse:
    if not x_trial_user_email or "@" not in x_trial_user_email:
        # Marketing always sends this header; missing is a coding bug
        # on its side rather than user input — 422 is appropriate.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="X-Trial-User-Email header required",
        )
    email = x_trial_user_email.lower().strip()

    trial_user_id: UUID | None = None
    if x_trial_user_id:
        try:
            trial_user_id = UUID(x_trial_user_id)
        except ValueError:
            # Defensive: marketing should send a valid uuid; an
            # invalid one is logged + dropped rather than failing the
            # request. The trial still runs.
            _logger.warning(
                "trial received invalid X-Trial-User-Id header: %s",
                x_trial_user_id,
            )

    # File-format sanity. Both extensions handled by the existing
    # parsers; anything else is a 422 (user-facing) rather than a
    # 400 (malformed protocol).
    if file.filename is None or not file.filename.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="dosya adı boş olamaz",
        )
    safe_name = Path(file.filename).name
    suffix = Path(safe_name).suffix.lower()
    if suffix not in (".csv", ".xlsx"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="desteklenmeyen dosya türü; sadece .csv ve .xlsx kabul edilir",
        )

    # Bind tenant context inline. The admin session bypasses RLS for
    # reads, but the policy on trial_analyses still checks
    # ``app.current_tenant_id`` on writes via FOR ALL ... WITH CHECK.
    # Setting it to the trial tenant id keeps the route honest with
    # the rest of the schema's tenant-isolation contract.
    await admin_session.execute(
        text("SELECT set_config('app.current_tenant_id', :t, true)"),
        {"t": str(TRIAL_TENANT_ID)},
    )

    # Lazy GC — drop any rows whose 24h window has lapsed. Keeps the
    # table self-cleaning without a worker.
    deleted = await gc_expired(admin_session)
    if deleted:
        _logger.info("trial gc deleted %d expired rows", deleted)

    # Idempotency: same email within the TTL → return cached.
    cached = await get_cached_analysis(admin_session, email=email)
    if cached is not None:
        _logger.info(
            "trial idempotent hit email=%s request_id=%s",
            email, cached.request_id,
        )
        return TrialAnalyzeResponse(**serialize_for_response(cached))

    # Stream + size-cap. Read into a temp file so the existing
    # parsers (which take Path) can consume it.
    settings = request.app.state.settings
    upload_base = settings.batch.upload_dir / "public-trial"
    upload_base.mkdir(parents=True, exist_ok=True)

    async with temp_upload_dir(upload_base) as tmp:
        file_path = tmp / safe_name
        written = 0
        with file_path.open("wb") as out:
            while True:
                chunk = await file.read(1024 * 64)
                if not chunk:
                    break
                written += len(chunk)
                if written > TRIAL_MAX_FILE_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=(
                            f"dosya boyutu {TRIAL_MAX_FILE_BYTES // 1024} "
                            "KB sınırını aşıyor"
                        ),
                    )
                out.write(chunk)

        try:
            row = await run_trial_analysis(
                admin_session,
                pipeline=pipeline,
                file_path=file_path,
                file_name=safe_name,
                email=email,
                trial_user_id=trial_user_id,
            )
        except TrialRowCapError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc
        except TrialNoTextColumnError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc
        except TrialEmptyError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc

    return TrialAnalyzeResponse(**serialize_for_response(row))
