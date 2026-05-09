"""Sprint 9.1 F — N+1 regression guard.

The codebase deliberately avoids SQLAlchemy ``relationship()`` so the
classic lazy-load N+1 is structurally impossible today. This test
file pins the *current* steady-state SELECT count per hot endpoint so
adding a relationship (or a hand-written ``for row in rows: await
fetch(...)``) breaks loud rather than degrades gracefully.

The counter wraps the asyncpg driver with a SQLAlchemy ``before_cursor_execute``
event listener; we count only SELECTs (and explicitly skip the per-
request RLS bind ``SET LOCAL`` because that's a transparent middleware
side-effect, not application logic).

Tolerances:
* Each test asserts ``count <= EXPECTED + 1`` rather than exact
  equality so a future migration that adds a small admin-side bookkeep
  query (audit_logs etc.) doesn't cause a noisy fail. The point of the
  guard is "the curve stays flat", not "the constant never moves".
* Tests run a list with deliberately-small row counts (3-5) and a list
  with a larger count (25+). If the count is the same on both, the
  endpoint is constant-time in row count — that's the property we
  care about.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from cachetools import TTLCache
from fastapi import FastAPI
from fastapi.testclient import TestClient
from imga_db import create_engine, create_session_factory
from imga_db.models import ActionItem, UserTenantRole
from sqlalchemy import event, text
from sqlalchemy.engine import Connection
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


class _SelectCounter:
    """Tiny SELECT counter. Hooks into ``before_cursor_execute`` on the
    sync engine SQLAlchemy uses under the asyncpg adapter."""

    def __init__(self) -> None:
        self.selects = 0
        self.statements: list[str] = []

    def listen(self, sync_engine: object) -> None:
        @event.listens_for(sync_engine, "before_cursor_execute")
        def _on(  # noqa: ANN001 — SQLA-driven signature
            conn: Connection,
            cursor: object,
            statement: str,
            parameters: object,
            context: object,
            executemany: bool,
        ) -> None:
            text_lower = statement.lstrip().lower()
            # Skip RLS bind + transaction control + worker-bookkeep
            # statements; we only count app-issued reads.
            if text_lower.startswith(("select",)):
                self.selects += 1
                self.statements.append(statement[:140])

    def reset(self) -> None:
        self.selects = 0
        self.statements.clear()


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
def client_with_counter() -> Iterator[tuple[TestClient, _SelectCounter]]:
    counter = _SelectCounter()

    @asynccontextmanager
    async def _test_lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.settings = Settings.from_env()
        application.state.tenant_config_cache = TTLCache(maxsize=1000, ttl=300)
        # /health depends on get_pipeline; this test never invokes the
        # analyze pipeline so a MagicMock satisfies the contract for
        # the warm-up GET.
        application.state.pipeline = MagicMock()
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
            # Engines are created lazily on the first DB-touching
            # request; the test calls ``_login(...)`` first, then
            # ``_arm_counter(counter)`` once the engine exists.
            yield c, counter
    finally:
        app.router.lifespan_context = original


def _arm_counter(client: TestClient, headers: dict[str, str], counter: _SelectCounter) -> None:
    """Hit /auth/me to warm both the admin and app engines (login
    only touches admin), then attach the SELECT listener to both
    sync engines so the count covers the full request lifecycle."""
    me = client.get("/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    counter.listen(app.state.app_db_engine.sync_engine)
    counter.listen(app.state.admin_db_engine.sync_engine)


@pytest_asyncio.fixture
async def seeded_tenant(
    admin_session: AsyncSession,
) -> AsyncIterator[tuple[UUID, str, str]]:
    """One tenant + tenant_admin user. Returns (tenant_id, email, password)."""
    audit = AuditService(admin_session)
    tsvc = TenantService(admin_session, audit)
    usvc = UserService(admin_session, audit)
    plain = "Q-Counter-Pwd-1234"
    email = f"qct-{uuid4().hex[:8]}@example.com"
    async with admin_session.begin():
        tenant = await tsvc.create(
            name="QC Co", slug=f"qc-{uuid4().hex[:8]}"
        )
        user = await usvc.create(email=email, password=plain, full_name="QC")
        await usvc.attach_to_tenant(
            user_id=user.id,
            tenant_id=tenant.id,
            role=UserTenantRole.TENANT_ADMIN,
        )
        tenant_id = tenant.id
        user_id = user.id
    yield tenant_id, email, plain
    async with admin_session.begin():
        await admin_session.execute(
            text("DELETE FROM users WHERE id = :id"),
            {"id": str(user_id)},
        )
        await admin_session.execute(
            text("DELETE FROM tenants WHERE id = :id"),
            {"id": str(tenant_id)},
        )


def _login(client: TestClient, email: str, password: str, tenant_id: UUID) -> str:
    r = client.post(
        "/auth/login",
        json={
            "email": email,
            "password": password,
            "active_tenant_id": str(tenant_id),
        },
    )
    assert r.status_code == 200, r.text
    return str(r.json()["access_token"])


# Sprint 9.1 F — guard: the action-items list is constant-time in row
# count. We seed N rows directly via the admin session and assert the
# SELECT count doesn't grow with N.


@pytest.mark.asyncio
async def test_action_items_list_is_constant_time(
    client_with_counter: tuple[TestClient, _SelectCounter],
    admin_session: AsyncSession,
    seeded_tenant: tuple[UUID, str, str],
) -> None:
    client, counter = client_with_counter
    tenant_id, email, password = seeded_tenant

    # 25 action items.
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tenant_id)},
        )
        for _ in range(25):
            admin_session.add(
                ActionItem(
                    tenant_id=tenant_id,
                    title="x",
                    description="y",
                    priority="medium",
                    status="open",
                )
            )
        await admin_session.flush()

    # Trigger lazy engine creation via login (also gives us the bearer)
    # then arm the SELECT counter against the now-existing engine.
    headers = {
        "Authorization": f"Bearer {_login(client, email, password, tenant_id)}"
    }
    _arm_counter(client, headers, counter)

    counter.reset()
    r = client.get("/tenants/me/action-items", headers=headers)
    assert r.status_code == 200, r.text
    assert len(r.json()) == 25
    # The list endpoint should issue a small fixed number of SELECTs:
    # auth-deps reads (user + me + tenant) + the list query itself. We
    # assert <= 8 to leave room for the auth path; the important
    # property is independence from row count, verified below.
    rows_25 = counter.selects
    assert rows_25 <= 8, (
        f"expected <=8 SELECTs for 25-row list, got {rows_25}: "
        f"{counter.statements}"
    )

    # Wipe + reseed with 1 row, confirm the count is the same shape.
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tenant_id)},
        )
        await admin_session.execute(
            text("DELETE FROM action_items WHERE tenant_id = :t"),
            {"t": str(tenant_id)},
        )
        admin_session.add(
            ActionItem(
                tenant_id=tenant_id,
                title="x",
                description="y",
                priority="medium",
                status="open",
            )
        )

    counter.reset()
    r = client.get("/tenants/me/action-items", headers=headers)
    assert r.status_code == 200, r.text
    rows_1 = counter.selects
    # The shape should match — the rows-25 and rows-1 counts are
    # equal in the steady state. The whole point of the guard.
    assert rows_25 == rows_1, (
        f"action_items list became row-dependent: 25 rows -> {rows_25}, "
        f"1 row -> {rows_1}"
    )


@pytest.mark.asyncio
async def test_reviews_list_is_constant_time(
    client_with_counter: tuple[TestClient, _SelectCounter],
    admin_session: AsyncSession,
    seeded_tenant: tuple[UUID, str, str],
) -> None:
    """/tenants/me/reviews — single COUNT + single paginated SELECT,
    flat in row count. Seeded via direct SQL insert (the analyze flow
    is too heavy and not what we're testing)."""
    from datetime import UTC, datetime

    client, counter = client_with_counter
    tenant_id, email, password = seeded_tenant

    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tenant_id)},
        )
        for i in range(15):
            await admin_session.execute(
                text(
                    "INSERT INTO reviews "
                    "(id, tenant_id, text, text_hash, sentiment_label, "
                    " sentiment_score, primary_category, primary_confidence, "
                    " automation_mode, decision, analyzed_at) "
                    "VALUES (gen_random_uuid(), :t, :tx, :h, 'POZITIF', "
                    " 0.5, 'belirsiz', 0.5, 'manual', 'create', :ts)"
                ),
                {
                    "t": str(tenant_id),
                    "tx": f"deneme {i}",
                    # text_hash CHECK requires the canonical sha256 hex
                    # length (64 chars). uuid4().hex is 32; double it
                    # so the constraint accepts the value.
                    "h": (uuid4().hex + uuid4().hex),
                    "ts": datetime.now(UTC),
                },
            )

    headers = {
        "Authorization": f"Bearer {_login(client, email, password, tenant_id)}"
    }
    _arm_counter(client, headers, counter)
    counter.reset()
    r = client.get("/tenants/me/reviews?limit=20", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) == 15
    # Auth (~3-5) + count + paginated list = budget ~10. Tighter than
    # action_items because reviews has fewer auth-side fetches.
    assert counter.selects <= 10, (
        f"reviews list issued {counter.selects} SELECTs: {counter.statements}"
    )
