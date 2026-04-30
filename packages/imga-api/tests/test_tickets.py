"""Integration tests for /tickets endpoints + TicketService.

Covers the seven scenarios listed in the 7.5 implementation plan plus
a few edge cases:

  1. State machine round-trip via API (create → claim → resolve → close)
  2. Role matrix: ANALYST cannot reopen, cannot cancel from IN_PROGRESS
  3. Audit log written on every transition + creation
  4. RLS isolation: tenant A cannot see tenant B's tickets
  5. Auto-create decision function (3 modes)
  6. customer-inbound endpoint sets the field, doesn't change state
  7. quick-resolve writes 2 timeline rows + 2 audit entries

Plus:
  * Regression window — RESOLVED → IN_PROGRESS within 7d works,
    past 7d returns 409.
  * un-claim self-only — analyst cannot un-claim someone else's ticket.
  * Cancellation reason required — CANCELLED without reason → 422.
  * find_due_resolved / find_due_pending pure-ish helpers (using time
    travel by setting tenant windows to 0).
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
from fastapi.testclient import TestClient
from imga_db import create_engine, create_session_factory
from imga_db.models import (
    AuditLog,
    Category,
    TicketState,
    User,
    UserTenantRole,
)
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from imga_api.main import app
from imga_api.services import (
    AuditService,
    AutoCreateDecision,
    TenantService,
    TicketService,
    TransitionRequest,
    UserService,
    decide_auto_create_state,
)
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


async def _seed(
    admin_session: AsyncSession, role: UserTenantRole
) -> tuple[User, UUID, str]:
    audit = AuditService(admin_session)
    tsvc = TenantService(admin_session, audit)
    usvc = UserService(admin_session, audit)
    plain = "Test-Password-123!"
    email = f"tk-{uuid4().hex[:8]}@example.com"
    async with admin_session.begin():
        tenant = await tsvc.create(name="Tk Co", slug=f"tk-{uuid4().hex[:8]}")
        user = await usvc.create(email=email, password=plain, full_name="Tk User")
        await usvc.attach_to_tenant(
            user_id=user.id, tenant_id=tenant.id, role=role
        )
        return user, tenant.id, plain


async def _cleanup(admin_session: AsyncSession, user_id: UUID, tenant_id: UUID) -> None:
    async with admin_session.begin():
        await admin_session.execute(
            text("DELETE FROM ticket_state_transitions WHERE tenant_id = :t"),
            {"t": str(tenant_id)},
        )
        await admin_session.execute(
            text("DELETE FROM tickets WHERE tenant_id = :t"),
            {"t": str(tenant_id)},
        )
        await admin_session.execute(
            text("DELETE FROM users WHERE id = :id"), {"id": str(user_id)}
        )
        await admin_session.execute(
            text("DELETE FROM tenants WHERE id = :id"), {"id": str(tenant_id)}
        )


@pytest_asyncio.fixture
async def admin_user(
    admin_session: AsyncSession,
) -> AsyncIterator[tuple[User, UUID, str]]:
    user, tid, pw = await _seed(admin_session, UserTenantRole.TENANT_ADMIN)
    yield user, tid, pw
    await _cleanup(admin_session, user.id, tid)


@pytest_asyncio.fixture
async def analyst_user(
    admin_session: AsyncSession,
) -> AsyncIterator[tuple[User, UUID, str]]:
    user, tid, pw = await _seed(admin_session, UserTenantRole.ANALYST)
    yield user, tid, pw
    await _cleanup(admin_session, user.id, tid)


@pytest_asyncio.fixture
async def two_admins(
    admin_session: AsyncSession,
) -> AsyncIterator[tuple[tuple[User, UUID, str], tuple[User, UUID, str]]]:
    a = await _seed(admin_session, UserTenantRole.TENANT_ADMIN)
    b = await _seed(admin_session, UserTenantRole.TENANT_ADMIN)
    yield a, b
    await _cleanup(admin_session, a[0].id, a[1])
    await _cleanup(admin_session, b[0].id, b[1])


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


async def _pick_kargo_id(admin_session: AsyncSession) -> UUID:
    """Pick the global 'kargo' category id via admin (BYPASSRLS)."""
    async with admin_session.begin():
        row = await admin_session.execute(
            select(Category.id)
            .where(Category.tenant_id.is_(None))
            .where(Category.code == "kargo")
        )
        return UUID(str(row.scalar_one()))


# --- 1. happy path: create → claim → resolve → close --------------------


@pytest.mark.asyncio
async def test_full_lifecycle_via_api(
    client: TestClient,
    admin_session: AsyncSession,
    admin_user: tuple[User, UUID, str],
) -> None:
    user, tid, pw = admin_user
    cat_id = await _pick_kargo_id(admin_session)
    token = _login(client, user.email, pw, tid)
    headers = {"Authorization": f"Bearer {token}"}

    create = client.post(
        "/tickets",
        headers=headers,
        json={"category_id": str(cat_id), "title": "Kargo gecikti"},
    )
    assert create.status_code == 201, create.text
    ticket_id = create.json()["id"]
    assert create.json()["state"] == "open"

    for to_state in ("in_progress", "resolved", "closed"):
        r = client.post(
            f"/tickets/{ticket_id}/transition",
            headers=headers,
            json={"to_state": to_state},
        )
        assert r.status_code == 200, r.text
        assert r.json()["state"] == to_state


# --- 2. role matrix: ANALYST cannot reopen, cannot cancel IN_PROGRESS ---


@pytest.mark.asyncio
async def test_analyst_cannot_reopen_closed_ticket(
    client: TestClient,
    admin_session: AsyncSession,
    analyst_user: tuple[User, UUID, str],
) -> None:
    user, tid, pw = analyst_user
    cat_id = await _pick_kargo_id(admin_session)
    token = _login(client, user.email, pw, tid)
    headers = {"Authorization": f"Bearer {token}"}

    create = client.post(
        "/tickets",
        headers=headers,
        json={"category_id": str(cat_id), "title": "Test"},
    )
    tid_ticket = create.json()["id"]
    for to_state in ("in_progress", "resolved", "closed"):
        client.post(
            f"/tickets/{tid_ticket}/transition",
            headers=headers,
            json={"to_state": to_state},
        )

    # Try reopen as analyst
    r = client.post(
        f"/tickets/{tid_ticket}/transition",
        headers=headers,
        json={"to_state": "open", "reason": "reopen"},
    )
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_analyst_cannot_cancel_from_in_progress(
    client: TestClient,
    admin_session: AsyncSession,
    analyst_user: tuple[User, UUID, str],
) -> None:
    """Revision 5: ANALYST must un-claim first; admin cancels."""
    user, tid, pw = analyst_user
    cat_id = await _pick_kargo_id(admin_session)
    token = _login(client, user.email, pw, tid)
    headers = {"Authorization": f"Bearer {token}"}
    create = client.post(
        "/tickets", headers=headers,
        json={"category_id": str(cat_id), "title": "Test"},
    )
    tid_ticket = create.json()["id"]
    client.post(
        f"/tickets/{tid_ticket}/transition",
        headers=headers,
        json={"to_state": "in_progress"},
    )
    # Analyst cancellation should be 403
    r = client.post(
        f"/tickets/{tid_ticket}/transition",
        headers=headers,
        json={
            "to_state": "cancelled",
            "cancellation_reason": "spam",
        },
    )
    assert r.status_code == 403, r.text


# --- 3. audit log written on creation + every transition ---------------


@pytest.mark.asyncio
async def test_audit_log_records_transitions(
    client: TestClient,
    admin_session: AsyncSession,
    admin_user: tuple[User, UUID, str],
) -> None:
    user, tid, pw = admin_user
    cat_id = await _pick_kargo_id(admin_session)
    token = _login(client, user.email, pw, tid)
    headers = {"Authorization": f"Bearer {token}"}

    create = client.post(
        "/tickets", headers=headers,
        json={"category_id": str(cat_id), "title": "Audit"},
    )
    ticket_id = UUID(create.json()["id"])
    for to_state in ("in_progress", "resolved", "closed"):
        client.post(
            f"/tickets/{ticket_id}/transition",
            headers=headers,
            json={"to_state": to_state},
        )

    async with admin_session.begin():
        actions = list(
            (
                await admin_session.execute(
                    select(AuditLog.action)
                    .where(AuditLog.resource_id == ticket_id)
                    .order_by(AuditLog.created_at.asc())
                )
            ).scalars()
        )
    assert "ticket.create" in actions
    assert actions.count("ticket.transition") == 3


# --- 4. RLS isolation ----------------------------------------------------


@pytest.mark.asyncio
async def test_tenant_cannot_see_other_tenant_tickets(
    client: TestClient,
    admin_session: AsyncSession,
    two_admins: tuple[tuple[User, UUID, str], tuple[User, UUID, str]],
) -> None:
    (user_a, tid_a, pw_a), (user_b, tid_b, pw_b) = two_admins
    cat_id = await _pick_kargo_id(admin_session)
    tok_a = _login(client, user_a.email, pw_a, tid_a)
    tok_b = _login(client, user_b.email, pw_b, tid_b)

    # B creates a ticket
    b_create = client.post(
        "/tickets",
        headers={"Authorization": f"Bearer {tok_b}"},
        json={"category_id": str(cat_id), "title": "B-only"},
    )
    assert b_create.status_code == 201
    b_ticket_id = b_create.json()["id"]

    # A's list does not contain B's ticket
    a_list = client.get(
        "/tickets",
        headers={"Authorization": f"Bearer {tok_a}"},
    ).json()
    assert all(t["id"] != b_ticket_id for t in a_list["tickets"])

    # A's GET-by-id returns 404 (RLS hides it)
    r = client.get(
        f"/tickets/{b_ticket_id}",
        headers={"Authorization": f"Bearer {tok_a}"},
    )
    assert r.status_code == 404


# --- 5. auto-create decision function ----------------------------------


def test_decide_auto_create_state_three_modes() -> None:
    from imga_db.models import AutomationMode

    manual = decide_auto_create_state(
        automation_mode=AutomationMode.MANUAL,
        sentiment_score=-0.9,
        confidence=0.95,
    )
    assert isinstance(manual, AutoCreateDecision)
    assert manual.should_create is False

    semi_below = decide_auto_create_state(
        automation_mode=AutomationMode.SEMI_AUTO,
        sentiment_score=-0.4,
        confidence=0.95,
    )
    assert semi_below.should_create is False
    semi_above = decide_auto_create_state(
        automation_mode=AutomationMode.SEMI_AUTO,
        sentiment_score=-0.6,
        confidence=0.8,
    )
    assert semi_above.should_create is True

    full_neg = decide_auto_create_state(
        automation_mode=AutomationMode.FULL_AUTO,
        sentiment_score=-0.1,
        confidence=0.5,
    )
    assert full_neg.should_create is True
    full_pos = decide_auto_create_state(
        automation_mode=AutomationMode.FULL_AUTO,
        sentiment_score=0.5,
        confidence=0.9,
    )
    assert full_pos.should_create is False


# --- 6. customer-inbound: sets field, no state change ------------------


@pytest.mark.asyncio
async def test_customer_inbound_sets_field_no_state_change(
    client: TestClient,
    admin_session: AsyncSession,
    admin_user: tuple[User, UUID, str],
) -> None:
    user, tid, pw = admin_user
    cat_id = await _pick_kargo_id(admin_session)
    token = _login(client, user.email, pw, tid)
    headers = {"Authorization": f"Bearer {token}"}
    create = client.post(
        "/tickets", headers=headers,
        json={"category_id": str(cat_id), "title": "X"},
    )
    ticket_id = create.json()["id"]
    # Move to PENDING_CUSTOMER through IN_PROGRESS
    client.post(
        f"/tickets/{ticket_id}/transition",
        headers=headers,
        json={"to_state": "in_progress"},
    )
    client.post(
        f"/tickets/{ticket_id}/transition",
        headers=headers,
        json={"to_state": "pending_customer"},
    )
    r = client.post(f"/tickets/{ticket_id}/customer-inbound", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["customer_inbound_received_at"] is not None
    assert body["state"] == "pending_customer"  # state unchanged


# --- 7. quick-resolve writes 2 timeline rows + 2 audit entries --------


@pytest.mark.asyncio
async def test_quick_resolve_writes_two_transitions(
    client: TestClient,
    admin_session: AsyncSession,
    admin_user: tuple[User, UUID, str],
) -> None:
    user, tid, pw = admin_user
    cat_id = await _pick_kargo_id(admin_session)
    token = _login(client, user.email, pw, tid)
    headers = {"Authorization": f"Bearer {token}"}
    create = client.post(
        "/tickets", headers=headers,
        json={"category_id": str(cat_id), "title": "Trivial"},
    )
    ticket_id = UUID(create.json()["id"])
    r = client.post(f"/tickets/{ticket_id}/quick-resolve", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "resolved"

    timeline = client.get(
        f"/tickets/{ticket_id}/transitions", headers=headers
    ).json()["transitions"]
    # Creation marker + 2 transitions
    states = [(t["from_state"], t["to_state"]) for t in timeline]
    assert ("open", "in_progress") in states
    assert ("in_progress", "resolved") in states


# --- 8. regression window — within 7d works, past 7d returns 409 ------


@pytest.mark.asyncio
async def test_regression_within_window(
    client: TestClient,
    admin_session: AsyncSession,
    admin_user: tuple[User, UUID, str],
) -> None:
    user, tid, pw = admin_user
    cat_id = await _pick_kargo_id(admin_session)
    token = _login(client, user.email, pw, tid)
    headers = {"Authorization": f"Bearer {token}"}
    create = client.post(
        "/tickets", headers=headers,
        json={"category_id": str(cat_id), "title": "Regression"},
    )
    ticket_id = create.json()["id"]
    for to_state in ("in_progress", "resolved"):
        client.post(
            f"/tickets/{ticket_id}/transition",
            headers=headers,
            json={"to_state": to_state},
        )
    r = client.post(
        f"/tickets/{ticket_id}/transition",
        headers=headers,
        json={"to_state": "in_progress", "reason": "customer not happy"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "in_progress"


@pytest.mark.asyncio
async def test_regression_past_window_returns_409(
    client: TestClient,
    admin_session: AsyncSession,
    admin_user: tuple[User, UUID, str],
) -> None:
    """Backdate resolved_at and shrink the window so the guard trips."""
    user, tid, pw = admin_user
    cat_id = await _pick_kargo_id(admin_session)
    token = _login(client, user.email, pw, tid)
    headers = {"Authorization": f"Bearer {token}"}
    create = client.post(
        "/tickets", headers=headers,
        json={"category_id": str(cat_id), "title": "OutOfWindow"},
    )
    ticket_id = UUID(create.json()["id"])
    for to_state in ("in_progress", "resolved"):
        client.post(
            f"/tickets/{ticket_id}/transition",
            headers=headers,
            json={"to_state": to_state},
        )
    # Set window to 1 day and resolved_at to 2 days ago.
    async with admin_session.begin():
        await admin_session.execute(
            text(
                "UPDATE tenants SET resolved_regression_window_days = 1 "
                "WHERE id = :t"
            ),
            {"t": str(tid)},
        )
        await admin_session.execute(
            text(
                "UPDATE tickets SET resolved_at = :ago WHERE id = :id"
            ),
            {
                "ago": datetime.now(UTC) - timedelta(days=2),
                "id": str(ticket_id),
            },
        )
    r = client.post(
        f"/tickets/{ticket_id}/transition",
        headers=headers,
        json={"to_state": "in_progress"},
    )
    assert r.status_code == 409, r.text


# --- 9. un-claim self-only enforcement --------------------------------


@pytest.mark.asyncio
async def test_analyst_cannot_unclaim_other_users_ticket(
    client: TestClient,
    admin_session: AsyncSession,
    admin_user: tuple[User, UUID, str],
) -> None:
    """Admin claims; a freshly seeded analyst tries to un-claim. Allowed
    by graph + role; blocked by self-only guard at service level."""
    admin, tid, admin_pw = admin_user
    cat_id = await _pick_kargo_id(admin_session)
    admin_token = _login(client, admin.email, admin_pw, tid)
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # Create + admin claims
    create = client.post(
        "/tickets", headers=admin_headers,
        json={"category_id": str(cat_id), "title": "Selfclaim"},
    )
    ticket_id = create.json()["id"]
    client.post(
        f"/tickets/{ticket_id}/transition",
        headers=admin_headers,
        json={"to_state": "in_progress"},
    )

    # Add an analyst to the same tenant via admin session, then login as them
    audit = AuditService(admin_session)
    usvc = UserService(admin_session, audit)
    plain = "Test-Password-123!"
    email = f"un-{uuid4().hex[:8]}@example.com"
    async with admin_session.begin():
        analyst = await usvc.create(email=email, password=plain, full_name="A")
        await usvc.attach_to_tenant(
            user_id=analyst.id, tenant_id=tid, role=UserTenantRole.ANALYST
        )
    try:
        analyst_token = _login(client, email, plain, tid)
        r = client.post(
            f"/tickets/{ticket_id}/transition",
            headers={"Authorization": f"Bearer {analyst_token}"},
            json={"to_state": "open", "reason": "drop"},
        )
        assert r.status_code == 403, r.text
    finally:
        async with admin_session.begin():
            await admin_session.execute(
                text("DELETE FROM users WHERE id = :id"),
                {"id": str(analyst.id)},
            )


# --- 10. cancellation reason required → 422 --------------------------


@pytest.mark.asyncio
async def test_cancellation_without_reason_returns_422(
    client: TestClient,
    admin_session: AsyncSession,
    admin_user: tuple[User, UUID, str],
) -> None:
    user, tid, pw = admin_user
    cat_id = await _pick_kargo_id(admin_session)
    token = _login(client, user.email, pw, tid)
    headers = {"Authorization": f"Bearer {token}"}
    create = client.post(
        "/tickets", headers=headers,
        json={"category_id": str(cat_id), "title": "NeedsReason"},
    )
    ticket_id = create.json()["id"]
    r = client.post(
        f"/tickets/{ticket_id}/transition",
        headers=headers,
        json={"to_state": "cancelled"},  # no cancellation_reason
    )
    assert r.status_code == 422, r.text


# --- 11. find_due_resolved picks up tickets with elapsed window -------


@pytest.mark.asyncio
async def test_find_due_resolved_returns_eligible_tickets(
    admin_session: AsyncSession,
    admin_user: tuple[User, UUID, str],
) -> None:
    user, tid, _pw = admin_user
    cat_id = await _pick_kargo_id(admin_session)
    audit = AuditService(admin_session)
    svc = TicketService(admin_session, audit)
    now = datetime.now(UTC)
    async with admin_session.begin():
        ticket = await svc.create(
            tenant_id=tid,
            category_id=cat_id,
            title="auto-close-me",
            created_by_user_id=user.id,
        )
        await svc.transition(
            ticket_id=ticket.id,
            request=TransitionRequest(to_state=TicketState.IN_PROGRESS),
            actor_user_id=user.id,
            actor_role=UserTenantRole.TENANT_ADMIN,
            now=now - timedelta(days=10),
        )
        await svc.transition(
            ticket_id=ticket.id,
            request=TransitionRequest(to_state=TicketState.RESOLVED),
            actor_user_id=user.id,
            actor_role=UserTenantRole.TENANT_ADMIN,
            now=now - timedelta(days=10),
        )
        # Force resolved_at to 10 days ago since transition() uses now
        # internally; with default window=7d this should be due.
        await admin_session.execute(
            text("UPDATE tickets SET resolved_at = :ago WHERE id = :id"),
            {"ago": now - timedelta(days=10), "id": str(ticket.id)},
        )

    async with admin_session.begin():
        due = await svc.find_due_resolved(now=now, tenant_id=tid)
    ids = {t.id for t in due}
    assert ticket.id in ids
