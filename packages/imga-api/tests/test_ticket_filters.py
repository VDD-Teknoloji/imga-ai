"""Integration tests for /tickets filter + sort + paging + /tickets/stats.

Sprint 7.5.5 / Alt-Faz 2. Covers:

  * CSV parsing edge cases — ``state=open,in_progress`` / empty string /
    only-comma. Pydantic field_validator(mode="before") splits before
    enum validation, so "" yields [] (no 422) but unknown values yield
    422 with a clear field path.
  * Combined filters — state IN AND priority IN AND date range AND
    search; ``total`` reflects pre-pagination count, ``tickets`` reflects
    the page slice.
  * limit hard cap (Field(le=500)) — ?limit=501 returns 422.
  * order_by injection guard — Literal-typed, so ?order_by=foo is 422
    with no SQL touched.
  * Stats group_by — state / priority / category / assignee axes,
    inheriting the same filter chain as /tickets.
  * RLS isolation — /tickets/stats does NOT leak counts across tenants
    (the filter is bound by the tenant SET via bind_tenant + the
    explicit ``Ticket.tenant_id == X`` predicate).
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
    Category,
    Ticket,
    TicketPriority,
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


async def _pick_kargo_id(admin_session: AsyncSession) -> UUID:
    async with admin_session.begin():
        row = await admin_session.execute(
            select(Category.id)
            .where(Category.tenant_id.is_(None))
            .where(Category.code == "kargo")
        )
        return UUID(str(row.scalar_one()))


async def _pick_iade_id(admin_session: AsyncSession) -> UUID:
    async with admin_session.begin():
        row = await admin_session.execute(
            select(Category.id)
            .where(Category.tenant_id.is_(None))
            .where(Category.code == "iade")
        )
        return UUID(str(row.scalar_one()))


async def _seed_tenant_with_user(
    admin_session: AsyncSession,
) -> tuple[User, UUID, str]:
    audit = AuditService(admin_session)
    tsvc = TenantService(admin_session, audit)
    usvc = UserService(admin_session, audit)
    plain = "Test-Password-123!"
    email = f"flt-{uuid4().hex[:8]}@example.com"
    async with admin_session.begin():
        tenant = await tsvc.create(name="Flt Co", slug=f"flt-{uuid4().hex[:8]}")
        user = await usvc.create(email=email, password=plain, full_name="Flt User")
        await usvc.attach_to_tenant(
            user_id=user.id, tenant_id=tenant.id, role=UserTenantRole.TENANT_ADMIN
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


async def _seed_ticket(
    admin_session: AsyncSession,
    *,
    tenant_id: UUID,
    category_id: UUID,
    title: str,
    state: TicketState,
    priority: TicketPriority,
    opened_at: datetime | None = None,
) -> UUID:
    """Bypass RLS to create a ticket directly with arbitrary state/priority.

    Avoids running the state machine for every fixture row — the filter
    layer doesn't care about transition history."""
    moment = opened_at or datetime.now(UTC)
    ticket = Ticket(
        tenant_id=tenant_id,
        category_id=category_id,
        title=title,
        priority=priority,
        state=state,
        opened_at=moment,
        last_state_change_at=moment,
    )
    async with admin_session.begin():
        admin_session.add(ticket)
        await admin_session.flush()
        return ticket.id


@pytest_asyncio.fixture
async def filter_fixture(
    admin_session: AsyncSession,
) -> AsyncIterator[
    tuple[User, UUID, str, dict[str, UUID | str], list[UUID]]
]:
    """Single tenant + admin + 6 tickets across state/priority/category."""
    user, tid, pw = await _seed_tenant_with_user(admin_session)
    kargo_id = await _pick_kargo_id(admin_session)
    iade_id = await _pick_iade_id(admin_session)

    now = datetime.now(UTC)
    seeds: list[tuple[str, TicketState, TicketPriority, UUID, datetime]] = [
        ("open-high-kargo-recent", TicketState.OPEN, TicketPriority.HIGH, kargo_id, now),
        ("open-low-kargo-old", TicketState.OPEN, TicketPriority.LOW, kargo_id, now - timedelta(days=10)),
        ("inprog-urgent-iade-recent", TicketState.IN_PROGRESS, TicketPriority.URGENT, iade_id, now - timedelta(days=2)),
        ("resolved-normal-iade-old", TicketState.RESOLVED, TicketPriority.NORMAL, iade_id, now - timedelta(days=20)),
        ("closed-low-kargo-very-old", TicketState.CLOSED, TicketPriority.LOW, kargo_id, now - timedelta(days=60)),
        ("open-high-iade-recent", TicketState.OPEN, TicketPriority.HIGH, iade_id, now - timedelta(hours=2)),
    ]
    ids: list[UUID] = []
    for title, state, prio, cat_id, opened in seeds:
        tid_ticket = await _seed_ticket(
            admin_session,
            tenant_id=tid,
            category_id=cat_id,
            title=title,
            state=state,
            priority=prio,
            opened_at=opened,
        )
        ids.append(tid_ticket)

    cats = {"kargo": kargo_id, "iade": iade_id}
    yield user, tid, pw, cats, ids
    await _cleanup(admin_session, user.id, tid)


# --- CSV parsing edge cases -------------------------------------------------


@pytest.mark.asyncio
async def test_csv_empty_string_treated_as_no_filter(
    client: TestClient,
    filter_fixture: tuple[User, UUID, str, dict[str, UUID], list[UUID]],
) -> None:
    """Empty CSV (?state=) is "no filter", not 422."""
    user, tid, pw, _cats, ids = filter_fixture
    token = _login(client, user.email, pw, tid)
    headers = {"Authorization": f"Bearer {token}"}

    r = client.get("/tickets?state=", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == len(ids)


@pytest.mark.asyncio
async def test_csv_multi_value_state_filter(
    client: TestClient,
    filter_fixture: tuple[User, UUID, str, dict[str, UUID], list[UUID]],
) -> None:
    """state=open,in_progress should return only those two states."""
    user, tid, pw, _cats, _ids = filter_fixture
    token = _login(client, user.email, pw, tid)
    headers = {"Authorization": f"Bearer {token}"}

    r = client.get("/tickets?state=open,in_progress", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 4  # 3 OPEN + 1 IN_PROGRESS
    assert all(t["state"] in ("open", "in_progress") for t in body["tickets"])


@pytest.mark.asyncio
async def test_csv_unknown_enum_value_returns_422(
    client: TestClient,
    filter_fixture: tuple[User, UUID, str, dict[str, UUID], list[UUID]],
) -> None:
    """Unknown enum value (?state=bogus) → 422 with field path."""
    user, tid, pw, _cats, _ids = filter_fixture
    token = _login(client, user.email, pw, tid)
    headers = {"Authorization": f"Bearer {token}"}

    r = client.get("/tickets?state=bogus", headers=headers)
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_csv_only_commas_treated_as_empty(
    client: TestClient,
    filter_fixture: tuple[User, UUID, str, dict[str, UUID], list[UUID]],
) -> None:
    """state=,, contains no real values — should match all (no filter)."""
    user, tid, pw, _cats, ids = filter_fixture
    token = _login(client, user.email, pw, tid)
    headers = {"Authorization": f"Bearer {token}"}

    r = client.get("/tickets?state=,,", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["total"] == len(ids)


# --- combined filters -------------------------------------------------------


@pytest.mark.asyncio
async def test_combined_state_priority_category_filter(
    client: TestClient,
    filter_fixture: tuple[User, UUID, str, dict[str, UUID], list[UUID]],
) -> None:
    user, tid, pw, cats, _ids = filter_fixture
    token = _login(client, user.email, pw, tid)
    headers = {"Authorization": f"Bearer {token}"}

    # OPEN tickets in kargo with priority HIGH or URGENT — only "open-high-kargo-recent"
    r = client.get(
        f"/tickets?state=open&priority=high,urgent&category_id={cats['kargo']}",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    assert body["tickets"][0]["title"] == "open-high-kargo-recent"


@pytest.mark.asyncio
async def test_search_matches_title_substring(
    client: TestClient,
    filter_fixture: tuple[User, UUID, str, dict[str, UUID], list[UUID]],
) -> None:
    user, tid, pw, _cats, _ids = filter_fixture
    token = _login(client, user.email, pw, tid)
    headers = {"Authorization": f"Bearer {token}"}

    r = client.get("/tickets?search=urgent", headers=headers)
    assert r.status_code == 200
    body = r.json()
    # Only "inprog-urgent-iade-recent" matches.
    assert body["total"] == 1
    assert "urgent" in body["tickets"][0]["title"]


@pytest.mark.asyncio
async def test_date_range_filter(
    client: TestClient,
    filter_fixture: tuple[User, UUID, str, dict[str, UUID], list[UUID]],
) -> None:
    user, tid, pw, _cats, _ids = filter_fixture
    token = _login(client, user.email, pw, tid)
    headers = {"Authorization": f"Bearer {token}"}

    # Last 7 days only — open-high-kargo-recent + inprog-urgent-iade-recent + open-high-iade-recent
    cutoff = (datetime.now(UTC) - timedelta(days=7)).isoformat()
    r = client.get("/tickets", params={"opened_after": cutoff}, headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3


# --- pagination + caps ------------------------------------------------------


@pytest.mark.asyncio
async def test_limit_above_500_returns_422(
    client: TestClient,
    filter_fixture: tuple[User, UUID, str, dict[str, UUID], list[UUID]],
) -> None:
    """Pydantic Field(le=500) caps offset paging."""
    user, tid, pw, _cats, _ids = filter_fixture
    token = _login(client, user.email, pw, tid)
    headers = {"Authorization": f"Bearer {token}"}

    r = client.get("/tickets?limit=501", headers=headers)
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_pagination_offset_and_total(
    client: TestClient,
    filter_fixture: tuple[User, UUID, str, dict[str, UUID], list[UUID]],
) -> None:
    """``total`` ignores limit/offset; ``tickets`` is the slice."""
    user, tid, pw, _cats, ids = filter_fixture
    token = _login(client, user.email, pw, tid)
    headers = {"Authorization": f"Bearer {token}"}

    r = client.get("/tickets?limit=2&offset=1", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == len(ids)
    assert body["limit"] == 2
    assert body["offset"] == 1
    assert len(body["tickets"]) == 2


# --- order_by injection guard -----------------------------------------------


@pytest.mark.asyncio
async def test_order_by_unknown_column_returns_422(
    client: TestClient,
    filter_fixture: tuple[User, UUID, str, dict[str, UUID], list[UUID]],
) -> None:
    """Literal-typed order_by makes SQL injection / unknown column impossible."""
    user, tid, pw, _cats, _ids = filter_fixture
    token = _login(client, user.email, pw, tid)
    headers = {"Authorization": f"Bearer {token}"}

    r = client.get("/tickets?order_by=DROP+TABLE", headers=headers)
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_order_by_opened_at_asc(
    client: TestClient,
    filter_fixture: tuple[User, UUID, str, dict[str, UUID], list[UUID]],
) -> None:
    user, tid, pw, _cats, _ids = filter_fixture
    token = _login(client, user.email, pw, tid)
    headers = {"Authorization": f"Bearer {token}"}

    r = client.get(
        "/tickets?order_by=opened_at&order=asc",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    titles = [t["title"] for t in r.json()["tickets"]]
    # closed-low-kargo-very-old (60d) is the oldest.
    assert titles[0] == "closed-low-kargo-very-old"


# --- /tickets/stats ---------------------------------------------------------


@pytest.mark.asyncio
async def test_stats_group_by_state(
    client: TestClient,
    filter_fixture: tuple[User, UUID, str, dict[str, UUID], list[UUID]],
) -> None:
    user, tid, pw, _cats, ids = filter_fixture
    token = _login(client, user.email, pw, tid)
    headers = {"Authorization": f"Bearer {token}"}

    r = client.get("/tickets/stats?group_by=state", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["group_by"] == "state"
    assert body["total"] == len(ids)
    by_key = {b["key"]: b["count"] for b in body["results"]}
    assert by_key["open"] == 3
    assert by_key["in_progress"] == 1
    assert by_key["resolved"] == 1
    assert by_key["closed"] == 1


@pytest.mark.asyncio
async def test_stats_group_by_priority_with_filter(
    client: TestClient,
    filter_fixture: tuple[User, UUID, str, dict[str, UUID], list[UUID]],
) -> None:
    user, tid, pw, _cats, _ids = filter_fixture
    token = _login(client, user.email, pw, tid)
    headers = {"Authorization": f"Bearer {token}"}

    # Only OPEN tickets, grouped by priority — 2 high + 1 low
    r = client.get(
        "/tickets/stats?group_by=priority&state=open",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 3
    by_key = {b["key"]: b["count"] for b in body["results"]}
    assert by_key["high"] == 2
    assert by_key["low"] == 1


@pytest.mark.asyncio
async def test_stats_group_by_category_resolves_label(
    client: TestClient,
    filter_fixture: tuple[User, UUID, str, dict[str, UUID], list[UUID]],
) -> None:
    user, tid, pw, _cats, _ids = filter_fixture
    token = _login(client, user.email, pw, tid)
    headers = {"Authorization": f"Bearer {token}"}

    r = client.get("/tickets/stats?group_by=category", headers=headers)
    assert r.status_code == 200
    body = r.json()
    # Both kargo + iade have label_tr seeded by the migration; assert
    # that ``label`` is non-empty (not the UUID stub) for every bucket.
    assert all(b["label"] and len(b["label"]) > 8 for b in body["results"])


@pytest.mark.asyncio
async def test_stats_group_by_assignee_unassigned_bucket(
    client: TestClient,
    filter_fixture: tuple[User, UUID, str, dict[str, UUID], list[UUID]],
) -> None:
    user, tid, pw, _cats, ids = filter_fixture
    token = _login(client, user.email, pw, tid)
    headers = {"Authorization": f"Bearer {token}"}

    r = client.get("/tickets/stats?group_by=assignee", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    # All seeded tickets are unassigned; expect a single "unassigned" bucket.
    assert len(body["results"]) == 1
    assert body["results"][0]["key"] == "unassigned"
    assert body["results"][0]["count"] == len(ids)


# --- RLS isolation on /stats ------------------------------------------------


@pytest_asyncio.fixture
async def two_tenants_with_tickets(
    admin_session: AsyncSession,
) -> AsyncIterator[
    tuple[
        tuple[User, UUID, str],  # tenant A
        tuple[User, UUID, str],  # tenant B
        int,  # B ticket count
    ]
]:
    user_a, tid_a, pw_a = await _seed_tenant_with_user(admin_session)
    user_b, tid_b, pw_b = await _seed_tenant_with_user(admin_session)
    kargo_id = await _pick_kargo_id(admin_session)

    # B has 4 OPEN HIGH tickets, A has 1 RESOLVED LOW
    for i in range(4):
        await _seed_ticket(
            admin_session,
            tenant_id=tid_b,
            category_id=kargo_id,
            title=f"b-{i}",
            state=TicketState.OPEN,
            priority=TicketPriority.HIGH,
        )
    await _seed_ticket(
        admin_session,
        tenant_id=tid_a,
        category_id=kargo_id,
        title="a-only",
        state=TicketState.RESOLVED,
        priority=TicketPriority.LOW,
    )

    yield (user_a, tid_a, pw_a), (user_b, tid_b, pw_b), 4
    await _cleanup(admin_session, user_a.id, tid_a)
    await _cleanup(admin_session, user_b.id, tid_b)


@pytest.mark.asyncio
async def test_stats_does_not_leak_other_tenant_counts(
    client: TestClient,
    two_tenants_with_tickets: tuple[
        tuple[User, UUID, str], tuple[User, UUID, str], int
    ],
) -> None:
    """RLS verification: A's /stats sees only A's tickets (1), not A+B (5)."""
    (user_a, tid_a, pw_a), (_user_b, _tid_b, _pw_b), _b_count = two_tenants_with_tickets
    tok_a = _login(client, user_a.email, pw_a, tid_a)

    r = client.get(
        "/tickets/stats?group_by=state",
        headers={"Authorization": f"Bearer {tok_a}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    assert body["results"] == [{"key": "resolved", "label": "resolved", "count": 1}]


@pytest.mark.asyncio
async def test_list_does_not_leak_other_tenant_rows(
    client: TestClient,
    two_tenants_with_tickets: tuple[
        tuple[User, UUID, str], tuple[User, UUID, str], int
    ],
) -> None:
    """Same RLS check for the list path — independent enforcement of
    the same filter chain shouldn't introduce a leak."""
    (user_a, tid_a, pw_a), (_user_b, _tid_b, _pw_b), _b_count = two_tenants_with_tickets
    tok_a = _login(client, user_a.email, pw_a, tid_a)

    r = client.get(
        "/tickets",
        headers={"Authorization": f"Bearer {tok_a}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["tickets"][0]["title"] == "a-only"


# --- assignee="me" --------------------------------------------------------


@pytest.mark.asyncio
async def test_assignee_me_filter_resolves_to_caller_user(
    client: TestClient,
    admin_session: AsyncSession,
    filter_fixture: tuple[User, UUID, str, dict[str, UUID], list[UUID]],
) -> None:
    """assignee=me should resolve to the caller's user id server-side
    so the frontend doesn't have to cycle through /auth/me first."""
    user, tid, pw, _cats, ids = filter_fixture
    token = _login(client, user.email, pw, tid)
    headers = {"Authorization": f"Bearer {token}"}

    # Assign one ticket to the caller via direct SQL (bypass routes).
    target_id = ids[0]
    async with admin_session.begin():
        await admin_session.execute(
            text("UPDATE tickets SET assigned_to_user_id = :u WHERE id = :id"),
            {"u": str(user.id), "id": str(target_id)},
        )

    r = client.get("/tickets?assignee=me", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["tickets"][0]["id"] == str(target_id)


@pytest.mark.asyncio
async def test_assignee_unassigned_filter(
    client: TestClient,
    filter_fixture: tuple[User, UUID, str, dict[str, UUID], list[UUID]],
) -> None:
    user, tid, pw, _cats, ids = filter_fixture
    token = _login(client, user.email, pw, tid)
    headers = {"Authorization": f"Bearer {token}"}

    r = client.get("/tickets?assignee=unassigned", headers=headers)
    assert r.status_code == 200
    assert r.json()["total"] == len(ids)
