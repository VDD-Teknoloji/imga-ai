"""Sprint 9.3 D — ``/tenants/me/prompt-templates``.

Super-admin-only CRUD for tenant-override templates plus a read view
of the global defaults. Six endpoints:

  * GET    /code-defaults        — koda gömülü varsayılan prompt'lar
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

2026-09-02 (TASK B2) — WHOLE ROUTER locked to ``require_super_admin``.
Prompt gövdeleri (system_prompt/user_prompt_template) imga.ai'ın
kendi fikri mülkiyeti/rekabet avantajı — daha önce ``tenant_admin``
rolü hem ``/code-defaults`` (global varsayılan prompt metinleri) hem
de kendi kurumunun override listesini okuyabiliyordu; bir müşterinin
KENDİ admin'i bile prompt içeriğini görebiliyordu. Her endpoint ya
prompt metni döndürüyor (GET'ler, POST .../test) ya da bir prompt
satırını değiştiriyor (POST/PATCH/DELETE) — ayıracak "zararsız"
endpoint yok, o yüzden ``_AnyMember``/tenant_admin ayrımı kaldırılıp
tüm router süper-admine kilitlendi.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from imga_db.models import PromptTemplate
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import CurrentUser, bind_tenant, require_super_admin
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

# Prompt gövdesi taşıyan/değiştiren HER endpoint süper-admin gerektirir
# (bkz. modül docstring'i) — routes/admin/prompt_templates.py ile aynı
# isimlendirme.
_SuperAdmin = Depends(require_super_admin)


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
    model_name: str = "gemini-3-flash-preview"
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


class CodeDefaultTemplate(BaseModel):
    """Sprint 11.3 — koda gömülü varsayılan şablon. DB'de satır yoksa
    üretim bu içerikle akar; /settings/prompts sayfası 'mevcut
    prompt'u göstermek için bunu okur. ``user_prompt_editable=False``
    olan anahtarlarda (unified_classifier) user prompt yapısını kod
    kurar — yalnız system prompt override edilebilir."""

    template_key: str
    title: str
    description: str
    system_prompt: str
    user_prompt_template: str
    response_schema: dict[str, Any]
    model_name: str
    required_variables: list[str]
    user_prompt_editable: bool = True


def _build_code_defaults() -> list[CodeDefaultTemplate]:
    from imga_core.llm.unified_classifier import UNIFIED_SYSTEM_PROMPT

    from imga_api.llm.prompts.executive_briefing_v1 import (
        EXECUTIVE_BRIEFING_SYSTEM_PROMPT,
        EXECUTIVE_BRIEFING_USER_PROMPT_TEMPLATE,
    )
    from imga_api.llm.prompts.okr_v1 import (
        OKR_RESPONSE_SCHEMA,
        OKR_SYSTEM_PROMPT,
        OKR_USER_PROMPT_TEMPLATE,
    )
    from imga_api.llm.prompts.quality_report_v1 import (
        QUALITY_REPORT_RESPONSE_SCHEMA,
        QUALITY_REPORT_SYSTEM_PROMPT,
        QUALITY_REPORT_USER_PROMPT_TEMPLATE,
    )
    from imga_api.llm.prompts.root_cause_v1 import (
        ROOT_CAUSE_RESPONSE_SCHEMA,
        ROOT_CAUSE_SYSTEM_PROMPT,
        ROOT_CAUSE_USER_PROMPT_TEMPLATE,
    )
    from imga_api.llm.prompts.swot_v1 import (
        SWOT_RESPONSE_SCHEMA,
        SWOT_SYSTEM_PROMPT,
        SWOT_USER_PROMPT_TEMPLATE,
    )
    from imga_api.services.executive_briefing_service import (
        DEFAULT_MODEL_NAME as BRIEFING_MODEL,
    )
    from imga_api.services.llm_provider_factory import (
        GEMINI_STRUCTURED_DEFAULT_MODEL,
    )
    from imga_api.services.okr_service import (
        DEFAULT_MODEL_NAME as OKR_MODEL,
    )
    from imga_api.services.onboarding_service import (
        ONBOARDING_SUGGEST_RESPONSE_SCHEMA,
        ONBOARDING_SUGGEST_SYSTEM_PROMPT,
    )
    from imga_api.services.swot_service import (
        DEFAULT_MODEL_NAME as SWOT_MODEL,
    )

    return [
        CodeDefaultTemplate(
            template_key="swot",
            title="SWOT Analizi",
            description=(
                "Güçlü/zayıf yönler, fırsatlar, tehditler ve stratejik "
                "tavsiyeleri üreten prompt."
            ),
            system_prompt=SWOT_SYSTEM_PROMPT,
            user_prompt_template=SWOT_USER_PROMPT_TEMPLATE,
            response_schema=SWOT_RESPONSE_SCHEMA,
            model_name=SWOT_MODEL,
            required_variables=[],
        ),
        CodeDefaultTemplate(
            template_key="okr",
            title="OKR Hedefleri",
            description=(
                "SWOT çıktısından 12 haftalık ölçülebilir hedefler "
                "üreten prompt."
            ),
            system_prompt=OKR_SYSTEM_PROMPT,
            user_prompt_template=OKR_USER_PROMPT_TEMPLATE,
            response_schema=OKR_RESPONSE_SCHEMA,
            model_name=OKR_MODEL,
            required_variables=[],
        ),
        CodeDefaultTemplate(
            template_key="briefing",
            title="Yönetici Özeti",
            description=(
                "Dönemsel KPI değişimleri, kritik içgörüler ve "
                "öncelikli aksiyonları üreten prompt."
            ),
            system_prompt=EXECUTIVE_BRIEFING_SYSTEM_PROMPT,
            user_prompt_template=EXECUTIVE_BRIEFING_USER_PROMPT_TEMPLATE,
            response_schema={},
            model_name=BRIEFING_MODEL,
            required_variables=[],
        ),
        CodeDefaultTemplate(
            template_key="unified_classifier",
            title="Yorum Sınıflandırma",
            description=(
                "Her yorumun duygu + kategori kararını veren birleşik "
                "sınıflandırma sistemi prompt'u. Yorum listesi ve "
                "düzeltme örnekleri sistem tarafından otomatik eklenir "
                "— yalnız sistem talimatı düzenlenebilir."
            ),
            system_prompt=UNIFIED_SYSTEM_PROMPT,
            user_prompt_template="(yorum listesi sistem tarafından kurulur)",
            response_schema={},
            model_name="gemini-3-flash-preview",
            required_variables=[],
            user_prompt_editable=False,
        ),
        # B8 (süper-admin denetim raporu) — root_cause/quality_report/
        # onboarding_suggest daha önce select_prompt()'a hiç bağlı
        # değildi (B1); katalogdaki eksiklikleri kapatıldıktan sonra
        # bunlar da /settings/prompts sayfasında görünür + override
        # edilebilir olmalı. required_variables=[] mevcut 4 girdinin
        # şekliyle bilinçli tutarlı (SWOT/OKR/briefing de gerçek Jinja
        # değişkenlerini burada listelemiyor).
        CodeDefaultTemplate(
            template_key="root_cause",
            title="Kök Neden Analizi",
            description=(
                "Bir alt kategori kovasındaki ham yorumlardan nokta "
                "atışı operasyonel kök nedenler çıkaran prompt."
            ),
            system_prompt=ROOT_CAUSE_SYSTEM_PROMPT,
            user_prompt_template=ROOT_CAUSE_USER_PROMPT_TEMPLATE,
            response_schema=ROOT_CAUSE_RESPONSE_SCHEMA,
            model_name=GEMINI_STRUCTURED_DEFAULT_MODEL,
            required_variables=[],
        ),
        CodeDefaultTemplate(
            template_key="quality_report",
            title="Veri Kalitesi Raporu",
            description=(
                "Toplu yükleme veri kalitesi bayraklarından (kopya/boş/"
                "şablon/anlamsız) Türkçe değerlendirme üreten prompt."
            ),
            system_prompt=QUALITY_REPORT_SYSTEM_PROMPT,
            user_prompt_template=QUALITY_REPORT_USER_PROMPT_TEMPLATE,
            response_schema=QUALITY_REPORT_RESPONSE_SCHEMA,
            model_name=GEMINI_STRUCTURED_DEFAULT_MODEL,
            required_variables=[],
        ),
        CodeDefaultTemplate(
            template_key="onboarding_suggest",
            title="Onboarding Kategori Önerisi",
            description=(
                "Kurumun sektörü/büyüklüğü/iş tanımına göre özel "
                "kategori ve alt taksonomi önerisi üreten prompt. Kurum "
                "bağlamı ve örnek yorumlar sistem tarafından otomatik "
                "eklenir — yalnız sistem talimatı düzenlenebilir."
            ),
            system_prompt=ONBOARDING_SUGGEST_SYSTEM_PROMPT,
            user_prompt_template=(
                "(kurum bağlamı ve örnek yorumlar sistem tarafından kurulur)"
            ),
            response_schema=ONBOARDING_SUGGEST_RESPONSE_SCHEMA,
            model_name=GEMINI_STRUCTURED_DEFAULT_MODEL,
            required_variables=[],
            user_prompt_editable=False,
        ),
    ]


@router.get(
    "/code-defaults",
    response_model=list[CodeDefaultTemplate],
    summary=(
        "Koda gömülü varsayılan prompt'lar — DB'de override yokken "
        "üretimin kullandığı içerik."
    ),
)
async def list_code_defaults(
    current: Annotated[CurrentUser, _SuperAdmin],
) -> list[CodeDefaultTemplate]:
    _require_active_tenant(current)
    return _build_code_defaults()


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
    current: Annotated[CurrentUser, _SuperAdmin],
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
    current: Annotated[CurrentUser, _SuperAdmin],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> PromptTemplateResponse:
    tenant_id = _require_active_tenant(current)
    # B8 — süper-admin denetim raporu: B1'in "sessiz tuzak" yarısını
    # kapatır. Öncesinde herhangi bir template_key kabul ediliyordu;
    # bir yanlış yazım (ör. "roon_cause") ya da var olmayan bir anahtar
    # DB'ye sorunsuzca yazılıyor ama HİÇBİR select_prompt() çağrısı onu
    # asla okumuyordu (kod hangi anahtarları aradığını sabit string
    # olarak biliyor). Doğrulama YALNIZ burada (yeni yazım) — GET
    # listelemesi bilerek değişmedi: DB'de whitelist-dışı eski bir satır
    # varsa yine görünür, yalnız yeni POST'lar reddedilir. PATCH/DELETE/
    # test endpoint'leri template_key almaz/değiştirmez, bu yüzden
    # doğrulama yalnız burada gerekli.
    valid_keys = {t.template_key for t in _build_code_defaults()}
    if body.template_key not in valid_keys:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"bilinmeyen şablon anahtarı: {body.template_key!r}; "
                f"geçerliler: {', '.join(sorted(valid_keys))}"
            ),
        )
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
    current: Annotated[CurrentUser, _SuperAdmin],
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
    current: Annotated[CurrentUser, _SuperAdmin],
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
    current: Annotated[CurrentUser, _SuperAdmin],
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
