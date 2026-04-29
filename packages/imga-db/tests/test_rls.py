"""Row-Level Security isolation tests.

Critical guarantees verified here:
  1. Two tenants' rows are mutually invisible to imga_app sessions.
  2. FORCE ROW LEVEL SECURITY: imga_app cannot read ANY rows when
     app.current_tenant_id is unset.
  3. imga_admin (BYPASSRLS) reads everything across tenants.
  4. set_current_tenant requires an active transaction (fail-fast).
  5. Pool checkin RESETs app.current_tenant_id (defense in depth).
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from imga_db import create_session_factory, set_current_tenant


@pytest_asyncio.fixture
async def alpha_user_link(
    owner_engine: AsyncEngine,
    alpha_tenant_id: UUID,
) -> UUID:
    """Insert a user + user_tenants row scoped to alpha tenant."""
    factory = create_session_factory(owner_engine)
    user_id = uuid4()
    async with factory() as s, s.begin():
        await s.execute(
            text(
                "INSERT INTO users (id, email, password_hash, full_name) "
                "VALUES (:id, :email, 'hash', 'Alpha User')"
            ),
            {"id": str(user_id), "email": f"alpha-{user_id.hex[:8]}@test"},
        )
        await s.execute(
            text(
                "INSERT INTO user_tenants (user_id, tenant_id, role) "
                "VALUES (:uid, :tid, 'analyst')"
            ),
            {"uid": str(user_id), "tid": str(alpha_tenant_id)},
        )
    return user_id


@pytest_asyncio.fixture
async def beta_user_link(
    owner_engine: AsyncEngine,
    beta_tenant_id: UUID,
) -> UUID:
    factory = create_session_factory(owner_engine)
    user_id = uuid4()
    async with factory() as s, s.begin():
        await s.execute(
            text(
                "INSERT INTO users (id, email, password_hash, full_name) "
                "VALUES (:id, :email, 'hash', 'Beta User')"
            ),
            {"id": str(user_id), "email": f"beta-{user_id.hex[:8]}@test"},
        )
        await s.execute(
            text(
                "INSERT INTO user_tenants (user_id, tenant_id, role) "
                "VALUES (:uid, :tid, 'analyst')"
            ),
            {"uid": str(user_id), "tid": str(beta_tenant_id)},
        )
    return user_id


# --- 1. Tenant isolation: alpha can't see beta's rows --------------------


@pytest.mark.asyncio
async def test_app_session_in_alpha_context_sees_only_alpha_rows(
    app_session_factory: async_sessionmaker[AsyncSession],
    alpha_tenant_id: UUID,
    beta_tenant_id: UUID,
    alpha_user_link: UUID,
    beta_user_link: UUID,
) -> None:
    async with app_session_factory() as s, s.begin():
        await set_current_tenant(s, alpha_tenant_id)

        result = await s.execute(text("SELECT tenant_id FROM user_tenants"))
        rows = result.all()

    seen = {row[0] for row in rows}
    assert alpha_tenant_id in seen, "alpha rows must be visible"
    assert beta_tenant_id not in seen, "beta rows MUST be hidden by RLS"


@pytest.mark.asyncio
async def test_app_session_cannot_insert_into_other_tenant(
    app_session_factory: async_sessionmaker[AsyncSession],
    alpha_tenant_id: UUID,
    beta_tenant_id: UUID,
    alpha_user_link: UUID,
) -> None:
    """RLS WITH CHECK: cannot insert rows tagged with someone else's tenant."""
    async with app_session_factory() as s, s.begin():
        await set_current_tenant(s, alpha_tenant_id)
        # asyncpg raises InsufficientPrivilege ("new row violates row-level
        # security policy"), which SQLAlchemy wraps in DBAPIError.
        with pytest.raises(DBAPIError, match="row-level security"):
            await s.execute(
                text(
                    "INSERT INTO user_tenants (user_id, tenant_id, role) "
                    "VALUES (:uid, :tid, 'viewer')"
                ),
                {"uid": str(alpha_user_link), "tid": str(beta_tenant_id)},
            )


# --- 2. FORCE RLS: imga_app sees nothing without context ----------------


@pytest.mark.asyncio
async def test_app_session_without_tenant_context_sees_zero_rows(
    app_session_factory: async_sessionmaker[AsyncSession],
    alpha_user_link: UUID,
    beta_user_link: UUID,
) -> None:
    """app.current_tenant_id unset -> current_setting returns NULL ->
    NULL = NULL is NULL (not true) -> RLS returns 0 rows."""
    async with app_session_factory() as s, s.begin():
        # Deliberately NOT calling set_current_tenant
        result = await s.execute(text("SELECT count(*) FROM user_tenants"))
        count = result.scalar_one()
    assert count == 0, "FORCE RLS must hide everything when context is missing"


# --- 3. BYPASSRLS: imga_admin reads everything --------------------------


@pytest.mark.asyncio
async def test_admin_session_bypasses_rls(
    admin_session_factory: async_sessionmaker[AsyncSession],
    alpha_user_link: UUID,
    beta_user_link: UUID,
) -> None:
    """imga_admin has BYPASSRLS — sees rows from every tenant."""
    async with admin_session_factory() as s:
        result = await s.execute(text("SELECT DISTINCT tenant_id FROM user_tenants"))
        tenants_seen = {row[0] for row in result}
    # Both fixtures inserted rows for two distinct tenants.
    assert len(tenants_seen) >= 2, f"admin should see all tenants, got {tenants_seen}"


# --- 4. set_current_tenant must run inside a transaction ----------------


@pytest.mark.asyncio
async def test_set_current_tenant_outside_transaction_raises(
    app_session_factory: async_sessionmaker[AsyncSession],
    alpha_tenant_id: UUID,
) -> None:
    async with app_session_factory() as s:
        # No s.begin() — autocommit mode for asyncpg means in_transaction()
        # returns False. set_current_tenant must refuse.
        with pytest.raises(RuntimeError, match="active transaction"):
            await set_current_tenant(s, alpha_tenant_id)


# --- 5. Defense-in-depth: SET LOCAL does not survive pool reuse ---------


@pytest.mark.asyncio
async def test_pool_reuse_does_not_leak_tenant_setting(
    alpha_tenant_id: UUID,
) -> None:
    """SET LOCAL is transaction-scoped; on commit the setting is discarded.

    A tiny single-connection pool guarantees the second session reuses the
    exact same DB connection that hosted the first session's transaction.
    If we accidentally used SET (without LOCAL), the setting would still
    be visible here — this test catches that regression.
    """
    import os

    from sqlalchemy.ext.asyncio import create_async_engine

    from imga_db.session import create_session_factory

    # Use the runtime URL the rest of the suite uses, but with a 1-slot pool.
    url = os.environ["DATABASE_URL"]
    engine = create_async_engine(url, pool_size=1, max_overflow=0)
    factory = create_session_factory(engine)
    try:
        # First session: bind tenant inside a transaction, then commit.
        async with factory() as s, s.begin():
            await set_current_tenant(s, alpha_tenant_id)
            # Inside the transaction, current_setting should reflect alpha.
            result = await s.execute(
                text("SELECT current_setting('app.current_tenant_id', true)")
            )
            assert result.scalar_one() == str(alpha_tenant_id)

        # Second session: same physical connection, fresh transaction.
        async with factory() as s, s.begin():
            result = await s.execute(
                text("SELECT current_setting('app.current_tenant_id', true)")
            )
            value = result.scalar_one()
        assert value in ("", None), f"Tenant leaked across pool reuse: {value!r}"
    finally:
        await engine.dispose()


# --- 6. Transaction-less SELECT is still RLS-protected ------------------


@pytest.mark.asyncio
async def test_transactionless_select_is_rls_blocked(
    app_session_factory: async_sessionmaker[AsyncSession],
    alpha_user_link: UUID,
) -> None:
    """Even when the caller forgets `async with s.begin():`, RLS still
    returns zero rows because current_setting is NULL on a fresh
    autocommit statement.
    """
    async with app_session_factory() as s:
        # No begin/commit wrapper — asyncpg autocommits each statement.
        result = await s.execute(text("SELECT count(*) FROM user_tenants"))
        count = result.scalar_one()
    assert count == 0, (
        "FORCE RLS must hide everything in transaction-less mode too "
        "(current_setting is NULL outside the helper's transaction)"
    )


# --- 7. Helper uses set_config(..., true) — i.e. SET LOCAL semantics ---


def test_set_current_tenant_uses_local_scope() -> None:
    """If a refactor accidentally drops the third `true` argument from
    set_config(), the helper's binding would survive commit and leak across
    pool checkouts. This source-level guard catches that regression.
    """
    import inspect

    from imga_db.session import set_current_tenant

    src = inspect.getsource(set_current_tenant)
    assert "set_config" in src, "expected set_config(...) call (parametrizable SET LOCAL)"
    assert ", true)" in src or ", :is_local" in src, (
        "expected is_local=true third argument to set_config; without it the "
        "binding would be SESSION-scope and leak across pool reuse"
    )
