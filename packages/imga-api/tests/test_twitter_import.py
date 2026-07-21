""" "Twitter'dan Çek" entegrasyonu — route seviyesi testler.

Gerçek twitterapi.io çağrısı yok: ``fetch_tweets`` route modülü
üzerinden monkeypatch'lenir. Kapsam:
  * 503 — IMGA_TWITTERAPI_IO_KEY yapılandırılmamış
  * 201 — mutlu yol: CSV diske iner, queued job + scheduler dispatch
  * 422 — sorgu sonuç döndürmedi
  * 403 — viewer rolü yazamaz
  * birim — build_search_query / clean_tweet_text
"""

from __future__ import annotations

import csv
from dataclasses import replace
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient
from imga_api.main import app
from imga_api.routes import tenant_twitter
from imga_api.services import AuditService, UserService
from imga_api.services.twitter_import import (
    TwitterFetchResult,
    build_search_query,
    clean_tweet_text,
)
from imga_db.models import User, UserTenantRole
from sqlalchemy.ext.asyncio import AsyncSession

from tests.batch_helpers import fetch_job, login_token

# --- birim: sorgu + temizlik -----------------------------------------


def test_build_search_query_quotes_term_and_filters() -> None:
    q = build_search_query("Navlungo", None)
    assert q == '"Navlungo" lang:tr -filter:retweets'


def test_build_search_query_excludes_official_handle() -> None:
    q = build_search_query("Navlungo", "@navlungo")
    assert q == '"Navlungo" -from:navlungo lang:tr -filter:retweets'


def test_clean_tweet_text_strips_urls_and_leading_mentions() -> None:
    raw = "@destek @kargo  Paket hâlâ gelmedi https://t.co/abc123 çok kötü"
    assert clean_tweet_text(raw) == "Paket hâlâ gelmedi çok kötü"


# --- route yardımcıları ----------------------------------------------


def _enable_key(client: TestClient) -> None:
    test_app = client.app  # type: ignore[attr-defined]
    test_app.state.settings = replace(test_app.state.settings, twitterapi_io_key="test-key")


def _post(client: TestClient, token: str, payload: dict[str, object]) -> httpx.Response:
    return client.post(
        "/tenants/me/analyze/twitter-import",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )


# --- route testleri --------------------------------------------------


@pytest.mark.asyncio
async def test_twitter_import_requires_configuration(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = _post(batch_client, token, {"term": "Navlungo"})
    assert r.status_code == 503, r.text


@pytest.mark.asyncio
async def test_twitter_import_happy_path(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    _enable_key(batch_client)

    async def fake_fetch(
        *, api_key: str, term: str, count: int, exclude_handle: str | None = None
    ) -> TwitterFetchResult:
        assert api_key == "test-key"
        assert term == "Navlungo"
        assert count == 100
        return TwitterFetchResult(
            texts=["kargo çok iyi geldi", "teslimat kötü ve geç"],
            fetched_total=3,
            pages=1,
            exhausted=True,
        )

    monkeypatch.setattr(tenant_twitter, "fetch_tweets", fake_fetch)

    r = _post(batch_client, token, {"term": "Navlungo", "count": 100})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["found"] == 2
    assert body["requested"] == 100
    assert body["exhausted"] is True
    job_view = body["job"]
    assert job_view["status"] == "queued"
    assert job_view["total_rows"] == 2
    assert job_view["text_column"] == "yorum"
    assert job_view["source_column"] == "kaynak"
    assert job_view["file_name"] == "twitter-navlungo.csv"

    # Dosya şablon kolonlarıyla diske inmiş olmalı — worker'ın
    # okuyacağı gerçek CSV.
    job = await fetch_job(admin_session, UUID(job_view["job_id"]))
    file_path = Path(job.file_path)
    assert file_path.exists()
    with file_path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))
    assert rows[0] == ["yorum", "kaynak"]
    assert rows[1] == ["kargo çok iyi geldi", "twitter"]
    assert len(rows) == 3

    scheduler = app.state.batch_scheduler
    assert len(scheduler.added) == 1


@pytest.mark.asyncio
async def test_twitter_import_empty_results_is_422(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    _enable_key(batch_client)

    async def fake_fetch(
        *, api_key: str, term: str, count: int, exclude_handle: str | None = None
    ) -> TwitterFetchResult:
        return TwitterFetchResult(texts=[], fetched_total=0, pages=1, exhausted=True)

    monkeypatch.setattr(tenant_twitter, "fetch_tweets", fake_fetch)

    r = _post(batch_client, token, {"term": "hiçsonuçyokterim"})
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_twitter_import_viewer_forbidden(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    _user, tid, _pw = semi_auto_tenant
    plain = "Viewer-Password-123!"
    usvc = UserService(admin_session, AuditService(admin_session))
    async with admin_session.begin():
        viewer = await usvc.create(
            email="twitter-viewer@example.com",
            password=plain,
            full_name="Viewer",
        )
        await usvc.attach_to_tenant(user_id=viewer.id, tenant_id=tid, role=UserTenantRole.VIEWER)
        viewer_email = viewer.email
        viewer_id = viewer.id
    try:
        token = login_token(batch_client, viewer_email, plain, tid)
        _enable_key(batch_client)
        r = _post(batch_client, token, {"term": "Navlungo"})
        assert r.status_code == 403, r.text
    finally:
        from sqlalchemy import text as sql_text

        async with admin_session.begin():
            await admin_session.execute(
                sql_text("DELETE FROM users WHERE id = :id"),
                {"id": str(viewer_id)},
            )
