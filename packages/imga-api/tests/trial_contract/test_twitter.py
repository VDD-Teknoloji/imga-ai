"""Protected demo adapters must use the same Twitter services as the SaaS."""

from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from imga_api.db_deps import get_admin_session
from imga_api.routes import public_trial_twitter as adapter
from imga_api.routes.public_trial import router
from imga_api.services.llm_credentials import NoCredentialsError
from imga_api.services.trial_analysis_service import TRIAL_TENANT_ID
from imga_api.services.twitter_brand_service import BrandSearchPlan, RelevanceVerdict
from imga_api.services.twitter_import import TwitterFetchResult, TwitterTweet, build_search_query

KEY = "local-twitter-contract-key"
HEADERS = {"Authorization": f"Bearer {KEY}"}
BODY = {
    "brand": "Karaca",
    "term": "karaca, karaca home, -cem karaca",
    "handle": "@karacaonline",
    "count": 10,
}


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = FastAPI()
    app.state.settings = SimpleNamespace(
        imga_api_trial_key=KEY, twitterapi_io_key="stub-provider-key"
    )
    app.include_router(router)
    app.dependency_overrides[get_admin_session] = lambda: AsyncMock()
    with TestClient(app) as value:
        yield value


@pytest.mark.parametrize("action", ["plan", "preview", "fetch"])
def test_all_twitter_adapters_require_bearer(client: TestClient, action: str) -> None:
    assert client.post(f"/public/trial/twitter/{action}", json=BODY).status_code == 401


def test_preview_matches_shared_query_builder(client: TestClient) -> None:
    result = client.post("/public/trial/twitter/preview", headers=HEADERS, json=BODY)
    assert result.status_code == 200
    assert result.json()["query_preview"] == build_search_query(BODY["term"], "karacaonline")
    assert (
        client.post(
            "/public/trial/twitter/preview", headers=HEADERS, json={**BODY, "term": "-exclude"}
        ).status_code
        == 422
    )


def test_plan_uses_fixed_trial_tenant(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    planner = AsyncMock(
        return_value=BrandSearchPlan(
            "Karaca", "Homeware brand", ["karaca home"], ["cem karaca"], "karacaonline", True
        )
    )
    monkeypatch.setattr(adapter, "plan_brand_search", planner)
    result = client.post(
        "/public/trial/twitter/plan",
        headers=HEADERS,
        json={**BODY, "tenant_id": "caller-controlled"},
    )
    assert result.status_code == 200
    assert planner.call_args.args[1] == TRIAL_TENANT_ID
    assert planner.call_args.kwargs["actor_user_id"] is None
    assert result.json()["bare_name_ambiguous"] is True
    assert "-cem karaca" in result.json()["term"]


def test_fetch_applies_shared_relevance_and_returns_safe_details(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    tweets = [
        TwitterTweet(
            "Ürün çok iyi",
            None,
            "https://x.com/i/web/status/123",
            raw_text="@karacaonline Ürün çok iyi",
            like_count=2,
        ),
        TwitterTweet("Alakasız yorum", None),
    ]
    fetcher = AsyncMock(
        return_value=TwitterFetchResult(tweets, 20, 1, True, filtered_out=10, excluded_collab=8)
    )
    judge = AsyncMock(return_value=RelevanceVerdict([True, False], 1, 0, dropped=1))
    monkeypatch.setattr(adapter, "fetch_tweets", fetcher)
    monkeypatch.setattr(adapter, "judge_tweet_relevance", judge)
    result = client.post("/public/trial/twitter/fetch", headers=HEADERS, json=BODY)
    assert result.status_code == 200, result.text
    assert fetcher.call_args.kwargs["max_pages"] == 20
    assert fetcher.call_args.kwargs["exclude_handle"] == "karacaonline"
    assert judge.call_args.args[1] == TRIAL_TENANT_ID
    assert judge.call_args.kwargs["tweets"][0].startswith("@karacaonline")
    data = result.json()
    assert data["texts"] == ["Ürün çok iyi"]
    assert data["details"]["filtered_by_ai"] == 1
    assert data["details"]["kept"] == 1
    assert data["details"]["tweets"][0]["like_count"] == 2
    assert "raw_text" not in result.text and "author" not in result.text
    assert (
        client.post(
            "/public/trial/twitter/fetch", headers=HEADERS, json={**BODY, "count": 101}
        ).status_code
        == 422
    )


def test_missing_ai_credentials_are_disclosed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        adapter,
        "fetch_tweets",
        AsyncMock(
            return_value=TwitterFetchResult([TwitterTweet("Marka yorumu", None)], 1, 1, True)
        ),
    )
    monkeypatch.setattr(
        adapter, "judge_tweet_relevance", AsyncMock(side_effect=NoCredentialsError("missing"))
    )
    result = client.post("/public/trial/twitter/fetch", headers=HEADERS, json=BODY)
    assert result.status_code == 200
    assert result.json()["details"]["ai_check_skipped"] is True
    assert result.json()["details"]["kept"] == 1
