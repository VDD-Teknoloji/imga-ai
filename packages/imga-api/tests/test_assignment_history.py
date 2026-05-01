"""Integration tests for ticket assignment history (Sprint 7.7.2 patch).

Each `TicketService.assign` call that actually changes the assignee
writes a row to ``ticket_assignment_history``. The polymorphic
``GET /tickets/{id}/timeline`` endpoint merges these into the event
stream alongside state transitions and comments.

Coverage:

  * Assign new (None → user) writes one history row.
  * Reassign (user → user) writes one history row with both fields set.
  * Unassign (user → None) writes one history row with to=None.
  * No-op (user → same user) does NOT write a history row OR an audit log.
  * RLS: tenant B cannot SELECT tenant A's history rows.
  * Timeline merge: assignment events interleave with state transitions
    and comments in chronological order.
  * /timeline emits the new event with the expected shape.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from cachetools import TTLCache
from fastapi.testclient import TestClient
from imga_db import create_engine, create_session_factory, set_current_tenant
from imga_db.models import (
    AuditLog,
    Category,
    Ticket,
    TicketAssignmentEvent,
    TicketState,
    User,
    UserTenantRole,
)
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from imga_api.main import app
from imga_api.services import (
    AuditService,
    TenantService,
    TicketService,
    UserService,
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


# --- shared seeding ------------------------------------------------------


async def _pick_kargo_id(admin_session: AsyncSession) -> UUID:
    async with admin_session.begin():
        row = await admin_session.execute(
            select(Category.id)
            .where(Category.tenant_id.is_(None))
            .where(Category.code == "kargo")
        )
        return UUID(str(row.scalar_one()))


async def _seed_tenant(admin_session: AsyncSession) -> UUID:
    audit = AuditService(admin_session)
    tsvc = TenantService(admin_session, audit)
    async with admin_session.begin():
        tenant = await tsvc.create(name="Asg Co", slug=f"asg-{uuid4().hex[:8]}")
    return tenant.id


async def _seed_user(
    admin_session: AsyncSession,
    *,
    tenant_id: UUID,
    role: UserTenantRole = UserTenantRole.ANALYST,
) -> tuple[User, str]:
    audit = AuditService(admin_session)
    usvc = UserService(admin_session, audit)
    plain = "Test-Password-123!"
    email = f"asg-{uuid4().hex[:8]}@example.com"
    async with admin_session.begin():
        user = await usvc.create(email=email, password=plain, full_name="Asg User")
        await usvc.attach_to_tenant(
            user_id=user.id, tenant_id=tenant_id, role=role
        )
    return user, plain


async def _seed_ticket(
    admin_session: AsyncSession, *, tenant_id: UUID, category_id: UUID,
) -> UUID:
    moment = datetime.now(UTC)
    ticket = Ticket(
        tenant_id=tenant_id,
        category_id=category_id,
        title="asg-test",
        state=TicketState.OPEN,
        opened_at=moment,
        last_state_change_at=moment,
    )
    async with admin_session.begin():
        admin_session.add(ticket)
        await admin_session.flush()
        return ticket.id


async def _cleanup(
    admin_session: AsyncSession, tenant_id: UUID, user_ids: list[UUID]
) -> None:
    async with admin_session.begin():
        await admin_session.execute(
            text("DELETE FROM ticket_assignment_history WHERE tenant_id = :t"),
            {"t": str(tenant_id)},
        )
        await admin_session.execute(
            text("DELETE FROM ticket_comments WHERE tenant_id = :t"),
            {"t": str(tenant_id)},
        )
        await admin_session.execute(
            text("DELETE FROM ticket_state_transitions WHERE tenant_id = :t"),
            {"t": str(tenant_id)},
        )
        await admin_session.execute(
            text("DELETE FROM tickets WHERE tenant_id = :t"),
            {"t": str(tenant_id)},
        )
        for uid in user_ids:
            await admin_session.execute(
                text("DELETE FROM users WHERE id = :id"), {"id": str(uid)}
            )
        await admin_session.execute(
            text("DELETE FROM tenants WHERE id = :id"), {"id": str(tenant_id)},
        )


@pytest_asyncio.fixture
async def asg_fixture(
    admin_session: AsyncSession,
) -> AsyncIterator[
    tuple[
        UUID,                   # tenant_id
        tuple[User, str],       # admin (TENANT_ADMIN)
        tuple[User, str],       # alice (ANALYST)
        tuple[User, str],       # bob (ANALYST)
        UUID,                   # ticket_id (OPEN, unassigned)
    ]
]:
    tenant_id = await _seed_tenant(admin_session)
    cat_id = await _pick_kargo_id(admin_session)
    admin_pair = await _seed_user(
        admin_session, tenant_id=tenant_id, role=UserTenantRole.TENANT_ADMIN
    )
    alice_pair = await _seed_user(admin_session, tenant_id=tenant_id)
    bob_pair = await _seed_user(admin_session, tenant_id=tenant_id)
    ticket_id = await _seed_ticket(
        admin_session, tenant_id=tenant_id, category_id=cat_id
    )
    yield tenant_id, admin_pair, alice_pair, bob_pair, ticket_id
    await _cleanup(
        admin_session,
        tenant_id,
        [admin_pair[0].id, alice_pair[0].id, bob_pair[0].id],
    )


# --- service-layer tests -------------------------------------------------


@pytest.mark.asyncio
async def test_assign_new_writes_history_row(
    admin_session: AsyncSession,
    asg_fixture: tuple[
        UUID, tuple[User, str], tuple[User, str], tuple[User, str], UUID
    ],
) -> None:
    tenant_id, _admin, alice, _bob, ticket_id = asg_fixture
    a_user, _ = alice

    app_engine = create_engine("app")
    app_factory = create_session_factory(app_engine)
    try:
        async with app_factory() as app_session:
            audit = AuditService(app_session)
            tickets = TicketService(app_session, audit)
            async with app_session.begin():
                await set_current_tenant(app_session, tenant_id)
                await tickets.assign(
                    ticket_id=ticket_id,
                    new_assignee_id=a_user.id,
                    actor_user_id=a_user.id,
                )
    finally:
        await app_engine.dispose()

    async with admin_session.begin():
        rows = (
            await admin_session.execute(
                select(TicketAssignmentEvent).where(
                    TicketAssignmentEvent.ticket_id == ticket_id
                )
            )
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0].from_user_id is None
    assert rows[0].to_user_id == a_user.id
    assert rows[0].actor_user_id == a_user.id


@pytest.mark.asyncio
async def test_reassign_writes_history_row_with_both_sides(
    admin_session: AsyncSession,
    asg_fixture: tuple[
        UUID, tuple[User, str], tuple[User, str], tuple[User, str], UUID
    ],
) -> None:
    tenant_id, admin, alice, bob, ticket_id = asg_fixture
    adm_user, _ = admin
    a_user, _ = alice
    b_user, _ = bob

    app_engine = create_engine("app")
    app_factory = create_session_factory(app_engine)
    try:
        async with app_factory() as app_session:
            audit = AuditService(app_session)
            tickets = TicketService(app_session, audit)
            async with app_session.begin():
                await set_current_tenant(app_session, tenant_id)
                # First: alice assigns to herself.
                await tickets.assign(
                    ticket_id=ticket_id,
                    new_assignee_id=a_user.id,
                    actor_user_id=a_user.id,
                )
                # Then: admin reassigns to bob.
                await tickets.assign(
                    ticket_id=ticket_id,
                    new_assignee_id=b_user.id,
                    actor_user_id=adm_user.id,
                )
    finally:
        await app_engine.dispose()

    async with admin_session.begin():
        rows = (
            await admin_session.execute(
                select(TicketAssignmentEvent)
                .where(TicketAssignmentEvent.ticket_id == ticket_id)
                .order_by(TicketAssignmentEvent.occurred_at.asc())
            )
        ).scalars().all()
    assert len(rows) == 2
    # First: None → alice.
    assert rows[0].from_user_id is None
    assert rows[0].to_user_id == a_user.id
    # Second: alice → bob, actor=admin.
    assert rows[1].from_user_id == a_user.id
    assert rows[1].to_user_id == b_user.id
    assert rows[1].actor_user_id == adm_user.id


@pytest.mark.asyncio
async def test_unassign_writes_history_row(
    admin_session: AsyncSession,
    asg_fixture: tuple[
        UUID, tuple[User, str], tuple[User, str], tuple[User, str], UUID
    ],
) -> None:
    tenant_id, _admin, alice, _bob, ticket_id = asg_fixture
    a_user, _ = alice

    app_engine = create_engine("app")
    app_factory = create_session_factory(app_engine)
    try:
        async with app_factory() as app_session:
            audit = AuditService(app_session)
            tickets = TicketService(app_session, audit)
            async with app_session.begin():
                await set_current_tenant(app_session, tenant_id)
                await tickets.assign(
                    ticket_id=ticket_id,
                    new_assignee_id=a_user.id,
                    actor_user_id=a_user.id,
                )
                await tickets.assign(
                    ticket_id=ticket_id,
                    new_assignee_id=None,
                    actor_user_id=a_user.id,
                )
    finally:
        await app_engine.dispose()

    async with admin_session.begin():
        rows = (
            await admin_session.execute(
                select(TicketAssignmentEvent)
                .where(TicketAssignmentEvent.ticket_id == ticket_id)
                .order_by(TicketAssignmentEvent.occurred_at.asc())
            )
        ).scalars().all()
    assert len(rows) == 2
    # Last row: alice → None.
    assert rows[1].from_user_id == a_user.id
    assert rows[1].to_user_id is None


@pytest.mark.asyncio
async def test_noop_assign_writes_no_history_or_audit(
    admin_session: AsyncSession,
    asg_fixture: tuple[
        UUID, tuple[User, str], tuple[User, str], tuple[User, str], UUID
    ],
) -> None:
    """Assigning to the current assignee is a no-op and writes nothing."""
    tenant_id, _admin, alice, _bob, ticket_id = asg_fixture
    a_user, _ = alice

    app_engine = create_engine("app")
    app_factory = create_session_factory(app_engine)
    try:
        async with app_factory() as app_session:
            audit = AuditService(app_session)
            tickets = TicketService(app_session, audit)
            async with app_session.begin():
                await set_current_tenant(app_session, tenant_id)
                # Real assign.
                await tickets.assign(
                    ticket_id=ticket_id,
                    new_assignee_id=a_user.id,
                    actor_user_id=a_user.id,
                )
                # No-op: same user again. Should write nothing.
                await tickets.assign(
                    ticket_id=ticket_id,
                    new_assignee_id=a_user.id,
                    actor_user_id=a_user.id,
                )
    finally:
        await app_engine.dispose()

    async with admin_session.begin():
        history_rows = (
            await admin_session.execute(
                select(TicketAssignmentEvent).where(
                    TicketAssignmentEvent.ticket_id == ticket_id
                )
            )
        ).scalars().all()
        audit_rows = (
            await admin_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "ticket.assign",
                    AuditLog.resource_id == ticket_id,
                )
            )
        ).scalars().all()
    # Exactly one of each: the first real assign. The no-op contributes
    # nothing to either table.
    assert len(history_rows) == 1
    assert len(audit_rows) == 1


# --- RLS isolation -------------------------------------------------------


@pytest.mark.asyncio
async def test_assignment_history_rls_isolation(
    admin_session: AsyncSession,
    asg_fixture: tuple[
        UUID, tuple[User, str], tuple[User, str], tuple[User, str], UUID
    ],
) -> None:
    """Tenant B's bound session cannot SELECT tenant A's assignment rows."""
    tid_a, _admin_a, alice, _bob, ticket_a = asg_fixture
    a_user, _ = alice

    # Tenant A: write a real assignment row.
    app_engine = create_engine("app")
    app_factory = create_session_factory(app_engine)
    try:
        async with app_factory() as app_session:
            audit = AuditService(app_session)
            tickets = TicketService(app_session, audit)
            async with app_session.begin():
                await set_current_tenant(app_session, tid_a)
                await tickets.assign(
                    ticket_id=ticket_a,
                    new_assignee_id=a_user.id,
                    actor_user_id=a_user.id,
                )

        # Tenant B: stand up.
        tid_b = await _seed_tenant(admin_session)
        try:
            async with app_factory() as app_session, app_session.begin():
                await set_current_tenant(app_session, tid_b)
                visible = (
                    await app_session.execute(select(TicketAssignmentEvent))
                ).scalars().all()
                assert len(visible) == 0
        finally:
            await _cleanup(admin_session, tid_b, [])
    finally:
        await app_engine.dispose()


# --- /timeline endpoint -------------------------------------------------


@pytest.mark.asyncio
async def test_timeline_emits_assignment_changed_events(
    client: TestClient,
    asg_fixture: tuple[
        UUID, tuple[User, str], tuple[User, str], tuple[User, str], UUID
    ],
) -> None:
    """End-to-end: assign through the route, /timeline emits the event
    with the new assignment_changed type and from/to_user_id payload."""
    tenant_id, admin, alice, bob, ticket_id = asg_fixture
    adm_user, adm_pw = admin
    a_user, _ = alice
    b_user, _ = bob

    token = _login(client, adm_user.email, adm_pw, tenant_id)
    headers = {"Authorization": f"Bearer {token}"}

    # Two assignments via the API: None → alice, alice → bob.
    r1 = client.post(
        f"/tickets/{ticket_id}/assign",
        headers=headers,
        json={"assignee_user_id": str(a_user.id)},
    )
    assert r1.status_code == 200, r1.text
    r2 = client.post(
        f"/tickets/{ticket_id}/assign",
        headers=headers,
        json={"assignee_user_id": str(b_user.id)},
    )
    assert r2.status_code == 200, r2.text

    timeline = client.get(
        f"/tickets/{ticket_id}/timeline", headers=headers
    ).json()
    events = timeline["events"]
    assignment_events = [e for e in events if e["type"] == "assignment_changed"]
    assert len(assignment_events) == 2
    # Chronological — first None → alice, then alice → bob.
    assert assignment_events[0]["from_user_id"] is None
    assert assignment_events[0]["to_user_id"] == str(a_user.id)
    assert assignment_events[1]["from_user_id"] == str(a_user.id)
    assert assignment_events[1]["to_user_id"] == str(b_user.id)


@pytest.mark.asyncio
async def test_timeline_orders_assignment_with_state_transitions(
    client: TestClient,
    asg_fixture: tuple[
        UUID, tuple[User, str], tuple[User, str], tuple[User, str], UUID
    ],
) -> None:
    """Mixed sequence — transition then assign — interleave correctly."""
    tenant_id, admin, alice, _bob, ticket_id = asg_fixture
    adm_user, adm_pw = admin
    a_user, _ = alice

    token = _login(client, adm_user.email, adm_pw, tenant_id)
    headers = {"Authorization": f"Bearer {token}"}

    # in_progress (transition) → assign to alice → resolved (transition).
    client.post(
        f"/tickets/{ticket_id}/transition",
        headers=headers,
        json={"to_state": "in_progress"},
    )
    client.post(
        f"/tickets/{ticket_id}/assign",
        headers=headers,
        json={"assignee_user_id": str(a_user.id)},
    )
    client.post(
        f"/tickets/{ticket_id}/transition",
        headers=headers,
        json={"to_state": "resolved"},
    )

    timeline = client.get(
        f"/tickets/{ticket_id}/timeline", headers=headers
    ).json()
    events = timeline["events"]
    timestamps = [e["occurred_at"] for e in events]
    assert timestamps == sorted(timestamps)

    types_in_order = [e["type"] for e in events]
    # Note: the transition→in_progress also auto-sets assigned_to_user_id
    # in TicketService._apply_state_change when the actor wasn't already
    # the assignee. But that's a metadata side effect, not a separate
    # assign() call, so it does NOT write a history row. We only get
    # the explicit /assign call's history row here.
    assignment_count = types_in_order.count("assignment_changed")
    transition_count = types_in_order.count("state_transition")
    assert assignment_count >= 1
    # The fixture seeds the ticket via direct INSERT (no creation
    # marker in ticket_state_transitions), so we expect exactly the
    # two transition() calls = 2. Service-level creates also write a
    # creation marker; that path is exercised in test_tickets.py.
    assert transition_count == 2
