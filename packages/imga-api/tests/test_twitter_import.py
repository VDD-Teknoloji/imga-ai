""" "Twitter'dan Çek" entegrasyonu — route seviyesi testler.

Gerçek twitterapi.io çağrısı yok: ``fetch_tweets``/``judge_tweet_relevance``
``imga_api.workers.twitter_fetch`` üzerinden monkeypatch'lenir (ARTIK route
modülünde değil — 2026-09-02'den beri o zincir arka planda koşuyor). Kapsam:
  * 503 — IMGA_TWITTERAPI_IO_KEY yapılandırılmamış
  * 202 — mutlu yol: POST anında job_id döner, arka plan işi (elle
    tetiklenir — ``_run_twitter_fetch_worker``) CSV'yi diske yazar +
    Redis ilerleme kaydını "done"a taşır
  * GET .../jobs/{job_id} — queued/running/done/failed anlık durumu
  * 422 — sorgu sözdizimi geçersiz (POST'ta hâlâ senkron doğrulanır)
  * arka planda: no_results / no_relevant_results → status="failed"
  * 403 — viewer rolü yazamaz
  * birim — build_search_query / clean_tweet_text / is_collab_hashtag /
    fetch_tweets'in on_page kancası
"""

from __future__ import annotations

import csv
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from imga_db.models import User, UserTenantRole
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.cache.redis_client import set_redis_client
from imga_api.main import app
from imga_api.routes import tenant_twitter
from imga_api.services import AuditService, UserService
from imga_api.services.llm_credentials import NoCredentialsError
from imga_api.services.twitter_brand_service import BrandSearchPlan, RelevanceVerdict
from imga_api.services.twitter_import import (
    SearchTerms,
    TwitterFetchProgress,
    TwitterFetchResult,
    TwitterTweet,
    build_search_query,
    clean_tweet_text,
    fetch_tweets,
    is_collab_hashtag,
    parse_search_terms,
    parse_tweet_created_at,
    tweet_matches_terms,
    tweet_url_from_item,
)
from imga_api.workers import batch_analyzer, twitter_fetch
from tests.batch_helpers import fetch_job, login_token

# --- Redis ilerleme HASH'i — event-loop'a bağlı olmayan stub ----------
#
# route testleri Redis'e İKİ FARKLI event loop'tan dokunur: POST/GET
# TestClient'ın kendi BlockingPortal loop'unda (init_job/read_job),
# ``_run_twitter_fetch_worker`` ise testin KENDİ loop'unda (update_*/
# mark_* — worker'ın taze WorkerContext'i test loop'una bağlı, bkz.
# o fonksiyonun docstring'i). fakeredis'in bağlantıları oluşturuldukları
# loop'a bağlıdır; ikinci loop'tan kullanmak "Future attached to a
# different loop" ile patlar (MEMORY.md: "SSE tüketicisine polling
# emniyeti şart" dersiyle aynı köke sahip önceki bir kesinti —
# tenant_twitter git geçmişindeki 4d9d3e8 committeki döngü-bağımsız
# Redis stub deseni; ikiz bir kopyası test_root_cause_overview.py'de).
# Bu yüzden fakeredis DEĞİL, bellek-içi düz bir sözlükle çalışan minik
# bir stub kullanılır — hangi loop'tan çağrıldığı önemsiz.


class _StubRedis:
    """``workers/twitter_fetch.py``'ın kullandığı tek komut kümesi:
    HASH (hset mapping=, expire, hgetall). Event-loop'a bağlı hiçbir
    kaynak açmaz."""

    def __init__(self) -> None:
        self._hashes: dict[str, dict[bytes, bytes]] = {}

    async def hset(self, key: str, mapping: dict[str, object] | None = None) -> int:
        bucket = self._hashes.setdefault(key, {})
        added = 0
        for field, value in (mapping or {}).items():
            field_b = field.encode() if isinstance(field, str) else field
            if field_b not in bucket:
                added += 1
            bucket[field_b] = str(value).encode()
        return added

    async def expire(self, key: str, seconds: int) -> bool:
        del seconds
        return key in self._hashes

    async def hgetall(self, key: str) -> dict[bytes, bytes]:
        return dict(self._hashes.get(key, {}))


@pytest.fixture(autouse=True)
def _twitter_fetch_redis_stub() -> Any:
    """Bu dosyadaki HER test için process-singleton Redis client'ı
    döngü-bağımsız bir stub'a çevirir; birim testler Redis'e hiç
    dokunmadığından etkilenmez, route testleri için ise şart."""
    set_redis_client(_StubRedis())
    yield
    set_redis_client(None)


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


def test_tweet_url_from_item_strips_handle_via_id() -> None:
    # KVKK: id sayısalsa hesap adı hiç okunmaz, url alanı yok sayılır.
    assert (
        tweet_url_from_item({"url": "https://x.com/handle/status/1", "id": "1"})
        == "https://x.com/i/web/status/1"
    )
    assert tweet_url_from_item({"id": "2092540287411159128"}) == (
        "https://x.com/i/web/status/2092540287411159128"
    )


def test_tweet_url_from_item_extracts_id_from_url_when_id_missing() -> None:
    # id eksik/sayısal değilse url'deki status id'si regex ile çıkarılır
    # ama hesap adı ("handle" kısmı) sonuca hiç taşınmaz.
    assert (
        tweet_url_from_item({"url": "https://x.com/handle/status/42", "id": "abc"})
        == "https://x.com/i/web/status/42"
    )
    assert (
        tweet_url_from_item({"url": "https://twitter.com/handle/status/7"})
        == "https://x.com/i/web/status/7"
    )
    assert tweet_url_from_item({"url": "https://x.com/handle/status/not-a-number"}) is None
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
                # Migration 0049 — engagement counts, one absent
                # (replyCount) and one malformed (viewCount) to hit the
                # None path alongside the happy-path ints.
                "likeCount": 12,
                "retweetCount": 3,
                "viewCount": "not-a-number",
            },
            {
                "id": "3",
                "text": "Karaca'nın porselenleri gerçekten kaliteli",
                "createdAt": "2026-08-26T08:00:00Z",
                "likeCount": 0,
                "retweetCount": 0,
                "replyCount": 0,
                "viewCount": 99,
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
    # id alanı sayısal olduğundan, item["url"]'deki "musteri" hesap
    # adı çıktıya hiç taşınmaz (KVKK) — her iki gönderi de kanonik,
    # hesap adı içermeyen bağlantıyla döner.
    assert result.tweets[0].url == "https://x.com/i/web/status/2"
    assert result.tweets[1].url == "https://x.com/i/web/status/3"
    assert result.tweets[1].created_at == datetime(2026, 8, 26, 8, 0, tzinfo=UTC)
    # Migration 0049 — likeCount/retweetCount parsed; absent replyCount
    # and malformed viewCount both fall back to None (tolerant, never
    # raises). Second tweet: all four counts present, including the
    # legitimate 0 case (must NOT be confused with "absent").
    assert result.tweets[0].like_count == 12
    assert result.tweets[0].retweet_count == 3
    assert result.tweets[0].reply_count is None
    assert result.tweets[0].view_count is None
    assert result.tweets[1].like_count == 0
    assert result.tweets[1].retweet_count == 0
    assert result.tweets[1].reply_count == 0
    assert result.tweets[1].view_count == 99


# --- birim: #işbirliği/#reklam ön-filtresi ---------------------------


@pytest.mark.parametrize(
    "tag",
    [
        "işbirliği",
        "İşbirliği",
        "ISBIRLIGI",
        "reklam",
        "REKLAM",
        "sponsor",
        "sponsorlu",
        "Sponsorlu",
    ],
)
def test_is_collab_hashtag_matches_case_and_diacritic_variants(tag: str) -> None:
    assert is_collab_hashtag(f"Bu ürün harika #{tag}")


def test_is_collab_hashtag_does_not_match_reklamsiz() -> None:
    # "#reklamsız" ("reklamsız" = reklam yok) markayla ilgili meşru bir
    # gönderi olabilir — startswith değil, tam eşleşme kuralı.
    assert not is_collab_hashtag("Bu ürün #reklamsız gerçekten iyi")


def test_is_collab_hashtag_ignores_two_word_phrase() -> None:
    # "iş birliği" iki ayrı kelime bir hashtag'e hiç giremez (#\w+ boşluk
    # üzerinden eşleşmez) — sıradan bir cümlede yanlış pozitif üretmez.
    assert not is_collab_hashtag("Bu markayla iş birliği yaptık, çok iyi gitti")


def test_is_collab_hashtag_false_without_hashtag() -> None:
    assert not is_collab_hashtag("Karaca ürünü harika, tavsiye ederim")


@pytest.mark.asyncio
async def test_fetch_tweets_excludes_collab_hashtag_before_relevance_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """İşbirliği etiketli gönderi hakeme hiç gitmeden ``excluded_collab``a
    sayılır — aynı gönderi konu dışı da olsa ``filtered_out``a DEĞİL."""
    page = {
        "tweets": [
            {
                "id": "1",
                "text": "Karaca ürünü harika #işbirliği",
                "createdAt": "2026-08-26T08:00:00Z",
            },
            {"id": "2", "text": "Karaca ürünü berbat geldi", "createdAt": "2026-08-26T09:00:00Z"},
        ],
        "has_next_page": False,
        "next_cursor": "",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=page)

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def patched_client(**kwargs: object) -> httpx.AsyncClient:
        return real_client(transport=transport, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(httpx, "AsyncClient", patched_client)

    result = await fetch_tweets(api_key="k", term="karaca", count=10)
    assert result.excluded_collab == 1
    assert result.filtered_out == 0
    assert [t.text for t in result.tweets] == ["Karaca ürünü berbat geldi"]


@pytest.mark.asyncio
async def test_fetch_tweets_on_page_hook_reports_running_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``on_page`` her sayfa sonunda (son sayfa dahil) bir kez çağrılır;
    en eski/en yeni tarih çalışırken güncellenir."""
    pages = [
        {
            "tweets": [
                {"id": "1", "text": "Karaca ürünü harika", "createdAt": "2026-08-20T10:00:00Z"}
            ],
            "has_next_page": True,
            "next_cursor": "c2",
        },
        {
            "tweets": [
                {"id": "2", "text": "Karaca kargo geç geldi", "createdAt": "2026-08-25T10:00:00Z"}
            ],
            "has_next_page": False,
            "next_cursor": "",
        },
    ]
    responses = iter(pages)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=next(responses))

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def patched_client(**kwargs: object) -> httpx.AsyncClient:
        return real_client(transport=transport, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(httpx, "AsyncClient", patched_client)

    snapshots: list[TwitterFetchProgress] = []

    async def on_page(progress: TwitterFetchProgress) -> None:
        snapshots.append(progress)

    result = await fetch_tweets(api_key="k", term="karaca", count=10, on_page=on_page)
    assert [s.pages_done for s in snapshots] == [1, 2]
    assert snapshots[-1].tweets_found == 2
    assert snapshots[-1].oldest_tweet_at == datetime(2026, 8, 20, 10, 0, tzinfo=UTC)
    assert snapshots[-1].newest_tweet_at == datetime(2026, 8, 25, 10, 0, tzinfo=UTC)
    assert result.oldest_tweet_at == snapshots[-1].oldest_tweet_at
    assert result.newest_tweet_at == snapshots[-1].newest_tweet_at


@pytest.mark.asyncio
async def test_fetch_tweets_on_page_hook_exception_is_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kanca bir istisna fırlatsa bile çekim durmaz, sonuç eksiksiz döner."""
    page = {
        "tweets": [{"id": "1", "text": "Karaca ürünü harika", "createdAt": "2026-08-26T08:00:00Z"}],
        "has_next_page": False,
        "next_cursor": "",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=page)

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def patched_client(**kwargs: object) -> httpx.AsyncClient:
        return real_client(transport=transport, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(httpx, "AsyncClient", patched_client)

    async def bad_hook(progress: TwitterFetchProgress) -> None:
        raise RuntimeError("boom")

    result = await fetch_tweets(api_key="k", term="karaca", count=10, on_page=bad_hook)
    assert len(result.tweets) == 1


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


def _get_job(client: TestClient, token: str, job_id: UUID | str) -> httpx.Response:
    return client.get(
        f"/tenants/me/analyze/twitter-import/jobs/{job_id}",
        headers={"Authorization": f"Bearer {token}"},
    )


async def _run_twitter_fetch_worker(client: TestClient, entry: dict[str, Any]) -> None:
    """``RecordingScheduler``'ın yakaladığı ``process_twitter_fetch_job``
    çağrısını (route'un arq'sız APScheduler yedeği — bkz. ``batch_client``
    fixture'ının hiç ``arq_pool`` kurmaması) test'in KENDİ event loop'una
    bağlı taze bir ``WorkerContext`` ile koştur.

    ``batch_helpers.run_worker`` ile AYNI gerekçe: yakalanan
    ``app.state.batch_worker_context`` TestClient'ın BlockingPortal
    loop'una bağlı — doğrudan await etmek 'Future attached to a
    different loop' ile patlar. ``entry["kwargs"]["args"]``'daki
    ``payload`` düz bir dataclass (event loop'a bağlı hiçbir kaynak
    taşımaz), bu yüzden loop'lar arası güvenle taşınabilir; yalnız
    context'i taze kurmak yeterli."""
    call_args = entry["kwargs"]["args"]
    call_kwargs = entry["kwargs"]["kwargs"]
    job_id, tenant_id, payload, _stale_context = call_args
    api_key = call_kwargs["api_key"]

    test_app = client.app  # type: ignore[attr-defined]
    pipeline = test_app.state.pipeline
    cache = test_app.state.tenant_config_cache
    settings = test_app.state.settings.batch
    context = await batch_analyzer.build_worker_context(
        pipeline=pipeline,
        tenant_config_cache=cache,
        settings=settings,
    )
    try:
        await twitter_fetch.process_twitter_fetch_job(
            job_id, tenant_id, payload, context, api_key=api_key
        )
    finally:
        await context.dispose()


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
                url="https://x.com/i/web/status/1",
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
        *,
        api_key: str,
        term: str,
        count: int,
        exclude_handle: str | None = None,
        on_page: object = None,
    ) -> TwitterFetchResult:
        assert api_key == "test-key"
        assert term == "Navlungo"
        assert count == 100
        return TwitterFetchResult(
            tweets=[
                TwitterTweet(
                    text="kargo çok iyi geldi",
                    created_at=datetime(2026, 5, 12, 8, 15, tzinfo=UTC),
                    url="https://x.com/i/web/status/123",
                ),
                TwitterTweet(text="teslimat kötü ve geç", created_at=None),
            ],
            fetched_total=3,
            pages=1,
            exhausted=True,
            filtered_out=1,
        )

    monkeypatch.setattr(twitter_fetch, "fetch_tweets", fake_fetch)
    monkeypatch.setattr(twitter_fetch, "judge_tweet_relevance", _keep_all_judge)

    r = _post(batch_client, token, {"term": "Navlungo", "count": 100})
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] == "queued"
    job_id = body["job_id"]

    # POST ANINDA henüz hiçbir şey çekilmedi — iş "queued" görünür.
    status_body = _get_job(batch_client, token, job_id).json()
    assert status_body["status"] == "queued"
    assert status_body["requested"] == 100

    scheduler = app.state.batch_scheduler
    assert len(scheduler.added) == 1
    await _run_twitter_fetch_worker(batch_client, scheduler.added[-1])

    status_body = _get_job(batch_client, token, job_id).json()
    assert status_body["status"] == "done"
    assert status_body["tweets_found"] == 2
    assert status_body["kept_after_filter"] == 2
    assert status_body["exhausted"] is True
    assert status_body["filtered_out"] == 1
    assert status_body["excluded_collab"] == 0
    assert status_body["fetched_total"] == 3
    assert status_body["filtered_by_ai"] == 0
    assert status_body["ai_check_skipped"] is False
    batch_job_id = status_body["batch_job_id"]
    assert batch_job_id is not None

    # Dosya şablon kolonlarıyla diske inmiş olmalı — worker'ın
    # okuyacağı gerçek CSV.
    job = await fetch_job(admin_session, UUID(batch_job_id))
    assert job.status == "queued"
    assert job.total_rows == 2
    assert job.text_column == "yorum"
    assert job.source_column == "kaynak"
    assert job.file_name == "twitter-navlungo.csv"
    file_path = Path(job.file_path)
    assert file_path.exists()
    with file_path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))
    assert rows[0] == [
        "yorum",
        "tarih",
        "kaynak",
        "bağlantı",
        "beğeni",
        "retweet",
        "yanıt",
        "görüntülenme",
    ]
    assert rows[1] == [
        "kargo çok iyi geldi",
        "2026-05-12T08:15:00+00:00",
        "twitter",
        "https://x.com/i/web/status/123",
        "",
        "",
        "",
        "",
    ]
    # Tarihi çözülemeyen tweet boş 'tarih' hücresiyle iner — parser
    # bunu None'a çevirir, satır yine analiz edilir. Bağlantısız tweet
    # de boş 'bağlantı' hücresiyle iner; bu fake_fetch hiçbir sayaç
    # vermediği için dört yeni kolon da boş kalır (migration 0049).
    assert rows[2] == ["teslimat kötü ve geç", "", "twitter", "", "", "", "", ""]
    assert len(rows) == 3


@pytest.mark.asyncio
async def test_twitter_import_dispatches_via_arq_when_available_and_never_leaks_api_key(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    """arq bağlıysa ONUN üzerinden kuyruklanır (in-process yedeğe hiç
    düşülmez) ve sır (api key) arq argümanlarında ASLA taşınmaz — işçi
    kendi ortamından okur (bkz. workers/twitter_fetch.py)."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    _enable_key(batch_client)

    test_app = batch_client.app  # type: ignore[attr-defined]
    arq_pool = AsyncMock()
    arq_pool.enqueue_job.return_value = SimpleNamespace(job_id="arq-job-1")
    test_app.state.arq_pool = arq_pool
    try:
        r = _post(batch_client, token, {"term": "Navlungo", "count": 50})
        assert r.status_code == 202, r.text
        job_id = r.json()["job_id"]

        arq_pool.enqueue_job.assert_awaited_once()
        call_args, call_kwargs = arq_pool.enqueue_job.call_args
        assert call_args[0] == "process_twitter_fetch_task"
        assert call_args[1] == job_id
        assert call_args[2] == str(tid)
        assert call_args[3] == "Navlungo"
        assert call_args[4] == 50
        assert "test-key" not in call_args
        assert call_kwargs["_job_id"] == f"twitter-fetch:{job_id}"
        assert call_kwargs["_queue_name"] == "imga-batch"

        # arq yolu alındı — in-process yedeğe HİÇ düşülmedi.
        assert app.state.batch_scheduler.added == []
    finally:
        test_app.state.arq_pool = None


@pytest.mark.asyncio
async def test_twitter_fetch_job_status_404_when_unknown(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = _get_job(batch_client, token, uuid4())
    assert r.status_code == 404, r.text


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

    monkeypatch.setattr(twitter_fetch, "fetch_tweets", fake_fetch)
    monkeypatch.setattr(twitter_fetch, "judge_tweet_relevance", fake_judge)

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
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]
    await _run_twitter_fetch_worker(batch_client, app.state.batch_scheduler.added[-1])

    status_body = _get_job(batch_client, token, job_id).json()
    assert status_body["status"] == "done"
    assert status_body["kept_after_filter"] == 1
    assert status_body["fetched_total"] == 5
    assert status_body["filtered_out"] == 3
    assert status_body["filtered_by_ai"] == 1
    assert status_body["ai_check_skipped"] is False
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

    job = await fetch_job(admin_session, UUID(status_body["batch_job_id"]))
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

    monkeypatch.setattr(twitter_fetch, "fetch_tweets", fake_fetch)
    monkeypatch.setattr(twitter_fetch, "judge_tweet_relevance", judge_must_not_run)

    r = _post(batch_client, token, {"term": "karaca", "relevance_check": False})
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]
    await _run_twitter_fetch_worker(batch_client, app.state.batch_scheduler.added[-1])

    status_body = _get_job(batch_client, token, job_id).json()
    assert status_body["status"] == "done"
    assert status_body["kept_after_filter"] == 2
    assert status_body["filtered_by_ai"] == 0
    assert status_body["ai_check_skipped"] is False


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

    monkeypatch.setattr(twitter_fetch, "fetch_tweets", fake_fetch)
    monkeypatch.setattr(twitter_fetch, "judge_tweet_relevance", no_keys)

    r = _post(batch_client, token, {"term": "karaca"})
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]
    await _run_twitter_fetch_worker(batch_client, app.state.batch_scheduler.added[-1])

    status_body = _get_job(batch_client, token, job_id).json()
    assert status_body["status"] == "done"
    assert status_body["kept_after_filter"] == 2
    assert status_body["ai_check_skipped"] is True


@pytest.mark.asyncio
async def test_twitter_import_all_dropped_by_ai_marks_job_failed(
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

    monkeypatch.setattr(twitter_fetch, "fetch_tweets", fake_fetch)
    monkeypatch.setattr(twitter_fetch, "judge_tweet_relevance", drop_all)

    r = _post(batch_client, token, {"term": "karaca"})
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]
    await _run_twitter_fetch_worker(batch_client, app.state.batch_scheduler.added[-1])

    status_body = _get_job(batch_client, token, job_id).json()
    assert status_body["status"] == "failed"
    assert status_body["error"] == "no_relevant_results"
    assert status_body["kept_after_filter"] == 0
    # Donmuş fetch-aşaması sayısı: 2 gönderi çekildi, hakem HEPSİNİ
    # eledi — 0 değil (analyze.twitter.noRelevantError "{found} gönderi
    # çekildi ama..." mesajı bu alanı okur).
    assert status_body["tweets_found"] == 2
    assert status_body["batch_job_id"] is None


@pytest.mark.asyncio
async def test_twitter_import_empty_fetch_marks_job_failed_with_counts(
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

    monkeypatch.setattr(twitter_fetch, "fetch_tweets", fake_fetch)
    r = _post(batch_client, token, {"term": "karaca"})
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]
    await _run_twitter_fetch_worker(batch_client, app.state.batch_scheduler.added[-1])

    status_body = _get_job(batch_client, token, job_id).json()
    assert status_body["status"] == "failed"
    assert status_body["error"] == "no_results"
    assert status_body["fetched_total"] == 40
    assert status_body["filtered_out"] == 40


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
async def test_twitter_import_empty_results_marks_job_failed(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    _enable_key(batch_client)

    async def fake_fetch(
        *,
        api_key: str,
        term: str,
        count: int,
        exclude_handle: str | None = None,
        on_page: object = None,
    ) -> TwitterFetchResult:
        return TwitterFetchResult(tweets=[], fetched_total=0, pages=1, exhausted=True)

    monkeypatch.setattr(twitter_fetch, "fetch_tweets", fake_fetch)

    # POST hâlâ ANINDA 202 döner — çekim henüz hiç çalışmadı, sonuç
    # yalnız arka plan işi koştuktan SONRA "failed" olarak görülür.
    r = _post(batch_client, token, {"term": "hiçsonuçyokterim"})
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]
    await _run_twitter_fetch_worker(batch_client, app.state.batch_scheduler.added[-1])

    status_body = _get_job(batch_client, token, job_id).json()
    assert status_body["status"] == "failed"
    assert status_body["error"] == "no_results"


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
