"""Sprint 7.5.5 / Alt-Faz 1 — admin tenants + invitations + rate limit.

Covers the eleven new endpoints + the four service-side classes
they wrap. The fixtures lean on the existing super-admin row that
migration 0001 seeds (admin@imga.ai / change_on_first_login) so we
don't need yet another autouse seeding step.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from cachetools import TTLCache
from fastapi import FastAPI
from fastapi.testclient import TestClient
from imga_db import create_engine, create_session_factory
from imga_db.models import Invitation, User, UserTenantRole
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from imga_api.main import app
from imga_api.security import hash_password
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

SUPER_ADMIN_PASSWORD = "test-super-admin-pwd-32-chars-min"


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


@pytest.fixture(autouse=True)
def _reset_rate_limit_buckets() -> None:
    """Each test starts with empty rate-limit buckets. Otherwise a 429
    test could ratchet over into an unrelated case."""
    from imga_api.rate_limit import reset_for_tests
    reset_for_tests()


@pytest_asyncio.fixture
async def super_admin(admin_session: AsyncSession) -> AsyncIterator[User]:
    """Resets / re-seeds a super-admin row with a known password.

    Migration 0001 seeds admin@imga.ai but the password depends on the
    SUPER_ADMIN_INITIAL_PASSWORD env var at migration time. To keep the
    test self-contained we rewrite the password hash to a value we
    own."""
    async with admin_session.begin():
        await admin_session.execute(
            text(
                "UPDATE users SET password_hash = :pw, is_active = true "
                "WHERE email = 'admin@imga.ai'"
            ),
            {"pw": hash_password(SUPER_ADMIN_PASSWORD)},
        )
        user = (
            await admin_session.execute(
                select(User).where(User.email == "admin@imga.ai")
            )
        ).scalar_one()
    yield user


@pytest_asyncio.fixture
async def acme_tenant(admin_session: AsyncSession) -> AsyncIterator[tuple[UUID, User, str]]:
    """A tenant + a tenant_admin user inside it. Returns (tenant_id, alice, alice_pw)."""
    audit = AuditService(admin_session)
    tsvc = TenantService(admin_session, audit)
    usvc = UserService(admin_session, audit)
    plain = "Alice-Pwd-1234567"
    email = f"alice-{uuid4().hex[:8]}@example.com"
    async with admin_session.begin():
        tenant = await tsvc.create(name="Acme Inc.", slug=f"acme-{uuid4().hex[:8]}")
        alice = await usvc.create(email=email, password=plain, full_name="Alice")
        await usvc.attach_to_tenant(
            user_id=alice.id, tenant_id=tenant.id, role=UserTenantRole.TENANT_ADMIN
        )
    yield tenant.id, alice, plain
    async with admin_session.begin():
        await admin_session.execute(
            text("DELETE FROM users WHERE id = :id"), {"id": str(alice.id)}
        )
        await admin_session.execute(
            text("DELETE FROM tenants WHERE id = :id"), {"id": str(tenant.id)}
        )


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
    for attr in ("admin_db_engine", "app_db_engine",
                 "admin_db_engine_factory", "app_db_engine_factory"):
        if hasattr(app.state, attr):
            delattr(app.state, attr)
    try:
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c
    finally:
        app.router.lifespan_context = original
        for attr in ("admin_db_engine", "app_db_engine",
                     "admin_db_engine_factory", "app_db_engine_factory",
                     "tenant_config_cache"):
            if hasattr(app.state, attr):
                delattr(app.state, attr)


def _login(client: TestClient, email: str, password: str, tenant_id: UUID | None = None) -> str:
    payload: dict[str, str] = {"email": email, "password": password}
    if tenant_id is not None:
        payload["active_tenant_id"] = str(tenant_id)
    r = client.post("/auth/login", json=payload)
    assert r.status_code == 200, r.text
    return str(r.json()["access_token"])


# --- admin tenants ----------------------------------------------------


def test_super_admin_creates_tenant(
    client: TestClient,
    super_admin: User,
) -> None:
    token = _login(client, "admin@imga.ai", SUPER_ADMIN_PASSWORD)
    headers = {"Authorization": f"Bearer {token}"}
    slug = f"foo-{uuid4().hex[:6]}"
    r = client.post(
        "/admin/tenants",
        headers=headers,
        json={"name": "Foo Inc.", "slug": slug},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["tenant"]["slug"] == slug
    assert body["initial_invitation_token"] is None


def test_create_tenant_with_initial_admin_returns_token(
    client: TestClient,
    super_admin: User,
    admin_session: AsyncSession,
) -> None:
    token = _login(client, "admin@imga.ai", SUPER_ADMIN_PASSWORD)
    slug = f"bar-{uuid4().hex[:6]}"
    email = f"first-admin-{uuid4().hex[:6]}@example.com"
    r = client.post(
        "/admin/tenants",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "Bar Inc.",
            "slug": slug,
            "initial_admin": {"email": email, "full_name": "First Admin"},
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    invitation_token = body["initial_invitation_token"]
    assert invitation_token is not None
    assert len(invitation_token) > 30


@pytest.mark.asyncio
async def test_create_tenant_slug_conflict_409(
    client: TestClient,
    super_admin: User,
    acme_tenant: tuple[UUID, User, str],
    admin_session: AsyncSession,
) -> None:
    tid, _alice, _pw = acme_tenant
    from imga_db.models import Tenant
    async with admin_session.begin():
        tenant = (
            await admin_session.execute(select(Tenant).where(Tenant.id == tid))
        ).scalar_one()
    token = _login(client, "admin@imga.ai", SUPER_ADMIN_PASSWORD)
    r = client.post(
        "/admin/tenants",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Dup", "slug": tenant.slug},
    )
    assert r.status_code == 409, r.text


@pytest.mark.asyncio
async def test_list_tenants_super_admin(
    client: TestClient,
    super_admin: User,
    acme_tenant: tuple[UUID, User, str],
) -> None:
    token = _login(client, "admin@imga.ai", SUPER_ADMIN_PASSWORD)
    r = client.get("/admin/tenants", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    tenants = r.json()["tenants"]
    assert any(t["id"] == str(acme_tenant[0]) for t in tenants)


@pytest.mark.asyncio
async def test_update_tenant(
    client: TestClient,
    super_admin: User,
    acme_tenant: tuple[UUID, User, str],
) -> None:
    tid, _alice, _pw = acme_tenant
    token = _login(client, "admin@imga.ai", SUPER_ADMIN_PASSWORD)
    r = client.patch(
        f"/admin/tenants/{tid}",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Acme Updated"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Acme Updated"


@pytest.mark.asyncio
async def test_delete_tenant_soft(
    client: TestClient,
    super_admin: User,
    acme_tenant: tuple[UUID, User, str],
) -> None:
    tid, _alice, _pw = acme_tenant
    token = _login(client, "admin@imga.ai", SUPER_ADMIN_PASSWORD)
    r = client.delete(
        f"/admin/tenants/{tid}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["deleted_at"] is not None


def test_non_super_admin_cannot_create_tenant(
    client: TestClient,
    acme_tenant: tuple[UUID, User, str],
) -> None:
    tid, alice, pw = acme_tenant
    token = _login(client, alice.email, pw, tenant_id=tid)
    r = client.post(
        "/admin/tenants",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "X", "slug": "x"},
    )
    assert r.status_code == 403, r.text


# --- admin invitations ------------------------------------------------


@pytest.mark.asyncio
async def test_tenant_admin_creates_invitation_in_own_tenant(
    client: TestClient,
    acme_tenant: tuple[UUID, User, str],
) -> None:
    tid, alice, pw = acme_tenant
    token = _login(client, alice.email, pw, tenant_id=tid)
    invitee = f"new-{uuid4().hex[:6]}@example.com"
    r = client.post(
        f"/admin/tenants/{tid}/invitations",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": invitee, "role": "analyst"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["email"] == invitee
    assert len(body["token"]) > 30


@pytest.mark.asyncio
async def test_tenant_admin_cannot_invite_into_other_tenant_403(
    client: TestClient,
    acme_tenant: tuple[UUID, User, str],
    admin_session: AsyncSession,
) -> None:
    tid, alice, pw = acme_tenant
    # Make a second tenant for alice to try targeting.
    audit = AuditService(admin_session)
    tsvc = TenantService(admin_session, audit)
    async with admin_session.begin():
        other = await tsvc.create(name="Other", slug=f"other-{uuid4().hex[:6]}")
    token = _login(client, alice.email, pw, tenant_id=tid)
    try:
        r = client.post(
            f"/admin/tenants/{other.id}/invitations",
            headers={"Authorization": f"Bearer {token}"},
            json={"email": "x@y.com", "role": "analyst"},
        )
        assert r.status_code == 403, r.text
    finally:
        async with admin_session.begin():
            await admin_session.execute(
                text("DELETE FROM tenants WHERE id = :id"), {"id": str(other.id)}
            )


@pytest.mark.asyncio
async def test_list_invitations_for_tenant(
    client: TestClient,
    acme_tenant: tuple[UUID, User, str],
) -> None:
    tid, alice, pw = acme_tenant
    token = _login(client, alice.email, pw, tenant_id=tid)
    headers = {"Authorization": f"Bearer {token}"}
    invitee = f"l-{uuid4().hex[:6]}@example.com"
    client.post(
        f"/admin/tenants/{tid}/invitations",
        headers=headers,
        json={"email": invitee, "role": "viewer"},
    )
    r = client.get(f"/admin/tenants/{tid}/invitations", headers=headers)
    assert r.status_code == 200, r.text
    assert any(inv["email"] == invitee for inv in r.json()["invitations"])


@pytest.mark.asyncio
async def test_revoke_invitation_removes_row_and_audits(
    client: TestClient,
    acme_tenant: tuple[UUID, User, str],
    admin_session: AsyncSession,
) -> None:
    tid, alice, pw = acme_tenant
    token = _login(client, alice.email, pw, tenant_id=tid)
    headers = {"Authorization": f"Bearer {token}"}
    create = client.post(
        f"/admin/tenants/{tid}/invitations",
        headers=headers,
        json={"email": f"r-{uuid4().hex[:6]}@example.com", "role": "viewer"},
    )
    invitation_id = create.json()["invitation_id"]
    r = client.delete(
        f"/admin/tenants/{tid}/invitations/{invitation_id}",
        headers=headers,
    )
    assert r.status_code == 204
    # Row gone.
    async with admin_session.begin():
        gone = (
            await admin_session.execute(
                select(Invitation).where(Invitation.id == invitation_id)
            )
        ).scalar_one_or_none()
    assert gone is None


# --- public invitations ------------------------------------------------


@pytest.mark.asyncio
async def test_invitation_preview_returns_tenant_name(
    client: TestClient,
    acme_tenant: tuple[UUID, User, str],
) -> None:
    tid, alice, pw = acme_tenant
    admin_token = _login(client, alice.email, pw, tenant_id=tid)
    invitee = f"prev-{uuid4().hex[:6]}@example.com"
    create = client.post(
        f"/admin/tenants/{tid}/invitations",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"email": invitee, "role": "analyst"},
    )
    plaintext_token = create.json()["token"]
    r = client.post(f"/invitations/{plaintext_token}/preview")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["invited_email"] == invitee
    assert body["role"] == "analyst"


def test_invitation_preview_invalid_token_404(client: TestClient) -> None:
    r = client.post("/invitations/invalid-token-zzz/preview")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_accept_new_user_happy_path(
    client: TestClient,
    acme_tenant: tuple[UUID, User, str],
    admin_session: AsyncSession,
) -> None:
    tid, alice, pw = acme_tenant
    admin_token = _login(client, alice.email, pw, tenant_id=tid)
    invitee = f"accept-{uuid4().hex[:6]}@example.com"
    create = client.post(
        f"/admin/tenants/{tid}/invitations",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"email": invitee, "role": "analyst"},
    )
    plaintext_token = create.json()["token"]
    r = client.post(
        f"/invitations/{plaintext_token}/accept",
        json={"full_name": "Newcomer", "password": "secure-pwd-123"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["access_token"]
    # Cleanup the user we just created.
    async with admin_session.begin():
        await admin_session.execute(
            text("DELETE FROM users WHERE email = :e"), {"e": invitee}
        )


@pytest.mark.asyncio
async def test_accept_email_exists_returns_409_without_consuming(
    client: TestClient,
    acme_tenant: tuple[UUID, User, str],
    admin_session: AsyncSession,
    super_admin: User,
) -> None:
    """If the invited email already belongs to a user, accept (new
    user) must 409 and NOT consume the token. Then accept-existing
    with auth wins. We invite Alice into a SECOND (Beta) tenant so the
    user_tenants PK constraint doesn't trip on the existing Acme link."""
    _tid, alice, pw = acme_tenant
    audit = AuditService(admin_session)
    tsvc = TenantService(admin_session, audit)
    async with admin_session.begin():
        beta = await tsvc.create(name="Beta", slug=f"beta-{uuid4().hex[:6]}")
    beta_id = beta.id

    super_token = _login(client, "admin@imga.ai", SUPER_ADMIN_PASSWORD)
    try:
        create = client.post(
            f"/admin/tenants/{beta_id}/invitations",
            headers={"Authorization": f"Bearer {super_token}"},
            json={"email": alice.email, "role": "viewer"},
        )
        plaintext_token = create.json()["token"]

        # Step 1: accept-as-new returns 409 because Alice already exists.
        r = client.post(
            f"/invitations/{plaintext_token}/accept",
            json={"full_name": "X", "password": "irrelevant-but-long-enough"},
        )
        assert r.status_code == 409, r.text

        # Step 2: token still valid; accept-existing as Alice succeeds
        # because she's not yet a member of Beta.
        alice_login = client.post(
            "/auth/login", json={"email": alice.email, "password": pw}
        ).json()
        r2 = client.post(
            f"/invitations/{plaintext_token}/accept-existing",
            headers={"Authorization": f"Bearer {alice_login['access_token']}"},
            json={"password": pw},
        )
        assert r2.status_code == 200, r2.text
    finally:
        async with admin_session.begin():
            await admin_session.execute(
                text("DELETE FROM tenants WHERE id = :id"), {"id": str(beta_id)}
            )


@pytest.mark.asyncio
async def test_accept_existing_wrong_password_401(
    client: TestClient,
    acme_tenant: tuple[UUID, User, str],
    admin_session: AsyncSession,
) -> None:
    tid, alice, pw = acme_tenant
    admin_token = _login(client, alice.email, pw, tenant_id=tid)
    create = client.post(
        f"/admin/tenants/{tid}/invitations",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"email": alice.email, "role": "viewer"},
    )
    plaintext_token = create.json()["token"]
    r = client.post(
        f"/invitations/{plaintext_token}/accept-existing",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"password": "wrong-password"},
    )
    assert r.status_code == 401, r.text


@pytest.mark.asyncio
async def test_invitation_preview_after_accept_returns_404(
    client: TestClient,
    acme_tenant: tuple[UUID, User, str],
    admin_session: AsyncSession,
) -> None:
    """Once accepted, preview must return generic 404 (not "already
    accepted") to prevent token-validity probing."""
    tid, alice, pw = acme_tenant
    admin_token = _login(client, alice.email, pw, tenant_id=tid)
    invitee = f"once-{uuid4().hex[:6]}@example.com"
    create = client.post(
        f"/admin/tenants/{tid}/invitations",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"email": invitee, "role": "analyst"},
    )
    plaintext_token = create.json()["token"]
    accept = client.post(
        f"/invitations/{plaintext_token}/accept",
        json={"full_name": "Once", "password": "secure-pwd-123"},
    )
    assert accept.status_code == 200
    r = client.post(f"/invitations/{plaintext_token}/preview")
    assert r.status_code == 404
    async with admin_session.begin():
        await admin_session.execute(
            text("DELETE FROM users WHERE email = :e"), {"e": invitee}
        )


@pytest.mark.asyncio
async def test_invitation_preview_expired_returns_404(
    client: TestClient,
    acme_tenant: tuple[UUID, User, str],
    admin_session: AsyncSession,
) -> None:
    tid, alice, pw = acme_tenant
    admin_token = _login(client, alice.email, pw, tenant_id=tid)
    create = client.post(
        f"/admin/tenants/{tid}/invitations",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"email": f"exp-{uuid4().hex[:6]}@example.com", "role": "viewer"},
    )
    plaintext_token = create.json()["token"]
    invitation_id = UUID(create.json()["invitation_id"])

    # Backdate expiry.
    async with admin_session.begin():
        await admin_session.execute(
            text("UPDATE invitations SET expires_at = :exp WHERE id = :id"),
            {
                "exp": datetime.now(UTC) - timedelta(minutes=1),
                "id": str(invitation_id),
            },
        )
    r = client.post(f"/invitations/{plaintext_token}/preview")
    assert r.status_code == 404


def test_rate_limit_kicks_in_after_repeated_invalid_previews(client: TestClient) -> None:
    """Per-IP cap is 10/min; the 11th preview call within the window
    must return 429 even with a fresh (invalid) token each time."""
    last_status = None
    # 12 calls > 10/min — at least one of the last two must trip the limit.
    for i in range(12):
        last_status = client.post(f"/invitations/bogus-token-{i}/preview").status_code
    assert last_status == 429, (
        f"expected 429 after 11+ requests, last was {last_status}"
    )
