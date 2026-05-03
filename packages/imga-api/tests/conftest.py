"""Shared fixtures: classic stubbed-pipeline ``client`` for unit-style tests
plus ``e2e_client`` / ``e2e_seed`` for the Sprint-7 consolidation E2E run.

The two clients deliberately don't share a name. test_endpoints.py uses the
classic stubbed ``client``; the per-feature integration tests
(test_auth, test_tenant_config, test_tickets) define their own local
``client`` fixtures with full DB engines. The E2E flow uses ``e2e_client``
+ ``e2e_seed`` from this file.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from cachetools import TTLCache
from fastapi import FastAPI
from fastapi.testclient import TestClient
from imga_core import (
    AnalysisPipeline,
    AnalyzerPrediction,
    KeywordCategoryClassifier,
    SentimentAnalyzer,
)
from imga_db import create_engine, create_session_factory
from imga_db.models import UserTenantRole
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.dependencies import get_classifier, get_pipeline, get_settings
from imga_api.main import app
from imga_api.services import AuditService, TenantService, UserService
from imga_api.settings import Settings


class StubAnalyzer(SentimentAnalyzer):
    """Deterministic analyzer: positive on 'iyi'/'güzel', negative on 'kötü', else neutral."""

    def __init__(self) -> None:
        self.calls = 0

    def analyze_batch(self, texts: list[str]) -> list[AnalyzerPrediction]:
        self.calls += 1
        out: list[AnalyzerPrediction] = []
        for t in texts:
            low = t.lower()
            if "iyi" in low or "güzel" in low:
                out.append(AnalyzerPrediction(label="POZITIF", score=0.85))
            elif "kötü" in low:
                out.append(AnalyzerPrediction(label="NEGATIF", score=-0.7))
            else:
                out.append(AnalyzerPrediction(label="NÖTR", score=0.0))
        return out


@pytest.fixture
def stub_classifier() -> KeywordCategoryClassifier:
    """Real keyword classifier — no LLM, fully deterministic for tests."""
    return KeywordCategoryClassifier()


@pytest.fixture
def stub_pipeline(stub_classifier: KeywordCategoryClassifier) -> AnalysisPipeline:
    return AnalysisPipeline(
        analyzer=StubAnalyzer(),
        classifier=stub_classifier,
    )


@pytest.fixture
def client(
    stub_pipeline: AnalysisPipeline,
    stub_classifier: KeywordCategoryClassifier,
) -> Iterator[TestClient]:
    """TestClient with dependencies overridden — lifespan not triggered."""
    settings = Settings()  # defaults, no env reads
    app.dependency_overrides[get_pipeline] = lambda: stub_pipeline
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_classifier] = lambda: stub_classifier
    try:
        c = TestClient(app)
        yield c
    finally:
        app.dependency_overrides.clear()


# --- E2E test fixtures (Sprint 7.6 öncesi konsolidasyon) -----------------


_HOST = os.environ.get("IMGA_TEST_PG_HOST", "localhost")
_PORT = os.environ.get("IMGA_POSTGRES_PORT", "5433")
_ADMIN_URL = (
    f"postgresql+asyncpg://imga_admin:imga_admin_password@{_HOST}:{_PORT}/imga"
)
_APP_URL = f"postgresql+asyncpg://imga_app:imga_app_password@{_HOST}:{_PORT}/imga"
_OWNER_URL = (
    f"postgresql+asyncpg://imga_owner:imga_dev_password@{_HOST}:{_PORT}/imga"
)


@dataclass(frozen=True, slots=True)
class SeededUser:
    """Pre-seeded user the test logs in as via the real /auth/login flow.

    Plaintext password is kept on the dataclass because UserService.create
    hashed it with argon2 — the test still goes through verify_password,
    not a shortcut that bypasses the security path.
    """

    user_id: UUID
    email: str
    password: str


@dataclass(frozen=True, slots=True)
class E2ESeed:
    """Starting state for the E2E flow test."""

    acme_tenant_id: UUID
    beta_tenant_id: UUID
    alice: SeededUser  # tenant_admin in Acme
    bob: SeededUser    # analyst in Acme + viewer in Beta


@pytest.fixture
def _e2e_env() -> None:
    """Wire DB URLs + a stable JWT secret. Activated only by tests that
    depend on it (e2e_client / e2e_seed) so test_endpoints.py is not
    perturbed."""
    os.environ["DATABASE_URL"] = _APP_URL
    os.environ["DATABASE_URL_ADMIN"] = _ADMIN_URL
    os.environ["DATABASE_URL_OWNER"] = _OWNER_URL
    os.environ["JWT_SECRET_KEY"] = "test-secret-key-32-bytes-min-padding-xyz"


@pytest.fixture
def e2e_client(_e2e_env: None) -> Iterator[TestClient]:
    """TestClient that skips BERT loading but still wires settings +
    tenant_config_cache on app.state. Same trick as the per-file
    ``client`` fixtures elsewhere; named distinctly to avoid collision."""

    @asynccontextmanager
    async def _test_lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.settings = Settings.from_env()
        application.state.tenant_config_cache = TTLCache(maxsize=1000, ttl=300)
        yield

    original = app.router.lifespan_context
    app.router.lifespan_context = _test_lifespan

    for attr in (
        "admin_db_engine",
        "app_db_engine",
        "admin_db_engine_factory",
        "app_db_engine_factory",
    ):
        if hasattr(app.state, attr):
            delattr(app.state, attr)

    try:
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c
    finally:
        app.router.lifespan_context = original
        for attr in (
            "admin_db_engine",
            "app_db_engine",
            "admin_db_engine_factory",
            "app_db_engine_factory",
            "tenant_config_cache",
        ):
            if hasattr(app.state, attr):
                delattr(app.state, attr)


@pytest_asyncio.fixture
async def e2e_seed(_e2e_env: None) -> AsyncIterator[E2ESeed]:
    """Seed two tenants + two users + three role bindings.

    Why direct DB seeding: the invitation HTTP routes and the
    super-admin tenant-create route are not yet shipped — they live
    in the Sprint 7.5.5 backlog (see docs/sprint-8-backlog.md). The
    fixture sets up the bare minimum so the test can exercise the
    parts that DO ship. TenantService.create handles the eight-global
    category seed for each tenant on insert; the test then exercises
    automation_mode toggle, custom-category creation, etc. through
    the API.
    """
    engine = create_engine("admin")
    factory = create_session_factory(engine)

    alice_pw = "Alice-Secure-Pwd-123!"
    bob_pw = "Bob-Secure-Pwd-456!"

    async with factory() as session:
        audit = AuditService(session)
        tsvc = TenantService(session, audit)
        usvc = UserService(session, audit)

        async with session.begin():
            acme = await tsvc.create(
                name="Acme Inc.", slug=f"acme-{uuid4().hex[:8]}"
            )
            beta = await tsvc.create(
                name="Beta Co.", slug=f"beta-{uuid4().hex[:8]}"
            )

            alice_user = await usvc.create(
                email=f"alice-{uuid4().hex[:6]}@example.com",
                password=alice_pw,
                full_name="Alice Admin",
            )
            bob_user = await usvc.create(
                email=f"bob-{uuid4().hex[:6]}@example.com",
                password=bob_pw,
                full_name="Bob Analyst",
            )

            await usvc.attach_to_tenant(
                user_id=alice_user.id,
                tenant_id=acme.id,
                role=UserTenantRole.TENANT_ADMIN,
            )
            await usvc.attach_to_tenant(
                user_id=bob_user.id,
                tenant_id=acme.id,
                role=UserTenantRole.ANALYST,
            )
            await usvc.attach_to_tenant(
                user_id=bob_user.id,
                tenant_id=beta.id,
                role=UserTenantRole.VIEWER,
            )

            seed = E2ESeed(
                acme_tenant_id=acme.id,
                beta_tenant_id=beta.id,
                alice=SeededUser(
                    user_id=alice_user.id,
                    email=alice_user.email,
                    password=alice_pw,
                ),
                bob=SeededUser(
                    user_id=bob_user.id,
                    email=bob_user.email,
                    password=bob_pw,
                ),
            )

        yield seed

        # Cleanup. CASCADE on tenants takes care of tickets / categories /
        # tenant_categories / audit_logs / user_tenants. CASCADE on users
        # handles refresh_token_records.
        async with session.begin():
            await session.execute(
                text("DELETE FROM users WHERE id = ANY(:ids)"),
                {"ids": [str(alice_user.id), str(bob_user.id)]},
            )
            await session.execute(
                text("DELETE FROM tenants WHERE id = ANY(:ids)"),
                {"ids": [str(acme.id), str(beta.id)]},
            )

    await engine.dispose()


# --- Sprint 8.3.1 batch upload fixtures ---------------------------------


@pytest.fixture
def _batch_env(_e2e_env: None, tmp_path: Path) -> None:
    """Per-test batch env: tmp upload dir + tighter limits.

    Depends on _e2e_env so DB URLs + JWT secret are wired the same way.
    Tests that touch /tenants/me/analyze/batch should request the
    ``client`` fixture below which depends on this env.
    """
    os.environ["IMGA_UPLOAD_DIR"] = str(tmp_path / "uploads")
    os.environ["IMGA_BATCH_CHUNK_SIZE"] = "100"
    os.environ["IMGA_BATCH_GLOBAL_CONCURRENCY"] = "2"
    os.environ["IMGA_BATCH_PER_TENANT_CONCURRENCY"] = "1"


@pytest.fixture
def stub_batch_pipeline() -> Any:
    """Deterministic pipeline used by the batch worker. Same signature as
    AnalysisPipeline; isolated from the test_endpoints stub_pipeline so
    the two suites don't entangle."""
    from imga_core import AnalysisPipeline, KeywordCategoryClassifier

    from tests.batch_helpers import StubBatchAnalyzer

    return AnalysisPipeline(
        analyzer=StubBatchAnalyzer(),
        classifier=KeywordCategoryClassifier(),
    )


@pytest_asyncio.fixture
async def admin_engine() -> AsyncIterator[Any]:
    from imga_db import create_engine

    engine = create_engine("admin")
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def admin_session(admin_engine: Any) -> AsyncIterator[AsyncSession]:
    from imga_db import create_session_factory

    factory = create_session_factory(admin_engine)
    async with factory() as session:
        yield session


@pytest.fixture
def batch_client(
    _batch_env: None,
    stub_batch_pipeline: Any,
    tmp_path: Path,
) -> Iterator[TestClient]:
    """TestClient with the batch lifespan: settings + tenant_config_cache
    + recording scheduler + worker context (engines + stub pipeline).
    Per-test isolation includes resetting the worker module's in-memory
    concurrency primitives."""
    from cachetools import TTLCache

    from imga_api.dependencies import get_pipeline
    from imga_api.workers.batch_analyzer import build_worker_context
    from imga_api.workers.report_generator import build_report_context
    from tests.batch_helpers import RecordingScheduler

    @asynccontextmanager
    async def _test_lifespan(application: FastAPI) -> AsyncIterator[None]:
        s = Settings.from_env()
        application.state.settings = s
        application.state.pipeline = stub_batch_pipeline
        application.state.tenant_config_cache = TTLCache(maxsize=1000, ttl=300)
        application.state.batch_scheduler = RecordingScheduler()
        s.batch.upload_dir.mkdir(parents=True, exist_ok=True)
        s.report.reports_dir.mkdir(parents=True, exist_ok=True)
        worker_ctx = await build_worker_context(
            pipeline=stub_batch_pipeline,
            tenant_config_cache=application.state.tenant_config_cache,
            settings=s.batch,
        )
        application.state.batch_worker_context = worker_ctx
        # Sprint 8.3.2: report worker context lives next to the batch
        # one; tests that hit /reports/* via the upload route's
        # ``submit_report_job`` path read it here. Tests that drive the
        # report worker directly build a fresh test-loop context
        # (same pattern as run_worker — see test_report_generation
        # `_build_test_context`).
        report_ctx = await build_report_context(settings=s.report)
        application.state.report_worker_context = report_ctx
        try:
            yield
        finally:
            # Dispose engines so the next test's event loop doesn't
            # inherit asyncpg connections from this loop.
            await worker_ctx.dispose()
            await report_ctx.dispose()

    original = app.router.lifespan_context
    app.router.lifespan_context = _test_lifespan
    app.dependency_overrides[get_pipeline] = lambda: stub_batch_pipeline

    for attr in (
        "admin_db_engine",
        "app_db_engine",
        "admin_db_engine_factory",
        "app_db_engine_factory",
    ):
        if hasattr(app.state, attr):
            delattr(app.state, attr)

    try:
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c
    finally:
        app.dependency_overrides.clear()
        app.router.lifespan_context = original
        for attr in (
            "admin_db_engine",
            "app_db_engine",
            "admin_db_engine_factory",
            "app_db_engine_factory",
            "tenant_config_cache",
            "batch_scheduler",
            "batch_worker_context",
            "report_worker_context",
            "pipeline",
            "settings",
        ):
            if hasattr(app.state, attr):
                delattr(app.state, attr)


@pytest_asyncio.fixture
async def semi_auto_tenant(
    admin_session: AsyncSession,
) -> AsyncIterator[tuple[Any, UUID, str]]:
    from imga_db.models import AutomationMode

    from tests.batch_helpers import cleanup_tenant, seed_tenant_with_admin

    user, tid, pw = await seed_tenant_with_admin(
        admin_session, automation_mode=AutomationMode.SEMI_AUTO
    )
    yield user, tid, pw
    await cleanup_tenant(admin_session, user.id, tid)


@pytest_asyncio.fixture
async def manual_tenant(
    admin_session: AsyncSession,
) -> AsyncIterator[tuple[Any, UUID, str]]:
    from imga_db.models import AutomationMode

    from tests.batch_helpers import cleanup_tenant, seed_tenant_with_admin

    user, tid, pw = await seed_tenant_with_admin(
        admin_session, automation_mode=AutomationMode.MANUAL
    )
    yield user, tid, pw
    await cleanup_tenant(admin_session, user.id, tid)


@pytest_asyncio.fixture
async def full_auto_tenant(
    admin_session: AsyncSession,
) -> AsyncIterator[tuple[Any, UUID, str]]:
    from imga_db.models import AutomationMode

    from tests.batch_helpers import cleanup_tenant, seed_tenant_with_admin

    user, tid, pw = await seed_tenant_with_admin(
        admin_session, automation_mode=AutomationMode.FULL_AUTO
    )
    yield user, tid, pw
    await cleanup_tenant(admin_session, user.id, tid)


# ---------------------------------------------------------------------------
# Sprint 8.3.6 — LLM credential + tenant context fixtures
# ---------------------------------------------------------------------------
#
# Five fixtures shared by every Sprint 8.3.6.x test file. They live
# here (rather than per-file) so the encryption helper's lru_cache is
# reset uniformly: a stale cache between tests is the same class of
# bug Sprint 8.3.5.2 caught with migration version persistence.
#
# Layout:
#   * master_key_path     — repo-local Fernet key, swaps env var,
#                           clears the encryption cache on yield.
#   * encryption_helper   — module reference (encrypt / decrypt /
#                           reset_fernet_cache), wired to master_key_path.
#   * mock_gemini_credential — factory: insert one encrypted credential
#                              row for a given tenant, return the row id.
#   * tenant_with_context — semi_auto_tenant + industry/size/description
#                           prefilled (e_commerce / medium / "...").
#   * prompt_template_swot_v1 — read the migration-seeded placeholder
#                               row; tests that need the real prompt
#                               UPDATE it inside the fixture.


@pytest.fixture
def master_key_path(tmp_path: Path) -> Iterator[Path]:
    """Per-test Fernet key written to tmp_path. Sets the env var the
    encryption helper reads, yields the path, then clears the cache
    so the next test re-binds to its own key."""
    from cryptography.fernet import Fernet

    from imga_core.security.encryption import reset_fernet_cache

    key_path = tmp_path / "master.key"
    key_path.write_bytes(Fernet.generate_key())
    prev = os.environ.get("IMGA_MASTER_KEY_PATH")
    os.environ["IMGA_MASTER_KEY_PATH"] = str(key_path)
    reset_fernet_cache()
    try:
        yield key_path
    finally:
        if prev is None:
            os.environ.pop("IMGA_MASTER_KEY_PATH", None)
        else:
            os.environ["IMGA_MASTER_KEY_PATH"] = prev
        reset_fernet_cache()


@pytest.fixture
def encryption_helper(master_key_path: Path) -> Any:  # noqa: ARG001
    """Returns the encryption module so tests can call
    ``encryption_helper.encrypt(...)`` without re-importing. The
    ``master_key_path`` dependency wires the env + clears the cache;
    by the time this fixture yields the module is bound to the new
    key. ``master_key_path`` is read for its side effect only — the
    ARG001 noqa silences the unused-arg lint."""
    from imga_core.security import encryption

    return encryption


@pytest_asyncio.fixture
async def mock_gemini_credential(
    admin_session: AsyncSession,
    encryption_helper: Any,
) -> AsyncIterator[Any]:
    """Factory fixture: inserts one encrypted Gemini credential row for
    a given tenant. Returns a callable so a single test can mint
    multiple credentials with different priorities (primary +
    fallback). Cleanup deletes everything inserted via this factory.

    Usage::

        async def test_rotator(mock_gemini_credential, semi_auto_tenant):
            user, tid, _ = semi_auto_tenant
            await mock_gemini_credential(tid, "fake-key-1", priority=0)
            await mock_gemini_credential(tid, "fake-key-2", priority=1)
            ...
    """
    from imga_db.models import TenantLlmCredential

    inserted_ids: list[UUID] = []

    async def _insert(
        tenant_id: UUID,
        plaintext_key: str,
        *,
        provider: str = "gemini",
        label: str = "Birincil Hesap",
        priority: int = 0,
    ) -> UUID:
        ciphertext = encryption_helper.encrypt(plaintext_key)
        async with admin_session.begin():
            await admin_session.execute(
                text("SELECT set_config('app.current_tenant_id', :t, true)"),
                {"t": str(tenant_id)},
            )
            cred = TenantLlmCredential(
                tenant_id=tenant_id,
                provider=provider,
                label=label,
                encrypted_value=ciphertext,
                priority=priority,
            )
            admin_session.add(cred)
            await admin_session.flush()
            cred_id = cred.id
            inserted_ids.append(cred_id)
        return cred_id

    yield _insert

    # Teardown — remove every credential the factory inserted.
    if inserted_ids:
        async with admin_session.begin():
            await admin_session.execute(
                text("DELETE FROM tenant_llm_credentials WHERE id = ANY(:ids)"),
                {"ids": [str(cid) for cid in inserted_ids]},
            )


@pytest_asyncio.fixture
async def tenant_with_context(
    admin_session: AsyncSession,
    semi_auto_tenant: tuple[Any, UUID, str],
) -> AsyncIterator[tuple[Any, UUID, str]]:
    """A semi_auto tenant with industry/company_size/business_description
    prefilled — the SWOT/OKR generators expect this shape; running them
    against an empty tenant context should be a separate test. The
    fixture leaves the cleanup to ``semi_auto_tenant`` (CASCADE on
    tenant DELETE)."""
    user, tid, pw = semi_auto_tenant
    async with admin_session.begin():
        await admin_session.execute(
            text(
                "UPDATE tenants SET industry = :ind, "
                "company_size = :sz, business_description = :desc "
                "WHERE id = :tid"
            ),
            {
                "ind": "e_commerce",
                "sz": "medium",
                "desc": (
                    "Türkiye genelinde online çocuk ürünleri satışı; "
                    "kargo + iade süreci kritik."
                ),
                "tid": str(tid),
            },
        )
    yield user, tid, pw


@pytest_asyncio.fixture
async def prompt_template_swot_v1(
    admin_session: AsyncSession,
) -> AsyncIterator[Any]:
    """Returns the migration-seeded ``swot_v1`` prompt template row.
    Tests that need the finalised prompt UPDATE the row in-place
    inside their own setup; this fixture's job is just to surface the
    placeholder so the test doesn't have to know the migration shape.
    """
    from imga_db.models import PromptTemplate
    from sqlalchemy import select

    async with admin_session.begin():
        row = (
            await admin_session.execute(
                select(PromptTemplate).where(
                    PromptTemplate.template_key == "swot_v1"
                )
            )
        ).scalar_one()
        admin_session.expunge(row)
    yield row
