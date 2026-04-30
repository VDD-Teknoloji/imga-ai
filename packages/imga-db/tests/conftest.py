"""Shared async-pytest fixtures for imga-db.

Strategy: tests run against the live `imga-postgres` container. The
session-scoped fixtures connect once with three different roles (owner,
app, admin) so we can assert that imga_app is bound by RLS while imga_admin
bypasses it. Every test cleans up the rows it inserted.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from imga_db import create_engine, create_session_factory

# All tests reach the host-mapped port; production uses the docker hostname.
_HOST = os.environ.get("IMGA_TEST_PG_HOST", "localhost")
_PORT = os.environ.get("IMGA_POSTGRES_PORT", "5433")

OWNER_URL = f"postgresql+asyncpg://imga_owner:imga_dev_password@{_HOST}:{_PORT}/imga"
APP_URL = f"postgresql+asyncpg://imga_app:imga_app_password@{_HOST}:{_PORT}/imga"
ADMIN_URL = f"postgresql+asyncpg://imga_admin:imga_admin_password@{_HOST}:{_PORT}/imga"


@pytest_asyncio.fixture
async def owner_engine() -> AsyncIterator[AsyncEngine]:
    os.environ["DATABASE_URL_OWNER"] = OWNER_URL
    engine = create_engine("owner")
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def app_engine() -> AsyncIterator[AsyncEngine]:
    os.environ["DATABASE_URL"] = APP_URL
    engine = create_engine("app")
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def admin_engine() -> AsyncIterator[AsyncEngine]:
    os.environ["DATABASE_URL_ADMIN"] = ADMIN_URL
    engine = create_engine("admin")
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def owner_session(
    owner_engine: AsyncEngine,
) -> AsyncIterator[AsyncSession]:
    factory = create_session_factory(owner_engine)
    async with factory() as session:
        yield session


@pytest_asyncio.fixture
async def app_session_factory(
    app_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(app_engine)


@pytest_asyncio.fixture
async def admin_session_factory(
    admin_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(admin_engine)


@pytest_asyncio.fixture
async def alpha_tenant_id(owner_engine: AsyncEngine) -> AsyncIterator[UUID]:
    """Create a 'tenant_alpha' tenant for the duration of a test."""
    factory = create_session_factory(owner_engine)
    tid = uuid4()
    async with factory() as s, s.begin():
        await s.execute(
            text(
                "INSERT INTO tenants (id, name, slug, plan_tier, automation_mode, "
                "settings) VALUES (:id, 'Alpha', :slug, 'trial', "
                "'semi_auto', '{}'::json)"
            ),
            {"id": str(tid), "slug": f"alpha-{tid.hex[:8]}"},
        )
    yield tid
    async with factory() as s, s.begin():
        await s.execute(text("DELETE FROM tenants WHERE id = :id"), {"id": str(tid)})


@pytest_asyncio.fixture
async def beta_tenant_id(owner_engine: AsyncEngine) -> AsyncIterator[UUID]:
    factory = create_session_factory(owner_engine)
    tid = uuid4()
    async with factory() as s, s.begin():
        await s.execute(
            text(
                "INSERT INTO tenants (id, name, slug, plan_tier, automation_mode, "
                "settings) VALUES (:id, 'Beta', :slug, 'trial', "
                "'semi_auto', '{}'::json)"
            ),
            {"id": str(tid), "slug": f"beta-{tid.hex[:8]}"},
        )
    yield tid
    async with factory() as s, s.begin():
        await s.execute(text("DELETE FROM tenants WHERE id = :id"), {"id": str(tid)})
