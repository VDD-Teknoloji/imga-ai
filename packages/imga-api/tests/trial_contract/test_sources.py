"""Standalone trial route contracts. Run with --confcutdir at this directory."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response
from imga_api.db_deps import get_admin_session
from imga_api.dependencies import get_pipeline
from imga_api.routes.public_trial import router
from imga_core.models import AnalysisResult
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

KEY = "local-trial-contract-test-key"
DATABASE_URL = os.environ.get("IMGA_TRIAL_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="Requires an isolated trial test DB")


class StubPipeline:
    async def analyze_batch_async(self, texts: list[str]) -> list[AnalysisResult]:
        return [
            AnalysisResult(
                text=value,
                sentiment_label="NEGATIF" if "kötü" in value else "POZITIF",
                sentiment_score=-0.8 if "kötü" in value else 0.8,
            )
            for value in texts
        ]


@pytest.fixture
def source_client(tmp_path: Path) -> Iterator[tuple[TestClient, str]]:
    assert DATABASE_URL is not None
    engine = create_async_engine(DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    email = f"trial-source-{uuid4().hex}@example.com"

    async def session_override() -> AsyncIterator[AsyncSession]:
        async with factory() as session, session.begin():
            yield session

    app = FastAPI()
    app.include_router(router)
    app.state.settings = SimpleNamespace(
        imga_api_trial_key=KEY, batch=SimpleNamespace(upload_dir=tmp_path)
    )
    app.dependency_overrides[get_admin_session] = session_override
    app.dependency_overrides[get_pipeline] = StubPipeline
    with TestClient(app) as client:
        yield client, email

    async def cleanup() -> None:
        async with factory() as session, session.begin():
            await session.execute(
                text("DELETE FROM trial_analyses WHERE email = :email"), {"email": email}
            )
        await engine.dispose()

    asyncio.run(cleanup())


def send(client: TestClient, email: str, source: str | None, rows: list[str]) -> Response:
    headers = {"Authorization": f"Bearer {KEY}", "X-Trial-User-Email": email}
    if source is not None:
        headers["X-Trial-Source"] = source
    return client.post(
        "/public/trial/analyze",
        headers=headers,
        files={"file": ("comments.csv", ("yorum\n" + "\n".join(rows)).encode(), "text/csv")},
    )


@pytest.mark.parametrize(
    ("first_source", "second_source"),
    [("excel", "twitter"), ("twitter", "google_play"), ("google_play", "app_store")],
)
def test_source_changes_produce_distinct_results(
    source_client: tuple[TestClient, str], first_source: str, second_source: str
) -> None:
    client, email = source_client
    first = send(client, email, first_source, ["Çok kötü"] * 3)
    second = send(client, email, second_source, ["Çok güzel"] * 5)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["source"] == first_source
    assert second.json()["source"] == second_source
    assert first.json()["request_id"] != second.json()["request_id"]
    assert second.json()["sentiment_distribution"] == {"POZITIF": 5, "NEGATIF": 0, "NÖTR": 0}
    repeated = send(client, email, second_source, ["Başka yorum"])
    assert repeated.json()["request_id"] == second.json()["request_id"]


def test_legacy_calls_default_to_excel(source_client: tuple[TestClient, str]) -> None:
    client, email = source_client
    first = send(client, email, None, ["Çok güzel"])
    repeated = send(client, email, "excel", ["Çok kötü"])
    assert first.status_code == 200, first.text
    assert repeated.json()["source"] == "excel"
    assert first.json()["request_id"] == repeated.json()["request_id"]


def test_failed_source_change_preserves_previous_cache(
    source_client: tuple[TestClient, str],
) -> None:
    client, email = source_client
    first = send(client, email, "google_play", ["Çok güzel"])
    failed = send(client, email, "app_store", ["Çok kötü"] * 101)
    assert failed.status_code == 422, failed.text
    repeated = send(client, email, "google_play", ["Başka veri"])
    assert repeated.json()["request_id"] == first.json()["request_id"]


def test_unknown_source_is_rejected(source_client: tuple[TestClient, str]) -> None:
    client, email = source_client
    assert send(client, email, "arbitrary", ["Yorum"]).status_code == 422


def test_missing_bearer_is_rejected(source_client: tuple[TestClient, str]) -> None:
    client, email = source_client
    response = client.post(
        "/public/trial/analyze",
        headers={"X-Trial-User-Email": email},
        files={"file": ("comments.csv", b"yorum\ntest", "text/csv")},
    )
    assert response.status_code == 401
