"""Async DB session dependencies for FastAPI.

Three engines (Sprint 7.1):
  * owner — migrations only, not exposed to handlers
  * app   — default for tenant-scoped endpoints; RLS enforced
  * admin — super-admin endpoints; BYPASSRLS

`get_app_session` opens a transaction and binds app.current_tenant_id
*before* yielding the session. That guarantees every query the handler
makes is RLS-scoped, and that the SET LOCAL is automatically discarded
on commit/rollback.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from fastapi import Request
from imga_db import create_engine, create_session_factory
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


def _ensure_engine(app: Any, role: str, attr: str) -> AsyncEngine:
    if not hasattr(app.state, attr):
        engine = create_engine(role)
        setattr(app.state, attr, engine)
        setattr(app.state, f"{attr}_factory", create_session_factory(engine))
    return getattr(app.state, attr)  # type: ignore[no-any-return]


def _factory(request: Request, role: str, attr: str) -> async_sessionmaker[AsyncSession]:
    _ensure_engine(request.app, role, attr)
    return getattr(request.app.state, f"{attr}_factory")  # type: ignore[no-any-return]


async def get_admin_session(request: Request) -> AsyncIterator[AsyncSession]:
    """imga_admin role (BYPASSRLS). Use only for super-admin endpoints
    and for AuthService at login (no tenant context yet)."""
    factory = _factory(request, "admin", "admin_db_engine")
    async with factory() as session:
        try:
            yield session
            if session.in_transaction():
                await session.commit()
        except Exception:
            if session.in_transaction():
                await session.rollback()
            raise


async def get_app_session(request: Request) -> AsyncIterator[AsyncSession]:
    """imga_app role (RLS enforced). Use for tenant-scoped endpoints."""
    factory = _factory(request, "app", "app_db_engine")
    async with factory() as session:
        try:
            yield session
            if session.in_transaction():
                await session.commit()
        except Exception:
            if session.in_transaction():
                await session.rollback()
            raise
