"""Auth flow integration tests against the live postgres container.

Covers JWT issuance, refresh chain detection, logout, password change,
RBAC, and access-token freshness.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from imga_db import create_engine, create_session_factory
from imga_db.models import RefreshTokenRecord, User, UserTenantRole
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from imga_api.main import app
from imga_api.security import decode_access_token
from imga_api.services import (
    AuditService,
    AuthService,
    TenantService,
    UserService,
)
from imga_api.settings import JWTSettings, Settings

_HOST = os.environ.get("IMGA_TEST_PG_HOST", "localhost")
_PORT = os.environ.get("IMGA_POSTGRES_PORT", "5433")
ADMIN_URL = f"postgresql+asyncpg://imga_admin:imga_admin_password@{_HOST}:{_PORT}/imga"
APP_URL = f"postgresql+asyncpg://imga_app:imga_app_password@{_HOST}:{_PORT}/imga"
OWNER_URL = f"postgresql+asyncpg://imga_owner:imga_dev_password@{_HOST}:{_PORT}/imga"


@pytest.fixture(autouse=True)
def _set_test_env() -> None:
    """Ensure the API uses the test postgres + a stable JWT secret."""
    os.environ["DATABASE_URL"] = APP_URL
    os.environ["DATABASE_URL_ADMIN"] = ADMIN_URL
    os.environ["DATABASE_URL_OWNER"] = OWNER_URL
    os.environ["JWT_SECRET_KEY"] = "test-secret-key-32-bytes-min-padding-xyz"
    os.environ["JWT_ACCESS_TOKEN_TTL_MINUTES"] = "15"
    os.environ["JWT_REFRESH_TOKEN_TTL_DAYS"] = "7"


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
async def jwt_settings() -> JWTSettings:
    return Settings.from_env().jwt


@pytest_asyncio.fixture
async def seeded_user_and_tenant(
    admin_session: AsyncSession,
) -> AsyncIterator[tuple[User, UUID, str]]:
    """Create a tenant + user + UserTenantLink (analyst role); cleanup after."""
    audit = AuditService(admin_session)
    tsvc = TenantService(admin_session, audit)
    usvc = UserService(admin_session, audit)
    plain_password = "Test-Password-123!"
    email = f"auth-{uuid4().hex[:8]}@example.com"
    async with admin_session.begin():
        tenant = await tsvc.create(name="Auth Co", slug=f"auth-{uuid4().hex[:8]}")
        user = await usvc.create(
            email=email,
            password=plain_password,
            full_name="Auth Tester",
        )
        await usvc.attach_to_tenant(
            user_id=user.id,
            tenant_id=tenant.id,
            role=UserTenantRole.ANALYST,
        )
        user_id = user.id
        tenant_id = tenant.id
    yield user, tenant_id, plain_password

    async with admin_session.begin():
        await admin_session.execute(
            text("DELETE FROM users WHERE id = :id"), {"id": str(user_id)}
        )
        await admin_session.execute(
            text("DELETE FROM tenants WHERE id = :id"), {"id": str(tenant_id)}
        )


@pytest.fixture
def client() -> Iterator[TestClient]:
    """TestClient with a no-op lifespan (skip BERT load) and shared portal.

    Why ``with TestClient(app) as c:``: starlette's TestClient runs every
    request through the same anyio portal when used as a context manager,
    so the asyncpg connection pool sees a single event loop for the whole
    test. Without it, each .post()/.get() spawns its own loop and asyncpg
    connections from the previous request fail with
    ``'NoneType' object has no attribute 'send'`` on Windows.
    """
    @asynccontextmanager
    async def _test_lifespan(application: object) -> AsyncIterator[None]:
        application.state.settings = Settings.from_env()  # type: ignore[attr-defined]
        yield

    original_lifespan = app.router.lifespan_context
    app.router.lifespan_context = _test_lifespan

    # Wipe any engine cache from a previous test (different event loop).
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
                     "admin_db_engine_factory", "app_db_engine_factory"):
            if hasattr(app.state, attr):
                delattr(app.state, attr)


# --- login ---------------------------------------------------------------


def test_login_returns_token_pair(
    client: TestClient,
    seeded_user_and_tenant: tuple[User, UUID, str],
) -> None:
    user, _tenant_id, password = seeded_user_and_tenant
    r = client.post("/auth/login", json={"email": user.email, "password": password})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["token_type"] == "Bearer"


def test_login_wrong_password_returns_401(
    client: TestClient,
    seeded_user_and_tenant: tuple[User, UUID, str],
) -> None:
    user, _tid, _pw = seeded_user_and_tenant
    r = client.post("/auth/login", json={"email": user.email, "password": "WRONG"})
    assert r.status_code == 401


def test_login_unknown_email_returns_401(client: TestClient) -> None:
    r = client.post(
        "/auth/login",
        json={"email": "nobody@example.com", "password": "anything"},
    )
    assert r.status_code == 401


def test_login_with_explicit_active_tenant_embeds_role(
    client: TestClient,
    seeded_user_and_tenant: tuple[User, UUID, str],
    jwt_settings: JWTSettings,
) -> None:
    user, tenant_id, password = seeded_user_and_tenant
    r = client.post(
        "/auth/login",
        json={
            "email": user.email,
            "password": password,
            "active_tenant_id": str(tenant_id),
        },
    )
    assert r.status_code == 200, r.text
    payload = decode_access_token(r.json()["access_token"], jwt_settings)
    assert payload.active_tenant_id == tenant_id
    assert payload.active_role == "analyst"


# --- /me -----------------------------------------------------------------


def test_me_requires_bearer(client: TestClient) -> None:
    r = client.get("/auth/me")
    assert r.status_code == 401


def test_me_returns_user_active_context_and_available_tenants(
    client: TestClient,
    seeded_user_and_tenant: tuple[User, UUID, str],
) -> None:
    user, tenant_id, password = seeded_user_and_tenant
    login = client.post(
        "/auth/login", json={"email": user.email, "password": password}
    ).json()
    r = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {login['access_token']}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user"]["email"] == user.email
    assert body["active_context"]["tenant_id"] == str(tenant_id)
    assert body["active_context"]["role"] == "analyst"
    available_ids = {t["id"] for t in body["available_tenants"]}
    assert str(tenant_id) in available_ids


@pytest.mark.asyncio
async def test_me_super_admin_lists_nonmember_tenants(
    client: TestClient,
    admin_session: AsyncSession,
    seeded_user_and_tenant: tuple[User, UUID, str],
) -> None:
    """Süper yönetici, üyeliği olmayan kurumları da available_tenants
    içinde 'super_admin' rol etiketiyle görmeli — kurum seçici bu
    listeden beslenir ve switch-tenant zaten üyelik istemiyor."""
    _user, tenant_id, _pw = seeded_user_and_tenant
    audit = AuditService(admin_session)
    usvc = UserService(admin_session, audit)
    plain = "Root-Password-123!"
    email = f"root-{uuid4().hex[:8]}@example.com"
    async with admin_session.begin():
        root = await usvc.create(
            email=email,
            password=plain,
            full_name="Root User",
            is_super_admin=True,
        )
        root_id = root.id
        root_email = root.email
    try:
        login = client.post(
            "/auth/login", json={"email": root_email, "password": plain}
        ).json()
        r = client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {login['access_token']}"},
        )
        assert r.status_code == 200, r.text
        rows = {t["id"]: t for t in r.json()["available_tenants"]}
        assert str(tenant_id) in rows
        assert rows[str(tenant_id)]["role"] == "super_admin"
    finally:
        async with admin_session.begin():
            await admin_session.execute(
                text("DELETE FROM users WHERE id = :id"), {"id": str(root_id)}
            )


# --- refresh + chain detection ------------------------------------------


def test_refresh_rotates_token(
    client: TestClient,
    seeded_user_and_tenant: tuple[User, UUID, str],
) -> None:
    user, _tid, password = seeded_user_and_tenant
    login = client.post(
        "/auth/login", json={"email": user.email, "password": password}
    ).json()
    r = client.post(
        "/auth/refresh", json={"refresh_token": login["refresh_token"]}
    )
    assert r.status_code == 200, r.text
    new_pair = r.json()
    # Refresh token always rotates — JTI is unique per row.
    assert new_pair["refresh_token"] != login["refresh_token"]
    # Access tokens carry no JTI; if login + refresh land in the same
    # Unix second AND the claims are identical, the encoded JWTs are
    # byte-equal. Don't assert on byte difference — the rotation
    # contract is on the refresh chain.


def test_refresh_preserves_active_tenant_context(
    client: TestClient,
    seeded_user_and_tenant: tuple[User, UUID, str],
    jwt_settings: JWTSettings,
) -> None:
    """Regression: prod 8.2 hotfix.

    Silent refresh used to drop ``active_tenant_id`` because the refresh
    path issued the new access token with ``None`` claims. The fix
    persists the tenant context on the ``RefreshTokenRecord`` row and
    carries it across rotations. After /switch-tenant or fresh login,
    the rotated access token must still embed the same tenant + role.
    """
    user, tenant_id, password = seeded_user_and_tenant
    login = client.post(
        "/auth/login",
        json={
            "email": user.email,
            "password": password,
            "active_tenant_id": str(tenant_id),
        },
    ).json()
    # Sanity: login token has the tenant context.
    login_payload = decode_access_token(login["access_token"], jwt_settings)
    assert login_payload.active_tenant_id == tenant_id
    assert login_payload.active_role == "analyst"

    rotated = client.post(
        "/auth/refresh", json={"refresh_token": login["refresh_token"]}
    )
    assert rotated.status_code == 200, rotated.text
    rotated_payload = decode_access_token(
        rotated.json()["access_token"], jwt_settings
    )
    assert rotated_payload.active_tenant_id == tenant_id
    assert rotated_payload.active_role == "analyst"


def test_refresh_token_reuse_revokes_family(
    client: TestClient,
    seeded_user_and_tenant: tuple[User, UUID, str],
) -> None:
    """Replay protection: presenting an already-rotated refresh token
    must revoke the entire family and reject the second use."""
    user, _tid, password = seeded_user_and_tenant
    login = client.post(
        "/auth/login", json={"email": user.email, "password": password}
    ).json()
    # First refresh succeeds
    r1 = client.post(
        "/auth/refresh", json={"refresh_token": login["refresh_token"]}
    )
    assert r1.status_code == 200
    # Replaying the original refresh token now fails (chain compromise)
    r2 = client.post(
        "/auth/refresh", json={"refresh_token": login["refresh_token"]}
    )
    assert r2.status_code == 401
    # And the rotated successor is also dead now
    r3 = client.post(
        "/auth/refresh", json={"refresh_token": r1.json()["refresh_token"]}
    )
    assert r3.status_code == 401


# --- logout --------------------------------------------------------------


def test_logout_revokes_family_and_subsequent_refresh_fails(
    client: TestClient,
    seeded_user_and_tenant: tuple[User, UUID, str],
) -> None:
    user, _tid, password = seeded_user_and_tenant
    login = client.post(
        "/auth/login", json={"email": user.email, "password": password}
    ).json()
    out = client.post("/auth/logout", json={"refresh_token": login["refresh_token"]})
    assert out.status_code == 204
    rr = client.post(
        "/auth/refresh", json={"refresh_token": login["refresh_token"]}
    )
    assert rr.status_code == 401


def test_logout_with_unknown_token_is_idempotent(client: TestClient) -> None:
    out = client.post("/auth/logout", json={"refresh_token": "not-a-real-token"})
    assert out.status_code == 204


def test_logout_revokes_entire_family_including_rotated_successors(
    client: TestClient,
    seeded_user_and_tenant: tuple[User, UUID, str],
) -> None:
    """Logout must revoke every live token in the family, not just the
    one presented. Build a chain (login -> refresh) so the family has
    two records, log out with the latest token, and confirm both rows
    are dead."""
    user, _tid, password = seeded_user_and_tenant
    login = client.post(
        "/auth/login", json={"email": user.email, "password": password}
    ).json()
    rotated = client.post(
        "/auth/refresh", json={"refresh_token": login["refresh_token"]}
    ).json()
    # Rotated successor exists in the same family as the login token.
    out = client.post(
        "/auth/logout", json={"refresh_token": rotated["refresh_token"]}
    )
    assert out.status_code == 204
    # The original (already-rotated) token was used_at-set; replaying it
    # would normally trigger chain_compromise, but the family is already
    # revoked — either way it must fail.
    r_orig = client.post(
        "/auth/refresh", json={"refresh_token": login["refresh_token"]}
    )
    assert r_orig.status_code == 401
    # And the rotated successor — the very token we logged out with —
    # is also dead.
    r_rotated = client.post(
        "/auth/refresh", json={"refresh_token": rotated["refresh_token"]}
    )
    assert r_rotated.status_code == 401


# --- switch-tenant -------------------------------------------------------


def test_switch_tenant_re_issues_with_new_active_context(
    client: TestClient,
    seeded_user_and_tenant: tuple[User, UUID, str],
    jwt_settings: JWTSettings,
) -> None:
    user, tenant_id, password = seeded_user_and_tenant
    login = client.post(
        "/auth/login", json={"email": user.email, "password": password}
    ).json()
    r = client.post(
        "/auth/switch-tenant",
        headers={"Authorization": f"Bearer {login['access_token']}"},
        json={"tenant_id": str(tenant_id)},
    )
    assert r.status_code == 200, r.text
    payload = decode_access_token(r.json()["access_token"], jwt_settings)
    assert payload.active_tenant_id == tenant_id


def test_switch_tenant_to_unjoined_tenant_returns_403(
    client: TestClient,
    seeded_user_and_tenant: tuple[User, UUID, str],
) -> None:
    user, _tid, password = seeded_user_and_tenant
    login = client.post(
        "/auth/login", json={"email": user.email, "password": password}
    ).json()
    r = client.post(
        "/auth/switch-tenant",
        headers={"Authorization": f"Bearer {login['access_token']}"},
        json={"tenant_id": str(uuid4())},
    )
    assert r.status_code == 403


# --- password change -----------------------------------------------------


def test_change_password_requires_current_and_revokes_refresh_tokens(
    client: TestClient,
    seeded_user_and_tenant: tuple[User, UUID, str],
) -> None:
    user, _tid, password = seeded_user_and_tenant
    login = client.post(
        "/auth/login", json={"email": user.email, "password": password}
    ).json()

    # Wrong current password -> 400
    r1 = client.post(
        "/auth/change-password",
        headers={"Authorization": f"Bearer {login['access_token']}"},
        json={"current_password": "wrong", "new_password": "Replaced-99!"},
    )
    assert r1.status_code == 400

    # Correct -> 204
    r2 = client.post(
        "/auth/change-password",
        headers={"Authorization": f"Bearer {login['access_token']}"},
        json={"current_password": password, "new_password": "Replaced-99!"},
    )
    assert r2.status_code == 204

    # Old refresh token revoked
    rr = client.post(
        "/auth/refresh", json={"refresh_token": login["refresh_token"]}
    )
    assert rr.status_code == 401


def test_access_token_issued_before_password_change_is_rejected(
    client: TestClient,
    seeded_user_and_tenant: tuple[User, UUID, str],
) -> None:
    """Tokens whose iat < users.password_changed_at fail freshness check."""
    user, _tid, password = seeded_user_and_tenant
    login = client.post(
        "/auth/login", json={"email": user.email, "password": password}
    ).json()
    # Change password — bumps users.password_changed_at
    out = client.post(
        "/auth/change-password",
        headers={"Authorization": f"Bearer {login['access_token']}"},
        json={"current_password": password, "new_password": "Replaced-99!"},
    )
    assert out.status_code == 204
    # The old access token is now too old (iat < password_changed_at)
    me = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {login['access_token']}"},
    )
    assert me.status_code == 401


# --- access-token revocation via password_changed_at --------------------


@pytest.mark.asyncio
async def test_refresh_token_records_carry_family_and_parent_links(
    admin_session: AsyncSession,
    jwt_settings: JWTSettings,
    seeded_user_and_tenant: tuple[User, UUID, str],
) -> None:
    """Direct DB inspection: rotation chain rows linked correctly."""
    user, _tid, _pw = seeded_user_and_tenant
    audit = AuditService(admin_session)
    users = UserService(admin_session, audit)
    auth = AuthService(admin_session, users, audit, jwt_settings)
    async with admin_session.begin():
        _u, pair1 = await auth.login(email=user.email, password=_pw)
    async with admin_session.begin():
        _u, _pair2 = await auth.refresh(pair1.refresh_token)

    # Two rows in the same family; second has parent_jti = first jti.
    async with admin_session.begin():
        rows = (
            await admin_session.execute(
                select(RefreshTokenRecord)
                .where(RefreshTokenRecord.user_id == user.id)
                .order_by(RefreshTokenRecord.issued_at)
            )
        ).scalars().all()
    assert len(rows) >= 2
    assert rows[0].family_id == rows[1].family_id
    assert rows[1].parent_jti == rows[0].jti
    assert rows[0].used_at is not None  # rotated
    assert rows[1].used_at is None       # newly minted


# --- Sprint 9.0.6 C: rate limits ----------------------------------------


def test_login_per_ip_rate_limit_returns_429(
    client: TestClient,
    seeded_user_and_tenant: tuple[User, UUID, str],
) -> None:
    """5/min/IP — sixth attempt against any user from one IP should 429."""
    user, _tid, password = seeded_user_and_tenant
    # Five wrong-password POSTs all 401, sixth tips into 429.
    for _ in range(5):
        r = client.post(
            "/auth/login",
            json={"email": user.email, "password": "WRONG"},
        )
        assert r.status_code == 401, r.text
    blocked = client.post(
        "/auth/login",
        json={"email": user.email, "password": password},
    )
    assert blocked.status_code == 429, blocked.text
    assert blocked.headers.get("Retry-After") == "60"


def test_login_per_username_rate_limit_is_case_insensitive(
    client: TestClient,
    seeded_user_and_tenant: tuple[User, UUID, str],
) -> None:
    """Per-username cap (10/min) keyed lower-case so casing can't bypass."""
    user, _tid, _pw = seeded_user_and_tenant
    # Bypass the 5/min/IP cap by spoofing a fresh X-Forwarded-For per call.
    # The username bucket is single-keyed regardless of IP, so we'll trip
    # it on the 11th attempt.
    upper_email = user.email.upper()
    for i in range(10):
        r = client.post(
            "/auth/login",
            headers={"X-Forwarded-For": f"10.0.0.{i + 1}"},
            json={"email": upper_email, "password": "WRONG"},
        )
        # 401 (wrong password) is fine; what matters is that the per-IP
        # cap doesn't fire because each request comes from a different IP.
        assert r.status_code == 401, r.text
    blocked = client.post(
        "/auth/login",
        headers={"X-Forwarded-For": "10.0.0.99"},
        # Lower-case email — same bucket as the 10 upper-case attempts
        # above, proving the limiter normalises.
        json={"email": user.email, "password": "WRONG"},
    )
    assert blocked.status_code == 429, blocked.text


def test_refresh_per_ip_rate_limit_returns_429(
    client: TestClient,
    seeded_user_and_tenant: tuple[User, UUID, str],
) -> None:
    """30/min/IP — past the cap any /auth/refresh hits return 429."""
    user, _tid, password = seeded_user_and_tenant
    login = client.post(
        "/auth/login", json={"email": user.email, "password": password}
    ).json()
    # Send 30 invalid refreshes; the 31st should 429 (not 401).
    for _ in range(30):
        r = client.post(
            "/auth/refresh", json={"refresh_token": "obviously-not-valid"}
        )
        assert r.status_code == 401, r.text
    blocked = client.post(
        "/auth/refresh", json={"refresh_token": login["refresh_token"]}
    )
    assert blocked.status_code == 429, blocked.text


def test_change_password_per_user_rate_limit_returns_429(
    client: TestClient,
    seeded_user_and_tenant: tuple[User, UUID, str],
) -> None:
    """3/min/user — fourth change-password attempt 429s even with valid auth."""
    user, _tid, password = seeded_user_and_tenant
    login = client.post(
        "/auth/login", json={"email": user.email, "password": password}
    ).json()
    headers = {"Authorization": f"Bearer {login['access_token']}"}
    for _ in range(3):
        r = client.post(
            "/auth/change-password",
            headers=headers,
            json={"current_password": "wrong", "new_password": "Whatever-99!"},
        )
        assert r.status_code == 400, r.text
    blocked = client.post(
        "/auth/change-password",
        headers=headers,
        json={"current_password": password, "new_password": "Whatever-99!"},
    )
    assert blocked.status_code == 429, blocked.text
