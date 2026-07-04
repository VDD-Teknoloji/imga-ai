"""Integration tests for /tenants/me/analyze + the auto-ticket bridge.

Sprint 7.5.5 / Alt-Faz 3. Covers all five decision branches plus
dedup TTL boundary, RLS isolation, and audit log shape.

The test client uses a real DB but a STUB pipeline so analyze() runs
deterministically and quickly — no BERT load. The stub produces
real ``AnalysisResult`` payloads (NEGATIF/NÖTR/POZITIF based on
trigger keywords; kategoriler keyword classifier üzerinden çalışır).
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
from imga_core import (
    AnalysisPipeline,
    AnalyzerPrediction,
    KeywordCategoryClassifier,
    SentimentAnalyzer,
)
from imga_db import create_engine, create_session_factory, set_current_tenant
from imga_db.models import (
    AuditLog,
    AutomationMode,
    Review,
    ReviewDecision,
    Tenant,
    User,
    UserTenantRole,
)
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from imga_api.dependencies import get_pipeline
from imga_api.main import app
from imga_api.services import (
    AuditService,
    ReviewService,
    TenantConfigService,
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


# --- stub pipeline (deterministic, no BERT) -------------------------------


class _StubAnalyzer(SentimentAnalyzer):
    """Deterministic sentiment: 'kötü' / 'gelmedi' → NEGATIF, 'güzel'
    / 'iyi' → POZITIF, else NÖTR. Keyword detection runs against the
    Turkish-normalized text so casing doesn't matter."""

    def analyze_batch(self, texts: list[str]) -> list[AnalyzerPrediction]:
        from imga_core.text_utils import normalize_turkish

        out: list[AnalyzerPrediction] = []
        for raw in texts:
            t = normalize_turkish(raw)
            if "kötü" in t or "gelmedi" in t or "berbat" in t:
                out.append(AnalyzerPrediction(label="NEGATIF", score=-0.8))
            elif "güzel" in t or "harika" in t or "iyi" in t:
                out.append(AnalyzerPrediction(label="POZITIF", score=0.85))
            else:
                out.append(AnalyzerPrediction(label="NÖTR", score=0.0))
        return out


@pytest.fixture
def stub_pipeline() -> AnalysisPipeline:
    return AnalysisPipeline(
        analyzer=_StubAnalyzer(),
        classifier=KeywordCategoryClassifier(),
    )


# --- DB fixtures ----------------------------------------------------------


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


# --- TestClient with stub pipeline ----------------------------------------


@pytest.fixture
def client(stub_pipeline: AnalysisPipeline) -> Iterator[TestClient]:
    """TestClient with real DB lifespan but stubbed pipeline.

    Lifespan still wires settings + tenant_config_cache; we override
    ``get_pipeline`` so analyze() returns deterministic output without
    loading BERT."""

    @asynccontextmanager
    async def _test_lifespan(application: object) -> AsyncIterator[None]:
        application.state.settings = Settings.from_env()  # type: ignore[attr-defined]
        application.state.tenant_config_cache = TTLCache(  # type: ignore[attr-defined]
            maxsize=1000, ttl=300
        )
        yield

    original_lifespan = app.router.lifespan_context
    app.router.lifespan_context = _test_lifespan
    app.dependency_overrides[get_pipeline] = lambda: stub_pipeline

    for attr in ("admin_db_engine", "app_db_engine",
                 "admin_db_engine_factory", "app_db_engine_factory"):
        if hasattr(app.state, attr):
            delattr(app.state, attr)

    try:
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c
    finally:
        app.dependency_overrides.clear()
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


# --- per-test seeded tenant + admin ---------------------------------------


async def _seed_tenant_with_admin(
    admin_session: AsyncSession,
    *,
    automation_mode: AutomationMode,
) -> tuple[User, UUID, str]:
    """Create a tenant + tenant_admin, set automation_mode, enable
    every global category for the tenant so the keyword classifier's
    output is always a configured category."""
    audit = AuditService(admin_session)
    tsvc = TenantService(admin_session, audit)
    usvc = UserService(admin_session, audit)
    plain = "Test-Password-123!"
    email = f"rev-{uuid4().hex[:8]}@example.com"
    async with admin_session.begin():
        tenant = await tsvc.create(name="Rev Co", slug=f"rev-{uuid4().hex[:8]}")
        # Override automation_mode on the freshly created tenant.
        tenant_obj = await admin_session.get(Tenant, tenant.id)
        assert tenant_obj is not None
        tenant_obj.automation_mode = automation_mode

        user = await usvc.create(email=email, password=plain, full_name="Rev User")
        await usvc.attach_to_tenant(
            user_id=user.id, tenant_id=tenant.id, role=UserTenantRole.TENANT_ADMIN
        )
        return user, tenant.id, plain


async def _cleanup_tenant(
    admin_session: AsyncSession, user_id: UUID, tenant_id: UUID
) -> None:
    async with admin_session.begin():
        # Reviews must be cleared explicitly — CASCADE on tickets sets
        # reviews.ticket_id to NULL but doesn't drop the rows.
        await admin_session.execute(
            text("DELETE FROM reviews WHERE tenant_id = :t"), {"t": str(tenant_id)},
        )
        await admin_session.execute(
            text("DELETE FROM ticket_state_transitions WHERE tenant_id = :t"),
            {"t": str(tenant_id)},
        )
        await admin_session.execute(
            text("DELETE FROM tickets WHERE tenant_id = :t"), {"t": str(tenant_id)},
        )
        await admin_session.execute(
            text("DELETE FROM users WHERE id = :id"), {"id": str(user_id)},
        )
        await admin_session.execute(
            text("DELETE FROM tenants WHERE id = :id"), {"id": str(tenant_id)},
        )


@pytest_asyncio.fixture
async def manual_tenant(
    admin_session: AsyncSession,
) -> AsyncIterator[tuple[User, UUID, str]]:
    user, tid, pw = await _seed_tenant_with_admin(
        admin_session, automation_mode=AutomationMode.MANUAL
    )
    yield user, tid, pw
    await _cleanup_tenant(admin_session, user.id, tid)


@pytest_asyncio.fixture
async def semi_auto_tenant(
    admin_session: AsyncSession,
) -> AsyncIterator[tuple[User, UUID, str]]:
    user, tid, pw = await _seed_tenant_with_admin(
        admin_session, automation_mode=AutomationMode.SEMI_AUTO
    )
    yield user, tid, pw
    await _cleanup_tenant(admin_session, user.id, tid)


@pytest_asyncio.fixture
async def full_auto_tenant(
    admin_session: AsyncSession,
) -> AsyncIterator[tuple[User, UUID, str]]:
    user, tid, pw = await _seed_tenant_with_admin(
        admin_session, automation_mode=AutomationMode.FULL_AUTO
    )
    yield user, tid, pw
    await _cleanup_tenant(admin_session, user.id, tid)


# --- decision branch tests ------------------------------------------------


@pytest.mark.asyncio
async def test_skipped_belirsiz_short_circuits_regardless_of_mode(
    client: TestClient,
    full_auto_tenant: tuple[User, UUID, str],
) -> None:
    """A text the keyword classifier can't categorize lands in
    'belirsiz' and skips the bridge even when full_auto is on."""
    user, tid, pw = full_auto_tenant
    token = _login(client, user.email, pw, tid)
    headers = {"Authorization": f"Bearer {token}"}

    # No kargo / iade / fatura keywords; sentiment is NÖTR.
    r = client.post(
        "/tenants/me/analyze",
        headers=headers,
        json={"text": "Bugün ofise erken geldim, çok yorgunum"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["decision"] == "skipped_belirsiz"
    assert body["ticket_id"] is None
    assert body["analysis"]["categorization"]["primary"] == "belirsiz"


@pytest.mark.asyncio
async def test_skipped_mode_in_manual_tenant(
    client: TestClient,
    manual_tenant: tuple[User, UUID, str],
) -> None:
    """A negative text that would auto-create in full_auto stays skipped
    when the tenant is in manual mode."""
    user, tid, pw = manual_tenant
    token = _login(client, user.email, pw, tid)
    headers = {"Authorization": f"Bearer {token}"}

    r = client.post(
        "/tenants/me/analyze",
        headers=headers,
        json={"text": "Kargom kötü ve 5 gündür gelmedi"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["decision"] == "skipped_mode"
    assert body["ticket_id"] is None


@pytest.mark.asyncio
async def test_skipped_threshold_full_auto_positive_sentiment(
    client: TestClient,
    full_auto_tenant: tuple[User, UUID, str],
) -> None:
    """full_auto only auto-creates when sentiment < 0. A POZITIF text
    with a real category should still skip.

    Choosing a 'pazarlama' (marketing) category text on purpose: most
    of the other categories share keywords with TIER2_ISSUES, which
    would override the BERT score down to negative via the post-BERT
    fallback. Pazarlama keywords like 'kampanya' / 'reklam' don't
    intersect that set, so the positive sentiment survives intact."""
    user, tid, pw = full_auto_tenant
    token = _login(client, user.email, pw, tid)
    headers = {"Authorization": f"Bearer {token}"}

    r = client.post(
        "/tenants/me/analyze",
        headers=headers,
        json={"text": "Kampanya çok güzeldi, harika fırsatlar vardı"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["decision"] == "skipped_threshold"
    assert body["decision_reason"] == "full_auto_non_negative"
    assert body["ticket_id"] is None


@pytest.mark.asyncio
async def test_skipped_threshold_semi_auto_below_threshold(
    client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    """semi_auto needs confidence > 0.7 AND sentiment < -0.5. A NÖTR
    sentiment fails the second check even with high category confidence."""
    user, tid, pw = semi_auto_tenant
    token = _login(client, user.email, pw, tid)
    headers = {"Authorization": f"Bearer {token}"}

    # 'kargo' keyword present, sentiment neutral.
    r = client.post(
        "/tenants/me/analyze",
        headers=headers,
        json={"text": "Kargom geldi"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["decision"] == "skipped_threshold"
    assert body["ticket_id"] is None


@pytest.mark.asyncio
async def test_create_branch_in_full_auto(
    client: TestClient,
    admin_session: AsyncSession,
    full_auto_tenant: tuple[User, UUID, str],
) -> None:
    """full_auto + NEGATIF + non-belirsiz → ticket created."""
    user, tid, pw = full_auto_tenant
    token = _login(client, user.email, pw, tid)
    headers = {"Authorization": f"Bearer {token}"}

    r = client.post(
        "/tenants/me/analyze",
        headers=headers,
        json={"text": "Kargom 5 gündür gelmedi, berbat hizmet"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["decision"] == "create"
    assert body["ticket_id"] is not None

    # Verify the ticket exists and points back to the review id.
    async with admin_session.begin():
        ticket_row = (
            await admin_session.execute(
                text(
                    "SELECT review_id, state, title FROM tickets WHERE id = :id"
                ),
                {"id": body["ticket_id"]},
            )
        ).one()
    assert ticket_row.state == "open"
    assert str(ticket_row.review_id) == body["review_id"]


@pytest.mark.asyncio
async def test_skipped_dedup_within_24h_collapses_to_existing_ticket(
    client: TestClient,
    full_auto_tenant: tuple[User, UUID, str],
) -> None:
    """Same text submitted twice within 24h: first creates, second
    falls into skipped_dedup with the original ticket_id."""
    user, tid, pw = full_auto_tenant
    token = _login(client, user.email, pw, tid)
    headers = {"Authorization": f"Bearer {token}"}

    payload = {"text": "Kargom 5 gündür gelmedi, berbat"}

    first = client.post("/tenants/me/analyze", headers=headers, json=payload).json()
    assert first["decision"] == "create"
    first_ticket_id = first["ticket_id"]
    assert first_ticket_id is not None

    second = client.post("/tenants/me/analyze", headers=headers, json=payload).json()
    assert second["decision"] == "skipped_dedup"
    assert second["ticket_id"] == first_ticket_id
    assert second["review_id"] != first["review_id"]


@pytest.mark.asyncio
async def test_dedup_respects_casing_and_whitespace(
    client: TestClient,
    full_auto_tenant: tuple[User, UUID, str],
) -> None:
    """Same content with different casing / padding still dedups —
    that's the whole point of normalize_turkish-based hashing."""
    user, tid, pw = full_auto_tenant
    token = _login(client, user.email, pw, tid)
    headers = {"Authorization": f"Bearer {token}"}

    first = client.post(
        "/tenants/me/analyze",
        headers=headers,
        json={"text": "kargom kötü 5 gündür gelmedi"},
    ).json()
    assert first["decision"] == "create"

    # KARGOM with leading whitespace and Turkish capital İ.
    second = client.post(
        "/tenants/me/analyze",
        headers=headers,
        json={"text": "  KARGOM KÖTÜ 5 GÜNDÜR GELMEDİ  "},
    ).json()
    assert second["decision"] == "skipped_dedup"
    assert second["ticket_id"] == first["ticket_id"]


@pytest.mark.asyncio
async def test_dedup_window_lapsed_creates_new_ticket(
    admin_session: AsyncSession,
    full_auto_tenant: tuple[User, UUID, str],
    stub_pipeline: AnalysisPipeline,
) -> None:
    """Beyond 24h the second submission should mint a fresh ticket.

    We exercise this at the service layer so we can pass an explicit
    ``now`` rather than messing with system clock — same as the
    auto-close worker tests do."""
    user, tid, _pw = full_auto_tenant
    cache: TTLCache[UUID, dict[str, object]] = TTLCache(maxsize=10, ttl=300)

    # Build the service stack manually against an app-role session so
    # RLS engages properly.
    app_engine = create_engine("app")
    app_factory = create_session_factory(app_engine)
    try:
        async with app_factory() as app_session:
            audit = AuditService(app_session)
            tickets = TicketService(app_session, audit)
            config = TenantConfigService(app_session, audit, cache)
            reviews = ReviewService(app_session, audit, tickets, config)

            async with app_session.begin():
                await set_current_tenant(app_session, tid)
                analysis = stub_pipeline.analyze("Kargom 5 gündür gelmedi berbat")

                day_zero = datetime.now(UTC) - timedelta(days=2)
                first = await reviews.record_and_decide(
                    tenant_id=tid,
                    text="Kargom 5 gündür gelmedi berbat",
                    analysis=analysis,
                    actor_user_id=user.id,
                    now=day_zero,
                )
                assert first.decision == ReviewDecision.CREATE

                # 25 hours later — outside dedup window.
                later = day_zero + timedelta(hours=25)
                second = await reviews.record_and_decide(
                    tenant_id=tid,
                    text="Kargom 5 gündür gelmedi berbat",
                    analysis=analysis,
                    actor_user_id=user.id,
                    now=later,
                )
                assert second.decision == ReviewDecision.CREATE
                assert second.ticket_id != first.ticket_id
    finally:
        await app_engine.dispose()


@pytest.mark.asyncio
async def test_audit_log_shape_for_review_analyzed(
    client: TestClient,
    admin_session: AsyncSession,
    full_auto_tenant: tuple[User, UUID, str],
) -> None:
    """audit_logs row exists for every analyze call with the expected
    {decision, review_id, ticket_id} payload."""
    user, tid, pw = full_auto_tenant
    token = _login(client, user.email, pw, tid)
    headers = {"Authorization": f"Bearer {token}"}

    r = client.post(
        "/tenants/me/analyze",
        headers=headers,
        json={"text": "Kargom 5 gündür gelmedi berbat"},
    ).json()
    assert r["decision"] == "create"

    async with admin_session.begin():
        row = (
            await admin_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "review.analyzed",
                    AuditLog.tenant_id == tid,
                )
            )
        ).scalar_one()
    assert row.details["decision"] == "create"
    assert row.details["review_id"] == r["review_id"]
    assert row.details["ticket_id"] == r["ticket_id"]


# --- RLS isolation --------------------------------------------------------


@pytest.mark.asyncio
async def test_rls_hides_other_tenant_reviews(
    admin_session: AsyncSession,
    full_auto_tenant: tuple[User, UUID, str],
    stub_pipeline: AnalysisPipeline,
) -> None:
    """Tenant B cannot SELECT tenant A's reviews even when A has
    successfully created tickets. Verifies the migration's RLS+FORCE
    policy is enforced for the new table."""
    user_a, tid_a, _pw_a = full_auto_tenant

    # Create a second tenant via direct seed.
    audit = AuditService(admin_session)
    tsvc = TenantService(admin_session, audit)
    usvc = UserService(admin_session, audit)
    pw_b = "Bee-Pwd-123!"
    async with admin_session.begin():
        tenant_b = await tsvc.create(name="B Co", slug=f"b-{uuid4().hex[:8]}")
        b_obj = await admin_session.get(Tenant, tenant_b.id)
        assert b_obj is not None
        b_obj.automation_mode = AutomationMode.FULL_AUTO
        user_b = await usvc.create(
            email=f"b-{uuid4().hex[:6]}@example.com",
            password=pw_b,
            full_name="B Admin",
        )
        await usvc.attach_to_tenant(
            user_id=user_b.id, tenant_id=tenant_b.id, role=UserTenantRole.TENANT_ADMIN
        )

    try:
        # Tenant A creates a review via the service stack.
        cache: TTLCache[UUID, dict[str, object]] = TTLCache(maxsize=10, ttl=300)
        app_engine = create_engine("app")
        app_factory = create_session_factory(app_engine)
        try:
            async with app_factory() as app_session:
                audit_a = AuditService(app_session)
                tickets_a = TicketService(app_session, audit_a)
                config_a = TenantConfigService(app_session, audit_a, cache)
                rsvc_a = ReviewService(app_session, audit_a, tickets_a, config_a)
                async with app_session.begin():
                    await set_current_tenant(app_session, tid_a)
                    analysis = stub_pipeline.analyze(
                        "Kargom 5 gündür gelmedi berbat"
                    )
                    a_result = await rsvc_a.record_and_decide(
                        tenant_id=tid_a,
                        text="Kargom 5 gündür gelmedi berbat",
                        analysis=analysis,
                        actor_user_id=user_a.id,
                    )
                    assert a_result.decision == ReviewDecision.CREATE

                # Now bind to tenant B and verify SELECT returns nothing.
                async with app_session.begin():
                    await set_current_tenant(app_session, tenant_b.id)
                    visible = (
                        await app_session.execute(select(Review))
                    ).scalars().all()
                    assert len(visible) == 0
        finally:
            await app_engine.dispose()
    finally:
        async with admin_session.begin():
            await admin_session.execute(
                text("DELETE FROM users WHERE id = :id"),
                {"id": str(user_b.id)},
            )
            await admin_session.execute(
                text("DELETE FROM tenants WHERE id = :id"),
                {"id": str(tenant_b.id)},
            )

