"""Service-layer integration tests against the live postgres container.

Covers:
  - Tenant CRUD + slug uniqueness
  - User create + email uniqueness
  - Password hash/verify roundtrip
  - Invitation create -> accept flow (positive)
  - Invitation expired -> reject
  - Invitation already accepted -> reject (idempotent / race)
  - Audit log entries written for every critical action
  - RLS-scoped tables (invitations) need set_current_tenant
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from imga_db import create_engine, create_session_factory, set_current_tenant
from imga_db.models import AuditLog, UserTenantLink, UserTenantRole
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from imga_api.security import hash_password, verify_password
from imga_api.services import (
    AuditService,
    InvitationAcceptanceError,
    InvitationService,
    TenantService,
    UserService,
)
from imga_api.services.tenant_service import TenantSlugTakenError
from imga_api.services.user_service import EmailTakenError

_HOST = os.environ.get("IMGA_TEST_PG_HOST", "localhost")
_PORT = os.environ.get("IMGA_POSTGRES_PORT", "5433")
OWNER_URL = f"postgresql+asyncpg://imga_owner:imga_dev_password@{_HOST}:{_PORT}/imga"
APP_URL = f"postgresql+asyncpg://imga_app:imga_app_password@{_HOST}:{_PORT}/imga"


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
async def owner_session(
    owner_engine: AsyncEngine,
) -> AsyncIterator[AsyncSession]:
    factory = create_session_factory(owner_engine)
    async with factory() as s:
        yield s


# Each test cleans up the rows it creates explicitly via the fixtures
# below or via inline DELETE so we don't leak state across runs.


# --- Password hashing -----------------------------------------------------


class TestPasswordHashing:
    def test_hash_and_verify_roundtrip(self) -> None:
        hashed = hash_password("S3cret!")
        assert verify_password("S3cret!", hashed) is True

    def test_wrong_password_rejected(self) -> None:
        hashed = hash_password("S3cret!")
        assert verify_password("wrong", hashed) is False

    def test_empty_password_rejected_at_hash(self) -> None:
        with pytest.raises(ValueError):
            hash_password("")

    def test_empty_password_rejected_at_verify(self) -> None:
        hashed = hash_password("S3cret!")
        assert verify_password("", hashed) is False

    def test_garbage_hash_returns_false(self) -> None:
        assert verify_password("anything", "not-a-real-hash") is False


# --- TenantService ---------------------------------------------------------


@pytest.mark.asyncio
async def test_tenant_create_assigns_id_and_logs(
    owner_session: AsyncSession,
) -> None:
    audit = AuditService(owner_session)
    svc = TenantService(owner_session, audit)
    slug = f"acme-{uuid4().hex[:8]}"
    async with owner_session.begin():
        tenant = await svc.create(name="Acme", slug=slug)
        # Assertions inside transaction so audit log is visible
        log = (
            await owner_session.execute(
                select(AuditLog)
                .where(AuditLog.resource_id == tenant.id)
                .where(AuditLog.action == "tenant.create")
            )
        ).scalar_one()
        assert log.details["slug"] == slug
    assert tenant.id is not None
    # Cleanup
    async with owner_session.begin():
        await owner_session.execute(
            text("DELETE FROM tenants WHERE id = :id"), {"id": str(tenant.id)}
        )


@pytest.mark.asyncio
async def test_tenant_slug_uniqueness_raises(
    owner_session: AsyncSession,
) -> None:
    svc = TenantService(owner_session, AuditService(owner_session))
    slug = f"dup-{uuid4().hex[:8]}"
    async with owner_session.begin():
        t1 = await svc.create(name="First", slug=slug)
        # Capture the id before any later rollback expires `t1`.
        t1_id = t1.id
    # `pytest.raises` wraps the begin() so the failed transaction
    # auto-rolls back on context exit before the next begin().
    with pytest.raises(TenantSlugTakenError):
        async with owner_session.begin():
            await svc.create(name="Second", slug=slug)
    async with owner_session.begin():
        await owner_session.execute(
            text("DELETE FROM tenants WHERE id = :id"), {"id": str(t1_id)}
        )


# --- UserService ----------------------------------------------------------


@pytest.mark.asyncio
async def test_user_create_hashes_password(owner_session: AsyncSession) -> None:
    svc = UserService(owner_session, AuditService(owner_session))
    email = f"uc-{uuid4().hex[:8]}@test"
    async with owner_session.begin():
        user = await svc.create(email=email, password="secret123", full_name="UC")
    assert user.password_hash != "secret123"
    assert verify_password("secret123", user.password_hash) is True
    async with owner_session.begin():
        await owner_session.execute(
            text("DELETE FROM users WHERE id = :id"), {"id": str(user.id)}
        )


@pytest.mark.asyncio
async def test_user_email_uniqueness_raises(owner_session: AsyncSession) -> None:
    svc = UserService(owner_session, AuditService(owner_session))
    email = f"udup-{uuid4().hex[:8]}@test"
    async with owner_session.begin():
        u1 = await svc.create(email=email, password="x", full_name="One")
        u1_id = u1.id
    with pytest.raises(EmailTakenError):
        async with owner_session.begin():
            await svc.create(email=email, password="y", full_name="Two")
    async with owner_session.begin():
        await owner_session.execute(
            text("DELETE FROM users WHERE id = :id"), {"id": str(u1_id)}
        )


@pytest.mark.asyncio
async def test_verify_credentials_returns_user_on_match(
    owner_session: AsyncSession,
) -> None:
    svc = UserService(owner_session, AuditService(owner_session))
    email = f"vc-{uuid4().hex[:8]}@test"
    async with owner_session.begin():
        await svc.create(email=email, password="hunter2", full_name="VC")
    async with owner_session.begin():
        result = await svc.verify_credentials(email, "hunter2")
    assert result is not None
    assert result.email == email
    async with owner_session.begin():
        result = await svc.verify_credentials(email, "wrong")
    assert result is None
    async with owner_session.begin():
        await owner_session.execute(
            text("DELETE FROM users WHERE email = :e"), {"e": email}
        )


@pytest.mark.asyncio
async def test_verify_credentials_rejects_inactive_user(
    owner_session: AsyncSession,
) -> None:
    svc = UserService(owner_session, AuditService(owner_session))
    email = f"in-{uuid4().hex[:8]}@test"
    async with owner_session.begin():
        u = await svc.create(email=email, password="hunter2", full_name="In")
        u.is_active = False
    async with owner_session.begin():
        result = await svc.verify_credentials(email, "hunter2")
    assert result is None
    async with owner_session.begin():
        await owner_session.execute(
            text("DELETE FROM users WHERE email = :e"), {"e": email}
        )


# --- InvitationService ----------------------------------------------------


@pytest_asyncio.fixture
async def tenant_and_admin(
    owner_session: AsyncSession,
) -> AsyncIterator[tuple[UUID, UUID]]:
    """Create a tenant + a tenant_admin user; tear down at end."""
    audit = AuditService(owner_session)
    tsvc = TenantService(owner_session, audit)
    usvc = UserService(owner_session, audit)
    async with owner_session.begin():
        tenant = await tsvc.create(name="Inv Co", slug=f"inv-{uuid4().hex[:8]}")
        admin = await usvc.create(
            email=f"admin-{uuid4().hex[:8]}@test",
            password="x",
            full_name="Admin",
        )
        # Capture ids before any later expire/rollback in the test body.
        tenant_id, admin_id = tenant.id, admin.id
    yield tenant_id, admin_id
    async with owner_session.begin():
        await owner_session.execute(
            text("DELETE FROM users WHERE id = :id"), {"id": str(admin_id)}
        )
        await owner_session.execute(
            text("DELETE FROM tenants WHERE id = :id"), {"id": str(tenant_id)}
        )


@pytest.mark.asyncio
async def test_invitation_create_returns_plaintext_token_once(
    owner_session: AsyncSession,
    tenant_and_admin: tuple[UUID, UUID],
) -> None:
    tenant_id, admin_id = tenant_and_admin
    audit = AuditService(owner_session)
    svc = InvitationService(
        owner_session,
        audit,
        UserService(owner_session, audit),
    )
    async with owner_session.begin():
        await set_current_tenant(owner_session, tenant_id)
        invitation, plaintext = await svc.create_invitation(
            tenant_id=tenant_id,
            email=f"invitee-{uuid4().hex[:8]}@test",
            role=UserTenantRole.ANALYST,
            invited_by=admin_id,
        )
    assert plaintext  # caller receives it once
    assert invitation.token_hash != plaintext  # only hash persisted
    assert invitation.accepted_at is None
    assert invitation.expires_at > datetime.now(UTC)


@pytest.mark.asyncio
async def test_invitation_accept_creates_user_and_link(
    owner_session: AsyncSession,
    tenant_and_admin: tuple[UUID, UUID],
) -> None:
    tenant_id, admin_id = tenant_and_admin
    audit = AuditService(owner_session)
    usvc = UserService(owner_session, audit)
    svc = InvitationService(owner_session, audit, usvc)

    invitee_email = f"newhire-{uuid4().hex[:8]}@test"
    async with owner_session.begin():
        await set_current_tenant(owner_session, tenant_id)
        _inv, plaintext = await svc.create_invitation(
            tenant_id=tenant_id,
            email=invitee_email,
            role=UserTenantRole.ANALYST,
            invited_by=admin_id,
        )

    async with owner_session.begin():
        await set_current_tenant(owner_session, tenant_id)
        user, invitation = await svc.accept_invitation(
            plaintext_token=plaintext,
            full_name="New Hire",
            password="StrongPass!",
        )
        # Capture inside the txn so attribute access doesn't lazy-load.
        accepted_at = invitation.accepted_at
        observed_email = user.email
        user_id = user.id

    assert accepted_at is not None
    assert observed_email == invitee_email

    # User attached to tenant with correct role
    async with owner_session.begin():
        link = (
            await owner_session.execute(
                select(UserTenantLink).where(UserTenantLink.user_id == user_id)
            )
        ).scalar_one()
        assert link.tenant_id == tenant_id
        assert link.role == UserTenantRole.ANALYST


@pytest.mark.asyncio
async def test_invitation_replay_is_rejected(
    owner_session: AsyncSession,
    tenant_and_admin: tuple[UUID, UUID],
) -> None:
    tenant_id, admin_id = tenant_and_admin
    audit = AuditService(owner_session)
    svc = InvitationService(
        owner_session,
        audit,
        UserService(owner_session, audit),
    )

    async with owner_session.begin():
        await set_current_tenant(owner_session, tenant_id)
        _inv, plaintext = await svc.create_invitation(
            tenant_id=tenant_id,
            email=f"dup-{uuid4().hex[:8]}@test",
            role=UserTenantRole.VIEWER,
            invited_by=admin_id,
        )

    async with owner_session.begin():
        await set_current_tenant(owner_session, tenant_id)
        await svc.accept_invitation(
            plaintext_token=plaintext, full_name="A", password="x"
        )

    with pytest.raises(InvitationAcceptanceError):
        async with owner_session.begin():
            await set_current_tenant(owner_session, tenant_id)
            await svc.accept_invitation(
                plaintext_token=plaintext, full_name="B", password="y"
            )


@pytest.mark.asyncio
async def test_invitation_expired_is_rejected(
    owner_session: AsyncSession,
    tenant_and_admin: tuple[UUID, UUID],
) -> None:
    tenant_id, admin_id = tenant_and_admin
    audit = AuditService(owner_session)
    svc = InvitationService(
        owner_session,
        audit,
        UserService(owner_session, audit),
    )

    # Negative TTL -> already expired
    async with owner_session.begin():
        await set_current_tenant(owner_session, tenant_id)
        _inv, plaintext = await svc.create_invitation(
            tenant_id=tenant_id,
            email=f"late-{uuid4().hex[:8]}@test",
            role=UserTenantRole.VIEWER,
            invited_by=admin_id,
            ttl=timedelta(seconds=-1),
        )

    with pytest.raises(InvitationAcceptanceError):
        async with owner_session.begin():
            await set_current_tenant(owner_session, tenant_id)
            await svc.accept_invitation(
                plaintext_token=plaintext, full_name="X", password="x"
            )


@pytest.mark.asyncio
async def test_invitation_unknown_token_is_rejected(
    owner_session: AsyncSession,
) -> None:
    audit = AuditService(owner_session)
    svc = InvitationService(
        owner_session,
        audit,
        UserService(owner_session, audit),
    )
    with pytest.raises(InvitationAcceptanceError):
        async with owner_session.begin():
            await svc.accept_invitation(
                plaintext_token="bogus-token", full_name="X", password="x"
            )


@pytest.mark.asyncio
async def test_invitations_table_is_rls_protected_for_app_role(
    owner_session: AsyncSession,
    app_engine: AsyncEngine,
    tenant_and_admin: tuple[UUID, UUID],
) -> None:
    """An imga_app session without tenant context cannot read invitations."""
    tenant_id, admin_id = tenant_and_admin
    audit = AuditService(owner_session)
    svc = InvitationService(
        owner_session,
        audit,
        UserService(owner_session, audit),
    )
    async with owner_session.begin():
        await set_current_tenant(owner_session, tenant_id)
        await svc.create_invitation(
            tenant_id=tenant_id,
            email=f"rls-{uuid4().hex[:8]}@test",
            role=UserTenantRole.ANALYST,
            invited_by=admin_id,
        )

    factory = create_session_factory(app_engine)
    async with factory() as app_s, app_s.begin():
        # No set_current_tenant -> FORCE RLS -> 0 rows visible
        result = await app_s.execute(text("SELECT count(*) FROM invitations"))
        assert result.scalar_one() == 0
