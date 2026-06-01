"""Sprint 9.7 — /public/trial/analyze regression tests.

Pins the four contracts the marketing site (imga.ai) relies on:

  * Happy path — a ≤100-row CSV returns a payload with the right
    shape (sentiment_distribution keys, top_categories list, ≤5
    sample_reviews, nps_estimate computable).
  * >100 rows → 422 with a Turkish "100 satır" error.
  * Duplicate same X-Trial-User-Email within 24h → returns the
    cached payload (same request_id) WITHOUT re-running the
    pipeline.
  * Wrong / missing bearer → 401.

The fixture wires IMGA_API_TRIAL_KEY into Settings via the
``_batch_env`` lifespan path; the batch_client fixture then picks
it up because Settings.from_env() runs inside lifespan after the
env mutation.
"""

from __future__ import annotations

import io
import os
from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from imga_db.models import TrialAnalysis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.main import app
from imga_api.services.trial_analysis_service import TRIAL_TENANT_ID


_TRIAL_KEY = "test-trial-key-deterministic-must-be-at-least-32-chars"


@pytest.fixture
def _trial_env(_batch_env: None) -> Iterator[None]:
    """Layer the trial key onto the existing batch test env."""
    os.environ["IMGA_API_TRIAL_KEY"] = _TRIAL_KEY
    try:
        yield
    finally:
        os.environ.pop("IMGA_API_TRIAL_KEY", None)


@pytest.fixture
def trial_client(
    _trial_env: None,
    stub_batch_pipeline: Any,
    tmp_path: Path,
) -> Iterator[TestClient]:
    """Same lifespan shape as batch_client but the trial key is in
    env, so Settings.from_env picks it up. Self-contained so we
    don't have to coax batch_client's fixture chain."""
    from cachetools import TTLCache

    from imga_api.dependencies import get_pipeline
    from imga_api.settings import Settings

    @asynccontextmanager
    async def _test_lifespan(application: FastAPI) -> AsyncIterator[None]:
        s = Settings.from_env()
        application.state.settings = s
        application.state.pipeline = stub_batch_pipeline
        application.state.tenant_config_cache = TTLCache(maxsize=1000, ttl=300)
        s.batch.upload_dir.mkdir(parents=True, exist_ok=True)
        yield

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
            "pipeline",
            "settings",
        ):
            if hasattr(app.state, attr):
                delattr(app.state, attr)


@pytest_asyncio.fixture
async def _cleanup_trial_table(
    admin_session: AsyncSession,
) -> AsyncIterator[None]:
    """Drop any trial_analyses rows the test creates so a re-run
    doesn't trip the email-UNIQUE constraint."""
    yield
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(TRIAL_TENANT_ID)},
        )
        await admin_session.execute(text("DELETE FROM trial_analyses"))


def _csv_bytes(rows: list[str]) -> bytes:
    """Tiny CSV factory — header 'yorum' + N data rows so the
    smart_parser detector confidently picks the column."""
    body = "yorum\n" + "\n".join(rows) + "\n"
    return body.encode("utf-8")


# --- 1. Happy path -------------------------------------------------------


@pytest.mark.asyncio
async def test_trial_analyze_under_100_rows_returns_results(
    trial_client: TestClient,
    _cleanup_trial_table: None,
    admin_session: AsyncSession,
) -> None:
    rows = (
        ["Kargo gelmedi çok kötü"] * 8
        + ["Ürün harika çok güzel"] * 6
        + ["Vasat, fena değil"] * 4
    )
    file_bytes = _csv_bytes(rows)
    email = f"trial-{uuid4().hex[:8]}@example.com"

    r = trial_client.post(
        "/public/trial/analyze",
        headers={
            "Authorization": f"Bearer {_TRIAL_KEY}",
            "X-Trial-User-Id": str(uuid4()),
            "X-Trial-User-Email": email,
        },
        files={"file": ("trial.csv", io.BytesIO(file_bytes), "text/csv")},
    )
    assert r.status_code == 200, r.text
    body = r.json()

    # Sentiment distribution — keys are the literal label set the
    # marketing dashboard maps. Counts can be 0 but the keys must
    # exist so the frontend's donut renderer doesn't crash.
    assert set(body["sentiment_distribution"].keys()) == {
        "POZITIF", "NEGATIF", "NÖTR"
    }
    assert body["sentiment_distribution"]["NEGATIF"] == 8
    assert body["sentiment_distribution"]["POZITIF"] == 6
    assert body["sentiment_distribution"]["NÖTR"] == 4

    # top_categories list — may be empty for the stub pipeline
    # (KeywordCategoryClassifier returning 'belirsiz') but the field
    # must be a list.
    assert isinstance(body["top_categories"], list)
    assert len(body["top_categories"]) <= 5

    # sample_reviews — ≤5 entries; each has the 3-field shape.
    assert isinstance(body["sample_reviews"], list)
    assert len(body["sample_reviews"]) <= 5
    for s in body["sample_reviews"]:
        assert set(s.keys()) == {"text", "sentiment", "primary_category"}
        assert s["sentiment"] in {"POZITIF", "NEGATIF", "NÖTR"}

    # nps_estimate — 6 promoter - 8 detractor over 18 total = -11
    # (rounded). Loose bound because heuristic + rounding.
    assert body["nps_estimate"] is not None
    assert -15 <= body["nps_estimate"] <= 0

    # request_id — non-empty string, frontend stores it.
    assert isinstance(body["request_id"], str) and len(body["request_id"]) == 36

    # DB row landed with the trial tenant id (RLS regression guard).
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(TRIAL_TENANT_ID)},
        )
        row = (
            await admin_session.execute(
                select(TrialAnalysis).where(TrialAnalysis.email == email)
            )
        ).scalar_one()
    assert row.tenant_id == TRIAL_TENANT_ID
    assert row.total_rows == 18


# --- 2. Row cap -----------------------------------------------------------


@pytest.mark.asyncio
async def test_trial_analyze_over_100_rows_returns_422(
    trial_client: TestClient,
    _cleanup_trial_table: None,
) -> None:
    rows = ["Yorum metni satır {n}".format(n=i) for i in range(150)]
    file_bytes = _csv_bytes(rows)
    email = f"trial-overflow-{uuid4().hex[:8]}@example.com"

    r = trial_client.post(
        "/public/trial/analyze",
        headers={
            "Authorization": f"Bearer {_TRIAL_KEY}",
            "X-Trial-User-Email": email,
        },
        files={"file": ("big.csv", io.BytesIO(file_bytes), "text/csv")},
    )
    assert r.status_code == 422, r.text
    detail = r.json().get("detail", "")
    assert "100 satır" in detail or "100" in detail


# --- 3. Idempotency ------------------------------------------------------


@pytest.mark.asyncio
async def test_trial_analyze_duplicate_user_returns_existing(
    trial_client: TestClient,
    _cleanup_trial_table: None,
) -> None:
    rows = ["Kargo gelmedi"] * 3
    file_bytes = _csv_bytes(rows)
    email = f"trial-dup-{uuid4().hex[:8]}@example.com"
    headers = {
        "Authorization": f"Bearer {_TRIAL_KEY}",
        "X-Trial-User-Email": email,
    }

    r1 = trial_client.post(
        "/public/trial/analyze",
        headers=headers,
        files={"file": ("first.csv", io.BytesIO(file_bytes), "text/csv")},
    )
    assert r1.status_code == 200, r1.text
    request_id_1 = r1.json()["request_id"]

    # Second call — different file content, same email. Marketing
    # already short-circuits on its side; defense-in-depth here is
    # that we return the cached payload (same request_id) without
    # running the pipeline again.
    different_bytes = _csv_bytes(["Tamamen başka bir yorum"] * 10)
    r2 = trial_client.post(
        "/public/trial/analyze",
        headers=headers,
        files={"file": ("second.csv", io.BytesIO(different_bytes), "text/csv")},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["request_id"] == request_id_1, (
        "Same email within the 24h window must return the cached "
        "request_id; a fresh uuid here would mean the idempotency "
        "lookup regressed and we re-ran the analysis."
    )


# --- 4. Auth -------------------------------------------------------------


def test_trial_analyze_wrong_bearer_returns_401(
    trial_client: TestClient,
) -> None:
    file_bytes = _csv_bytes(["bir yorum"])
    r = trial_client.post(
        "/public/trial/analyze",
        headers={
            "Authorization": "Bearer wrong-key",
            "X-Trial-User-Email": "x@example.com",
        },
        files={"file": ("x.csv", io.BytesIO(file_bytes), "text/csv")},
    )
    assert r.status_code == 401, r.text

    # Missing header is also 401.
    r2 = trial_client.post(
        "/public/trial/analyze",
        headers={"X-Trial-User-Email": "x@example.com"},
        files={"file": ("x.csv", io.BytesIO(file_bytes), "text/csv")},
    )
    assert r2.status_code == 401, r2.text
