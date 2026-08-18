"""``/tenants/me/profile`` — read/update the tenant context fed into
SWOT/OKR prompts.

Sprint 8.3.6.5 / Alt-Faz 8.3.6.5.D. Migration 0019 added four
nullable columns to ``tenants``:

  * ``industry`` — enum (e_commerce, retail, ..., other). Hybrid:
    ``other`` defers to ``industry_other_text`` for the free-form
    label.
  * ``industry_other_text`` — required when industry == "other";
    max 128 chars.
  * ``company_size`` — enum (solo / small / medium / large /
    enterprise).
  * ``business_description`` — free-form Türkçe text, max 500 chars.
    Surfaced verbatim in the SWOT user prompt.

The frontend's /settings/profile page (Sprint 8.3.6.6) reads + writes
through these two routes.

2026-08-18 (WS1/WS3, migration 0042) — ``tenants.terminology``
(``list[{"term": str, "note": str}]``) joined the profile surface.
Onboarding's tenant-create path (``routes/admin/tenants.py`` ->
``TenantService.create``) is the only WRITE path before this change;
this PATCH is the post-onboarding edit surface. Semantics: full-
replace (the whole list overwrites, no per-entry merge — falls out of
the existing ``exclude_unset`` + ``setattr`` PATCH loop for free,
same as every other field here). Validation is stricter than the
admin create path's best-effort shape check (``strategic_constants.
terminology_directive`` tolerates malformed entries so four
downstream LLM prompts never 500 on legacy data): here ``term`` is
required/non-blank and the list is capped at 50 entries — an
editing surface a human fills in one field at a time can afford (and
should have) tighter input validation than a bulk admin-create
payload.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from imga_db.models import Tenant, UserTenantRole
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import CurrentUser, bind_tenant, require_role
from imga_api.db_deps import get_app_session
from imga_api.services import (
    DECISION_TENANT_SETTING_CHANGED,
    DecisionAuditService,
)
from imga_api.services.strategic_constants import (
    COMPANY_SIZE_LABELS,
    INDUSTRY_LABELS,
)

router = APIRouter(prefix="/tenants/me/profile", tags=["Tenant Config"])

# Sprint 8.3.6 spec: tenant_admin + analyst can edit; viewer reads-only
# (the GET path uses _AnyMember so all three see the current state, but
# PATCH is gated to writers).
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


# --- response + request models -------------------------------------


class TerminologyEntry(BaseModel):
    """2026-08-18 (WS3) — ``terminology_directive``'in ham girdi
    şekli (``strategic_constants.py``). Write-path (bu route) katı:
    ``term`` zorunlu + boş olamaz; ``note`` opsiyonel. Read-path
    (``TenantProfileResponse``) kasten daha gevşek — bkz. orada."""

    model_config = ConfigDict(extra="forbid")

    term: str = Field(..., max_length=128)
    note: str | None = Field(default=None, max_length=500)

    @field_validator("term")
    @classmethod
    def _term_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("term boş olamaz")
        return v

    @field_validator("note")
    @classmethod
    def _note_strip(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None


class TenantProfileResponse(BaseModel):
    industry: str | None
    industry_other_text: str | None
    company_size: str | None
    business_description: str | None
    # ``list[dict[str, Any]]`` bilinçli — ``TerminologyEntry`` ile
    # yeniden doğrulamak, PATCH'in katı şekli devreye girmeden ÖNCE
    # (ör. admin create path'i / eski satırlar) yazılmış olabilecek
    # şekilce gevşek kayıtları GET'te 500'e düşürebilirdi;
    # ``terminology_directive`` zaten aynı gevşek-okuma ilkesini
    # izliyor (bkz. strategic_constants.py).
    terminology: list[dict[str, Any]] | None = None


class TenantProfileUpdateRequest(BaseModel):
    """All fields optional — PATCH semantics. Provided fields overwrite,
    omitted fields stay as-is. Pass ``null`` explicitly to clear.

    ``terminology`` — tam-değiştirme: alan gönderilirse TÜM liste
    yenisiyle değişir (per-entry merge YOK); en çok 50 madde, her
    maddede ``term`` zorunlu/boş olamaz (bkz. ``TerminologyEntry``)."""

    industry: str | None = Field(default=None)
    industry_other_text: str | None = Field(default=None, max_length=128)
    company_size: str | None = Field(default=None)
    business_description: str | None = Field(default=None, max_length=500)
    terminology: list[TerminologyEntry] | None = Field(
        default=None, max_length=50
    )

    @field_validator("industry")
    @classmethod
    def _industry_in_enum(cls, v: str | None) -> str | None:
        if v is not None and v not in INDUSTRY_LABELS:
            valid = ", ".join(sorted(INDUSTRY_LABELS))
            raise ValueError(
                f"industry must be one of: {valid} (got {v!r})"
            )
        return v

    @field_validator("company_size")
    @classmethod
    def _size_in_enum(cls, v: str | None) -> str | None:
        if v is not None and v not in COMPANY_SIZE_LABELS:
            valid = ", ".join(sorted(COMPANY_SIZE_LABELS))
            raise ValueError(
                f"company_size must be one of: {valid} (got {v!r})"
            )
        return v

    @model_validator(mode="after")
    def _other_requires_text(self) -> TenantProfileUpdateRequest:
        # Only enforce when the request explicitly sets industry to
        # "other". A PATCH that doesn't touch industry but touches
        # industry_other_text is allowed (might just be a typo fix).
        if self.industry == "other" and not (
            self.industry_other_text and self.industry_other_text.strip()
        ):
            raise ValueError(
                "industry_other_text is required when industry == 'other'"
            )
        return self


# --- endpoints -----------------------------------------------------


@router.get(
    "",
    response_model=TenantProfileResponse,
    summary="Get the active tenant's SWOT/OKR profile fields.",
)
async def get_tenant_profile(
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> TenantProfileResponse:
    tenant_id = _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        tenant = await app_session.get(Tenant, tenant_id)
        if tenant is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="tenant not found",
            )
        return TenantProfileResponse(
            industry=tenant.industry,
            industry_other_text=tenant.industry_other_text,
            company_size=tenant.company_size,
            business_description=tenant.business_description,
            terminology=tenant.terminology,
        )


@router.patch(
    "",
    response_model=TenantProfileResponse,
    summary="Update the active tenant's SWOT/OKR profile fields.",
)
async def update_tenant_profile(
    body: TenantProfileUpdateRequest,
    request: Request,
    current: Annotated[CurrentUser, _WriteMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> TenantProfileResponse:
    tenant_id = _require_active_tenant(current)
    payload = body.model_dump(exclude_unset=True)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        tenant = await app_session.get(Tenant, tenant_id)
        if tenant is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="tenant not found",
            )
        for field, value in payload.items():
            setattr(tenant, field, value)
        # Idempotent re-validation against the persisted state: if the
        # caller cleared industry to "other" and removed
        # industry_other_text in separate PATCH calls, the post-state
        # would be invalid. The model_validator above only sees the
        # request payload; re-check post-merge here.
        if (
            tenant.industry == "other"
            and not (tenant.industry_other_text and tenant.industry_other_text.strip())
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "industry='other' requires industry_other_text on the "
                    "tenant row; provide it in the same PATCH"
                ),
            )
        # Sprint 9.3 C — operator decision audit. Profile fields feed
        # SWOT/OKR prompts, so a profile edit changes downstream LLM
        # output; surface the changed-field set on the timeline.
        await DecisionAuditService(app_session).record_decision(
            tenant_id=tenant_id,
            decision_type=DECISION_TENANT_SETTING_CHANGED,
            related_entity_type="tenant",
            related_entity_id=tenant_id,
            actor_user_id=current.user_id,
            payload={
                "setting": "profile",
                "changed_fields": sorted(payload.keys()),
            },
            request_id=getattr(request.state, "request_id", None),
        )
        return TenantProfileResponse(
            industry=tenant.industry,
            industry_other_text=tenant.industry_other_text,
            company_size=tenant.company_size,
            business_description=tenant.business_description,
            terminology=tenant.terminology,
        )
