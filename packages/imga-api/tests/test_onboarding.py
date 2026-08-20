"""2026-08-18 (migration 0042, WS1) — onboarding + AI kategori önerisi.

Kapsam:
  * POST /admin/tenants — opsiyonel profil alanları (industry/
    company_size/business_description/terminology) Tenant satırına
    yazılıyor.
  * POST /v1/admin/tenants (partner API) — TenantService.create
    üzerinden geçiyor: bug fix, kategori/taksonomi bootstrap artık
    ATLANMIYOR.
  * OnboardingService.suggest_categories — TEK LLM çağrısı (mock
    provider), normalize: global kod çakışması + bilinmeyen
    primary_category_code filtrelenir, sonuç PERSIST EDİLMEZ.
  * OnboardingService.apply_categories — seçilen alt küme tek
    transaction'da yazılır (custom Category + CategoryTaxonomy +
    global toggle); geçersiz kod/primary → OnboardingServiceError.
  * Route katmanı: rol/authz (TENANT_ADMIN), NoCredentialsError → 412.

Desenler test_admin_invitations.py (super_admin fixture) ve
test_swot_service.py'den (mock provider injection) alınmıştır.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from imga_db.models import (
    Category,
    CategoryTaxonomy,
    Tenant,
    TenantCategory,
    User,
    UserTenantRole,
)
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.security import hash_password
from imga_api.services import AuditService, UserService
from tests.batch_helpers import login_token

SUPER_ADMIN_PASSWORD = "test-super-admin-pwd-32-chars-min"


@pytest.fixture(autouse=True)
def _reset_rate_limit_buckets() -> None:
    """Süper-admin login çağrıları rate-limit sayaçlarını paylaşır;
    her test temiz başlasın (test_admin_invitations.py ile aynı
    önlem)."""
    from imga_api.rate_limit import reset_for_tests

    reset_for_tests()


@pytest.fixture
async def super_admin(admin_session: AsyncSession) -> Any:
    """Migration 0001'in seed ettiği admin@imga.ai satırının şifresini
    testin bildiği bir değere çeker (test_admin_invitations.py ile
    aynı desen)."""
    async with admin_session.begin():
        await admin_session.execute(
            text(
                "UPDATE users SET password_hash = :pw, is_active = true "
                "WHERE email = 'admin@imga.ai'"
            ),
            {"pw": hash_password(SUPER_ADMIN_PASSWORD)},
        )
        user = (
            await admin_session.execute(
                select(User).where(User.email == "admin@imga.ai")
            )
        ).scalar_one()
    return user


async def _add_viewer(
    admin_session: AsyncSession, tenant_id: UUID
) -> tuple[str, str]:
    audit = AuditService(admin_session)
    usvc = UserService(admin_session, audit)
    plain = "Viewer-Pwd-123456"
    email = f"viewer-{uuid4().hex[:8]}@example.com"
    async with admin_session.begin():
        user = await usvc.create(email=email, password=plain, full_name="Viewer")
        await usvc.attach_to_tenant(
            user_id=user.id, tenant_id=tenant_id, role=UserTenantRole.VIEWER
        )
    return email, plain


async def _bind_tenant_raw(session: AsyncSession, tenant_id: UUID) -> None:
    await session.execute(
        text("SELECT set_config('app.current_tenant_id', :t, true)"),
        {"t": str(tenant_id)},
    )


def _login_super_admin(client: TestClient, email: str, password: str) -> str:
    """``login_token`` (batch_helpers.py) her zaman ``active_tenant_id``
    gönderir — süper-admin'in aktif tenant'ı yok, alanı hiç
    göndermeyen ayrı bir yardımcı gerekir (test_admin_invitations.py
    ``_login`` ile aynı desen)."""
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return str(r.json()["access_token"])


# ---------------------------------------------------------------------------
# GÖREV A.1 — admin tenant create profil alanları
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_create_tenant_with_profile_fields(
    batch_client: TestClient,
    super_admin: User,
    admin_session: AsyncSession,
) -> None:
    token = _login_super_admin(batch_client, "admin@imga.ai", SUPER_ADMIN_PASSWORD)
    slug = f"onboard-{uuid4().hex[:6]}"
    r = batch_client.post(
        "/admin/tenants",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "Onboard Test A.Ş.",
            "slug": slug,
            "industry": "e_commerce",
            "company_size": "small",
            "business_description": "Test amaçlı e-ticaret şirketi.",
            "terminology": [
                {"term": "çok parçalı gönderi", "note": "birden fazla kutu"},
            ],
        },
    )
    assert r.status_code == 201, r.text
    tenant_id = UUID(r.json()["tenant"]["id"])

    async with admin_session.begin():
        tenant = await admin_session.get(Tenant, tenant_id)
        assert tenant is not None
        assert tenant.industry == "e_commerce"
        assert tenant.company_size == "small"
        assert tenant.business_description == "Test amaçlı e-ticaret şirketi."
        assert tenant.terminology == [
            {"term": "çok parçalı gönderi", "note": "birden fazla kutu"}
        ]


@pytest.mark.asyncio
async def test_admin_create_tenant_without_profile_fields_stays_empty(
    batch_client: TestClient,
    super_admin: User,
    admin_session: AsyncSession,
) -> None:
    """Profil alanları opsiyonel — boş bırakılırsa eski davranış
    (None) korunur."""
    token = _login_super_admin(batch_client, "admin@imga.ai", SUPER_ADMIN_PASSWORD)
    slug = f"onboard-empty-{uuid4().hex[:6]}"
    r = batch_client.post(
        "/admin/tenants",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Bos Profil A.Ş.", "slug": slug},
    )
    assert r.status_code == 201, r.text
    tenant_id = UUID(r.json()["tenant"]["id"])

    async with admin_session.begin():
        tenant = await admin_session.get(Tenant, tenant_id)
        assert tenant is not None
        assert tenant.industry is None
        assert tenant.terminology is None


# ---------------------------------------------------------------------------
# GÖREV A.2 — v1 partner API tenant create artık taksonomi seed'liyor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v1_create_tenant_seeds_taxonomy_and_categories(
    admin_session: AsyncSession,
) -> None:
    """2026-08-18 bug fix — v1/admin/tenants artık TenantService.create
    üzerinden geçiyor; önceden çıplak ``Tenant(...)`` satırı
    tenant_categories + category_taxonomies bootstrap'ını atlıyordu.
    HTTP/ops-token katmanını (pepper kurulumu) atlayıp route
    fonksiyonunu doğrudan çağırıyoruz — test_review_corrections.py'
    deki _apply_corrections / _apply_manual_corrections deseniyle
    aynı (bare-function call, gerçek DB session)."""
    from imga_db.seeds import DEFAULT_COMPANY_TAXONOMY

    from imga_api.v1.admin_tenants import TenantCreateRequest, create_tenant
    from imga_api.v1.auth import ApiPrincipal

    principal = ApiPrincipal(kind="ops", token_id=uuid4(), tenant_id=None)
    body = TenantCreateRequest(
        name=f"V1 Bootstrap {uuid4().hex[:6]}",
        contact_email="ops@example.com",
    )
    response = await create_tenant(body, principal, admin_session)

    async with admin_session.begin():
        tenant_id = (
            await admin_session.execute(
                select(Tenant.id).where(Tenant.slug == response.tenant_id)
            )
        ).scalar_one()
        cat_count = (
            await admin_session.execute(
                select(TenantCategory).where(TenantCategory.tenant_id == tenant_id)
            )
        ).scalars().all()
        taxonomy_rows = (
            await admin_session.execute(
                select(CategoryTaxonomy).where(
                    CategoryTaxonomy.tenant_id == tenant_id
                )
            )
        ).scalars().all()
    assert len(cat_count) > 0, "kategori bootstrap atlanmamalı"
    assert len(taxonomy_rows) == len(DEFAULT_COMPANY_TAXONOMY)


# ---------------------------------------------------------------------------
# GÖREV A.3 — suggest-categories (mock LLM sağlayıcı)
# ---------------------------------------------------------------------------


def _suggestion_payload() -> dict[str, Any]:
    return {
        "top_categories": [
            {
                "code": "abonelik_iptali",
                "label_tr": "Abonelik İptali",
                "description": "Abonelik iptal talepleri ve süreci.",
            },
            {
                # Global koda çakışıyor — normalize elemeli.
                "code": "kargo",
                "label_tr": "Bu elenmeli",
                "description": "x",
            },
        ],
        "subcategories": [
            {
                "code": "trial_iptali",
                "label_tr": "Deneme Süresi İptali",
                "primary_category_code": "abonelik_iptali",
            },
            {
                # primary_category_code hiçbir kümede yok — elenmeli.
                "code": "gecersiz_alt",
                "label_tr": "X",
                "primary_category_code": "olmayan_kod",
            },
        ],
        "disable_global_codes": ["urun_kalitesi", "belirsiz"],
        "rationale": "SaaS aboneliği için kargo/ürün kalitesi anlamsız.",
    }


def _build_mock_onboarding_provider(
    *, payload: dict[str, Any] | None = None, side_effect: Exception | None = None
) -> Any:
    """generate_root_cause ödünç alınan yöntemdir — bkz.
    onboarding_service.py modül docstring'i."""
    from imga_core.llm.gemini import GeminiProvider

    provider = GeminiProvider.__new__(GeminiProvider)
    if side_effect is not None:
        provider.generate_root_cause = AsyncMock(side_effect=side_effect)  # type: ignore[method-assign]
    else:
        provider.generate_root_cause = AsyncMock(  # type: ignore[method-assign]
            return_value=(payload or _suggestion_payload(), None)
        )
    return provider


@pytest.mark.asyncio
async def test_suggest_categories_filters_collisions_and_invalid_primary(
    admin_session: AsyncSession,
    semi_auto_tenant: tuple[User, UUID, str],
    mock_gemini_credential: Any,
) -> None:
    from imga_api.services.onboarding_service import OnboardingService

    _user, tid, _pw = semi_auto_tenant
    await mock_gemini_credential(tid, "fake-key", priority=0)

    async with admin_session.begin():
        await _bind_tenant_raw(admin_session, tid)
        service = OnboardingService(
            admin_session, tid, provider=_build_mock_onboarding_provider()
        )
        suggestion = await service.suggest_categories(sample_limit=0)

    top_codes = {c.code for c in suggestion.top_categories}
    assert top_codes == {"abonelik_iptali"}, "global koda çakışan öneri elenmeli"

    sub_codes = {t.code for t in suggestion.subcategories}
    assert sub_codes == {"trial_iptali"}, (
        "primary_category_code hiçbir kümede olmayan alt kategori elenmeli"
    )

    assert suggestion.disable_global_codes == ["urun_kalitesi"], (
        "'belirsiz' asla disable listesine giremez"
    )
    assert suggestion.rationale == (
        "SaaS aboneliği için kargo/ürün kalitesi anlamsız."
    )


@pytest.mark.asyncio
async def test_suggest_categories_excludes_archived_custom_code(
    admin_session: AsyncSession,
    semi_auto_tenant: tuple[User, UUID, str],
    mock_gemini_credential: Any,
) -> None:
    """2026-08-18 (bulgu düzeltmesi) — arşivlenmiş (soft-deleted) bir
    custom kategori kodu çakışma kümesinden düşmemeli.
    ``uq_categories_per_tenant_code`` (migration 0005) ``deleted_at``'i
    saymaz, yani arşivli bir kod DB seviyesinde hâlâ "dolu"; eski
    filtre (yalnız ``deleted_at IS NULL``) bu kodu yeniden önerip
    apply-categories'te ham IntegrityError'a çarpardı."""
    from cachetools import TTLCache

    from imga_api.services.audit_service import AuditService
    from imga_api.services.onboarding_service import OnboardingService
    from imga_api.services.tenant_config_service import TenantConfigService

    user, tid, _pw = semi_auto_tenant
    await mock_gemini_credential(tid, "fake-key", priority=0)

    async with admin_session.begin():
        await _bind_tenant_raw(admin_session, tid)
        cache: TTLCache[UUID, dict[str, Any]] = TTLCache(maxsize=10, ttl=60)
        config = TenantConfigService(
            admin_session, AuditService(admin_session), cache
        )
        cat = await config.create_custom_category(
            tid,
            code="abonelik_iptali",
            label_tr="Abonelik İptali",
            actor_user_id=user.id,
        )
        await config.archive_custom_category(tid, cat.id, actor_user_id=user.id)

    async with admin_session.begin():
        await _bind_tenant_raw(admin_session, tid)
        service = OnboardingService(
            admin_session, tid, provider=_build_mock_onboarding_provider()
        )
        suggestion = await service.suggest_categories(sample_limit=0)

    top_codes = {c.code for c in suggestion.top_categories}
    assert "abonelik_iptali" not in top_codes, "arşivli kod yeniden önerilmemeli"


@pytest.mark.asyncio
async def test_suggest_categories_uses_tenant_prompt_override(
    admin_session: AsyncSession,
    semi_auto_tenant: tuple[User, UUID, str],
    mock_gemini_credential: Any,
) -> None:
    """B1c — bir tenant override'ı ``prompt_templates``'a yazıldığında
    ``OnboardingService.suggest_categories`` sağlayıcıya override'ın
    system/user prompt'unu göndermeli, kod sabitlerini DEĞİL (öncesinde
    hiç ``select_prompt`` çağrılmıyordu — süper-admin denetim raporu
    B1). Override satırı hem system hem user prompt taşıdığında ikisi
    de birlikte kazanır — ``_render_user_prompt`` yalnız override YOKKEN
    ya da render PATLADIĞINDA devreye giren fallback'tir."""
    from imga_db.models import PromptTemplate

    from imga_api.services.onboarding_service import OnboardingService

    _user, tid, _pw = semi_auto_tenant
    await mock_gemini_credential(tid, "fake-key", priority=0)

    async with admin_session.begin():
        await _bind_tenant_raw(admin_session, tid)
        admin_session.add(
            PromptTemplate(
                template_key="onboarding_suggest",
                tenant_id=tid,
                system_prompt="ÖZEL SİSTEM PROMPTU - TEST OVERRIDE",
                user_prompt_template="ÖZEL KULLANICI PROMPTU - TEST OVERRIDE",
                response_schema={},
                model_name="gemini-3-flash-preview",
                is_active=True,
                is_default=True,
                required_variables=[],
            )
        )
        await admin_session.flush()

    provider = _build_mock_onboarding_provider()
    async with admin_session.begin():
        await _bind_tenant_raw(admin_session, tid)
        service = OnboardingService(admin_session, tid, provider=provider)
        await service.suggest_categories(sample_limit=0)

    kwargs = provider.generate_root_cause.await_args.kwargs
    assert kwargs["system_prompt"] == "ÖZEL SİSTEM PROMPTU - TEST OVERRIDE"
    assert kwargs["user_prompt"] == "ÖZEL KULLANICI PROMPTU - TEST OVERRIDE"


@pytest.mark.asyncio
async def test_suggest_categories_records_llm_audit_row(
    admin_session: AsyncSession,
    semi_auto_tenant: tuple[User, UUID, str],
    mock_gemini_credential: Any,
) -> None:
    """B5 — süper-admin denetim raporu: onboarding önerisi artık
    llm_call_audit'e yazıyor (öncesinde swot/root_cause'un aksine hiç
    auditor sarmalaması yoktu — bkz. onboarding_service.py modül
    docstring'i, 'Dalga-1 dışında yasak' notu). Migration 0045
    ``ck_llm_call_audit_call_type`` kısıtına ``'onboarding_suggest'``
    eklenmeden bu satır CheckViolation ile SESSİZCE düşer
    (``LLMCallAuditor`` savepoint içinde yutar, bkz. o dosyanın
    ``_insert_row`` docstring'i) — bu test yalnız 0045 sonrası
    anlamlıdır (lokalde şu an koşulamıyor)."""
    from imga_db.models import LlmCallAudit

    from imga_api.services.onboarding_service import OnboardingService

    _user, tid, _pw = semi_auto_tenant
    await mock_gemini_credential(tid, "fake-key", priority=0)

    async with admin_session.begin():
        await _bind_tenant_raw(admin_session, tid)
        service = OnboardingService(
            admin_session, tid, provider=_build_mock_onboarding_provider()
        )
        await service.suggest_categories(sample_limit=0)

    async with admin_session.begin():
        await _bind_tenant_raw(admin_session, tid)
        rows = (
            await admin_session.execute(
                select(LlmCallAudit)
                .where(LlmCallAudit.tenant_id == tid)
                .where(LlmCallAudit.call_type == "onboarding_suggest")
            )
        ).scalars().all()

    assert len(rows) == 1, (
        "onboarding_suggest cagrisi tam olarak bir llm_call_audit satiri "
        "birakmali; 0 ise migration 0045 (ck_llm_call_audit_call_type + "
        "'onboarding_suggest') henuz uygulanmamis demektir"
    )
    audit = rows[0]
    assert audit.success is True
    assert audit.related_entity_type == "tenant"
    assert audit.prompt_template_key == "onboarding_suggest"


@pytest.mark.asyncio
async def test_suggest_categories_no_credentials_raises(
    admin_session: AsyncSession,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    from imga_api.services.llm_credentials import NoCredentialsError
    from imga_api.services.onboarding_service import OnboardingService

    _user, tid, _pw = semi_auto_tenant
    async with admin_session.begin():
        await _bind_tenant_raw(admin_session, tid)
        service = OnboardingService(
            admin_session, tid, provider=_build_mock_onboarding_provider()
        )
        with pytest.raises(NoCredentialsError):
            await service.suggest_categories()


# ---------------------------------------------------------------------------
# GÖREV A.3 — apply-categories (LLM çağrısı YOK, gerçek DB)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_categories_creates_rows_and_disables_global(
    admin_session: AsyncSession,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    from cachetools import TTLCache

    from imga_api.services.onboarding_service import OnboardingService
    from imga_api.services.tenant_config_service import TenantConfigService

    user, tid, _pw = semi_auto_tenant
    async with admin_session.begin():
        await _bind_tenant_raw(admin_session, tid)
        cache: TTLCache[UUID, dict[str, Any]] = TTLCache(maxsize=10, ttl=60)
        config = TenantConfigService(admin_session, AuditService(admin_session), cache)
        service = OnboardingService(admin_session, tid)
        result = await service.apply_categories(
            config=config,
            top_categories=[
                {
                    "code": "abonelik_iptali",
                    "label_tr": "Abonelik İptali",
                    "description": "test",
                }
            ],
            subcategories=[
                {
                    "code": "trial_iptali",
                    "label_tr": "Deneme İptali",
                    "primary_category_code": "abonelik_iptali",
                }
            ],
            disable_global_codes=["urun_kalitesi"],
            actor_user_id=user.id,
        )

        assert result.created_categories == ["abonelik_iptali"]
        assert result.created_taxonomies == ["trial_iptali"]
        assert result.disabled_global_codes == ["urun_kalitesi"]

        cat = (
            await admin_session.execute(
                select(Category).where(
                    Category.tenant_id == tid, Category.code == "abonelik_iptali"
                )
            )
        ).scalar_one()
        assert cat.label_tr == "Abonelik İptali"

        taxonomy = (
            await admin_session.execute(
                select(CategoryTaxonomy).where(
                    CategoryTaxonomy.tenant_id == tid,
                    CategoryTaxonomy.code == "trial_iptali",
                )
            )
        ).scalar_one()
        assert taxonomy.primary_category_code == "abonelik_iptali"

        urun_kalitesi_id = (
            await admin_session.execute(
                select(Category.id).where(
                    Category.tenant_id.is_(None), Category.code == "urun_kalitesi"
                )
            )
        ).scalar_one()
        tc = await admin_session.get(TenantCategory, (tid, urun_kalitesi_id))
        assert tc is not None
        assert tc.is_enabled is False


@pytest.mark.asyncio
async def test_apply_categories_records_decision_audit(
    admin_session: AsyncSession,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    """B3d — süper-admin denetim raporu: Karar Geçmişi'ne 'onboarding
    categories applied' eylemi (``tenant_kpi_goals.py:195``'teki
    ``DecisionAuditService`` çağrı deseniyle aynı). Migration 0045
    ``ck_decision_audit_log_type`` kısıtına
    ``'onboarding_categories_applied'`` eklenmeden bu çağrı
    CheckViolation ile PATLAR (``DecisionAuditService.record_decision``
    hatayı yutmaz) — bu test yalnız 0045 sonrası anlamlıdır (lokalde
    şu an koşulamıyor)."""
    from cachetools import TTLCache
    from imga_db.models import DecisionAuditLog

    from imga_api.services.onboarding_service import OnboardingService
    from imga_api.services.tenant_config_service import TenantConfigService

    user, tid, _pw = semi_auto_tenant
    async with admin_session.begin():
        await _bind_tenant_raw(admin_session, tid)
        cache: TTLCache[UUID, dict[str, Any]] = TTLCache(maxsize=10, ttl=60)
        config = TenantConfigService(admin_session, AuditService(admin_session), cache)
        service = OnboardingService(admin_session, tid)
        await service.apply_categories(
            config=config,
            top_categories=[
                {
                    "code": "abonelik_iptali",
                    "label_tr": "Abonelik İptali",
                    "description": "test",
                }
            ],
            subcategories=[],
            disable_global_codes=[],
            actor_user_id=user.id,
        )

    async with admin_session.begin():
        await _bind_tenant_raw(admin_session, tid)
        row = (
            await admin_session.execute(
                select(DecisionAuditLog)
                .where(DecisionAuditLog.tenant_id == tid)
                .where(
                    DecisionAuditLog.decision_type
                    == "onboarding_categories_applied"
                )
            )
        ).scalar_one()

    assert row.related_entity_type == "tenant"
    assert row.related_entity_id == tid
    assert row.actor_user_id == user.id
    assert row.payload["created_categories_count"] == 1
    assert row.payload["created_taxonomies_count"] == 0
    assert row.payload["disabled_global_codes_count"] == 0


@pytest.mark.asyncio
async def test_apply_categories_rejects_global_collision_and_bad_primary(
    admin_session: AsyncSession,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    from cachetools import TTLCache

    from imga_api.services.onboarding_service import (
        OnboardingService,
        OnboardingServiceError,
    )
    from imga_api.services.tenant_config_service import TenantConfigService

    user, tid, _pw = semi_auto_tenant
    async with admin_session.begin():
        await _bind_tenant_raw(admin_session, tid)
        cache: TTLCache[UUID, dict[str, Any]] = TTLCache(maxsize=10, ttl=60)
        config = TenantConfigService(admin_session, AuditService(admin_session), cache)
        service = OnboardingService(admin_session, tid)

        with pytest.raises(OnboardingServiceError):
            await service.apply_categories(
                config=config,
                top_categories=[{"code": "kargo", "label_tr": "Global çakışması"}],
                subcategories=[],
                disable_global_codes=[],
                actor_user_id=user.id,
            )

        with pytest.raises(OnboardingServiceError):
            await service.apply_categories(
                config=config,
                top_categories=[],
                subcategories=[
                    {
                        "code": "x",
                        "label_tr": "Y",
                        "primary_category_code": "olmayan_kod",
                    }
                ],
                disable_global_codes=[],
                actor_user_id=user.id,
            )


@pytest.mark.asyncio
async def test_apply_categories_archived_code_conflict_returns_clean_409(
    admin_session: AsyncSession,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    """2026-08-18 (bulgu düzeltmesi) — arşivlenmiş bir custom kodla
    apply-categories'te AYNI kodu yeniden oluşturmaya çalışmak
    CategoryCodeArchivedError fırlatır (ham asyncpg IntegrityError
    DEĞİL — tenant_config_service.create_custom_category'nin pre-check'i
    ya da flush() etrafındaki savunma katmanı bunu yakalar)."""
    from cachetools import TTLCache

    from imga_api.services.onboarding_service import OnboardingService
    from imga_api.services.tenant_config_service import (
        CategoryCodeArchivedError,
        TenantConfigService,
    )

    user, tid, _pw = semi_auto_tenant
    async with admin_session.begin():
        await _bind_tenant_raw(admin_session, tid)
        cache: TTLCache[UUID, dict[str, Any]] = TTLCache(maxsize=10, ttl=60)
        config = TenantConfigService(admin_session, AuditService(admin_session), cache)
        cat = await config.create_custom_category(
            tid,
            code="abonelik_iptali",
            label_tr="Abonelik İptali",
            actor_user_id=user.id,
        )
        await config.archive_custom_category(tid, cat.id, actor_user_id=user.id)

        service = OnboardingService(admin_session, tid)
        with pytest.raises(CategoryCodeArchivedError) as excinfo:
            await service.apply_categories(
                config=config,
                top_categories=[
                    {
                        "code": "abonelik_iptali",
                        "label_tr": "Abonelik İptali Yeniden",
                    }
                ],
                subcategories=[],
                disable_global_codes=[],
                actor_user_id=user.id,
            )
        message = str(excinfo.value)
        assert "arşivde mevcut" in message
        # Ham DB detayı sızmamalı.
        for leak in (
            "IntegrityError",
            "asyncpg",
            "duplicate key",
            "uq_categories_per_tenant_code",
        ):
            assert leak not in message


@pytest.mark.asyncio
async def test_apply_categories_route_archived_code_conflict_returns_409(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """Aynı senaryo HTTP katmanından: route hata eşleyicisi
    ``CategoryCodeArchivedError``'ı 409 + temiz Türkçe mesaja çevirir
    (``_onboarding_error_to_http`` kesin tip kontrolü — genel
    ``OnboardingServiceError``'a sarılmadan)."""
    from cachetools import TTLCache

    from imga_api.services.tenant_config_service import TenantConfigService

    user, tid, pw = semi_auto_tenant
    async with admin_session.begin():
        await _bind_tenant_raw(admin_session, tid)
        cache: TTLCache[UUID, dict[str, Any]] = TTLCache(maxsize=10, ttl=60)
        config = TenantConfigService(admin_session, AuditService(admin_session), cache)
        cat = await config.create_custom_category(
            tid,
            code="abonelik_iptali",
            label_tr="Abonelik İptali",
            actor_user_id=user.id,
        )
        await config.archive_custom_category(tid, cat.id, actor_user_id=user.id)

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.post(
        "/tenants/me/onboarding/apply-categories",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "top_categories": [
                {"code": "abonelik_iptali", "label_tr": "Abonelik İptali Yeniden"}
            ],
            "subcategories": [],
            "disable_global_codes": [],
        },
    )
    assert r.status_code == 409, r.text
    body = r.json()
    assert body["detail"]["code"] == "category_code_archived"
    message = body["detail"]["message"]
    assert "arşivde mevcut" in message
    for leak in (
        "IntegrityError",
        "asyncpg",
        "duplicate key",
        "uq_categories_per_tenant_code",
    ):
        assert leak not in r.text


# ---------------------------------------------------------------------------
# Route katmanı — rol/authz + hata eşlemesi + gerçek apply akışı
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_categories_route_end_to_end(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    """LLM çağrısı yok — gerçek HTTP + gerçek DB, mock gerekmez."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)

    r = batch_client.post(
        "/tenants/me/onboarding/apply-categories",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "top_categories": [
                {"code": "abonelik_iptali", "label_tr": "Abonelik İptali"}
            ],
            "subcategories": [
                {
                    "code": "trial_iptali",
                    "label_tr": "Deneme İptali",
                    "primary_category_code": "abonelik_iptali",
                }
            ],
            "disable_global_codes": ["urun_kalitesi"],
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["created_categories"] == ["abonelik_iptali"]
    assert body["created_taxonomies"] == ["trial_iptali"]
    assert body["disabled_global_codes"] == ["urun_kalitesi"]


@pytest.mark.asyncio
async def test_suggest_categories_route_no_credentials_returns_412(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from imga_api.services import onboarding_service
    from imga_api.services.llm_credentials import NoCredentialsError

    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)

    monkeypatch.setattr(
        onboarding_service.OnboardingService,
        "suggest_categories",
        AsyncMock(side_effect=NoCredentialsError("no keys")),
    )

    r = batch_client.post(
        "/tenants/me/onboarding/suggest-categories",
        headers={"Authorization": f"Bearer {token}"},
        json={},
    )
    assert r.status_code == 412, r.text
    assert r.json()["detail"]["code"] == "no_llm_credentials"


@pytest.mark.asyncio
async def test_onboarding_routes_reject_viewer_role(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """/tenants/me/onboarding/* — routes/tenant_config.py ile aynı
    desen: TENANT_ADMIN gerekir, VIEWER 403 alır."""
    _admin_user, tid, _pw = semi_auto_tenant
    viewer_email, viewer_pw = await _add_viewer(admin_session, tid)
    token = login_token(batch_client, viewer_email, viewer_pw, tid)

    r = batch_client.post(
        "/tenants/me/onboarding/suggest-categories",
        headers={"Authorization": f"Bearer {token}"},
        json={},
    )
    assert r.status_code == 403

    r = batch_client.post(
        "/tenants/me/onboarding/apply-categories",
        headers={"Authorization": f"Bearer {token}"},
        json={"top_categories": [], "subcategories": [], "disable_global_codes": []},
    )
    assert r.status_code == 403
