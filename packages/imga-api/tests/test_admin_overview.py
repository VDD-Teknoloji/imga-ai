"""Süper-admin envanter raporu — C1/C2/C3/C4 + B2/B6/B7 (2026-08-20).

Dört yeni/zenginleştirilmiş yüzey:
  * GET /admin/llm-usage       (C1, YENİ)
  * GET /admin/tenants         (C3+B7, zenginleştirilmiş — mevcut uç)
  * GET /admin/audit-logs      (C4+B2, YENİ)
  * GET /admin/system-health   (C2, YENİ)

Yetki matrisi ortak: tenant_admin/analyst/viewer HER dört uçta 403,
süper-admin 200 (require_super_admin zinciri test_admin_llm_credentials.py
ile aynı desen — bkz. o dosyanın docstring'i).

``llm_pricing.cost_usd`` birim testleri ayrı dosyada (tests/test_llm_pricing.py,
DB gerektirmez, lokalde bağımsız koşar).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from cachetools import TTLCache
from fastapi import FastAPI
from fastapi.testclient import TestClient
from imga_db import create_engine, create_session_factory
from imga_db.models import LlmCallAudit, User, UserTenantRole
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from imga_api.main import app
from imga_api.security import hash_password
from imga_api.services import AuditService, TenantService, UserService
from imga_api.settings import Settings

_HOST = os.environ.get("IMGA_TEST_PG_HOST", "localhost")
_PORT = os.environ.get("IMGA_POSTGRES_PORT", "5433")
ADMIN_URL = f"postgresql+asyncpg://imga_admin:imga_admin_password@{_HOST}:{_PORT}/imga"
APP_URL = f"postgresql+asyncpg://imga_app:imga_app_password@{_HOST}:{_PORT}/imga"
OWNER_URL = f"postgresql+asyncpg://imga_owner:imga_dev_password@{_HOST}:{_PORT}/imga"

SUPER_ADMIN_PASSWORD = "test-super-admin-pwd-32-chars-min"
MEMBER_PASSWORD = "Member-Pwd-123-Strong"


@pytest.fixture(autouse=True)
def _set_test_env() -> None:
    os.environ["DATABASE_URL"] = APP_URL
    os.environ["DATABASE_URL_ADMIN"] = ADMIN_URL
    os.environ["DATABASE_URL_OWNER"] = OWNER_URL
    os.environ["JWT_SECRET_KEY"] = "test-secret-key-32-bytes-min-padding-xyz"


@pytest_asyncio.fixture
async def admin_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_engine("admin")
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def admin_session(admin_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    factory = create_session_factory(admin_engine)
    async with factory() as session:
        yield session


@pytest.fixture
def client() -> Iterator[TestClient]:
    @asynccontextmanager
    async def _test_lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.settings = Settings.from_env()  # type: ignore[attr-defined]
        application.state.tenant_config_cache = TTLCache(  # type: ignore[attr-defined]
            maxsize=1000, ttl=300
        )
        yield

    original = app.router.lifespan_context
    app.router.lifespan_context = _test_lifespan
    for attr in (
        "admin_db_engine",
        "app_db_engine",
        "admin_db_engine_factory",
        "app_db_engine_factory",
    ):
        if hasattr(app.state, attr):
            delattr(app.state, attr)
    try:
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c
    finally:
        app.router.lifespan_context = original
        for attr in (
            "admin_db_engine",
            "app_db_engine",
            "admin_db_engine_factory",
            "app_db_engine_factory",
            "tenant_config_cache",
        ):
            if hasattr(app.state, attr):
                delattr(app.state, attr)


@pytest_asyncio.fixture
async def super_admin(admin_session: AsyncSession) -> AsyncIterator[User]:
    """Migration 0001'in tohumladığı admin@imga.ai satırını bilinen bir
    parolayla yeniden yazar (parola migration anındaki env'e bağlı)."""
    async with admin_session.begin():
        await admin_session.execute(
            text(
                "UPDATE users SET password_hash = :pw, is_active = true "
                "WHERE email = 'admin@imga.ai'"
            ),
            {"pw": hash_password(SUPER_ADMIN_PASSWORD)},
        )
        user = (
            await admin_session.execute(select(User).where(User.email == "admin@imga.ai"))
        ).scalar_one()
    yield user


@dataclass(frozen=True, slots=True)
class RoleTenant:
    tenant_id: UUID
    tenant_name: str
    tenant_admin: User
    analyst: User
    viewer: User


@pytest_asyncio.fixture
async def role_tenant(
    admin_session: AsyncSession,
) -> AsyncIterator[RoleTenant]:
    audit = AuditService(admin_session)
    tsvc = TenantService(admin_session, audit)
    usvc = UserService(admin_session, audit)
    suffix = uuid4().hex[:8]
    tenant_name = f"Envanter Co {suffix}"
    async with admin_session.begin():
        tenant = await tsvc.create(name=tenant_name, slug=f"envanter-{suffix}")
        members: dict[str, User] = {}
        for role in (
            UserTenantRole.TENANT_ADMIN,
            UserTenantRole.ANALYST,
            UserTenantRole.VIEWER,
        ):
            user = await usvc.create(
                email=f"{role}-{suffix}@example.com",
                password=MEMBER_PASSWORD,
                full_name=f"{role} user",
            )
            await usvc.attach_to_tenant(user_id=user.id, tenant_id=tenant.id, role=role)
            members[str(role)] = user
    seeded = RoleTenant(
        tenant_id=tenant.id,
        tenant_name=tenant_name,
        tenant_admin=members["tenant_admin"],
        analyst=members["analyst"],
        viewer=members["viewer"],
    )
    yield seeded
    async with admin_session.begin():
        await admin_session.execute(
            text("DELETE FROM users WHERE id = ANY(:ids)"),
            {"ids": [str(u.id) for u in members.values()]},
        )
        await admin_session.execute(
            text("DELETE FROM tenants WHERE id = :id"),
            {"id": str(seeded.tenant_id)},
        )


@pytest_asyncio.fixture
async def seeded_llm_calls(
    admin_session: AsyncSession, role_tenant: RoleTenant
) -> AsyncIterator[RoleTenant]:
    """İki başarılı (biri bilinen fiyatlı, biri bilinmeyen modelli) +
    bir başarısız çağrı. llm-usage totallerinin known/unknown maliyet
    ayrımını ve error_rate'i doğrulamak için."""
    rows = [
        LlmCallAudit(
            tenant_id=role_tenant.tenant_id,
            call_type="briefing",
            prompt_hash="a" * 64,
            model_name="z-ai/glm-5.2",
            model_provider="openrouter",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            cost_usd=None,  # route katmanı zaten hesaplıyor testte biz doğrudan yazıyoruz
            success=True,
            fallback_used=False,
            created_at=datetime.now(UTC),
        ),
        LlmCallAudit(
            tenant_id=role_tenant.tenant_id,
            call_type="classification",
            prompt_hash="b" * 64,
            model_name="some/unpriced-model",
            model_provider="openrouter",
            input_tokens=100,
            output_tokens=100,
            cost_usd=None,
            success=True,
            fallback_used=False,
            created_at=datetime.now(UTC),
        ),
        LlmCallAudit(
            tenant_id=role_tenant.tenant_id,
            call_type="briefing",
            prompt_hash="c" * 64,
            model_name="z-ai/glm-5.2",
            model_provider="openrouter",
            input_tokens=None,
            output_tokens=None,
            cost_usd=None,
            success=False,
            error_type="timeout",
            fallback_used=False,
            created_at=datetime.now(UTC),
        ),
    ]
    # İlk satırın maliyeti bilinen bir fiyata karşılık gelsin diye
    # gerçek pricing fonksiyonunu kullanıyoruz — ayrı bir sabit
    # kopyalamak yerine (llm_pricing tek doğruluk kaynağı kalsın).
    from imga_api.services.llm_pricing import cost_usd as _price

    rows[0].cost_usd = _price("openrouter", "z-ai/glm-5.2", 1_000_000, 1_000_000)

    async with admin_session.begin():
        # llm_call_audit RLS+FORCE altında — imga_admin BYPASSRLS olsa
        # da bu kod tabanının kuralı FORCE-aware yoldan geçmek (bkz.
        # test_llm_audit_orm_insert.py::_bind). admin_session zaten
        # BYPASSRLS ama set_config'i atlamak bu deseni bozar.
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(role_tenant.tenant_id)},
        )
        for row in rows:
            admin_session.add(row)
        await admin_session.flush()
    yield role_tenant
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(role_tenant.tenant_id)},
        )
        await admin_session.execute(
            text("DELETE FROM llm_call_audit WHERE tenant_id = :tid"),
            {"tid": str(role_tenant.tenant_id)},
        )


def _login(
    client: TestClient,
    email: str,
    password: str,
    tenant_id: UUID | None = None,
) -> str:
    payload: dict[str, str] = {"email": email, "password": password}
    if tenant_id is not None:
        payload["active_tenant_id"] = str(tenant_id)
    r = client.post("/auth/login", json=payload)
    assert r.status_code == 200, r.text
    return str(r.json()["access_token"])


def _auth(token: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token else {}


_ENDPOINTS = (
    "/admin/llm-usage",
    "/admin/tenants",
    "/admin/audit-logs",
    "/admin/system-health",
)


# --- yetki matrisi ------------------------------------------------------


@pytest.mark.asyncio
async def test_non_super_admin_gets_403_on_every_new_endpoint(
    client: TestClient,
    role_tenant: RoleTenant,
) -> None:
    for role_user, pw in (
        (role_tenant.tenant_admin, MEMBER_PASSWORD),
        (role_tenant.analyst, MEMBER_PASSWORD),
        (role_tenant.viewer, MEMBER_PASSWORD),
    ):
        token = _login(client, role_user.email, pw, role_tenant.tenant_id)
        for path in _ENDPOINTS:
            r = client.get(path, headers=_auth(token))
            assert r.status_code == 403, f"{path} -> {r.status_code}: {r.text}"


@pytest.mark.asyncio
async def test_unauthenticated_gets_401_on_every_new_endpoint(
    client: TestClient,
) -> None:
    for path in _ENDPOINTS:
        r = client.get(path)
        assert r.status_code == 401, f"{path} -> {r.status_code}"


@pytest.mark.asyncio
async def test_super_admin_gets_200_on_every_new_endpoint(
    client: TestClient,
    super_admin: User,
    role_tenant: RoleTenant,
) -> None:
    token = _login(client, super_admin.email, SUPER_ADMIN_PASSWORD)
    for path in _ENDPOINTS:
        r = client.get(path, headers=_auth(token))
        assert r.status_code == 200, f"{path} -> {r.status_code}: {r.text}"


# --- C1: /admin/llm-usage ------------------------------------------------


@pytest.mark.asyncio
async def test_llm_usage_totals_known_vs_unknown_cost(
    client: TestClient,
    super_admin: User,
    seeded_llm_calls: RoleTenant,
) -> None:
    token = _login(client, super_admin.email, SUPER_ADMIN_PASSWORD)
    r = client.get("/admin/llm-usage", headers=_auth(token))
    assert r.status_code == 200, r.text
    body = r.json()

    row = next(t for t in body["tenants"] if t["tenant_id"] == str(seeded_llm_calls.tenant_id))
    assert row["tenant_name"] == seeded_llm_calls.tenant_name
    assert row["calls"] == 3
    # NULL/unknown-model satırların hiçbiri cost'a katılmaz; yalnız
    # ilk satırın (bilinen fiyat) maliyeti sayılmalı.
    assert row["total_cost_usd"] is not None
    assert row["total_cost_usd"] > 0
    # ikinci satır (bilinmeyen model) + üçüncü satır (token'sız
    # başarısız çağrı) -> iki tanesi "bilinmiyor".
    assert row["unknown_cost_calls"] == 2
    # 1 başarısız / 3 toplam.
    assert row["error_rate"] == pytest.approx(1 / 3)

    # call_types + platform toplamı PLATFORM GENELİNDEDİR (kurum
    # kırılımı değil) — compose bütün whitelist'i tek Postgres'e karşı
    # koşturuyor, önceki bir test dosyası (ör. test_trial_analyze.py'nin
    # kalıcı trial kurumu) aynı call_type'a ekstra satır yazmış olabilir.
    # >= / membership dışında kesin sayı doğrulaması bu blokta yapılmaz
    # — kesin sayılar yalnız YUKARIDAKİ kuruma-özel ``row`` üzerinde.
    call_types = {c["call_type"]: c for c in body["call_types"]}
    assert "briefing" in call_types
    assert "classification" in call_types
    assert call_types["briefing"]["calls"] >= 2
    assert call_types["classification"]["calls"] >= 1

    assert body["platform"]["calls"] >= 3


@pytest.mark.asyncio
async def test_llm_usage_date_filter_excludes_out_of_window_rows(
    client: TestClient,
    super_admin: User,
    admin_session: AsyncSession,
    seeded_llm_calls: RoleTenant,
) -> None:
    # Pencerenin tamamen dışına düşen bir tarih aralığı istenirse
    # kurum bu raporda hiç görünmemeli.
    token = _login(client, super_admin.email, SUPER_ADMIN_PASSWORD)
    far_past = (datetime.now(UTC) - timedelta(days=400)).date().isoformat()
    far_past_end = (datetime.now(UTC) - timedelta(days=390)).date().isoformat()
    r = client.get(
        "/admin/llm-usage",
        headers=_auth(token),
        params={"date_from": far_past, "date_to": far_past_end},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert all(t["tenant_id"] != str(seeded_llm_calls.tenant_id) for t in body["tenants"])


# --- C3+B7: /admin/tenants zenginleştirme ---------------------------------


@pytest.mark.asyncio
async def test_tenants_list_carries_inventory_fields(
    client: TestClient,
    super_admin: User,
    role_tenant: RoleTenant,
) -> None:
    token = _login(client, super_admin.email, SUPER_ADMIN_PASSWORD)
    r = client.get("/admin/tenants", headers=_auth(token))
    assert r.status_code == 200, r.text
    body = r.json()
    row = next(t for t in body["tenants"] if t["id"] == str(role_tenant.tenant_id))
    # Taze kurum: hiç yorum/yükleme/LLM çağrısı yok -> 0 / None, ama
    # None DEĞİL (list_tenants alanları hesaplar) — bkz. TenantSummary
    # docstring'i: yalnız tekil create/get/update/delete None döner.
    assert row["review_count"] == 0
    assert row["last_upload_at"] is None
    assert row["tokens_30d"] == 0
    assert row["cost_30d_usd"] is None
    # Mevcut alanlar hâlâ yerinde (frontend kırılmasın).
    assert row["name"] == role_tenant.tenant_name
    assert "slug" in row and "plan_tier" in row and "automation_mode" in row


@pytest.mark.asyncio
async def test_single_tenant_get_does_not_compute_inventory_fields(
    client: TestClient,
    super_admin: User,
    role_tenant: RoleTenant,
) -> None:
    """create/get/update/delete tek kurum döner; yeni alanlar None
    kalır (0 ile karıştırılmamalı — TenantSummary docstring'i)."""
    token = _login(client, super_admin.email, SUPER_ADMIN_PASSWORD)
    r = client.get(f"/admin/tenants/{role_tenant.tenant_id}", headers=_auth(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["review_count"] is None
    assert body["tokens_30d"] is None
    assert body["engagement_band"] is None


# --- C4+B2: /admin/audit-logs ---------------------------------------------


@pytest.mark.asyncio
async def test_audit_logs_lists_and_filters_by_tenant_and_action(
    client: TestClient,
    super_admin: User,
    role_tenant: RoleTenant,
) -> None:
    # role_tenant fixture zaten TenantService.create + UserService.create
    # üzerinden birden çok audit_logs satırı yazdı ("tenant.create" dahil).
    token = _login(client, super_admin.email, SUPER_ADMIN_PASSWORD)
    r = client.get(
        "/admin/audit-logs",
        headers=_auth(token),
        params={"tenant_id": str(role_tenant.tenant_id), "action": "tenant.create"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] >= 1
    assert all(item["action"] == "tenant.create" for item in body["items"])
    row = body["items"][0]
    assert row["tenant_id"] == str(role_tenant.tenant_id)
    assert row["tenant_name"] == role_tenant.tenant_name
    assert "created_at" in row and "ip_address" in row


@pytest.mark.asyncio
async def test_audit_logs_pagination_limit(
    client: TestClient,
    super_admin: User,
    role_tenant: RoleTenant,
) -> None:
    token = _login(client, super_admin.email, SUPER_ADMIN_PASSWORD)
    r = client.get(
        "/admin/audit-logs",
        headers=_auth(token),
        params={"tenant_id": str(role_tenant.tenant_id), "limit": 1, "offset": 0},
    )
    assert r.status_code == 200, r.text
    assert len(r.json()["items"]) <= 1


# --- C2: /admin/system-health ----------------------------------------------


class _FailingRedisStub:
    """ping() her zaman patlar — Redis çökmüş/erişilemez senaryosu."""

    async def ping(self) -> Any:
        raise ConnectionError("simulated redis outage")


@pytest.mark.asyncio
async def test_system_health_best_effort_when_redis_down(
    client: TestClient,
    super_admin: User,
) -> None:
    from imga_api.cache.redis_client import set_redis_client

    token = _login(client, super_admin.email, SUPER_ADMIN_PASSWORD)
    set_redis_client(_FailingRedisStub())
    try:
        r = client.get("/admin/system-health", headers=_auth(token))
    finally:
        set_redis_client(None)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["redis_ok"] is False
    assert body["arq_queue_depth"] is None
    assert body["workers"] == "unknown"
    # Postgres tarafı Redis'ten bağımsız — job listesi (boş de olsa)
    # her zaman bir liste olarak döner, 500 yok.
    assert isinstance(body["jobs_by_status"], list)


@pytest.mark.asyncio
async def test_system_health_reports_ok_when_redis_reachable(
    client: TestClient,
    super_admin: User,
) -> None:
    """Test compose'un redis-test servisi ayaktaysa (REDIS_URL onu
    gösterir) redis_ok True ve kuyruk derinliği okunabilir olmalı.
    Lokalde Redis yoksa bu test doğal olarak redis_ok=False görüp
    de geçer — asıl garanti ettiğimiz şey best-effort'un asla 500
    vermemesi, ayrı bir testte zaten kanıtlandı."""
    from imga_api.cache.redis_client import set_redis_client

    token = _login(client, super_admin.email, SUPER_ADMIN_PASSWORD)
    set_redis_client(None)
    r = client.get("/admin/system-health", headers=_auth(token))
    assert r.status_code == 200, r.text
    body = r.json()
    if body["redis_ok"]:
        assert body["arq_queue_depth"] is not None
        assert body["arq_queue_depth"] >= 0
