"""Super-admin LLM credential surface — 2026-08-09 yetki tasimasi.

Model / API anahtari yonetimi kurumdan alinip super-admin'e verildi.
Bu dosya iki seyi cakili tutar:

  * fonksiyonel yol: super-admin bir kurum icin listeler, ekler,
    gunceller, siralar, siler; anahtar DB'de sifreli durur.
  * yetki matrisi: tenant_admin / analyst / viewer HER admin ucunda
    403, kimliksiz istek 401, bilinmeyen kurum 404.

Ayrica ayni turdeki ikinci acigi da kapatir: /admin/prompt-templates
artik tenant_admin'e degil yalniz super-admin'e acik.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from cachetools import TTLCache
from fastapi import FastAPI
from fastapi.testclient import TestClient
from imga_db import create_engine, create_session_factory
from imga_db.models import TenantLlmCredential, User, UserTenantRole
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
    for attr in ("admin_db_engine", "app_db_engine",
                 "admin_db_engine_factory", "app_db_engine_factory"):
        if hasattr(app.state, attr):
            delattr(app.state, attr)
    try:
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c
    finally:
        app.router.lifespan_context = original
        for attr in ("admin_db_engine", "app_db_engine",
                     "admin_db_engine_factory", "app_db_engine_factory",
                     "tenant_config_cache"):
            if hasattr(app.state, attr):
                delattr(app.state, attr)


@pytest_asyncio.fixture
async def super_admin(admin_session: AsyncSession) -> AsyncIterator[User]:
    """Migration 0001'in tohumladigi admin@imga.ai satirini bilinen bir
    parolayla yeniden yazar (parola migration anindaki env'e bagli)."""
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
    yield user


@dataclass(frozen=True, slots=True)
class RoleTenant:
    """Tek kurum + ucu de o kurumda olan uyeler. Yetki matrisi tek bir
    ``tenant_id`` uzerinde kosulur — roller arasi fark kurum degil rol
    olsun diye."""

    tenant_id: UUID
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
    async with admin_session.begin():
        tenant = await tsvc.create(name="LLM Co", slug=f"llm-{suffix}")
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
            await usvc.attach_to_tenant(
                user_id=user.id, tenant_id=tenant.id, role=role
            )
            members[str(role)] = user
    seeded = RoleTenant(
        tenant_id=tenant.id,
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
        # tenant_llm_credentials FK'si ON DELETE CASCADE — kurum
        # silinince kimlikler de gider.
        await admin_session.execute(
            text("DELETE FROM tenants WHERE id = :id"),
            {"id": str(seeded.tenant_id)},
        )


# --- helpers ----------------------------------------------------------


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


def _base(tenant_id: UUID) -> str:
    return f"/admin/tenants/{tenant_id}/llm-credentials"


def _create(
    client: TestClient,
    token: str,
    tenant_id: UUID,
    *,
    label: str = "Birincil",
    api_key: str = "AIzaSy-test-key-1234",
    provider: str = "gemini",
    model: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "label": label,
        "api_key": api_key,
        "provider": provider,
        "model": model,
    }
    r = client.post(
        _base(tenant_id),
        headers={"Authorization": f"Bearer {token}"},
        json=body,
    )
    assert r.status_code == 201, r.text
    created: dict[str, Any] = r.json()
    return created


def _every_admin_call(
    client: TestClient, token: str | None, tenant_id: UUID
) -> list[tuple[str, int]]:
    """Her admin ucuna bir istek; (etiket, status) listesi doner. Rota
    tanimi kadar govde de gecerli olsun ki 403 gercekten yetkiden
    gelsin, 422'den degil."""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    cred_id = uuid4()
    base = _base(tenant_id)
    return [
        ("list", client.get(base, headers=headers).status_code),
        (
            "create",
            client.post(
                base,
                headers=headers,
                json={
                    "label": "X",
                    "api_key": "AIzaSy-key-9999",
                    "provider": "gemini",
                },
            ).status_code,
        ),
        (
            "patch",
            client.patch(
                f"{base}/{cred_id}",
                headers=headers,
                json={"is_active": False},
            ).status_code,
        ),
        (
            "reorder",
            client.put(
                f"{base}/reorder",
                headers=headers,
                json={"ordered_ids": [str(cred_id)]},
            ).status_code,
        ),
        (
            "delete",
            client.delete(f"{base}/{cred_id}", headers=headers).status_code,
        ),
        (
            "catalog",
            client.get("/admin/openrouter-models", headers=headers).status_code,
        ),
    ]


# --- super-admin happy path -------------------------------------------


@pytest.mark.asyncio
async def test_super_admin_lists_credentials_for_tenant(
    client: TestClient,
    super_admin: User,
    role_tenant: RoleTenant,
    encryption_helper: Any,
) -> None:
    token = _login(client, "admin@imga.ai", SUPER_ADMIN_PASSWORD)
    _create(client, token, role_tenant.tenant_id, label="Birincil")

    r = client.get(
        _base(role_tenant.tenant_id),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 1
    assert body[0]["label"] == "Birincil"
    assert body[0]["value_preview"] == "...1234"


@pytest.mark.asyncio
async def test_super_admin_create_encrypts_value_in_db(
    client: TestClient,
    super_admin: User,
    role_tenant: RoleTenant,
    admin_session: AsyncSession,
    encryption_helper: Any,
) -> None:
    """POST duz metni sifreler. Sutun asla duz metin tasimaz; yanit
    yalniz son-4 onizlemesini gosterir."""
    token = _login(client, "admin@imga.ai", SUPER_ADMIN_PASSWORD)
    plaintext = "AIzaSy-test-key-1234"
    r = client.post(
        _base(role_tenant.tenant_id),
        headers={"Authorization": f"Bearer {token}"},
        json={"label": "Birincil", "api_key": plaintext},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["priority"] == 0
    assert body["value_preview"] == "...1234"
    assert plaintext not in r.text  # No plaintext leak in response.

    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(role_tenant.tenant_id)},
        )
        row = (
            await admin_session.execute(
                select(TenantLlmCredential).where(
                    TenantLlmCredential.id == UUID(body["id"])
                )
            )
        ).scalar_one()
    assert row.encrypted_value != plaintext.encode()
    assert b"AIzaSy" not in row.encrypted_value
    assert row.tenant_id == role_tenant.tenant_id


@pytest.mark.asyncio
async def test_super_admin_create_second_credential_sets_priority_one(
    client: TestClient,
    super_admin: User,
    role_tenant: RoleTenant,
    encryption_helper: Any,
) -> None:
    token = _login(client, "admin@imga.ai", SUPER_ADMIN_PASSWORD)
    first = _create(
        client, token, role_tenant.tenant_id,
        label="Primary", api_key="AIzaSy-key-1234",
    )
    second = _create(
        client, token, role_tenant.tenant_id,
        label="Fallback", api_key="AIzaSy-key-5678",
    )
    assert first["priority"] == 0
    assert second["priority"] == 1


@pytest.mark.asyncio
async def test_super_admin_creates_openrouter_credential_with_model(
    client: TestClient,
    super_admin: User,
    role_tenant: RoleTenant,
    encryption_helper: Any,
) -> None:
    token = _login(client, "admin@imga.ai", SUPER_ADMIN_PASSWORD)
    created = _create(
        client, token, role_tenant.tenant_id,
        label="OpenRouter",
        api_key="sk-or-test-key-9999",
        provider="openrouter",
        model="openai/gpt-5-mini",
    )
    assert created["provider"] == "openrouter"
    assert created["model"] == "openai/gpt-5-mini"


@pytest.mark.asyncio
async def test_super_admin_patches_credential_model_and_status(
    client: TestClient,
    super_admin: User,
    role_tenant: RoleTenant,
    encryption_helper: Any,
) -> None:
    token = _login(client, "admin@imga.ai", SUPER_ADMIN_PASSWORD)
    created = _create(
        client, token, role_tenant.tenant_id,
        label="OpenRouter",
        api_key="sk-or-test-key-9999",
        provider="openrouter",
        model="openai/gpt-5-mini",
    )
    r = client.patch(
        f"{_base(role_tenant.tenant_id)}/{created['id']}",
        headers={"Authorization": f"Bearer {token}"},
        json={"model": "anthropic/claude-haiku-4.5", "is_active": False},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["model"] == "anthropic/claude-haiku-4.5"
    assert body["is_active"] is False


@pytest.mark.asyncio
async def test_super_admin_reorders_credentials(
    client: TestClient,
    super_admin: User,
    role_tenant: RoleTenant,
    encryption_helper: Any,
) -> None:
    """Oncelik yeniden yazimi: tam sirali liste 0..N atar."""
    token = _login(client, "admin@imga.ai", SUPER_ADMIN_PASSWORD)
    tid = role_tenant.tenant_id
    a = _create(client, token, tid, label="A", api_key="AIzaSy-key-AAAA")
    b = _create(client, token, tid, label="B", api_key="AIzaSy-key-BBBB")
    c = _create(client, token, tid, label="C", api_key="AIzaSy-key-CCCC")

    r = client.put(
        f"{_base(tid)}/reorder",
        headers={"Authorization": f"Bearer {token}"},
        json={"ordered_ids": [c["id"], a["id"], b["id"]]},
    )
    assert r.status_code == 200, r.text
    by_id = {item["id"]: item for item in r.json()}
    assert by_id[c["id"]]["priority"] == 0
    assert by_id[a["id"]]["priority"] == 1
    assert by_id[b["id"]]["priority"] == 2


@pytest.mark.asyncio
async def test_super_admin_reorder_with_missing_id_returns_400(
    client: TestClient,
    super_admin: User,
    role_tenant: RoleTenant,
    encryption_helper: Any,
) -> None:
    """Kismi liste reddedilir — eksik birakilan kaydin oncelik yuvasi
    oksuz kalirdi."""
    token = _login(client, "admin@imga.ai", SUPER_ADMIN_PASSWORD)
    tid = role_tenant.tenant_id
    a = _create(client, token, tid, label="A", api_key="AIzaSy-key-AAAA")
    _create(client, token, tid, label="B", api_key="AIzaSy-key-BBBB")

    r = client.put(
        f"{_base(tid)}/reorder",
        headers={"Authorization": f"Bearer {token}"},
        json={"ordered_ids": [a["id"]]},
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["code"] == "reorder_mismatch"


@pytest.mark.asyncio
async def test_super_admin_deletes_credential(
    client: TestClient,
    super_admin: User,
    role_tenant: RoleTenant,
    encryption_helper: Any,
) -> None:
    token = _login(client, "admin@imga.ai", SUPER_ADMIN_PASSWORD)
    tid = role_tenant.tenant_id
    created = _create(client, token, tid, label="X", api_key="AIzaSy-key-XXXX")

    headers = {"Authorization": f"Bearer {token}"}
    r = client.delete(f"{_base(tid)}/{created['id']}", headers=headers)
    assert r.status_code == 204, r.text

    after = client.get(_base(tid), headers=headers)
    assert after.status_code == 200
    assert after.json() == []


@pytest.mark.asyncio
async def test_admin_reorder_switches_winning_provider(
    client: TestClient,
    super_admin: User,
    role_tenant: RoleTenant,
    admin_session: AsyncSession,
    encryption_helper: Any,
) -> None:
    """Kazanan saglayici = en ustteki aktif kayit. Super-admin reorder'i
    ``load_active_llm_keys`` ciktisini degistirir — Gemini -> OpenRouter
    gecisi artik admin tarafinda yapiliyor."""
    from imga_api.services.llm_credentials import load_active_llm_keys

    token = _login(client, "admin@imga.ai", SUPER_ADMIN_PASSWORD)
    tid = role_tenant.tenant_id
    gem = _create(
        client, token, tid, label="Gemini", api_key="AIzaSy-key-1111",
    )
    openrouter = _create(
        client, token, tid,
        label="OpenRouter",
        api_key="sk-or-key-2222",
        provider="openrouter",
        model="anthropic/claude-haiku-4.5",
    )

    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        selection = await load_active_llm_keys(admin_session, tid)
    assert selection is not None
    assert selection.provider == "gemini"

    r = client.put(
        f"{_base(tid)}/reorder",
        headers={"Authorization": f"Bearer {token}"},
        json={"ordered_ids": [openrouter["id"], gem["id"]]},
    )
    assert r.status_code == 200, r.text

    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        selection = await load_active_llm_keys(admin_session, tid)
    assert selection is not None
    assert selection.provider == "openrouter"
    assert selection.model == "anthropic/claude-haiku-4.5"
    assert [k.value for k in selection.keys] == ["sk-or-key-2222"]


@pytest.mark.asyncio
async def test_unknown_tenant_id_returns_404(
    client: TestClient,
    super_admin: User,
    encryption_helper: Any,
) -> None:
    """Var olmayan kurum icin her uc 404 — BYPASSRLS oturumda yol
    parametresi tek kapsam kaynagi, dogrulanmadan yazilmamali."""
    token = _login(client, "admin@imga.ai", SUPER_ADMIN_PASSWORD)
    headers = {"Authorization": f"Bearer {token}"}
    ghost = uuid4()

    assert client.get(_base(ghost), headers=headers).status_code == 404
    created = client.post(
        _base(ghost),
        headers=headers,
        json={"label": "X", "api_key": "AIzaSy-key-9999"},
    )
    assert created.status_code == 404, created.text
    assert client.delete(
        f"{_base(ghost)}/{uuid4()}", headers=headers
    ).status_code == 404


@pytest.mark.asyncio
async def test_patch_rejects_credential_from_another_tenant(
    client: TestClient,
    super_admin: User,
    role_tenant: RoleTenant,
    admin_session: AsyncSession,
    encryption_helper: Any,
) -> None:
    """Yol tenant_id'si ile kaydin tenant_id'si uyusmazsa 404. Admin
    oturumu RLS'i bypass ettigi icin capraz-kurum yazimina karsi tek
    savunma bu."""
    audit = AuditService(admin_session)
    tsvc = TenantService(admin_session, audit)
    async with admin_session.begin():
        other = await tsvc.create(name="Other", slug=f"other-{uuid4().hex[:8]}")
    other_id = other.id

    token = _login(client, "admin@imga.ai", SUPER_ADMIN_PASSWORD)
    headers = {"Authorization": f"Bearer {token}"}
    try:
        created = _create(
            client, token, role_tenant.tenant_id, api_key="AIzaSy-key-7777",
        )
        r = client.patch(
            f"{_base(other_id)}/{created['id']}",
            headers=headers,
            json={"is_active": False},
        )
        assert r.status_code == 404, r.text
    finally:
        async with admin_session.begin():
            await admin_session.execute(
                text("DELETE FROM tenants WHERE id = :id"),
                {"id": str(other_id)},
            )


# --- yetki matrisi ----------------------------------------------------


def test_tenant_admin_forbidden_on_every_admin_endpoint(
    client: TestClient,
    role_tenant: RoleTenant,
) -> None:
    """UI'nin kapiyi gizlemesi yetmez — API'nin kendisi 403 demeli.
    Kurum yoneticisi kendi kurumunun anahtarlarini bile yonetemez."""
    token = _login(
        client,
        role_tenant.tenant_admin.email,
        MEMBER_PASSWORD,
        role_tenant.tenant_id,
    )
    for action, code in _every_admin_call(client, token, role_tenant.tenant_id):
        assert code == 403, f"tenant_admin/{action} beklenen 403, gelen {code}"


def test_analyst_forbidden_on_every_admin_endpoint(
    client: TestClient,
    role_tenant: RoleTenant,
) -> None:
    token = _login(
        client,
        role_tenant.analyst.email,
        MEMBER_PASSWORD,
        role_tenant.tenant_id,
    )
    for action, code in _every_admin_call(client, token, role_tenant.tenant_id):
        assert code == 403, f"analyst/{action} beklenen 403, gelen {code}"


def test_viewer_forbidden_on_every_admin_endpoint(
    client: TestClient,
    role_tenant: RoleTenant,
) -> None:
    token = _login(
        client,
        role_tenant.viewer.email,
        MEMBER_PASSWORD,
        role_tenant.tenant_id,
    )
    for action, code in _every_admin_call(client, token, role_tenant.tenant_id):
        assert code == 403, f"viewer/{action} beklenen 403, gelen {code}"


def test_unauthenticated_forbidden_on_every_admin_endpoint(
    client: TestClient,
    role_tenant: RoleTenant,
) -> None:
    for action, code in _every_admin_call(client, None, role_tenant.tenant_id):
        assert code == 401, f"anonim/{action} beklenen 401, gelen {code}"


# --- /admin/prompt-templates yetkisi ----------------------------------


def test_super_admin_can_list_prompt_templates(
    client: TestClient,
    super_admin: User,
) -> None:
    token = _login(client, "admin@imga.ai", SUPER_ADMIN_PASSWORD)
    r = client.get(
        "/admin/prompt-templates",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)


def test_tenant_admin_cannot_list_prompt_templates(
    client: TestClient,
    role_tenant: RoleTenant,
) -> None:
    """2026-08-09 oncesi herhangi bir kurumun tenant_admin'i sistem
    genelindeki sablonlari okuyabiliyordu — kurum sinirini asan bir
    yoldu, artik super-admin'e kapali."""
    token = _login(
        client,
        role_tenant.tenant_admin.email,
        MEMBER_PASSWORD,
        role_tenant.tenant_id,
    )
    r = client.get(
        "/admin/prompt-templates",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403, r.text
