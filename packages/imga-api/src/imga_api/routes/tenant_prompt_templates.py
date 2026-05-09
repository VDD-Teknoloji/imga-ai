"""Sprint 9.3 D — ``/tenants/me/prompt-templates``.

Admin-only CRUD for tenant-override templates plus a read view of
the global defaults. Five endpoints:

  * GET    /                     — list templates the tenant sees
                                   (global defaults + tenant overrides)
  * POST   /                     — create / replace a tenant override
  * PATCH  /{id}                 — edit override (system_prompt /
                                   user_prompt / required_variables)
  * DELETE /{id}                 — drop the override; the tenant
                                   reverts to the global default
  * POST   /{id}/test            — server-side render against
                                   user-supplied variables (dry run)

Override creation also fires a ``decision_audit_log`` row of type
``prompt_template_overridden`` so the admin timeline shows who
flipped the prompt.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from imga_db.models import PromptTemplate, UserTenantRole
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import CurrentUser, bind_tenant, require_role
from imga_api.db_deps import get_app_session
from imga_api.services import (
    DECISION_PROMPT_TEMPLATE_OVERRIDDEN,
    DecisionAuditService,
    MissingRequiredVariable,
    PromptResolver,
    PromptResolverError,
    PromptTemplateNotFound,
)
from imga_api.services.prompt_resolver import _render_row

_logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/tenants/me/prompt-templates",
    tags=["Prompt Templates"],
)

_AdminOnly = Depends(require_role(UserTenantRole.TENANT_ADMIN))
_AnyMember = Depends(require_role(
    UserTenantRole.TENANT_ADMIN,
    UserTenantRole.ANALYST,
    UserTenantRole.VIEWER,
))


class PromptTemplateResponse(BaseModel):
    id: UUID
    template_key: str
    version: str
    tenant_id: UUID | None  # None == global default
    system_prompt: str
    user_prompt_template: str
    response_schema: dict[str, Any]
    model_name: str
    temperature: float
    top_p: float
    max_output_tokens: int
    is_active: bool
    is_default: bool
    required_variables: list[str]
    created_at: datetime
    updated_at: datetime
    is_tenant_override: bool


class PromptTemplateUpsertRequest(BaseModel):
    template_key: str = Field(..., min_length=1, max_length=64)
    version: str = Field(default="v1-tenant", min_length=1, max_length=32)
    system_prompt: str = Field(..., min_length=1)
    user_prompt_template: str = Field(..., min_length=1)
    response_schema: dict[str, Any] = Field(default_factory=dict)
    model_name: str = "gemini-2.5-flash"
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    top_p: float = Field(default=0.9, ge=0.0, le=1.0)
    max_output_tokens: int = Field(default=8192, ge=1, le=65536)
    required_variables: list[str] = Field(default_factory=list)
    make_default: bool = True


class PromptTemplatePatchRequest(BaseModel):
    system_prompt: str | None = None
    user_prompt_template: str | None = None
    response_schema: dict[str, Any] | None = None
    model_name: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    top_p: float | None = Field(default=None, ge=0.0, le=1.0)
    max_output_tokens: int | None = Field(default=None, ge=1, le=65536)
    required_variables: list[str] | None = None
    is_active: bool | None = None
    is_default: bool | None = None


class PromptTemplateTestRequest(BaseModel):
    variables: dict[str, Any] = Field(default_factory=dict)


class PromptTemplateTestResponse(BaseModel):
    rendered_prompt: str
    system_prompt: str
    template_key: str
    version: str
    source: str  # tenant_override | global_default


def _require_active_tenant(current: CurrentUser) -> UUID:
    if current.active_tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="active tenant context required",
        )
    return current.active_tenant_id


def _row_to_response(row: PromptTemplate) -> PromptTemplateResponse:
    return PromptTemplateResponse(
        id=row.id,
        template_key=row.template_key,
        version=row.version,
        tenant_id=row.tenant_id,
        system_prompt=row.system_prompt,
        user_prompt_template=row.user_prompt_template,
        response_schema=dict(row.response_schema or {}),
        model_name=row.model_name,
        temperature=row.temperature,
        top_p=row.top_p,
        max_output_tokens=row.max_output_tokens,
        is_active=row.is_active,
        is_default=row.is_default,
        required_variables=list(row.required_variables or []),
        created_at=row.created_at,
        updated_at=row.updated_at,
        is_tenant_override=row.tenant_id is not None,
    )


@router.get(
    "",
    response_model=list[PromptTemplateResponse],
    summary=(
        "List templates visible to the active tenant — global "
        "defaults plus the tenant's own overrides."
    ),
)
async def list_templates(
    current: Annotated[CurrentUser, _AnyMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> list[PromptTemplateResponse]:
    tenant_id = _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        stmt = (
            select(PromptTemplate)
            .where(
                or_(
                    PromptTemplate.tenant_id.is_(None),
                    PromptTemplate.tenant_id == tenant_id,
                )
            )
            .order_by(
                PromptTemplate.template_key,
                PromptTemplate.tenant_id.is_(None),  # tenant overrides first
                PromptTemplate.version,
            )
        )
        rows = list((await app_session.execute(stmt)).scalars().all())
    return [_row_to_response(r) for r in rows]


@router.post(
    "",
    response_model=PromptTemplateResponse,
    status_code=status.HTTP_201_CREATED,
    summary=(
        "Create a tenant override. If make_default=True (the default), "
        "the new row becomes the active version for this tenant + "
        "template_key, demoting any prior tenant default."
    ),
)
async def create_override(
    body: PromptTemplateUpsertRequest,
    request: Request,
    current: Annotated[CurrentUser, _AdminOnly],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> PromptTemplateResponse:
    tenant_id = _require_active_tenant(current)
    try:
        async with app_session.begin():
            await bind_tenant(app_session, current)
            # Demote any existing tenant default for this key.
            if body.make_default:
                existing_defaults = (
                    await app_session.execute(
                        select(PromptTemplate)
                        .where(PromptTemplate.tenant_id == tenant_id)
                        .where(PromptTemplate.template_key == body.template_key)
                        .where(PromptTemplate.is_default.is_(True))
                    )
                ).scalars().all()
                for existing in existing_defaults:
                    existing.is_default = False
            row = PromptTemplate(
                template_key=body.template_key,
                version=body.version,
                tenant_id=tenant_id,
                system_prompt=body.system_prompt,
                user_prompt_template=body.user_prompt_template,
                response_schema=body.response_schema,
                model_name=body.model_name,
                temperature=body.temperature,
                top_p=body.top_p,
                max_output_tokens=body.max_output_tokens,
                is_active=True,
                is_default=body.make_default,
                required_variables=body.required_variables,
                created_by_user_id=current.user_id,
            )
            app_session.add(row)
            await app_session.flush()

            # Sprint 9.3 C — audit the override.
            audit = DecisionAuditService(app_session)
            await audit.record_decision(
                tenant_id=tenant_id,
                decision_type=DECISION_PROMPT_TEMPLATE_OVERRIDDEN,
                related_entity_type="prompt_template",
                related_entity_id=row.id,
                actor_user_id=current.user_id,
                payload={
                    "template_key": body.template_key,
                    "version": body.version,
                    "make_default": body.make_default,
                },
                request_id=getattr(request.state, "request_id", None),
            )
            response = _row_to_response(row)
        return response
    except HTTPException:
        raise
    except Exception:
        _logger.exception(
            "create_override failed",
            extra={
                "tenant_id": str(tenant_id),
                "template_key": body.template_key,
            },
        )
        raise


@router.patch(
    "/{template_id}",
    response_model=PromptTemplateResponse,
    summary="Edit a tenant override.",
)
async def patch_override(
    template_id: UUID,
    body: PromptTemplatePatchRequest,
    current: Annotated[CurrentUser, _AdminOnly],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> PromptTemplateResponse:
    tenant_id = _require_active_tenant(current)
    try:
        async with app_session.begin():
            await bind_tenant(app_session, current)
            row = await app_session.get(PromptTemplate, template_id)
            if row is None or row.tenant_id != tenant_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="prompt template bulunamadı",
                )
            data = body.model_dump(exclude_unset=True)
            # If the patch flips this row to default, demote peers.
            if data.get("is_default") is True:
                peers = (
                    await app_session.execute(
                        select(PromptTemplate)
                        .where(PromptTemplate.tenant_id == tenant_id)
                        .where(PromptTemplate.template_key == row.template_key)
                        .where(PromptTemplate.id != row.id)
                        .where(PromptTemplate.is_default.is_(True))
                    )
                ).scalars().all()
                for peer in peers:
                    peer.is_default = False
            for key, value in data.items():
                setattr(row, key, value)
            await app_session.flush()
            response = _row_to_response(row)
        return response
    except HTTPException:
        raise
    except Exception:
        _logger.exception(
            "patch_override failed",
            extra={"tenant_id": str(tenant_id), "template_id": str(template_id)},
        )
        raise


@router.delete(
    "/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Drop a tenant override; tenant reverts to global default.",
)
async def delete_override(
    template_id: UUID,
    current: Annotated[CurrentUser, _AdminOnly],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> None:
    tenant_id = _require_active_tenant(current)
    async with app_session.begin():
        await bind_tenant(app_session, current)
        row = await app_session.get(PromptTemplate, template_id)
        if row is None or row.tenant_id != tenant_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="prompt template bulunamadı",
            )
        await app_session.delete(row)


@router.post(
    "/{template_id}/test",
    response_model=PromptTemplateTestResponse,
    summary="Server-side render — variables in, rendered prompt out.",
)
async def test_render(
    template_id: UUID,
    body: PromptTemplateTestRequest,
    current: Annotated[CurrentUser, _AdminOnly],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> PromptTemplateTestResponse:
    tenant_id = _require_active_tenant(current)
    try:
        async with app_session.begin():
            await bind_tenant(app_session, current)
            row = await app_session.get(PromptTemplate, template_id)
            # Allow rendering global defaults too — admins may want
            # to inspect the global before deciding to override.
            if row is None or (
                row.tenant_id is not None and row.tenant_id != tenant_id
            ):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="prompt template bulunamadı",
                )
            try:
                resolved = _render_row(row, variables=body.variables)
            except MissingRequiredVariable as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
                ) from exc
            except PromptResolverError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
                ) from exc
        return PromptTemplateTestResponse(
            rendered_prompt=resolved.user_prompt_rendered,
            system_prompt=resolved.system_prompt,
            template_key=resolved.template_key,
            version=resolved.version,
            source=resolved.source,
        )
    except HTTPException:
        raise
    except Exception:
        _logger.exception(
            "test_render failed",
            extra={"tenant_id": str(tenant_id), "template_id": str(template_id)},
        )
        raise


__all__ = ["router"]


# Suppress unused-import warning for PromptResolver/PromptTemplateNotFound;
# they're imported so future endpoints can use them without re-import.
_ = (PromptResolver, PromptTemplateNotFound)
