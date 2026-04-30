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
