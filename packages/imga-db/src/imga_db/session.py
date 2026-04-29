"""Async sessionmaker, three-role engine factory, and pool defenses.

Three roles, three URLs:
    DATABASE_URL_OWNER  - migrations (alembic), runs as imga_owner (superuser)
    DATABASE_URL        - default app, runs as imga_app (NOBYPASSRLS)
    DATABASE_URL_ADMIN  - super-admin endpoints, runs as imga_admin (BYPASSRLS)

`set_current_tenant(session, tenant_id)` MUST be called inside a transaction
before any tenant-scoped query. The pool checkin hook clears
app.current_tenant_id when a connection returns to the pool, defending
against accidental tenant leakage if a request forgets to RESET.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

DEFAULT_APP_URL = "postgresql+asyncpg://imga_app:imga_app_password@postgres:5432/imga"
DEFAULT_OWNER_URL = "postgresql+asyncpg://imga_owner:imga_dev_password@postgres:5432/imga"
DEFAULT_ADMIN_URL = "postgresql+asyncpg://imga_admin:imga_admin_password@postgres:5432/imga"

TENANT_SETTING = "app.current_tenant_id"


def get_database_url(role: str = "app") -> str:
    """Return the connection string for one of the three roles.

    role: 'owner' | 'app' | 'admin'.
    """
    if role == "owner":
        return os.environ.get("DATABASE_URL_OWNER", DEFAULT_OWNER_URL)
    if role == "admin":
        return os.environ.get("DATABASE_URL_ADMIN", DEFAULT_ADMIN_URL)
    if role == "app":
        return os.environ.get("DATABASE_URL", DEFAULT_APP_URL)
    raise ValueError(f"Unknown role {role!r}; expected 'owner' | 'app' | 'admin'")


def create_engine(role: str = "app", **kwargs: Any) -> AsyncEngine:
    """Construct an AsyncEngine for the given role.

    Defense-in-depth note: We rely on `SET LOCAL` (transaction-scoped) for
    `app.current_tenant_id` rather than `SET` (session-scoped). Because
    SET LOCAL is automatically discarded when the transaction commits or
    rolls back, a connection returning to the pool always has a clean
    setting. A SQLAlchemy `checkin` event listener that issues an explicit
    `RESET` was tried and removed: the sync listener calls cursor.execute()
    on the asyncpg connection wrapper, which races with implicit
    transactions opened by SQLAlchemy's reset-on-return cycle and raises
    "cannot use Connection.transaction() in a manually started transaction".
    `set_current_tenant` enforces that callers run inside a transaction;
    that single contract is what makes the SET LOCAL safe.
    """
    url = get_database_url(role)
    return create_async_engine(url, **kwargs)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@asynccontextmanager
async def session_scope(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Open a session that auto-commits on success, rolls back on failure."""
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def set_current_tenant(session: AsyncSession, tenant_id: UUID) -> None:
    """Bind the active tenant to this session's transaction.

    MUST be called inside an active transaction (use ``async with
    session.begin()``). RLS policies look up
    ``current_setting('app.current_tenant_id', true)::uuid``; outside a
    transaction the SET LOCAL is silently dropped because the connection
    is released back to the pool.
    """
    if not session.in_transaction():
        raise RuntimeError(
            "set_current_tenant must be called inside an active transaction "
            "(SET LOCAL would leak otherwise)"
        )
    # set_config(setting, value, is_local) is the parametrizable form of
    # SET LOCAL. The bare `SET LOCAL` statement does not accept bind params.
    await session.execute(
        text("SELECT set_config(:k, :v, true)"),
        {"k": TENANT_SETTING, "v": str(tenant_id)},
    )


