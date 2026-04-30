"""Integration tests for GET /tenants/me/users.

Sprint 7.5.5 / Alt-Faz 4 (A7). Covers:

  * All three roles (TENANT_ADMIN / ANALYST / VIEWER) can read.
  * Search filter matches case-insensitive email + full_name.
  * Soft-deleted users are excluded.
  * RLS isolation: tenant B doesn't see tenant A's members.
  * last_login_at / invitation_accepted_at surfaced as expected.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from cachetools import TTLCache
from fastapi.testclient import TestClient
from imga_db import create_engine, create_session_factory
from imga_db.models import User, UserTenantRole
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from imga_api.main import app
from imga_api.services import AuditService, TenantService, UserService
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


@pytest.fixture
def client() -> Iterator[TestClient]:
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


async def _seed_user_with_role(
    admin_session: AsyncSession,
    *,
    tenant_id: UUID,
    role: UserTenantRole,
    full_name: str | None = None,
    email_prefix: str = "dir",
) -> tuple[User, str]:
    audit = AuditService(admin_session)
    usvc = UserService(admin_session, audit)
    plain = "Test-Password-123!"
    email = f"{email_prefix}-{uuid4().hex[:8]}@example.com"
    fname = full_name or f"Dir User {uuid4().hex[:4]}"
    async with admin_session.begin():
        user = await usvc.create(email=email, password=plain, full_name=fname)
        await usvc.attach_to_tenant(
            user_id=user.id,
            tenant_id=tenant_id,
            role=role,
            invitation_accepted_at=datetime.now(UTC),
        )
    return user, plain


@pytest_asyncio.fixture
async def directory_fixture(
    admin_session: AsyncSession,
) -> AsyncIterator[
    tuple[
        UUID,
        tuple[User, str],  # admin
        tuple[User, str],  # analyst
        tuple[User, str],  # viewer
    ]
]:
    audit = AuditService(admin_session)
    tsvc = TenantService(admin_session, audit)
    async with admin_session.begin():
        tenant = await tsvc.create(name="Dir Co", slug=f"dir-{uuid4().hex[:8]}")

    admin = await _seed_user_with_role(
        admin_session,
        tenant_id=tenant.id,
        role=UserTenantRole.TENANT_ADMIN,
        full_name="Alice Admin",
        email_prefix="alice",
    )
    analyst = await _seed_user_with_role(
        admin_session,
        tenant_id=tenant.id,
        role=UserTenantRole.ANALYST,
        full_name="Bob Analyst",
        email_prefix="bob",
    )
    viewer = await _seed_user_with_role(
        admin_session,
        tenant_id=tenant.id,
        role=UserTenantRole.VIEWER,
        full_name="Carol Viewer",
        email_prefix="carol",
    )
    yield tenant.id, admin, analyst, viewer

    async with admin_session.begin():
        for u in (admin[0], analyst[0], viewer[0]):
            await admin_session.execute(
                text("DELETE FROM users WHERE id = :id"), {"id": str(u.id)}
            )
        await admin_session.execute(
            text("DELETE FROM tenants WHERE id = :id"), {"id": str(tenant.id)},
        )


# --- read access ---------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_can_list_members(
    client: TestClient,
    directory_fixture: tuple[
        UUID, tuple[User, str], tuple[User, str], tuple[User, str]
    ],
) -> None:
    tenant_id, admin, _analyst, _viewer = directory_fixture
    a_user, a_pw = admin
    token = _login(client, a_user.email, a_pw, tenant_id)
    r = client.get("/tenants/me/users", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    members = r.json()["members"]
    # Admin + analyst + viewer = 3.
    assert len(members) == 3
    # Sorted by full_name → Alice, Bob, Carol.
    names = [m["full_name"] for m in members]
    assert names == sorted(names)
    roles = {m["role"] for m in members}
    assert roles == {"tenant_admin", "analyst", "viewer"}


@pytest.mark.asyncio
async def test_viewer_can_also_list_members(
    client: TestClient,
    directory_fixture: tuple[
        UUID, tuple[User, str], tuple[User, str], tuple[User, str]
    ],
) -> None:
    """A7 requirement: every member role can read the directory."""
    tenant_id, _admin, _analyst, viewer = directory_fixture
    v_user, v_pw = viewer
    token = _login(client, v_user.email, v_pw, tenant_id)
    r = client.get("/tenants/me/users", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    assert len(r.json()["members"]) == 3


# --- search filter -------------------------------------------------------


@pytest.mark.asyncio
async def test_search_filter_matches_email_substring(
    client: TestClient,
    directory_fixture: tuple[
        UUID, tuple[User, str], tuple[User, str], tuple[User, str]
    ],
) -> None:
    tenant_id, admin, _analyst, _viewer = directory_fixture
    a_user, a_pw = admin
    token = _login(client, a_user.email, a_pw, tenant_id)

    r = client.get(
        "/tenants/me/users?search=bob",
        headers={"Authorization": f"Bearer {token}"},
    )
    members = r.json()["members"]
    assert len(members) == 1
    assert members[0]["email"].startswith("bob-")


@pytest.mark.asyncio
async def test_search_filter_matches_full_name_case_insensitive(
    client: TestClient,
    directory_fixture: tuple[
        UUID, tuple[User, str], tuple[User, str], tuple[User, str]
    ],
) -> None:
    tenant_id, admin, _analyst, _viewer = directory_fixture
    a_user, a_pw = admin
    token = _login(client, a_user.email, a_pw, tenant_id)

    # Lowercase needle should still match capitalized seed.
    r = client.get(
        "/tenants/me/users?search=alice",
        headers={"Authorization": f"Bearer {token}"},
    )
    members = r.json()["members"]
    assert len(members) == 1
    assert members[0]["full_name"] == "Alice Admin"


@pytest.mark.asyncio
async def test_search_no_match_returns_empty(
    client: TestClient,
    directory_fixture: tuple[
        UUID, tuple[User, str], tuple[User, str], tuple[User, str]
    ],
) -> None:
    tenant_id, admin, _analyst, _viewer = directory_fixture
    a_user, a_pw = admin
    token = _login(client, a_user.email, a_pw, tenant_id)

    r = client.get(
        "/tenants/me/users?search=zzznotpresent",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.json()["members"] == []


# --- soft-deleted exclusion ----------------------------------------------


@pytest.mark.asyncio
async def test_soft_deleted_users_excluded(
    client: TestClient,
    admin_session: AsyncSession,
    directory_fixture: tuple[
        UUID, tuple[User, str], tuple[User, str], tuple[User, str]
    ],
) -> None:
    tenant_id, admin, analyst, _viewer = directory_fixture
    a_user, a_pw = admin

    # Soft-delete the analyst row.
    async with admin_session.begin():
        await admin_session.execute(
            text("UPDATE users SET deleted_at = now() WHERE id = :id"),
            {"id": str(analyst[0].id)},
        )

    token = _login(client, a_user.email, a_pw, tenant_id)
    r = client.get("/tenants/me/users", headers={"Authorization": f"Bearer {token}"})
    members = r.json()["members"]
    # Only admin + viewer; analyst is hidden.
    assert len(members) == 2
    assert all(m["user_id"] != str(analyst[0].id) for m in members)


# --- RLS / tenant isolation ----------------------------------------------


@pytest.mark.asyncio
async def test_other_tenant_members_not_visible(
    client: TestClient,
    admin_session: AsyncSession,
    directory_fixture: tuple[
        UUID, tuple[User, str], tuple[User, str], tuple[User, str]
    ],
) -> None:
    """Tenant B's admin sees only B's members, not A's."""
    _tid_a, _admin_a, _analyst_a, _viewer_a = directory_fixture

    # Stand up tenant B + admin + 1 extra member.
    audit = AuditService(admin_session)
    tsvc = TenantService(admin_session, audit)
    async with admin_session.begin():
        tenant_b = await tsvc.create(
            name="B Co", slug=f"b-{uuid4().hex[:8]}"
        )
    b_admin = await _seed_user_with_role(
        admin_session,
        tenant_id=tenant_b.id,
        role=UserTenantRole.TENANT_ADMIN,
        full_name="Beta Admin",
        email_prefix="beta",
    )
    b_extra = await _seed_user_with_role(
        admin_session,
        tenant_id=tenant_b.id,
        role=UserTenantRole.ANALYST,
        full_name="Beta Analyst",
        email_prefix="bex",
    )

    try:
        token = _login(client, b_admin[0].email, b_admin[1], tenant_b.id)
        r = client.get(
            "/tenants/me/users", headers={"Authorization": f"Bearer {token}"}
        )
        members = r.json()["members"]
        # Exactly B's 2 members; none from A's directory.
        assert len(members) == 2
        emails = {m["email"] for m in members}
        assert emails == {b_admin[0].email, b_extra[0].email}
    finally:
        async with admin_session.begin():
            for u in (b_admin[0], b_extra[0]):
                await admin_session.execute(
                    text("DELETE FROM users WHERE id = :id"), {"id": str(u.id)}
                )
            await admin_session.execute(
                text("DELETE FROM tenants WHERE id = :id"),
                {"id": str(tenant_b.id)},
            )


# --- last_login_at + invitation_accepted_at surface ----------------------


@pytest.mark.asyncio
async def test_last_login_at_set_after_login(
    client: TestClient,
    directory_fixture: tuple[
        UUID, tuple[User, str], tuple[User, str], tuple[User, str]
    ],
) -> None:
    """After /auth/login, the next directory read shows last_login_at
    set for the caller. Other members might be None (fixture only logs
    in the admin)."""
    tenant_id, admin, _analyst, _viewer = directory_fixture
    a_user, a_pw = admin
    token = _login(client, a_user.email, a_pw, tenant_id)
    r = client.get("/tenants/me/users", headers={"Authorization": f"Bearer {token}"})
    members = r.json()["members"]
    me = next(m for m in members if m["user_id"] == str(a_user.id))
    assert me["last_login_at"] is not None
    assert me["invitation_accepted_at"] is not None
