"""Yetki matrisi — ``/tenants/me/prompt-templates`` (2026-09-02, TASK B2).

Prompt gövdeleri (system_prompt/user_prompt_template) imga.ai'ın kendi
fikri mülkiyeti; bu router artık ``require_super_admin`` ile kilitli
(bkz. ``routes/tenant_prompt_templates.py`` modül docstring'i). Öncesinde
``tenant_admin`` hem ``/code-defaults`` (global varsayılan prompt
metinleri) hem de kendi kurumunun override listesini okuyabiliyordu —
bir müşterinin KENDİ admin'i bile prompt içeriğini görebiliyordu.

Bu dosya ``test_admin_llm_credentials.py``/``test_admin_overview.py``
ile aynı bağımsız fixture deseni kullanır (kendi ``client``/
``admin_session``/``super_admin``/``role_tenant``'ı — paylaşılan
conftest'e bağımlı değil)."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from cachetools import TTLCache
from fastapi import FastAPI
from fastapi.testclient import TestClient
from imga_db import create_engine, create_session_factory
from imga_db.models import User, UserTenantRole
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

_ENDPOINTS = (
    "/tenants/me/prompt-templates/code-defaults",
    "/tenants/me/prompt-templates",
)


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
    """Tek kurum + üçü de o kurumda olan üyeler. ``tenant_id`` ayrıca
    super-admin'in ``active_tenant_id`` olarak login'de seçtiği kurum —
    ``/tenants/me/prompt-templates`` ``current.active_tenant_id`` şart
    koşar (bkz. ``_require_active_tenant``), süper-adminin o kuruma üye
    olması gerekmez (routes/auth.py login'de ``is_super_admin`` üyelik
    kontrolünü atlar)."""

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
        tenant = await tsvc.create(name="Prompt Erişim Co", slug=f"prompt-erisim-{suffix}")
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


# --- helpers ------------------------------------------------------------


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


# --- yetki matrisi --------------------------------------------------------


@pytest.mark.asyncio
async def test_tenant_admin_gets_403_on_every_prompt_template_endpoint(
    client: TestClient,
    role_tenant: RoleTenant,
) -> None:
    """Kurumun KENDİ admin'i bile artık prompt içeriğini okuyamaz —
    2026-09-02 öncesi ``code-defaults`` ve liste ucu ``_AnyMember``
    altındaydı (tenant_admin/analyst/viewer hepsi 200 alıyordu)."""
    token = _login(client, role_tenant.tenant_admin.email, MEMBER_PASSWORD, role_tenant.tenant_id)
    for path in _ENDPOINTS:
        r = client.get(path, headers=_auth(token))
        assert r.status_code == 403, f"{path} -> {r.status_code}: {r.text}"


@pytest.mark.asyncio
async def test_analyst_gets_403_on_every_prompt_template_endpoint(
    client: TestClient,
    role_tenant: RoleTenant,
) -> None:
    token = _login(client, role_tenant.analyst.email, MEMBER_PASSWORD, role_tenant.tenant_id)
    for path in _ENDPOINTS:
        r = client.get(path, headers=_auth(token))
        assert r.status_code == 403, f"{path} -> {r.status_code}: {r.text}"


@pytest.mark.asyncio
async def test_viewer_gets_403_on_every_prompt_template_endpoint(
    client: TestClient,
    role_tenant: RoleTenant,
) -> None:
    token = _login(client, role_tenant.viewer.email, MEMBER_PASSWORD, role_tenant.tenant_id)
    for path in _ENDPOINTS:
        r = client.get(path, headers=_auth(token))
        assert r.status_code == 403, f"{path} -> {r.status_code}: {r.text}"


@pytest.mark.asyncio
async def test_unauthenticated_gets_401_on_every_prompt_template_endpoint(
    client: TestClient,
) -> None:
    for path in _ENDPOINTS:
        r = client.get(path)
        assert r.status_code == 401, f"{path} -> {r.status_code}"


@pytest.mark.asyncio
async def test_super_admin_gets_200_on_every_prompt_template_endpoint(
    client: TestClient,
    super_admin: User,
    role_tenant: RoleTenant,
) -> None:
    token = _login(client, super_admin.email, SUPER_ADMIN_PASSWORD, role_tenant.tenant_id)
    for path in _ENDPOINTS:
        r = client.get(path, headers=_auth(token))
        assert r.status_code == 200, f"{path} -> {r.status_code}: {r.text}"
    r = client.get("/tenants/me/prompt-templates/code-defaults", headers=_auth(token))
    codes = {row["template_key"] for row in r.json()}
    assert "root_cause" in codes
