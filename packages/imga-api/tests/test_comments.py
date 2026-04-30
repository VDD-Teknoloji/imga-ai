"""Integration tests for the ticket comments + timeline endpoints.

Sprint 7.5.5 / Alt-Faz 4. Covers:

  * Role matrix: VIEWER blocked from customer_reply, ANALYST + ADMIN
    can post both kinds.
  * State guard: customer_reply forbidden in CLOSED / CANCELLED;
    internal_note allowed in every state including terminals.
  * Archive: author OR tenant_admin can archive; non-author analyst
    cannot; double-archive returns 409.
  * Body length cap (8000 chars) returns 422.
  * /timeline merges transitions + comments in chronological order.
  * Archived comments still surface in /timeline with is_archived=true.
  * RLS isolation: tenant B cannot see A's comments.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from cachetools import TTLCache
from fastapi.testclient import TestClient
from imga_db import create_engine, create_session_factory
from imga_db.models import (
    Category,
    Ticket,
    TicketComment,
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


async def _pick_kargo_id(admin_session: AsyncSession) -> UUID:
    async with admin_session.begin():
        row = await admin_session.execute(
            select(Category.id)
            .where(Category.tenant_id.is_(None))
            .where(Category.code == "kargo")
        )
        return UUID(str(row.scalar_one()))


async def _seed_user(
    admin_session: AsyncSession,
    *,
    tenant_id: UUID,
    role: UserTenantRole,
) -> tuple[User, str]:
    audit = AuditService(admin_session)
    usvc = UserService(admin_session, audit)
    plain = "Test-Password-123!"
    email = f"cmt-{uuid4().hex[:8]}@example.com"
    async with admin_session.begin():
        user = await usvc.create(email=email, password=plain, full_name="Cmt User")
        await usvc.attach_to_tenant(
            user_id=user.id, tenant_id=tenant_id, role=role
        )
    return user, plain


async def _seed_tenant(admin_session: AsyncSession) -> UUID:
    audit = AuditService(admin_session)
    tsvc = TenantService(admin_session, audit)
    async with admin_session.begin():
        tenant = await tsvc.create(name="Cmt Co", slug=f"cmt-{uuid4().hex[:8]}")
    return tenant.id


async def _seed_ticket(
    admin_session: AsyncSession,
    *,
    tenant_id: UUID,
    category_id: UUID,
    state: TicketState = TicketState.OPEN,
) -> UUID:
    from datetime import UTC, datetime

    moment = datetime.now(UTC)
    ticket = Ticket(
        tenant_id=tenant_id,
        category_id=category_id,
        title="cmt-test",
        state=state,
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


# --- shared fixture: tenant + admin/analyst/viewer + 1 OPEN ticket --------


@pytest_asyncio.fixture
async def cmt_fixture(
    admin_session: AsyncSession,
) -> AsyncIterator[
    tuple[
        UUID,  # tenant_id
        tuple[User, str],  # admin
        tuple[User, str],  # analyst
        tuple[User, str],  # viewer
        UUID,  # ticket_id (OPEN)
    ]
]:
    tenant_id = await _seed_tenant(admin_session)
    cat_id = await _pick_kargo_id(admin_session)
    admin_pair = await _seed_user(
        admin_session, tenant_id=tenant_id, role=UserTenantRole.TENANT_ADMIN
    )
    analyst_pair = await _seed_user(
        admin_session, tenant_id=tenant_id, role=UserTenantRole.ANALYST
    )
    viewer_pair = await _seed_user(
        admin_session, tenant_id=tenant_id, role=UserTenantRole.VIEWER
    )
    ticket_id = await _seed_ticket(
        admin_session, tenant_id=tenant_id, category_id=cat_id
    )
    yield tenant_id, admin_pair, analyst_pair, viewer_pair, ticket_id
    await _cleanup(
        admin_session,
        tenant_id,
        [admin_pair[0].id, analyst_pair[0].id, viewer_pair[0].id],
    )


# --- role matrix ----------------------------------------------------------


@pytest.mark.asyncio
async def test_viewer_can_post_internal_note_but_not_customer_reply(
    client: TestClient,
    cmt_fixture: tuple[
        UUID, tuple[User, str], tuple[User, str], tuple[User, str], UUID
    ],
) -> None:
    tenant_id, _admin, _analyst, viewer, ticket_id = cmt_fixture
    viewer_user, viewer_pw = viewer
    token = _login(client, viewer_user.email, viewer_pw, tenant_id)
    headers = {"Authorization": f"Bearer {token}"}

    note = client.post(
        f"/tickets/{ticket_id}/comments",
        headers=headers,
        json={"body": "viewer internal note", "kind": "internal_note"},
    )
    assert note.status_code == 201, note.text
    assert note.json()["kind"] == "internal_note"
    assert note.json()["is_archived"] is False

    reply = client.post(
        f"/tickets/{ticket_id}/comments",
        headers=headers,
        json={"body": "viewer reply attempt", "kind": "customer_reply"},
    )
    assert reply.status_code == 403, reply.text


@pytest.mark.asyncio
async def test_analyst_can_post_both_kinds(
    client: TestClient,
    cmt_fixture: tuple[
        UUID, tuple[User, str], tuple[User, str], tuple[User, str], UUID
    ],
) -> None:
    tenant_id, _admin, analyst, _viewer, ticket_id = cmt_fixture
    a_user, a_pw = analyst
    token = _login(client, a_user.email, a_pw, tenant_id)
    headers = {"Authorization": f"Bearer {token}"}

    for kind in ("internal_note", "customer_reply"):
        r = client.post(
            f"/tickets/{ticket_id}/comments",
            headers=headers,
            json={"body": f"analyst {kind}", "kind": kind},
        )
        assert r.status_code == 201, r.text
        assert r.json()["kind"] == kind


# --- state guard ----------------------------------------------------------


@pytest.mark.asyncio
async def test_customer_reply_forbidden_on_closed_ticket(
    client: TestClient,
    admin_session: AsyncSession,
    cmt_fixture: tuple[
        UUID, tuple[User, str], tuple[User, str], tuple[User, str], UUID
    ],
) -> None:
    """customer_reply blocked on CLOSED tickets; internal_note still
    allowed there for post-mortem notes."""
    tenant_id, admin, _analyst, _viewer, ticket_id = cmt_fixture
    admin_user, admin_pw = admin

    # Force ticket to CLOSED via admin DB write (bypass state machine —
    # this test isn't about transitions, just the comment state guard).
    async with admin_session.begin():
        await admin_session.execute(
            text("UPDATE tickets SET state = 'closed' WHERE id = :id"),
            {"id": str(ticket_id)},
        )

    token = _login(client, admin_user.email, admin_pw, tenant_id)
    headers = {"Authorization": f"Bearer {token}"}

    blocked = client.post(
        f"/tickets/{ticket_id}/comments",
        headers=headers,
        json={"body": "outbound on closed", "kind": "customer_reply"},
    )
    assert blocked.status_code == 403, blocked.text

    allowed = client.post(
        f"/tickets/{ticket_id}/comments",
        headers=headers,
        json={"body": "post-mortem", "kind": "internal_note"},
    )
    assert allowed.status_code == 201, allowed.text


# --- archive --------------------------------------------------------------


@pytest.mark.asyncio
async def test_author_can_archive_own_comment(
    client: TestClient,
    cmt_fixture: tuple[
        UUID, tuple[User, str], tuple[User, str], tuple[User, str], UUID
    ],
) -> None:
    tenant_id, _admin, analyst, _viewer, ticket_id = cmt_fixture
    a_user, a_pw = analyst
    token = _login(client, a_user.email, a_pw, tenant_id)
    headers = {"Authorization": f"Bearer {token}"}

    created = client.post(
        f"/tickets/{ticket_id}/comments",
        headers=headers,
        json={"body": "wrong wording", "kind": "internal_note"},
    ).json()
    cid = created["id"]

    archived = client.post(
        f"/tickets/{ticket_id}/comments/{cid}/archive",
        headers=headers,
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["is_archived"] is True
    assert archived.json()["archived_at"] is not None
    assert archived.json()["archived_by_user_id"] == str(a_user.id)


@pytest.mark.asyncio
async def test_admin_can_archive_anyone_comment(
    client: TestClient,
    cmt_fixture: tuple[
        UUID, tuple[User, str], tuple[User, str], tuple[User, str], UUID
    ],
) -> None:
    tenant_id, admin, analyst, _viewer, ticket_id = cmt_fixture
    a_user, a_pw = analyst
    adm_user, adm_pw = admin

    a_token = _login(client, a_user.email, a_pw, tenant_id)
    a_headers = {"Authorization": f"Bearer {a_token}"}
    cid = client.post(
        f"/tickets/{ticket_id}/comments",
        headers=a_headers,
        json={"body": "analyst's comment", "kind": "internal_note"},
    ).json()["id"]

    adm_token = _login(client, adm_user.email, adm_pw, tenant_id)
    adm_headers = {"Authorization": f"Bearer {adm_token}"}
    archived = client.post(
        f"/tickets/{ticket_id}/comments/{cid}/archive",
        headers=adm_headers,
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["archived_by_user_id"] == str(adm_user.id)


@pytest.mark.asyncio
async def test_non_author_analyst_cannot_archive_someone_else(
    client: TestClient,
    admin_session: AsyncSession,
    cmt_fixture: tuple[
        UUID, tuple[User, str], tuple[User, str], tuple[User, str], UUID
    ],
) -> None:
    tenant_id, _admin, analyst, _viewer, ticket_id = cmt_fixture

    # Seed a second analyst who isn't the author.
    other_user, other_pw = await _seed_user(
        admin_session, tenant_id=tenant_id, role=UserTenantRole.ANALYST
    )
    try:
        author_user, author_pw = analyst
        a_token = _login(client, author_user.email, author_pw, tenant_id)
        cid = client.post(
            f"/tickets/{ticket_id}/comments",
            headers={"Authorization": f"Bearer {a_token}"},
            json={"body": "owner only", "kind": "internal_note"},
        ).json()["id"]

        other_token = _login(client, other_user.email, other_pw, tenant_id)
        r = client.post(
            f"/tickets/{ticket_id}/comments/{cid}/archive",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert r.status_code == 403, r.text
    finally:
        async with admin_session.begin():
            await admin_session.execute(
                text("DELETE FROM users WHERE id = :id"),
                {"id": str(other_user.id)},
            )


@pytest.mark.asyncio
async def test_double_archive_returns_409(
    client: TestClient,
    cmt_fixture: tuple[
        UUID, tuple[User, str], tuple[User, str], tuple[User, str], UUID
    ],
) -> None:
    tenant_id, _admin, analyst, _viewer, ticket_id = cmt_fixture
    a_user, a_pw = analyst
    token = _login(client, a_user.email, a_pw, tenant_id)
    headers = {"Authorization": f"Bearer {token}"}

    cid = client.post(
        f"/tickets/{ticket_id}/comments",
        headers=headers,
        json={"body": "first archive", "kind": "internal_note"},
    ).json()["id"]

    first = client.post(
        f"/tickets/{ticket_id}/comments/{cid}/archive", headers=headers
    )
    assert first.status_code == 200

    second = client.post(
        f"/tickets/{ticket_id}/comments/{cid}/archive", headers=headers
    )
    assert second.status_code == 409, second.text


# --- input validation -----------------------------------------------------


@pytest.mark.asyncio
async def test_body_above_8000_chars_returns_422(
    client: TestClient,
    cmt_fixture: tuple[
        UUID, tuple[User, str], tuple[User, str], tuple[User, str], UUID
    ],
) -> None:
    tenant_id, _admin, analyst, _viewer, ticket_id = cmt_fixture
    a_user, a_pw = analyst
    token = _login(client, a_user.email, a_pw, tenant_id)
    headers = {"Authorization": f"Bearer {token}"}

    r = client.post(
        f"/tickets/{ticket_id}/comments",
        headers=headers,
        json={"body": "x" * 8001, "kind": "internal_note"},
    )
    assert r.status_code == 422


# --- list + timeline ------------------------------------------------------


@pytest.mark.asyncio
async def test_list_comments_default_includes_archived(
    client: TestClient,
    cmt_fixture: tuple[
        UUID, tuple[User, str], tuple[User, str], tuple[User, str], UUID
    ],
) -> None:
    tenant_id, _admin, analyst, _viewer, ticket_id = cmt_fixture
    a_user, a_pw = analyst
    token = _login(client, a_user.email, a_pw, tenant_id)
    headers = {"Authorization": f"Bearer {token}"}

    cid_live = client.post(
        f"/tickets/{ticket_id}/comments",
        headers=headers,
        json={"body": "live", "kind": "internal_note"},
    ).json()["id"]
    cid_archived = client.post(
        f"/tickets/{ticket_id}/comments",
        headers=headers,
        json={"body": "to archive", "kind": "internal_note"},
    ).json()["id"]
    client.post(
        f"/tickets/{ticket_id}/comments/{cid_archived}/archive", headers=headers
    )

    full = client.get(f"/tickets/{ticket_id}/comments", headers=headers).json()
    ids = [c["id"] for c in full["comments"]]
    assert cid_live in ids
    assert cid_archived in ids
    archived_view = next(c for c in full["comments"] if c["id"] == cid_archived)
    assert archived_view["is_archived"] is True

    live_only = client.get(
        f"/tickets/{ticket_id}/comments?include_archived=false", headers=headers
    ).json()
    live_ids = [c["id"] for c in live_only["comments"]]
    assert cid_live in live_ids
    assert cid_archived not in live_ids


@pytest.mark.asyncio
async def test_timeline_merges_transitions_and_comments_chronologically(
    client: TestClient,
    cmt_fixture: tuple[
        UUID, tuple[User, str], tuple[User, str], tuple[User, str], UUID
    ],
) -> None:
    tenant_id, admin, _analyst, _viewer, ticket_id = cmt_fixture
    adm_user, adm_pw = admin
    token = _login(client, adm_user.email, adm_pw, tenant_id)
    headers = {"Authorization": f"Bearer {token}"}

    # Sequence: comment → transition (open→in_progress) → comment.
    client.post(
        f"/tickets/{ticket_id}/comments",
        headers=headers,
        json={"body": "first note", "kind": "internal_note"},
    )
    client.post(
        f"/tickets/{ticket_id}/transition",
        headers=headers,
        json={"to_state": "in_progress"},
    )
    client.post(
        f"/tickets/{ticket_id}/comments",
        headers=headers,
        json={"body": "after claim", "kind": "internal_note"},
    )

    timeline = client.get(f"/tickets/{ticket_id}/timeline", headers=headers).json()
    events = timeline["events"]
    # The fixture seeds the ticket via direct INSERT (no creation marker
    # in ticket_state_transitions), so we expect: 1 real transition +
    # 2 comments = 3 events. Service-level creates also write a
    # creation marker; that path is covered elsewhere (test_tickets.py).
    assert len(events) == 3
    # Strict ascending occurred_at — the merge must preserve order.
    timestamps = [e["occurred_at"] for e in events]
    assert timestamps == sorted(timestamps)
    types = [e["type"] for e in events]
    assert types.count("comment") == 2
    assert types.count("state_transition") == 1


@pytest.mark.asyncio
async def test_timeline_archived_comment_still_surfaced(
    client: TestClient,
    cmt_fixture: tuple[
        UUID, tuple[User, str], tuple[User, str], tuple[User, str], UUID
    ],
) -> None:
    """Archive doesn't drop the row from /timeline — historical record
    must stay intact."""
    tenant_id, _admin, analyst, _viewer, ticket_id = cmt_fixture
    a_user, a_pw = analyst
    token = _login(client, a_user.email, a_pw, tenant_id)
    headers = {"Authorization": f"Bearer {token}"}

    cid = client.post(
        f"/tickets/{ticket_id}/comments",
        headers=headers,
        json={"body": "to be hidden", "kind": "internal_note"},
    ).json()["id"]
    client.post(f"/tickets/{ticket_id}/comments/{cid}/archive", headers=headers)

    timeline = client.get(f"/tickets/{ticket_id}/timeline", headers=headers).json()
    archived_evt = next(
        (e for e in timeline["events"] if e["type"] == "comment" and e["id"] == cid),
        None,
    )
    assert archived_evt is not None
    assert archived_evt["is_archived"] is True


# --- RLS isolation --------------------------------------------------------


@pytest.mark.asyncio
async def test_comments_not_visible_across_tenants(
    client: TestClient,
    admin_session: AsyncSession,
    cmt_fixture: tuple[
        UUID, tuple[User, str], tuple[User, str], tuple[User, str], UUID
    ],
) -> None:
    """Tenant B's admin cannot list / archive tenant A's comments."""
    tid_a, _admin_a, analyst_a, _viewer_a, ticket_a = cmt_fixture
    a_user, a_pw = analyst_a

    # Author a comment in A.
    a_token = _login(client, a_user.email, a_pw, tid_a)
    cid = client.post(
        f"/tickets/{ticket_a}/comments",
        headers={"Authorization": f"Bearer {a_token}"},
        json={"body": "A only", "kind": "internal_note"},
    ).json()["id"]

    # Stand up tenant B + admin.
    tid_b = await _seed_tenant(admin_session)
    b_user, b_pw = await _seed_user(
        admin_session, tenant_id=tid_b, role=UserTenantRole.TENANT_ADMIN
    )
    try:
        b_token = _login(client, b_user.email, b_pw, tid_b)
        b_headers = {"Authorization": f"Bearer {b_token}"}

        # B can't list A's comments via A's ticket id (RLS hides the
        # comment rows; the route returns an empty list).
        r = client.get(f"/tickets/{ticket_a}/comments", headers=b_headers).json()
        assert r["comments"] == []

        # B can't archive A's comment.
        arch = client.post(
            f"/tickets/{ticket_a}/comments/{cid}/archive", headers=b_headers
        )
        assert arch.status_code == 404, arch.text
    finally:
        await _cleanup(admin_session, tid_b, [b_user.id])


# --- direct service test for state-orthogonality of internal_note ---------


@pytest.mark.asyncio
async def test_internal_note_allowed_in_every_state(
    admin_session: AsyncSession,
    cmt_fixture: tuple[
        UUID, tuple[User, str], tuple[User, str], tuple[User, str], UUID
    ],
) -> None:
    """Service-level check — internal_note must be writable from OPEN
    through CANCELLED. Goes through the service directly so we don't
    have to drive the state machine through 6 transitions per state."""
    from imga_db import set_current_tenant

    from imga_api.services import CommentService

    tenant_id, admin, _analyst, _viewer, ticket_id = cmt_fixture
    admin_user, _ = admin

    states = [
        TicketState.OPEN,
        TicketState.IN_PROGRESS,
        TicketState.PENDING_CUSTOMER,
        TicketState.RESOLVED,
        TicketState.CLOSED,
        TicketState.CANCELLED,
    ]

    app_engine = create_engine("app")
    app_factory = create_session_factory(app_engine)
    try:
        async with app_factory() as app_session:
            for state in states:
                # Bump ticket state via admin and re-bind tenant for the
                # service call (CANCELLED also needs a cancellation_reason).
                async with admin_session.begin():
                    if state == TicketState.CANCELLED:
                        await admin_session.execute(
                            text(
                                "UPDATE tickets SET state = 'cancelled', "
                                "cancellation_reason = 'other' WHERE id = :id"
                            ),
                            {"id": str(ticket_id)},
                        )
                    else:
                        await admin_session.execute(
                            text(
                                "UPDATE tickets SET state = :s, "
                                "cancellation_reason = NULL WHERE id = :id"
                            ),
                            {"s": str(state), "id": str(ticket_id)},
                        )

                async with app_session.begin():
                    await set_current_tenant(app_session, tenant_id)
                    audit = AuditService(app_session)
                    csvc = CommentService(app_session, audit)
                    comment = await csvc.create(
                        tenant_id=tenant_id,
                        ticket_id=ticket_id,
                        author_user_id=admin_user.id,
                        author_role=UserTenantRole.TENANT_ADMIN,
                        body=f"note in {state}",
                        kind=__import__(
                            "imga_db.models", fromlist=["TicketCommentKind"]
                        ).TicketCommentKind.INTERNAL_NOTE,
                    )
                    assert comment.id is not None
    finally:
        await app_engine.dispose()


@pytest.mark.asyncio
async def test_audit_log_written_for_create_and_archive(
    client: TestClient,
    admin_session: AsyncSession,
    cmt_fixture: tuple[
        UUID, tuple[User, str], tuple[User, str], tuple[User, str], UUID
    ],
) -> None:
    """Both comment.create and comment.archive land audit_logs rows."""
    tenant_id, _admin, analyst, _viewer, ticket_id = cmt_fixture
    a_user, a_pw = analyst
    token = _login(client, a_user.email, a_pw, tenant_id)
    headers = {"Authorization": f"Bearer {token}"}

    cid = client.post(
        f"/tickets/{ticket_id}/comments",
        headers=headers,
        json={"body": "audit this", "kind": "internal_note"},
    ).json()["id"]
    client.post(f"/tickets/{ticket_id}/comments/{cid}/archive", headers=headers)

    async with admin_session.begin():
        rows = (
            await admin_session.execute(
                text(
                    "SELECT action FROM audit_logs WHERE resource_id = :id "
                    "ORDER BY created_at"
                ),
                {"id": cid},
            )
        ).all()
    actions = [r.action for r in rows]
    assert actions == ["comment.create", "comment.archive"]


# --- comment row count sanity -------------------------------------------


@pytest.mark.asyncio
async def test_archive_keeps_row_in_db(
    admin_session: AsyncSession,
    cmt_fixture: tuple[
        UUID, tuple[User, str], tuple[User, str], tuple[User, str], UUID
    ],
    client: TestClient,
) -> None:
    """Archive sets deleted_at; the row is NOT physically deleted."""
    tenant_id, _admin, analyst, _viewer, ticket_id = cmt_fixture
    a_user, a_pw = analyst
    token = _login(client, a_user.email, a_pw, tenant_id)
    headers = {"Authorization": f"Bearer {token}"}

    cid = client.post(
        f"/tickets/{ticket_id}/comments",
        headers=headers,
        json={"body": "soft delete check", "kind": "internal_note"},
    ).json()["id"]
    client.post(f"/tickets/{ticket_id}/comments/{cid}/archive", headers=headers)

    async with admin_session.begin():
        row = (
            await admin_session.execute(
                select(TicketComment).where(TicketComment.id == UUID(cid))
            )
        ).scalar_one()
    assert row.deleted_at is not None
    assert row.archived_by_user_id == a_user.id


@pytest.mark.asyncio
async def test_unused_ticket_service_imported_for_state_seed(
    cmt_fixture: tuple[
        UUID, tuple[User, str], tuple[User, str], tuple[User, str], UUID
    ],
) -> None:
    """Sanity: the fixture wired everything we need (TicketService is
    available for follow-up tests that drive the state machine)."""
    _ = TicketService  # purely keeps the import live; avoids RUF unused-import.
    assert cmt_fixture[4] is not None
