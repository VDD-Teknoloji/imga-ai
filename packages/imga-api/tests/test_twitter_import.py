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
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient
from imga_db.models import User, UserTenantRole
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.main import app
from imga_api.routes import tenant_twitter
from imga_api.services import AuditService, UserService
from imga_api.services.llm_credentials import NoCredentialsError
from imga_api.services.twitter_brand_service import BrandSearchPlan, RelevanceVerdict
from imga_api.services.twitter_import import (
    SearchTerms,
    TwitterFetchResult,
    TwitterTweet,
    build_search_query,
    clean_tweet_text,
    fetch_tweets,
    parse_search_terms,
    parse_tweet_created_at,
    tweet_matches_terms,
    tweet_url_from_item,
)
from tests.batch_helpers import fetch_job, login_token

# --- birim: sorgu + temizlik -----------------------------------------


def test_build_search_query_quotes_term_and_filters() -> None:
    q = build_search_query("Navlungo", None)
    assert q == '"Navlungo" lang:tr -filter:retweets'


def test_build_search_query_excludes_official_handle() -> None:
    q = build_search_query("Navlungo", "@navlungo")
    assert q == '"Navlungo" -from:navlungo lang:tr -filter:retweets'


def test_parse_search_terms_splits_positive_and_negative() -> None:
    terms = parse_search_terms(' karaca , -"cem karaca", -hidayet karaca, k, karaca ')
    assert terms.positive == ("karaca",)
    assert terms.negative == ("cem karaca", "hidayet karaca")


def test_parse_search_terms_all_negative_has_no_positive() -> None:
    assert parse_search_terms("-cem karaca, -x").positive == ()


def test_build_search_query_multi_term_or_group_and_negatives() -> None:
    q = build_search_query("karaca tencere, @karacaonline, -cem karaca", "karacaonline")
    assert q == (
        '("karaca tencere" OR @karacaonline) -"cem karaca" '
        "-from:karacaonline lang:tr -filter:retweets"
    )


# --- birim: alaka filtresi + bağlantı --------------------------------


_TERMS = SearchTerms(positive=("karaca",), negative=())


def test_tweet_matches_when_term_in_raw_text_with_suffix_and_case() -> None:
    assert tweet_matches_terms("KARACA'nın tencereleri berbat", _TERMS, None)
    assert tweet_matches_terms("#karacahome çaydanlık sızdırıyor", _TERMS, None)


def test_tweet_does_not_match_author_name_only_hit() -> None:
    # X araması yazar adında eşledi ("Tuğçe Karaca"); metinde terim yok.
    assert not tweet_matches_terms(
        "ÖSYMyi de akademiye al sayın @Yusuf__Tekin", _TERMS, "karacaonline"
    )


def test_tweet_matches_when_addressed_to_official_handle() -> None:
    assert tweet_matches_terms("@KaracaOnline ürün 2 ayda bozuldu", _TERMS, "karacaonline")
    assert tweet_matches_terms(
        "ürün 2 ayda bozuldu", _TERMS, "@karacaonline", in_reply_to="karacaonline"
    )
    assert not tweet_matches_terms("ürün 2 ayda bozuldu", _TERMS, None, in_reply_to="baska")


def test_tweet_matches_is_accent_insensitive() -> None:
    terms = SearchTerms(positive=("çaydanlık",), negative=())
    assert tweet_matches_terms("caydanlik sızdırıyor", terms, None)


def test_tweet_url_from_item_prefers_url_then_id() -> None:
    assert (
        tweet_url_from_item({"url": "https://x.com/a/status/1", "id": "1"})
        == "https://x.com/a/status/1"
    )
    assert tweet_url_from_item({"id": "2092540287411159128"}) == (
        "https://x.com/i/web/status/2092540287411159128"
    )
    assert tweet_url_from_item({"id": "abc"}) is None
    assert tweet_url_from_item({}) is None


@pytest.mark.asyncio
async def test_fetch_tweets_filters_noise_and_keeps_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Yazar adıyla eşleşen gürültü elenir, markaya yazılan yanıt ve
    metninde terim geçen gönderi bağlantısıyla kalır."""
    page = {
        "tweets": [
            {
                "id": "1",
                "url": "https://x.com/tugce/status/1",
                "text": "ÖSYMyi de akademiye al sayın @Yusuf__Tekin",
                "createdAt": "Wed Aug 26 09:10:56 +0000 2026",
                "author": {"userName": "tugce", "name": "Tuğçe Karaca"},
            },
            {
                "id": "2",
                "url": "https://x.com/musteri/status/2",
                "text": "@karacaonline tencerenin dibi 2 ayda tuttu https://t.co/x",
                "createdAt": "Wed Aug 26 09:00:00 +0000 2026",
                "inReplyToUsername": "karacaonline",
            },
            {
                "id": "3",
                "text": "Karaca'nın porselenleri gerçekten kaliteli",
                "createdAt": "2026-08-26T08:00:00Z",
            },
        ],
        "has_next_page": False,
        "next_cursor": "",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-api-key"] == "k"
        assert request.url.params["queryType"] == "Latest"
        return httpx.Response(200, json=page)

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def patched_client(**kwargs: object) -> httpx.AsyncClient:
        return real_client(transport=transport, **kwargs)  # type: ignore[arg-type]

    # twitter_import modülü ``httpx.AsyncClient(...)`` diye çağırır; aynı
    # modül nesnesi olduğundan httpx üzerinde yamalamak yeterli.
    monkeypatch.setattr(httpx, "AsyncClient", patched_client)

    result = await fetch_tweets(api_key="k", term="karaca", count=10, exclude_handle="karacaonline")
    assert result.fetched_total == 3
    assert result.filtered_out == 1
    assert result.exhausted is True
    assert [t.text for t in result.tweets] == [
        "tencerenin dibi 2 ayda tuttu",
        "Karaca'nın porselenleri gerçekten kaliteli",
    ]
    assert result.tweets[0].url == "https://x.com/musteri/status/2"
    assert result.tweets[1].url == "https://x.com/i/web/status/3"
    assert result.tweets[1].created_at == datetime(2026, 8, 26, 8, 0, tzinfo=UTC)


def test_clean_tweet_text_strips_urls_and_leading_mentions() -> None:
    raw = "@destek @kargo  Paket hâlâ gelmedi https://t.co/abc123 çok kötü"
    assert clean_tweet_text(raw) == "Paket hâlâ gelmedi çok kötü"


def test_parse_tweet_created_at_twitter_classic_format() -> None:
    parsed = parse_tweet_created_at("Tue Dec 10 07:00:30 +0000 2024")
    assert parsed == datetime(2024, 12, 10, 7, 0, 30, tzinfo=UTC)


def test_parse_tweet_created_at_iso_fallback() -> None:
    parsed = parse_tweet_created_at("2026-05-12T10:30:00Z")
    assert parsed == datetime(2026, 5, 12, 10, 30, tzinfo=UTC)


@pytest.mark.parametrize("raw", [None, "", "bilinmeyen"])
def test_parse_tweet_created_at_unparseable_is_none(raw: object) -> None:
    assert parse_tweet_created_at(raw) is None


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


def _post_plan(client: TestClient, token: str, payload: dict[str, object]) -> httpx.Response:
    return client.post(
        "/tenants/me/analyze/twitter-import/plan",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )


async def _keep_all_judge(session: object, tenant_id: object, **kwargs: object) -> RelevanceVerdict:
    tweets = kwargs["tweets"]
    assert isinstance(tweets, list)
    return RelevanceVerdict(relevant=[True] * len(tweets), batches=1, failed_batches=0)


def _two_tweets_fetch(**_: object) -> TwitterFetchResult:
    return TwitterFetchResult(
        tweets=[
            TwitterTweet(
                text="tencerenin dibi tuttu",
                created_at=datetime(2026, 8, 26, 8, 0, tzinfo=UTC),
                url="https://x.com/a/status/1",
                raw_text="@karacaonline tencerenin dibi tuttu",
            ),
            TwitterTweet(text="Cem Karaca konseri harikaydı", created_at=None),
        ],
        fetched_total=5,
        pages=1,
        exhausted=True,
        filtered_out=3,
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
            tweets=[
                TwitterTweet(
                    text="kargo çok iyi geldi",
                    created_at=datetime(2026, 5, 12, 8, 15, tzinfo=UTC),
                    url="https://x.com/musteri/status/123",
                ),
                TwitterTweet(text="teslimat kötü ve geç", created_at=None),
            ],
            fetched_total=3,
            pages=1,
            exhausted=True,
            filtered_out=1,
        )

    monkeypatch.setattr(tenant_twitter, "fetch_tweets", fake_fetch)
    monkeypatch.setattr(tenant_twitter, "judge_tweet_relevance", _keep_all_judge)

    r = _post(batch_client, token, {"term": "Navlungo", "count": 100})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["found"] == 2
    assert body["requested"] == 100
    assert body["exhausted"] is True
    assert body["filtered_out"] == 1
    assert body["fetched_total"] == 3
    assert body["filtered_by_ai"] == 0
    assert body["ai_check_skipped"] is False
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
    assert rows[0] == ["yorum", "tarih", "kaynak", "bağlantı"]
    assert rows[1] == [
        "kargo çok iyi geldi",
        "2026-05-12T08:15:00+00:00",
        "twitter",
        "https://x.com/musteri/status/123",
    ]
    # Tarihi çözülemeyen tweet boş 'tarih' hücresiyle iner — parser
    # bunu None'a çevirir, satır yine analiz edilir. Bağlantısız tweet
    # de boş 'bağlantı' hücresiyle iner.
    assert rows[2] == ["teslimat kötü ve geç", "", "twitter", ""]
    assert len(rows) == 3

    scheduler = app.state.batch_scheduler
    assert len(scheduler.added) == 1


@pytest.mark.asyncio
async def test_twitter_import_ai_judge_drops_irrelevant_and_reports_counts(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    _enable_key(batch_client)

    async def fake_fetch(**kwargs: object) -> TwitterFetchResult:
        return _two_tweets_fetch()

    captured: dict[str, object] = {}

    async def fake_judge(session: object, tenant_id: object, **kwargs: object) -> RelevanceVerdict:
        captured.update(kwargs)
        return RelevanceVerdict(relevant=[True, False], batches=1, failed_batches=0, dropped=1)

    monkeypatch.setattr(tenant_twitter, "fetch_tweets", fake_fetch)
    monkeypatch.setattr(tenant_twitter, "judge_tweet_relevance", fake_judge)

    r = _post(
        batch_client,
        token,
        {
            "term": "karaca tencere, -cem karaca",
            "count": 50,
            "exclude_handle": "@karacaonline",
            "brand_summary": "Ev eşyası markası.",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["found"] == 1
    assert body["fetched_total"] == 5
    assert body["filtered_out"] == 3
    assert body["filtered_by_ai"] == 1
    assert body["ai_check_skipped"] is False
    # Hakem HAM metni görür (mention atılmamış), plan bağlamı geçer.
    assert captured["tweets"] == [
        "@karacaonline tencerenin dibi tuttu",
        "Cem Karaca konseri harikaydı",
    ]
    assert captured["brand"] == "karaca tencere"
    assert captured["include"] == ["karaca tencere"]
    assert captured["exclude"] == ["cem karaca"]
    assert captured["handle"] == "karacaonline"
    assert captured["brand_summary"] == "Ev eşyası markası."

    job = await fetch_job(admin_session, UUID(body["job"]["job_id"]))
    with Path(job.file_path).open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))
    assert rows[1][0] == "tencerenin dibi tuttu"
    assert len(rows) == 2
    assert job.file_name == "twitter-karaca-tencere.csv"


@pytest.mark.asyncio
async def test_twitter_import_relevance_check_off_skips_judge(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    _enable_key(batch_client)

    async def fake_fetch(**kwargs: object) -> TwitterFetchResult:
        return _two_tweets_fetch()

    async def judge_must_not_run(*args: object, **kwargs: object) -> RelevanceVerdict:
        raise AssertionError("judge çağrılmamalıydı")

    monkeypatch.setattr(tenant_twitter, "fetch_tweets", fake_fetch)
    monkeypatch.setattr(tenant_twitter, "judge_tweet_relevance", judge_must_not_run)

    r = _post(batch_client, token, {"term": "karaca", "relevance_check": False})
    assert r.status_code == 201, r.text
    assert r.json()["found"] == 2
    assert r.json()["filtered_by_ai"] == 0


@pytest.mark.asyncio
async def test_twitter_import_no_llm_key_skips_judge_but_imports(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    _enable_key(batch_client)

    async def fake_fetch(**kwargs: object) -> TwitterFetchResult:
        return _two_tweets_fetch()

    async def no_keys(*args: object, **kwargs: object) -> RelevanceVerdict:
        raise NoCredentialsError("yok")

    monkeypatch.setattr(tenant_twitter, "fetch_tweets", fake_fetch)
    monkeypatch.setattr(tenant_twitter, "judge_tweet_relevance", no_keys)

    r = _post(batch_client, token, {"term": "karaca"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["found"] == 2
    assert body["ai_check_skipped"] is True


@pytest.mark.asyncio
async def test_twitter_import_all_dropped_by_ai_is_422_with_counts(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    _enable_key(batch_client)

    async def fake_fetch(**kwargs: object) -> TwitterFetchResult:
        return _two_tweets_fetch()

    async def drop_all(session: object, tenant_id: object, **kwargs: object) -> RelevanceVerdict:
        return RelevanceVerdict(relevant=[False, False], batches=1, failed_batches=0, dropped=2)

    monkeypatch.setattr(tenant_twitter, "fetch_tweets", fake_fetch)
    monkeypatch.setattr(tenant_twitter, "judge_tweet_relevance", drop_all)

    r = _post(batch_client, token, {"term": "karaca"})
    assert r.status_code == 422, r.text
    assert "2 gönderi çekildi" in r.json()["detail"]


@pytest.mark.asyncio
async def test_twitter_import_empty_fetch_422_carries_counts(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    _enable_key(batch_client)

    async def fake_fetch(**kwargs: object) -> TwitterFetchResult:
        return TwitterFetchResult(
            tweets=[], fetched_total=40, pages=2, exhausted=True, filtered_out=40
        )

    monkeypatch.setattr(tenant_twitter, "fetch_tweets", fake_fetch)
    r = _post(batch_client, token, {"term": "karaca"})
    assert r.status_code == 422, r.text
    assert "40 gönderi çekildi, 40 tanesi" in r.json()["detail"]


# --- /plan ------------------------------------------------------------


@pytest.mark.asyncio
async def test_twitter_plan_returns_term_and_query_preview(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)

    async def fake_plan(session: object, tenant_id: object, **kwargs: object) -> BrandSearchPlan:
        assert kwargs["brand"] == "Karaca"
        assert kwargs["handle"] == "karacaonline"
        return BrandSearchPlan(
            brand="Karaca",
            brand_summary="Züccaciye ve ev tekstili markası.",
            include=["karaca tencere", "@karacaonline"],
            exclude=["cem karaca", "hidayet karaca"],
            handle="karacaonline",
            bare_name_ambiguous=True,
            notes="Soyadı olarak yaygın.",
        )

    monkeypatch.setattr(tenant_twitter, "plan_brand_search", fake_plan)
    r = _post_plan(batch_client, token, {"brand": "  Karaca ", "handle": "karacaonline"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["term"] == "karaca tencere, @karacaonline, -cem karaca, -hidayet karaca"
    assert body["query_preview"] == (
        '("karaca tencere" OR @karacaonline) -"cem karaca" -"hidayet karaca" '
        "-from:karacaonline lang:tr -filter:retweets"
    )
    assert body["bare_name_ambiguous"] is True
    assert body["handle"] == "karacaonline"


@pytest.mark.asyncio
async def test_twitter_plan_without_llm_key_is_412(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)

    async def no_keys(*args: object, **kwargs: object) -> BrandSearchPlan:
        raise NoCredentialsError("yok")

    monkeypatch.setattr(tenant_twitter, "plan_brand_search", no_keys)
    r = _post_plan(batch_client, token, {"brand": "Karaca"})
    assert r.status_code == 412, r.text
    assert r.json()["detail"]["code"] == "no_llm_credentials"


@pytest.mark.asyncio
async def test_twitter_import_all_negative_terms_is_422(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    _enable_key(batch_client)
    r = _post(batch_client, token, {"term": "-cem karaca, -hidayet karaca"})
    assert r.status_code == 422, r.text


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
        return TwitterFetchResult(tweets=[], fetched_total=0, pages=1, exhausted=True)

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
