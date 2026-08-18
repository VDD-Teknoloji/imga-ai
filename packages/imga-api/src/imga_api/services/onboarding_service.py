"""Kurum onboarding — AI kategori önerisi (2026-08-18, WS1).

İki adımlı akış:

  1. ``suggest_categories`` — tenant'ın sektör/büyüklük/iş tanımı/terim
     sözlüğü + (varsa) son yorumlarından bir örneklemi TEK structured
     LLM çağrısına gönderir; öneri PERSIST EDİLMEZ, yalnız döner.
     Kullanıcı /settings ya da onboarding sihirbazında öneriyi görür,
     istediği alt kümeyi seçer.
  2. ``apply_categories`` — seçilen alt küme tek transaction'da yazılır:
     custom ``Category`` satırları (``TenantConfigService.
     create_custom_category``), ``CategoryTaxonomy`` satırları
     (``tenant_config_service.create_taxonomy_entry`` — /tenants/me/
     taxonomies POST ile aynı yardımcı, kod tekrarı önlenir) ve globalleri
     kapatma (``TenantConfigService.toggle_category``).

Akış SWOT/OKR/brifing servisleriyle aynı iskeleti paylaşır (kimlik
yükleme -> sağlayıcı kurulum -> rotator ile çağrı -> hata sınıflama),
ama İKİ bilinçli sadeleştirmeyle:

  * Yeni bir ``generate_category_suggestion`` sağlayıcı metodu YOK —
    imga-core bu dalga donduruldu (Dalga-1 migration ajanı dışında
    kimse dokunmuyor). Dört ``generate_*`` metodu (swot/okr/root_cause/
    executive_briefing) hepsi ``_generate_structured``'a aynı imzayla
    (api_key, system_prompt, user_prompt, response_schema, model_name,
    temperature, top_p, max_output_tokens) yönlenen ince sarmalayıcı;
    ``generate_root_cause`` ödünç alınır (isim sızmaz — yalnız bu
    modülün içinde görünür, audit/log tarafında ayrı bir
    ``call_type`` kullanılmaz, bkz. aşağıdaki not).
  * ``llm_call_audit`` satırı YAZILMAZ — ``call_type`` kolonunda DB
    CHECK constraint var (``ck_llm_call_audit_call_type``:
    classification/briefing/strategic_report/action_extraction/okr/
    root_cause) ve yeni bir değer eklemek migration ister (Dalga-1
    dışında yasak). Görev bunu şart koşmuyor; SWOT/OKR'daki
    LLMCallAuditor sarmalaması burada bilinçli olarak YOK.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from imga_core.categories.taxonomy import (
    CATEGORY_DESCRIPTIONS_TR,
    GLOBAL_CATEGORY_CODES,
)
from imga_core.llm import (
    AllKeysExhaustedError,
    GeminiKeyRotator,
    InvalidKeyError,
    LLMError,
)
from imga_db.models import Category, CategoryTaxonomy, Review, Tenant
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.services.audit_service import AuditService
from imga_api.services.llm_credentials import (
    NoCredentialsError,
    load_active_llm_keys,
    mark_keys_failed,
)
from imga_api.services.llm_provider_factory import (
    StructuredProvider,
    build_structured_provider,
    resolve_model_name,
)
from imga_api.services.strategic_constants import (
    company_size_label,
    industry_label,
)
from imga_api.services.tenant_config_service import (
    CategoryCodeArchivedError,
    CategoryCodeConflictError,
    TenantConfigService,
    create_taxonomy_entry,
)

_logger = logging.getLogger(__name__)

# snake_case ASCII; bir alfa öncü, sonra alfa/rakam/alt çizgi —
# routes/tenant_taxonomies.py'deki _CODE_RE ile aynı kural.
_CODE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_CODE_MAX = 64
_LABEL_MAX = 128

SAMPLE_LIMIT_DEFAULT = 100
_SAMPLE_LIMIT_MAX = 300
_SAMPLE_SNIPPET_MAX_CHARS = 400
_TOP_CATEGORIES_MAX = 8
_SUBCATEGORIES_MAX = 20


class OnboardingServiceError(Exception):
    """Doğrulama / iş kuralı hatası — route 4xx'e çevirir."""


class OnboardingResponseInvalidError(OnboardingServiceError):
    """LLM'in döndürdüğü JSON, normalize sonrası kullanılabilir hiçbir
    öneri içermiyor (hepsi çakışma/şekil nedeniyle elendi)."""


@dataclass(frozen=True, slots=True)
class SuggestedCategory:
    code: str
    label_tr: str
    description: str


@dataclass(frozen=True, slots=True)
class SuggestedTaxonomy:
    code: str
    label_tr: str
    primary_category_code: str


@dataclass(frozen=True, slots=True)
class CategorySuggestion:
    top_categories: list[SuggestedCategory] = field(default_factory=list)
    subcategories: list[SuggestedTaxonomy] = field(default_factory=list)
    disable_global_codes: list[str] = field(default_factory=list)
    rationale: str = ""


@dataclass(frozen=True, slots=True)
class AppliedCategoriesResult:
    created_categories: list[str] = field(default_factory=list)
    created_taxonomies: list[str] = field(default_factory=list)
    disabled_global_codes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# LLM sözleşmesi
# ---------------------------------------------------------------------------

# Gemini SDK'nın proto-tabanlı Schema tipi minItems/maxItems bilmez
# (8.3.6.6 round-1 çökmesi, bkz. swot_v1.py); enum yalnız
# "type": "string" ile birlikte kabul edilir (round-3 çökmesi). İkisi
# de burada tekrarlanmadı çünkü bu şema enum KULLANMIYOR.
_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "top_categories",
        "subcategories",
        "disable_global_codes",
        "rationale",
    ],
    "properties": {
        "top_categories": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["code", "label_tr", "description"],
                "properties": {
                    "code": {"type": "string"},
                    "label_tr": {"type": "string"},
                    "description": {"type": "string"},
                },
            },
        },
        "subcategories": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["code", "label_tr", "primary_category_code"],
                "properties": {
                    "code": {"type": "string"},
                    "label_tr": {"type": "string"},
                    "primary_category_code": {"type": "string"},
                },
            },
        },
        "disable_global_codes": {
            "type": "array",
            "items": {"type": "string"},
        },
        "rationale": {"type": "string"},
    },
}

_SUGGESTION_SYSTEM_PROMPT = """\
Sen çok kurumlu bir müşteri geri bildirimi platformunun kategori \
mimarısın. Görevin: bir kurumun sektörüne, büyüklüğüne, iş tanımına \
ve (varsa) örnek müşteri yorumlarına bakarak kuruma ÖZEL üst-seviye \
şikayet/geri bildirim kategorileri ve alt-taksonomi (perspektif) \
önermek.

BAĞLAM:
Platformda 9 GLOBAL üst-seviye kategori zaten var (kargo, faturalama, \
urun_kalitesi, musteri_hizmetleri, iade, teknik_destek, siparis_sureci, \
pazarlama, belirsiz). Bu kategoriler her sektöre uymayabilir — örn. \
bir SaaS şirketi için "kargo" anlamsızdır; bir e-ticaret şirketi için \
teknik entegrasyon kategorisi gerekmeyebilir.

GÖREV:
1. top_categories: kuruma özel, GLOBAL kod kümesiyle ÇAKIŞMAYAN yeni \
   üst-seviye kategori önerileri (gerekmiyorsa boş liste dönebilirsin). \
   Her biri için: code (snake_case, ASCII), label_tr (kısa Türkçe \
   etiket), description (sınıflandırıcı promptuna gidecek, sınır \
   kuralı içeren 1-2 cümlelik tanım).
2. subcategories: hem global hem önerdiğin top_categories'in ALTINA \
   düşen daha ince taksonomi (perspektif) satırları. Her biri için: \
   code, label_tr, primary_category_code (bir global kod ya da senin \
   top_categories'te önerdiğin kodlardan biri olmalı).
3. disable_global_codes: bu kurumun sektöründe ANLAMSIZ olan global \
   kodlar (varsa).
4. rationale: önerinin kısa gerekçesi (2-4 cümle, Türkçe).

KURALLAR:
1. code alanları SADECE küçük harf, rakam ve alt çizgi (snake_case, \
   ASCII) — Türkçe karakter, boşluk, büyük harf KULLANMA.
2. GLOBAL kod kümesiyle (kargo, faturalama, urun_kalitesi, \
   musteri_hizmetleri, iade, teknik_destek, siparis_sureci, pazarlama, \
   belirsiz) çakışan code ÖNERME — bunlar zaten var.
3. "belirsiz" kodunu ASLA disable_global_codes'a ekleme — platformun \
   zorunlu fallback kovasıdır.
4. Örnek yorum verilmediyse yalnız sektör/iş tanımına dayan; yorum \
   uydurma.
5. Gereksiz kategori üretme — sektöre gerçekten uymayan ya da az \
   sayıda yorumu etkileyecek önerilerden kaçın; az sayıda isabetli \
   öneri, çok sayıda gereksiz öneriden iyidir.
6. Müşteri yorumlarında ve kurum sözlüğünde geçen alan terimlerini \
   BİREBİR koru; eş anlamlı/yakın kelimeyle değiştirme.
7. JSON formatında, response_schema'ya tam uyumlu yanıt ver.
"""


def _normalize_code(raw: Any) -> str | None:
    if not isinstance(raw, str):
        return None
    code = raw.strip().lower()
    if not code or len(code) > _CODE_MAX or not _CODE_RE.match(code):
        return None
    return code


def _normalize_label(raw: Any) -> str | None:
    if not isinstance(raw, str):
        return None
    label = raw.strip()
    if not label or len(label) > _LABEL_MAX:
        return None
    return label


def _render_user_prompt(
    *,
    tenant: Tenant,
    sample_reviews: list[str],
) -> str:
    lines: list[str] = [
        "KURUM BAĞLAMI:",
        f"- Sektör: {industry_label(tenant.industry, tenant.industry_other_text)}",
        f"- Büyüklük: {company_size_label(tenant.company_size)}",
    ]
    if tenant.business_description:
        lines.append(f"- İş tanımı: {tenant.business_description}")
    terminology = tenant.terminology or []
    term_lines = [
        (
            f"  - {entry.get('term')}"
            + (f" — {entry.get('note')}" if entry.get("note") else "")
        )
        for entry in terminology
        if isinstance(entry, dict) and entry.get("term")
    ]
    if term_lines:
        lines.append("- Terim sözlüğü:")
        lines.extend(term_lines)

    lines.append("")
    lines.append("MEVCUT GLOBAL KATEGORİLER (bunlarla ÇAKIŞMA):")
    for code in GLOBAL_CATEGORY_CODES:
        desc = CATEGORY_DESCRIPTIONS_TR.get(code, "")
        lines.append(f"- {code}: {desc}" if desc else f"- {code}")

    lines.append("")
    if sample_reviews:
        lines.append(f"ÖRNEK MÜŞTERİ YORUMLARI ({len(sample_reviews)} adet):")
        for i, text in enumerate(sample_reviews, start=1):
            snippet = text.strip().replace("\n", " ")[:_SAMPLE_SNIPPET_MAX_CHARS]
            lines.append(f"{i}. {snippet}")
    else:
        lines.append(
            "ÖRNEK MÜŞTERİ YORUMU YOK — yalnız sektör/iş tanımına dayan."
        )

    lines.append("")
    lines.append(
        "Yukarıdaki bağlama göre kategori önerisi üret. response_schema'ya "
        "tam uyumlu JSON yanıtla."
    )
    return "\n".join(lines)


class OnboardingService:
    """Tenant onboarding — AI kategori önerisi + uygulama."""

    def __init__(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        *,
        provider: StructuredProvider | None = None,
    ) -> None:
        self._session = session
        self._tenant_id = tenant_id
        self._audit = AuditService(session)
        # Provider injected for test isolation; production yolunda
        # sağlayıcı kurumun kazanan kimlik kaydına bağlı olduğu için
        # suggest_categories() içinde (DB'den seçim geldikten sonra)
        # kurulur (SWOT/OKR/brifing servisleriyle aynı desen).
        self._provider = provider

    async def suggest_categories(
        self, *, sample_limit: int = SAMPLE_LIMIT_DEFAULT
    ) -> CategorySuggestion:
        tenant = await self._session.get(Tenant, self._tenant_id)
        if tenant is None:
            raise OnboardingServiceError("tenant not found")

        sample_limit = max(0, min(sample_limit, _SAMPLE_LIMIT_MAX))
        sample_reviews: list[str] = []
        if sample_limit:
            rows = (
                await self._session.execute(
                    select(Review.text)
                    .where(Review.tenant_id == self._tenant_id)
                    .where(Review.deleted_at.is_(None))
                    .order_by(Review.analyzed_at.desc())
                    .limit(sample_limit)
                )
            ).scalars().all()
            sample_reviews = list(rows)

        key_selection = await load_active_llm_keys(self._session, self._tenant_id)
        if key_selection is None:
            raise NoCredentialsError(
                "Tenant has no active LLM API keys configured"
            )
        keys = key_selection.keys
        rotator = GeminiKeyRotator(keys)
        provider_name = key_selection.provider
        model_name = resolve_model_name(provider_name, key_selection.model)
        provider = self._provider or build_structured_provider(provider_name)

        user_prompt = _render_user_prompt(tenant=tenant, sample_reviews=sample_reviews)

        failed_invalid_key_ids: list[UUID] = []

        async def _call(api_key: str) -> tuple[dict[str, Any], dict[str, int] | None]:
            try:
                # 2026-08-18 — imga-core bu dalga donduruldu; ayrı bir
                # ``generate_category_suggestion`` metodu eklemek
                # yerine mevcut dört ince sarmalayıcıdan biri ödünç
                # alınır (hepsi aynı imzayla ``_generate_structured``a
                # yönlenir, bkz. modül docstring'i). temperature/
                # max_output_tokens açıkça geçilir — ödünç alınan
                # metodun kendi varsayılanlarına güvenilmez.
                return await provider.generate_root_cause(
                    api_key=api_key,
                    system_prompt=_SUGGESTION_SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                    response_schema=_RESPONSE_SCHEMA,
                    model_name=model_name,
                    temperature=0.3,
                    top_p=0.9,
                    max_output_tokens=4096,
                )
            except InvalidKeyError:
                for k in keys:
                    if k.value == api_key:
                        failed_invalid_key_ids.append(UUID(k.id))
                        break
                raise

        try:
            (response, _token_usage), _key_used = await rotator.call_with_rotation(
                _call
            )
        except AllKeysExhaustedError:
            # Rotator boyunca InvalidKey ile düşen key'ler burada
            # işaretlenir (SWOT/OKR servisleriyle aynı desen).
            await mark_keys_failed(self._session, failed_invalid_key_ids)
            raise
        except LLMError:
            # Diğer LLMError (Malformed, generic) — key'ler işaretlenmez.
            raise

        # Kazanan denemeden ÖNCE bir üst-öncelikli key InvalidKey ile
        # düştüyse, başarılı yolda da işaretlenir.
        if failed_invalid_key_ids:
            await mark_keys_failed(self._session, failed_invalid_key_ids)

        return await self._normalize_response(response)

    async def _normalize_response(
        self, response: dict[str, Any]
    ) -> CategorySuggestion:
        """OpenRouter yolu şemayı strict:false ile yalnız tavsiye
        olarak gönderir — eksik/şekli bozuk madde atlanabiliyor
        (bkz. memory: LLM-payload şekil sertleştirmesi). Burada da
        aynı disiplin: eksik/şekli bozuk/çakışan madde SESSİZCE
        filtrelenir, tüm cevap reddedilmez."""
        reserved = set(GLOBAL_CATEGORY_CODES)

        # 2026-08-18 (bulgu) — ARŞİVLENMİŞ (soft-deleted) custom kodlar
        # da çakışma kümesine girer: uq_categories_per_tenant_code
        # (migration 0005) deleted_at'i saymaz, yani arşivli bir kod DB
        # seviyesinde hâlâ "dolu". deleted_at filtresi kaldırılmadan
        # önce aynı kod tekrar önerilip apply-categories'te ham
        # IntegrityError'a çarpabiliyordu (bkz. tenant_config_service.
        # create_custom_category'nin CategoryCodeArchivedError kontrolü
        # — bu filtre onun ÖNÜNE geçip kullanıcıya baştan öneriyi hiç
        # göstermez).
        existing_custom_codes = set(
            (
                await self._session.execute(
                    select(Category.code).where(
                        Category.tenant_id == self._tenant_id
                    )
                )
            ).scalars().all()
        )
        existing_taxonomy_codes = set(
            (
                await self._session.execute(
                    select(CategoryTaxonomy.code).where(
                        CategoryTaxonomy.tenant_id == self._tenant_id
                    )
                )
            ).scalars().all()
        )

        top: list[SuggestedCategory] = []
        seen_top_codes: set[str] = set()
        for item in _as_list(response.get("top_categories")):
            if not isinstance(item, dict):
                continue
            code = _normalize_code(item.get("code"))
            label = _normalize_label(item.get("label_tr"))
            description = str(item.get("description") or "").strip()
            if code is None or label is None:
                continue
            if code in reserved or code in existing_custom_codes:
                continue
            if code in seen_top_codes:
                continue
            seen_top_codes.add(code)
            top.append(
                SuggestedCategory(code=code, label_tr=label, description=description)
            )
            if len(top) >= _TOP_CATEGORIES_MAX:
                break

        allowed_primary = reserved | seen_top_codes
        subs: list[SuggestedTaxonomy] = []
        seen_sub_codes: set[str] = set()
        for item in _as_list(response.get("subcategories")):
            if not isinstance(item, dict):
                continue
            code = _normalize_code(item.get("code"))
            label = _normalize_label(item.get("label_tr"))
            primary = _normalize_code(item.get("primary_category_code"))
            if code is None or label is None or primary is None:
                continue
            if primary not in allowed_primary:
                continue
            if code in existing_taxonomy_codes or code in seen_sub_codes:
                continue
            seen_sub_codes.add(code)
            subs.append(
                SuggestedTaxonomy(
                    code=code, label_tr=label, primary_category_code=primary
                )
            )
            if len(subs) >= _SUBCATEGORIES_MAX:
                break

        disable: list[str] = []
        for raw_code in _as_list(response.get("disable_global_codes")):
            code = _normalize_code(raw_code)
            if code is None or code not in reserved or code == "belirsiz":
                continue
            if code in disable:
                continue
            disable.append(code)

        rationale = str(response.get("rationale") or "").strip()

        return CategorySuggestion(
            top_categories=top,
            subcategories=subs,
            disable_global_codes=disable,
            rationale=rationale,
        )

    async def apply_categories(
        self,
        *,
        config: TenantConfigService,
        top_categories: list[dict[str, Any]],
        subcategories: list[dict[str, Any]],
        disable_global_codes: list[str],
        actor_user_id: UUID,
    ) -> AppliedCategoriesResult:
        """Kullanıcının seçtiği alt küme — tek transaction (çağıran
        route ``async with app_session.begin():`` içinde çağırır).
        Her alt-adım kendi audit satırını zaten yazar
        (TenantConfigService.create_custom_category / toggle_category,
        create_taxonomy_entry -> TaxonomyEditAudit); burada ayrıca bir
        özet ``tenant.onboarding.apply_categories`` audit_logs satırı
        düşülür ki onboarding eylemi tekil kategori düzenlemelerinden
        ayırt edilebilsin."""
        tenant_id = self._tenant_id
        reserved = set(GLOBAL_CATEGORY_CODES)

        created_categories: list[str] = []
        created_category_codes: set[str] = set()
        for item in top_categories:
            code = _normalize_code(item.get("code"))
            label = _normalize_label(item.get("label_tr"))
            if code is None or label is None:
                raise OnboardingServiceError(f"Geçersiz kategori: {item!r}")
            if code in reserved:
                raise OnboardingServiceError(
                    f"code {code!r} global bir kodla çakışıyor"
                )
            description = str(item.get("description") or "").strip() or None
            try:
                cat = await config.create_custom_category(
                    tenant_id,
                    code=code,
                    label_tr=label,
                    description=description,
                    actor_user_id=actor_user_id,
                )
            except CategoryCodeArchivedError:
                # 2026-08-18 (bulgu) — arşivli-kod çakışması AYNEN
                # yükselir (OnboardingServiceError'a SARILMAZ) — route
                # katmanı (_onboarding_error_to_http) bunu özel olarak
                # yakalayıp temiz Türkçe 409'a çevirir. Genel
                # CategoryCodeConflictError (global/aktif çakışma) eski
                # davranışta kalır: 400.
                raise
            except CategoryCodeConflictError as exc:
                raise OnboardingServiceError(str(exc)) from exc
            created_categories.append(cat.code)
            created_category_codes.add(cat.code)

        # primary_category_code doğrulama kümesi: globaller + tenant'ın
        # mevcut customları + bu payload'da az önce oluşan customlar
        # (routes/tenant_taxonomies.py'nin GLOBAL_CATEGORY_CODES-only
        # kısıtından bilinçli olarak daha geniş — bkz. modül
        # docstring'i / tenant_config_service.create_taxonomy_entry).
        existing_custom_codes = set(
            (
                await self._session.execute(
                    select(Category.code)
                    .where(Category.tenant_id == tenant_id)
                    .where(Category.deleted_at.is_(None))
                )
            ).scalars().all()
        )
        allowed_primary = reserved | created_category_codes | existing_custom_codes

        created_taxonomies: list[str] = []
        for item in subcategories:
            code = _normalize_code(item.get("code"))
            label = _normalize_label(item.get("label_tr"))
            primary = _normalize_code(item.get("primary_category_code"))
            if code is None or label is None:
                raise OnboardingServiceError(f"Geçersiz alt kategori: {item!r}")
            if primary is not None and primary not in allowed_primary:
                raise OnboardingServiceError(
                    f"primary_category_code geçersiz: {primary!r}"
                )
            existing = (
                await self._session.execute(
                    select(CategoryTaxonomy.id)
                    .where(CategoryTaxonomy.tenant_id == tenant_id)
                    .where(CategoryTaxonomy.code == code)
                )
            ).scalar_one_or_none()
            if existing is not None:
                raise OnboardingServiceError(
                    f"code {code!r} bu tenant için zaten var"
                )
            row = await create_taxonomy_entry(
                self._session,
                tenant_id=tenant_id,
                user_id=actor_user_id,
                code=code,
                label_tr=label,
                primary_category_code=primary,
            )
            created_taxonomies.append(row.code)

        disabled: list[str] = []
        for raw_code in disable_global_codes:
            code = _normalize_code(raw_code)
            if code is None or code not in reserved or code == "belirsiz":
                continue
            cat_id = (
                await self._session.execute(
                    select(Category.id)
                    .where(Category.tenant_id.is_(None))
                    .where(Category.code == code)
                )
            ).scalar_one_or_none()
            if cat_id is None:
                continue
            await config.toggle_category(
                tenant_id, cat_id, is_enabled=False, actor_user_id=actor_user_id
            )
            disabled.append(code)

        await self._audit.log(
            action="tenant.onboarding.apply_categories",
            resource_type="tenant",
            resource_id=tenant_id,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            details={
                "created_categories": created_categories,
                "created_taxonomies": created_taxonomies,
                "disabled_global_codes": disabled,
            },
        )

        return AppliedCategoriesResult(
            created_categories=created_categories,
            created_taxonomies=created_taxonomies,
            disabled_global_codes=disabled,
        )


def _as_list(raw: Any) -> list[Any]:
    return raw if isinstance(raw, list) else []


__all__ = [
    "SAMPLE_LIMIT_DEFAULT",
    "AppliedCategoriesResult",
    "CategorySuggestion",
    "OnboardingResponseInvalidError",
    "OnboardingService",
    "OnboardingServiceError",
    "SuggestedCategory",
    "SuggestedTaxonomy",
]
