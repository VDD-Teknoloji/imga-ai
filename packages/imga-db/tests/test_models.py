"""Sanity tests for the SQLAlchemy 2.0 models (CRUD + cascade)."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from imga_db import create_session_factory
from imga_db.models import Tenant, User, UserTenantLink, UserTenantRole


@pytest.mark.asyncio
async def test_create_tenant_via_model(owner_engine: AsyncEngine) -> None:
    factory = create_session_factory(owner_engine)
    async with factory() as s, s.begin():
        t = Tenant(name="Roundtrip Co", slug=f"rt-{uuid4().hex[:8]}")
        s.add(t)
        await s.flush()
        assert t.id is not None
        # cleanup
        await s.execute(text("DELETE FROM tenants WHERE id = :id"), {"id": str(t.id)})


@pytest.mark.asyncio
async def test_user_email_unique(owner_engine: AsyncEngine) -> None:
    factory = create_session_factory(owner_engine)
    email = f"unique-{uuid4().hex[:8]}@test"
    async with factory() as s, s.begin():
        u = User(email=email, password_hash="x", full_name="A")
        s.add(u)
        await s.flush()

    async with factory() as s, s.begin():
        with pytest.raises(IntegrityError):
            u2 = User(email=email, password_hash="y", full_name="B")
            s.add(u2)
            await s.flush()

    async with factory() as s, s.begin():
        await s.execute(text("DELETE FROM users WHERE email = :e"), {"e": email})


@pytest.mark.asyncio
async def test_super_admin_seeded(owner_engine: AsyncEngine) -> None:
    factory = create_session_factory(owner_engine)
    async with factory() as s:
        result = await s.execute(
            select(User).where(User.is_super_admin.is_(True))
        )
        admins = result.scalars().all()
    assert len(admins) >= 1
    assert any(a.email == "admin@imga.ai" for a in admins)


@pytest.mark.asyncio
async def test_user_tenant_link_via_model(
    owner_engine: AsyncEngine,
    alpha_tenant_id: UUID,
) -> None:
    factory = create_session_factory(owner_engine)
    user_id = uuid4()
    async with factory() as s, s.begin():
        s.add(User(id=user_id, email=f"link-{user_id.hex[:8]}@test",
                   password_hash="x", full_name="Link"))
        s.add(UserTenantLink(
            user_id=user_id,
            tenant_id=alpha_tenant_id,
            role=UserTenantRole.ANALYST,
        ))
        await s.flush()

    async with factory() as s:
        result = await s.execute(
            select(UserTenantLink).where(UserTenantLink.user_id == user_id)
        )
        links = result.scalars().all()
    assert len(links) == 1
    assert links[0].role == UserTenantRole.ANALYST

    async with factory() as s, s.begin():
        await s.execute(text("DELETE FROM users WHERE id = :id"), {"id": str(user_id)})
