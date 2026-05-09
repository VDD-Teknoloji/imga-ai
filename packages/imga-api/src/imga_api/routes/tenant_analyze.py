"""``POST /tenants/me/analyze`` — tenant-scoped analyze + auto-ticket bridge.

The anonymous ``/analyze`` endpoint stays as-is for panel preview /
SDK use. This route is the production ingestion path: bearer auth,
tenant-bound RLS session, every call lands a row in ``reviews`` and
(on the CREATE branch) mints a ticket.

Five decision branches are surfaced verbatim to the client so the
frontend can show "ticket created" vs "skipped (mode/threshold/
belirsiz/dedup)" without inferring from heuristics. The decision is
also written to the audit log via ReviewService — see Sprint 7.5.5
Alt-Faz 3 design notes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from imga_core import AnalysisPipeline, AnalysisResult
from imga_db.models import UserTenantRole
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import CurrentUser, bind_tenant, require_role
from imga_api.db_deps import get_app_session
from imga_api.dependencies import get_pipeline, get_review_service
from imga_api.services import (
    CategoryNotConfiguredError,
    ReviewService,
)

router = APIRouter(prefix="/tenants/me", tags=["Analyze"])

_AnyMember = Depends(require_role(
    UserTenantRole.TENANT_ADMIN,
    UserTenantRole.ANALYST,
    UserTenantRole.VIEWER,
))


# --- request / response models -----------------------------------------


class TenantAnalyzeRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "text": "Kargom 5 gündür gelmedi, takip numarası da çalışmıyor.",
                "nps_score": 3,
                "business_segment": "premium",
                "channel": "mobile",
            }
        },
    )
    text: str = Field(..., min_length=1, max_length=10_000)
    # Sprint 8.3.5. Optional NPS (0–10). When the caller also captured
    # the customer's "would you recommend us?" score, pass it through
    # so the review row carries it into analytics. Skipping is fine —
    # the pipeline ignores the value, only persistence reads it.
    nps_score: int | None = Field(default=None, ge=0, le=10)
    # Sprint 9.3 B — business impact dimensions. All four optional;
    # the analyze endpoint passes them straight onto the Review row
    # for downstream analytics breakdown. No validation against the
    # tenant's ``allowed_values`` here — that's a route-layer policy
    # the next sprint can layer on top.
    business_segment: str | None = Field(default=None, max_length=128)
    product_line: str | None = Field(default=None, max_length=128)
    channel: str | None = Field(default=None, max_length=64)
    customer_tier: str | None = Field(default=None, max_length=64)


class TenantAnalyzeResponse(BaseModel):
    """Wire shape for /tenants/me/analyze.

    ``decision`` is one of: ``create`` / ``skipped_belirsiz`` /
    ``skipped_mode`` / ``skipped_threshold`` / ``skipped_dedup``.
    ``ticket_id`` is set on ``create`` (newly minted) and
    ``skipped_dedup`` (the existing ticket the dedup window pointed
    at); other branches leave it null.
    """

    review_id: UUID
    decision: str
    decision_reason: str | None
    ticket_id: UUID | None
    analyzed_at: datetime
    analysis: AnalysisResult
    # Sprint 8.3.5.6 — heuristic company-perspective match. Both fields
    # None when the heuristic didn't fire / taxonomy is empty.
    company_perspective_code: str | None = None
    company_perspective_label_tr: str | None = None


def _require_active_tenant(current: CurrentUser) -> UUID:
    if current.active_tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="active tenant context required for this endpoint",
        )
    return current.active_tenant_id


# --- endpoint ----------------------------------------------------------


@router.post(
    "/analyze",
    response_model=TenantAnalyzeResponse,
    summary="Analyze a review and apply the auto-ticket bridge.",
    description=(
        "Runs the analysis pipeline against ``text`` and writes a row "
        "to ``reviews`` capturing the result + bridge decision. The "
        "decision is one of five branches — see the response schema "
        "for the enum. ``ticket_id`` is non-null on ``create`` (new "
        "ticket) and on ``skipped_dedup`` (pointer to the ticket the "
        "earlier identical text already produced within 24h)."
    ),
    responses={
        500: {"description": "Classifier returned an unconfigured category."},
    },
)
async def tenant_analyze(
    body: TenantAnalyzeRequest,
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    pipeline: Annotated[AnalysisPipeline, Depends(get_pipeline)],
    reviews: Annotated[ReviewService, Depends(get_review_service)],
) -> TenantAnalyzeResponse:
    """Tenant-scoped analyze with bridge wired.

    The pipeline runs synchronously inside the transaction so a
    classifier exception rolls back the (not-yet-persisted) review
    row. The bridge then evaluates the five decision branches in
    fixed order and persists exactly one review row.
    """
    tenant_id = _require_active_tenant(current)
    analysis = pipeline.analyze(body.text)

    async with app_session.begin():
        await bind_tenant(app_session, current)
        try:
            result = await reviews.record_and_decide(
                tenant_id=tenant_id,
                text=body.text,
                analysis=analysis,
                actor_user_id=current.user_id,
                nps_score=body.nps_score,
            )
        except CategoryNotConfiguredError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(exc),
            ) from exc

        # Sprint 9.3 B — back-fill business impact dimensions on the
        # row record_and_decide just minted. The bridge service is
        # dimension-agnostic; doing the patch here keeps the bridge
        # path narrow + lets every dimension stay nullable. UPDATE
        # only when at least one is set.
        if any(
            v is not None
            for v in (
                body.business_segment,
                body.product_line,
                body.channel,
                body.customer_tier,
            )
        ):
            from imga_db.models import Review
            from sqlalchemy import update as _update

            await app_session.execute(
                _update(Review)
                .where(Review.id == result.review_id)
                .values(
                    business_segment=body.business_segment,
                    product_line=body.product_line,
                    channel=body.channel,
                    customer_tier=body.customer_tier,
                )
            )

    return TenantAnalyzeResponse(
        review_id=result.review_id,
        decision=str(result.decision),
        decision_reason=result.decision_reason,
        ticket_id=result.ticket_id,
        analyzed_at=result.analyzed_at,
        analysis=analysis,
        company_perspective_code=result.company_perspective_code,
        company_perspective_label_tr=result.company_perspective_label_tr,
    )
