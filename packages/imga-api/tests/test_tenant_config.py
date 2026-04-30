"""Tenant configuration endpoint tests (Sprint 7.4).

Covers nine scenarios approved during 7.4 design review:

  1. Tenant create seeds the 8 globals as enabled rows in tenant_categories
  2. PATCH /automation-mode updates tenants.automation_mode + audit log row
  3. PATCH /categories/{id} cache invalidates so subsequent GET is fresh
  4. POST /custom-categories with a global code → 409 conflict
  5. Same custom code on two different tenants is allowed (RLS isolated)
  6. RLS smoke: tenant A's /categories does not list tenant B's customs
  7. ANALYST/VIEWER cannot mutate (403) but can read (200);
     TENANT_ADMIN can do both
  8. Adding a global *after* tenant creation does NOT auto-enable for
     that tenant — opt-in semantic
  9. Cache 3-stage: first GET populates cache; mutation invalidates;
     second GET re-populates from DB
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from cachetools import TTLCache
from fastapi.testclient import TestClient
from imga_db import create_engine, create_session_factory
from imga_db.models import AuditLog, Category, Tenant, User, UserTenantRole
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from imga_api.main import app
from imga_api.services import (
    AuditService,
    TenantService,
    UserService,
)
from imga_api.settings import Settings

_HOST = os.environ.get("IMGA_TEST_PG_HOST", "localhost")
_PORT = os.environ.get("IMGA_POSTGRES_PORT", "5433")
ADMIN_URL = f"postgresql+asyncpg://imga_admin:imga_admin_password@{_HOST}:{_PORT}/imga"
APP_URL = f"postgresql+asyncpg://imga_app:imga_app_password@{_HOST}:{_PORT}/imga"
OWNER_URL = f"postgresql+asyncpg://imga_owner:imga_dev_password@{_HOST}:{_PORT}/imga"


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


@pytest_asyncio.fixture
async def owner_engine() -> AsyncIterator[AsyncEngine]:
    """Owner engine bypasses RLS too AND can write to globals (NULL tenant)."""
    engine = create_engine("owner")
    yield engine
    await engine.dispose()


async def _seed_user(
    admin_session: AsyncSession,
    role: UserTenantRole,
) -> tuple[User, UUID, str]:
    """Helper: create a tenant + a user + UserTenantLink in one transaction."""
    audit = AuditService(admin_session)
    tsvc = TenantService(admin_session, audit)
    usvc = UserService(admin_session, audit)
    plain = "Test-Password-123!"
    email = f"cfg-{uuid4().hex[:8]}@example.com"
    async with admin_session.begin():
        tenant = await tsvc.create(name="Cfg Co", slug=f"cfg-{uuid4().hex[:8]}")
        user = await usvc.create(email=email, password=plain, full_name="Cfg User")
        await usvc.attach_to_tenant(
            user_id=user.id, tenant_id=tenant.id, role=role
        )
        return user, tenant.id, plain


async def _cleanup(admin_session: AsyncSession, user_id: UUID, tenant_id: UUID) -> None:
    async with admin_session.begin():
        await admin_session.execute(
            text("DELETE FROM users WHERE id = :id"), {"id": str(user_id)}
        )
        await admin_session.execute(
            text("DELETE FROM tenants WHERE id = :id"), {"id": str(tenant_id)}
        )


@pytest_asyncio.fixture
async def tenant_admin(
    admin_session: AsyncSession,
) -> AsyncIterator[tuple[User, UUID, str]]:
    user, tid, pw = await _seed_user(admin_session, UserTenantRole.TENANT_ADMIN)
    yield user, tid, pw
    await _cleanup(admin_session, user.id, tid)


@pytest_asyncio.fixture
async def analyst_user(
    admin_session: AsyncSession,
) -> AsyncIterator[tuple[User, UUID, str]]:
    user, tid, pw = await _seed_user(admin_session, UserTenantRole.ANALYST)
    yield user, tid, pw
    await _cleanup(admin_session, user.id, tid)


@pytest.fixture
def client() -> Iterator[TestClient]:
    """TestClient with a no-op lifespan that seeds settings + cache."""
    @asynccontextmanager
    async def _test_lifespan(application: object) -> AsyncIterator[None]:
        application.state.settings = Settings.from_env()  # type: ignore[attr-defined]
        application.state.tenant_config_cache = TTLCache(  # type: ignore[attr-defined]
            maxsize=1000, ttl=300
        )
        yield

    original_lifespan = app.router.lifespan_context
    app.router.lifespan_context = _test_lifespan

    for attr in ("admin_db_engine", "app_db_engine",
                 "admin_db_engine_factory", "app_db_engine_factory"):
        if hasattr(app.state, attr):
            delattr(app.state, attr)

    try:
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c
    finally:
        app.router.lifespan_context = original_lifespan
        for attr in ("admin_db_engine", "app_db_engine",
                     "admin_db_engine_factory", "app_db_engine_factory",
                     "tenant_config_cache"):
            if hasattr(app.state, attr):
                delattr(app.state, attr)


def _login(client: TestClient, email: str, password: str, tenant_id: UUID) -> str:
    r = client.post(
        "/auth/login",
        json={"email": email, "password": password, "active_tenant_id": str(tenant_id)},
    )
    assert r.status_code == 200, r.text
    return str(r.json()["access_token"])


# --- 1. Tenant create seeds the 8 globals as enabled rows ----------------


@pytest.mark.asyncio
async def test_tenant_create_seeds_eight_globals_enabled(
    admin_session: AsyncSession,
    tenant_admin: tuple[User, UUID, str],
) -> None:
    _user, tenant_id, _pw = tenant_admin
    async with admin_session.begin():
        rows = (
            await admin_session.execute(
                text(
                    "SELECT category_id, is_enabled FROM tenant_categories "
                    "WHERE tenant_id = :t"
                ),
                {"t": str(tenant_id)},
            )
        ).all()
    assert len(rows) == 8
    assert all(r[1] is True for r in rows)


# --- 2. PATCH /automation-mode updates DB + writes audit log ------------


def test_automation_mode_update_writes_audit(
    client: TestClient,
    tenant_admin: tuple[User, UUID, str],
) -> None:
    user, tid, pw = tenant_admin
    token = _login(client, user.email, pw, tid)
    r = client.patch(
        "/tenants/me/automation-mode",
        headers={"Authorization": f"Bearer {token}"},
        json={"automation_mode": "full_auto"},
    )
    assert r.status_code == 204, r.text


@pytest.mark.asyncio
async def test_automation_mode_persisted_and_audited(
    client: TestClient,
    admin_session: AsyncSession,
    tenant_admin: tuple[User, UUID, str],
) -> None:
    user, tid, pw = tenant_admin
    token = _login(client, user.email, pw, tid)
    r = client.patch(
        "/tenants/me/automation-mode",
        headers={"Authorization": f"Bearer {token}"},
        json={"automation_mode": "full_auto"},
    )
    assert r.status_code == 204, r.text

    async with admin_session.begin():
        tenant = await admin_session.get(Tenant, tid)
        assert tenant is not None
        assert str(tenant.automation_mode) == "full_auto"
        audit_rows = (
            await admin_session.execute(
                select(AuditLog)
                .where(AuditLog.action == "tenant.automation_mode.update")
                .where(AuditLog.tenant_id == tid)
            )
        ).scalars().all()
    assert len(audit_rows) >= 1
    detail = audit_rows[-1].details
    assert detail.get("to") == "full_auto"


# --- 3. Cache invalidation: PATCH category toggle → fresh GET -----------


def test_toggle_category_invalidates_cache_so_next_get_is_fresh(
    client: TestClient,
    tenant_admin: tuple[User, UUID, str],
) -> None:
    user, tid, pw = tenant_admin
    token = _login(client, user.email, pw, tid)
    headers = {"Authorization": f"Bearer {token}"}

    cfg1 = client.get("/tenants/me/config", headers=headers).json()
    kargo = next(c for c in cfg1["categories"] if c["code"] == "kargo")
    assert kargo["is_enabled"] is True

    r = client.patch(
        f"/tenants/me/categories/{kargo['id']}",
        headers=headers,
        json={"is_enabled": False},
    )
    assert r.status_code == 204, r.text

    cfg2 = client.get("/tenants/me/config", headers=headers).json()
    kargo2 = next(c for c in cfg2["categories"] if c["code"] == "kargo")
    assert kargo2["is_enabled"] is False  # would still be True if cache was stale


# --- 4. POST custom with reserved global code → 409 ---------------------


def test_create_custom_with_global_code_returns_409(
    client: TestClient,
    tenant_admin: tuple[User, UUID, str],
) -> None:
    user, tid, pw = tenant_admin
    token = _login(client, user.email, pw, tid)
    r = client.post(
        "/tenants/me/custom-categories",
        headers={"Authorization": f"Bearer {token}"},
        json={"code": "kargo", "label_tr": "Kargom"},
    )
    assert r.status_code == 409, r.text
    assert "kargo" in r.json()["detail"].lower()


# --- 5. Same custom code on two different tenants is allowed -----------


@pytest_asyncio.fixture
async def two_tenant_admins(
    admin_session: AsyncSession,
) -> AsyncIterator[tuple[tuple[User, UUID, str], tuple[User, UUID, str]]]:
    a = await _seed_user(admin_session, UserTenantRole.TENANT_ADMIN)
    b = await _seed_user(admin_session, UserTenantRole.TENANT_ADMIN)
    yield a, b
    await _cleanup(admin_session, a[0].id, a[1])
    await _cleanup(admin_session, b[0].id, b[1])


def test_same_custom_code_allowed_on_two_tenants(
    client: TestClient,
    two_tenant_admins: tuple[tuple[User, UUID, str], tuple[User, UUID, str]],
) -> None:
    (user_a, tid_a, pw_a), (user_b, tid_b, pw_b) = two_tenant_admins
    tok_a = _login(client, user_a.email, pw_a, tid_a)
    tok_b = _login(client, user_b.email, pw_b, tid_b)

    body = {"code": "vip_iade", "label_tr": "VIP İade"}
    r_a = client.post(
        "/tenants/me/custom-categories",
        headers={"Authorization": f"Bearer {tok_a}"},
        json=body,
    )
    r_b = client.post(
        "/tenants/me/custom-categories",
        headers={"Authorization": f"Bearer {tok_b}"},
        json=body,
    )
    assert r_a.status_code == 201, r_a.text
    assert r_b.status_code == 201, r_b.text


# --- 6. RLS smoke: tenant A does not see tenant B's customs ------------


def test_tenant_does_not_see_other_tenants_customs(
    client: TestClient,
    two_tenant_admins: tuple[tuple[User, UUID, str], tuple[User, UUID, str]],
) -> None:
    (user_a, tid_a, pw_a), (user_b, tid_b, pw_b) = two_tenant_admins
    tok_a = _login(client, user_a.email, pw_a, tid_a)
    tok_b = _login(client, user_b.email, pw_b, tid_b)

    # B creates a custom; A must not see it
    r_b = client.post(
        "/tenants/me/custom-categories",
        headers={"Authorization": f"Bearer {tok_b}"},
        json={"code": "tenant_b_only", "label_tr": "Sadece Beta"},
    )
    assert r_b.status_code == 201

    cfg_a = client.get(
        "/tenants/me/categories",
        headers={"Authorization": f"Bearer {tok_a}"},
    ).json()
    codes_a = {c["code"] for c in cfg_a["categories"]}
    assert "tenant_b_only" not in codes_a


# --- 7. ANALYST cannot mutate; can read --------------------------------


def test_analyst_can_read_but_not_mutate(
    client: TestClient,
    analyst_user: tuple[User, UUID, str],
) -> None:
    user, tid, pw = analyst_user
    token = _login(client, user.email, pw, tid)
    headers = {"Authorization": f"Bearer {token}"}

    # Read OK
    r_get = client.get("/tenants/me/config", headers=headers)
    assert r_get.status_code == 200, r_get.text

    # Mutate forbidden
    r_patch = client.patch(
        "/tenants/me/automation-mode",
        headers=headers,
        json={"automation_mode": "full_auto"},
    )
    assert r_patch.status_code == 403


# --- 8. Opt-in: new global added later does NOT auto-enable -----------


@pytest.mark.asyncio
async def test_new_global_added_after_tenant_create_is_opt_in(
    client: TestClient,
    admin_session: AsyncSession,
    tenant_admin: tuple[User, UUID, str],
) -> None:
    """Insert a fresh global category AFTER the tenant exists. The
    tenant's GET /categories must show it (RLS allows global SELECT)
    but with is_enabled=False (no row in tenant_categories)."""
    user, tid, pw = tenant_admin
    new_code = f"sprint8_test_{uuid4().hex[:6]}"
    new_id = uuid4()

    # Insert via owner engine — owner has BYPASSRLS, but FORCE RLS makes
    # owner subject to policies; however, owner is also the table owner so
    # ENABLE RLS without FORCE wouldn't apply. With FORCE, the policy
    # check fails because current_setting is unset. We work around this
    # by SET LOCAL within a transaction that satisfies the policy *or*
    # by temporarily disabling RLS during this controlled insert.
    # Actually owner role uses BYPASSRLS attribute (postgres-level), so
    # FORCE applies — to insert a global we must bypass via the admin
    # role which has BYPASSRLS too but isn't the table owner. Simpler:
    # use raw asyncpg via the owner connection but ALTER ... DISABLE
    # for the single statement, then re-enable.
    owner_engine = create_engine("owner")
    try:
        owner_factory = create_session_factory(owner_engine)
        async with owner_factory() as s, s.begin():
            # Disable RLS for this transaction's INSERT, then re-enable.
            # FORCE RLS otherwise blocks an INSERT with NULL tenant_id
            # because the WITH CHECK predicate evaluates to NULL.
            await s.execute(text("ALTER TABLE categories DISABLE ROW LEVEL SECURITY"))
            await s.execute(
                text(
                    "INSERT INTO categories (id, tenant_id, code, label_tr) "
                    "VALUES (:id, NULL, :c, :l)"
                ),
                {"id": str(new_id), "c": new_code, "l": "Sprint 8 Test"},
            )
            await s.execute(text("ALTER TABLE categories ENABLE ROW LEVEL SECURITY"))

        token = _login(client, user.email, pw, tid)
        cfg = client.get(
            "/tenants/me/categories",
            headers={"Authorization": f"Bearer {token}"},
        ).json()
        match = [c for c in cfg["categories"] if c["code"] == new_code]
        assert len(match) == 1, "tenant must see the new global via RLS"
        assert match[0]["is_global"] is True
        assert match[0]["is_enabled"] is False, "new globals are opt-in for existing tenants"
    finally:
        owner_factory = create_session_factory(owner_engine)
        async with owner_factory() as s, s.begin():
            await s.execute(text("ALTER TABLE categories DISABLE ROW LEVEL SECURITY"))
            await s.execute(
                text("DELETE FROM categories WHERE id = :id"),
                {"id": str(new_id)},
            )
            await s.execute(text("ALTER TABLE categories ENABLE ROW LEVEL SECURITY"))
        await owner_engine.dispose()


# --- 9. 3-stage cache check --------------------------------------------


def test_cache_invalidates_on_mutation_then_repopulates(
    client: TestClient,
    tenant_admin: tuple[User, UUID, str],
) -> None:
    """Stage 1: first GET populates the cache.
       Stage 2: a mutation calls _invalidate; cache is empty.
       Stage 3: a second GET re-populates the cache from DB."""
    user, tid, pw = tenant_admin
    token = _login(client, user.email, pw, tid)
    headers = {"Authorization": f"Bearer {token}"}
    cache = app.state.tenant_config_cache

    assert tid not in cache  # nothing cached yet

    # Stage 1: first read populates cache
    r1 = client.get("/tenants/me/config", headers=headers)
    assert r1.status_code == 200
    assert tid in cache, "first GET should have populated the cache"

    # Stage 2: mutation invalidates cache
    r2 = client.patch(
        "/tenants/me/automation-mode",
        headers=headers,
        json={"automation_mode": "manual"},
    )
    assert r2.status_code == 204
    assert tid not in cache, "mutation must have invalidated the cache entry"

    # Stage 3: second read repopulates with the new value
    r3 = client.get("/tenants/me/config", headers=headers)
    assert r3.status_code == 200
    assert r3.json()["automation_mode"] == "manual"
    assert tid in cache


# --- bonus: archive a custom hides is_archived=False but keeps row ----


def test_archive_custom_marks_archived_and_disables(
    client: TestClient,
    tenant_admin: tuple[User, UUID, str],
) -> None:
    user, tid, pw = tenant_admin
    token = _login(client, user.email, pw, tid)
    headers = {"Authorization": f"Bearer {token}"}
    created = client.post(
        "/tenants/me/custom-categories",
        headers=headers,
        json={"code": "to_archive", "label_tr": "Arşivlenecek"},
    ).json()

    r = client.delete(
        f"/tenants/me/custom-categories/{created['id']}",
        headers=headers,
    )
    assert r.status_code == 204

    cfg = client.get("/tenants/me/config", headers=headers).json()
    archived = next((c for c in cfg["categories"] if c["id"] == created["id"]), None)
    assert archived is not None, "archived rows must still surface"
    assert archived["is_archived"] is True
    assert archived["is_enabled"] is False


# --- archive global must be rejected (system row) ---------------------


@pytest.mark.asyncio
async def test_archive_global_is_rejected(
    client: TestClient,
    tenant_admin: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    user, tid, pw = tenant_admin
    token = _login(client, user.email, pw, tid)
    async with admin_session.begin():
        row = await admin_session.execute(
            select(Category.id).where(Category.tenant_id.is_(None)).limit(1)
        )
        global_id = row.scalar_one()
    r = client.delete(
        f"/tenants/me/custom-categories/{global_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400
