"""Arka plan "Twitter'dan Çek" işi + Redis ilerleme durumu.

2026-09-02. ``routes/tenant_twitter.py``'daki ``import_from_twitter``
ÖNCEDEN fetch→hakem→CSV→kuyruklama zincirinin TAMAMINI tek istek/yanıt
içinde, senkron koşturuyordu — 1000 gönderilik bir çekim ~1-3+ dakika
sürebiliyor, tarayıcı bu süre boyunca yalnız düğme spinner'ı görüyordu
(sayı yok, sayfa yok, ilerleme yok). Bu modül o zinciri arq'ın
``imga-batch`` kuyruğuna taşır (``process_twitter_fetch_task``) ve
ilerlemeyi bir Redis HASH'e yazar (``twitter_fetch:{tenant_id}:{job_id}``)
— web tarafı 2sn'lik düz GET polling ile okur (SSE değil; prod'da
Cloudflare'in 100sn boşta-kesme sınırını hiç görmez, MEMORY.md'deki
"SSE tüketicisine polling emniyeti şart" dersiyle de tutarlı).

İlerleme yazımları ``root_cause_autogen.py``'daki desenle AYNI en-iyi-
çaba sözleşmesini taşır: bir Redis hatası loglanır + yutulur, ÇEKİMİ
ASLA durdurmaz — bu yalnız bir UI ipucu. İSTİSNA iki uç: ``init_job``
(POST anında çağrılır; hatası PROPAGATE eder ki route izlenemeyen bir
işi kuyruğa hiç almasın) ve terminal yazımlar ``mark_done``/
``mark_failed`` (yine yutulur ama ERROR seviyesinde loglanır — bu
noktada ``AnalyzeBatchJob`` zaten Postgres'e kalıcı yazılmış olabilir,
"içe aktarma başarısız" değil "ilerleme izleme koptu" doğru hikâyedir).

TTL kademeleri ``root_cause_autogen.py`` ile aynı mantıkla seçildi,
tek fark: ``arq_worker.WorkerSettings.max_jobs`` bu değişiklikle HÂLÂ
1 (bkz. modülün alt kısmındaki ``process_twitter_fetch_task`` notu) —
yani büyük bir BERT batch'i kuyrukta öndeyse bu iş onun ARKASINDA
FIFO bekler, ``job_timeout`` (4h) kadar. "queued" TTL'i bu yüzden
``root_cause_autogen``'ın 60dk'lık enqueue-TTL'inden çok daha uzun:
``job_timeout`` ile eşit (14400s) — yoksa kuyrukta uzun bekleyen bir
iş, gerçekten çalışmaya başlamadan TTL'i dolup 404/jobLost'a düşer.

Alaka hakemi (``judge_tweet_relevance``) tek bir ``asyncio.gather``
ile TÜM partileri aynı anda bekler — partiler arası kısmi sinyal
yoktur. Bu yüzden ``stage="judging"`` süresince ilerleme SABİT kalır
(web tarafı bunu belirsiz/pulsing bir durum olarak gösterir); burada
YENİ bir parça-parça hakem kancası eklenmedi — 20-50sn'lik bekleme
için gereksiz karmaşıklık olurdu.

İki aşamalı kuyruklama: bu görevin kendisi (``process_twitter_fetch_task``)
ile CSV/iş satırı hazır olduktan SONRA tetiklenen normal batch analizi
(``process_batch_task``) AYRI arq işleridir — ikinci enqueue
``workers/batch_analyzer.py``'daki ``_enqueue_root_cause_auto_gen``
ile BİREBİR aynı çağrı şeklini kullanır (``context.arq_pool.
enqueue_job(...)`` doğrudan, FastAPI ``app`` nesnesine hiç dokunmadan
— bir worker görevinin içinden ``app.state`` erişilemez). ``context.
arq_pool`` None ise (arq bağlı değilse) bu ikinci enqueue best-effort
NO-OP'tur — ``_enqueue_root_cause_auto_gen``'ın zaten kabul ettiği aynı
sınır: arq'sız bir dağıtımda bu özelliğin ikinci aşaması elle
tetiklenmelidir, testlerde bu ``run_worker`` benzeri bir yardımcıyla
elle yapılır (bkz. ``tests/test_twitter_import.py``).
"""

from __future__ import annotations

import csv
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from imga_db import set_current_tenant
from imga_db.models import AnalyzeBatchJob
from sqlalchemy import update

from imga_api.cache.redis_client import get_redis_client
from imga_api.services import AuditService, BatchAnalyzeService
from imga_api.services.llm_credentials import NoCredentialsError
from imga_api.services.twitter_brand_service import judge_tweet_relevance
from imga_api.services.twitter_import import (
    TwitterFetchError,
    TwitterFetchProgress,
    TwitterTweet,
    fetch_tweets,
    parse_search_terms,
)
from imga_api.settings import Settings
from imga_api.workers.batch_analyzer import WorkerContext

_logger = logging.getLogger("imga-api.workers.twitter_fetch")

# ===========================================================================
# Redis ilerleme HASH'i — "twitter_fetch:{tenant_id}:{job_id}"
# ===========================================================================

_KEY_PREFIX = "twitter_fetch"
# max_jobs=1 tek-işçili FIFO'da büyük bir batch önde olabilir —
# job_timeout'la eşit tutmak, iş gerçekten başlamadan "queued" TTL'inin
# dolup 404/jobLost'a düşmesini önler (bkz. modül docstring'i).
_QUEUED_TTL_SECONDS = 14400
# Worker fiilen başladıktan sonra: her ilerleme yazımı bunu yeniler,
# tek bir sayfa/parti arasındaki en uzun boşluktan kat kat büyük.
_RUNNING_TTL_SECONDS = 30 * 60
# Terminal snapshot — geç bir sayfa yenilemesi bile son durumu görsün.
_TERMINAL_TTL_SECONDS = 24 * 60 * 60


def _key(tenant_id: UUID, job_id: UUID) -> str:
    return f"{_KEY_PREFIX}:{tenant_id}:{job_id}"


def _enc_opt_int(value: int | None) -> str:
    return "" if value is None else str(value)


def _enc_opt_bool(value: bool | None) -> str:
    if value is None:
        return ""
    return "1" if value else "0"


def _enc_opt_dt(value: datetime | None) -> str:
    return "" if value is None else value.isoformat()


def _dec_bytes(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return "" if value is None else str(value)


def _dec_int(raw: str, default: int = 0) -> int:
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _dec_opt_int(raw: str) -> int | None:
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _dec_opt_bool(raw: str) -> bool | None:
    if raw == "":
        return None
    return raw == "1"


def _dec_opt_dt(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _dec_opt_str(raw: str) -> str | None:
    return raw or None


@dataclass(frozen=True, slots=True)
class TwitterFetchJobSnapshot:
    """``read_job``'ın döndürdüğü anlık durum — ``GET .../jobs/{job_id}``
    yanıt gövdesinin ``job_id`` dışındaki tamamı."""

    status: str
    stage: str | None
    requested: int
    tweets_found: int
    pages_done: int
    fetched_total: int
    filtered_out: int
    excluded_collab: int
    oldest_tweet_at: datetime | None
    newest_tweet_at: datetime | None
    exhausted: bool | None
    kept_after_filter: int | None
    filtered_by_ai: int | None
    ai_check_skipped: bool | None
    batch_job_id: UUID | None
    error: str | None


async def init_job(tenant_id: UUID, job_id: UUID, *, requested: int) -> None:
    """POST anında çağrılır — HATA burada BİLEREK yutulmaz: yazımı
    başarısız olan bir iş kuyruğa hiç alınmamalı (route bunu 503'e
    çevirir), aksi halde ilk GET poll hiçbir zaman bulamayacağı bir
    işi 404'lerdi."""
    client = get_redis_client()
    key = _key(tenant_id, job_id)
    mapping = {
        "status": "queued",
        "stage": "",
        "requested": str(requested),
        "tweets_found": "0",
        "pages_done": "0",
        "fetched_total": "0",
        "filtered_out": "0",
        "excluded_collab": "0",
        "oldest_tweet_at": "",
        "newest_tweet_at": "",
        "exhausted": "",
        "kept_after_filter": "",
        "filtered_by_ai": "",
        "ai_check_skipped": "",
        "batch_job_id": "",
        "error": "",
    }
    await client.hset(key, mapping=mapping)
    await client.expire(key, _QUEUED_TTL_SECONDS)


async def update_fetch_progress(
    tenant_id: UUID,
    job_id: UUID,
    *,
    stage: str,
    tweets_found: int,
    pages_done: int,
    fetched_total: int,
    filtered_out: int,
    excluded_collab: int,
    oldest_tweet_at: datetime | None,
    newest_tweet_at: datetime | None,
) -> None:
    """Çekim (``fetching``) ya da hakem (``judging``) aşamasındaki
    anlık durum. En-iyi-çaba: bir Redis hatası loglanır + yutulur,
    çekimi asla durdurmaz."""
    try:
        client = get_redis_client()
        key = _key(tenant_id, job_id)
        mapping = {
            "status": "running",
            "stage": stage,
            "tweets_found": str(tweets_found),
            "pages_done": str(pages_done),
            "fetched_total": str(fetched_total),
            "filtered_out": str(filtered_out),
            "excluded_collab": str(excluded_collab),
            "oldest_tweet_at": _enc_opt_dt(oldest_tweet_at),
            "newest_tweet_at": _enc_opt_dt(newest_tweet_at),
        }
        await client.hset(key, mapping=mapping)
        await client.expire(key, _RUNNING_TTL_SECONDS)
    except Exception:
        _logger.warning(
            "twitter fetch progress: update_fetch_progress failed (non-fatal)",
            extra={"tenant_id": str(tenant_id), "job_id": str(job_id)},
            exc_info=True,
        )


async def update_judge_progress(
    tenant_id: UUID,
    job_id: UUID,
    *,
    kept_after_filter: int,
    filtered_by_ai: int,
    ai_check_skipped: bool,
) -> None:
    """Hakem sonuçlandığında (ya da ``relevance_check=False`` ile hiç
    çalışmadığında) bir kez çağrılır; ardından CSV yazımı + iş
    oluşturma + kuyruklama (``finalizing``) başlar. En-iyi-çaba."""
    try:
        client = get_redis_client()
        key = _key(tenant_id, job_id)
        mapping = {
            "status": "running",
            "stage": "finalizing",
            "kept_after_filter": str(kept_after_filter),
            "filtered_by_ai": str(filtered_by_ai),
            "ai_check_skipped": "1" if ai_check_skipped else "0",
        }
        await client.hset(key, mapping=mapping)
        await client.expire(key, _RUNNING_TTL_SECONDS)
    except Exception:
        _logger.warning(
            "twitter fetch progress: update_judge_progress failed (non-fatal)",
            extra={"tenant_id": str(tenant_id), "job_id": str(job_id)},
            exc_info=True,
        )


async def mark_done(
    tenant_id: UUID,
    job_id: UUID,
    *,
    batch_job_id: UUID,
    requested: int,
    found: int,
    exhausted: bool,
    fetched_total: int,
    filtered_out: int,
    excluded_collab: int,
    filtered_by_ai: int,
    ai_check_skipped: bool,
) -> None:
    """Terminal yazım — ``AnalyzeBatchJob`` zaten Postgres'e kalıcı
    yazıldıktan SONRA çağrılır, bu yüzden bir hata burada ERROR
    seviyesinde loglanır (sessiz değil) ama yine de yutulur: geç
    kalan bir sayfa yenilemesi "içe aktarma başarısız" yerine "iş
    zaten kuyrukta, Toplu Yüklemeler'e bak" görmeli."""
    try:
        client = get_redis_client()
        key = _key(tenant_id, job_id)
        mapping = {
            "status": "done",
            "stage": "",
            "batch_job_id": str(batch_job_id),
            "requested": str(requested),
            # tweets_found BİLEREK burada YAZILMAZ — hakem başlarken
            # dondurulan (fetch-aşaması) değer kalır; kept_after_filter
            # nihai (hakem sonrası) sayıyı taşır. Aynı alanı ikisiyle
            # de doldurmak "kaç tanesi hakemde elendi" bilgisini
            # kaybettirirdi (bkz. update_fetch_progress/update_judge_progress).
            "kept_after_filter": str(found),
            "exhausted": "1" if exhausted else "0",
            "fetched_total": str(fetched_total),
            "filtered_out": str(filtered_out),
            "excluded_collab": str(excluded_collab),
            "filtered_by_ai": str(filtered_by_ai),
            "ai_check_skipped": "1" if ai_check_skipped else "0",
            "error": "",
        }
        await client.hset(key, mapping=mapping)
        await client.expire(key, _TERMINAL_TTL_SECONDS)
    except Exception:
        _logger.exception(
            "twitter fetch progress: mark_done write failed (non-fatal; "
            "AnalyzeBatchJob %s already persisted)",
            batch_job_id,
            extra={"tenant_id": str(tenant_id), "job_id": str(job_id)},
        )


async def mark_failed(
    tenant_id: UUID,
    job_id: UUID,
    *,
    error: str,
    fetched_total: int | None = None,
    filtered_out: int | None = None,
    excluded_collab: int | None = None,
    tweets_found: int | None = None,
) -> None:
    """Terminal yazım — hata kodu tam olarak ``"fetch_failed"`` |
    ``"no_results"`` | ``"no_relevant_results"`` | ``"internal_error"``.
    Aynı ``mark_done`` gibi ERROR seviyesinde loglanır + yutulur."""
    try:
        client = get_redis_client()
        key = _key(tenant_id, job_id)
        mapping: dict[str, str] = {
            "status": "failed",
            "stage": "",
            "error": error,
        }
        if fetched_total is not None:
            mapping["fetched_total"] = str(fetched_total)
        if filtered_out is not None:
            mapping["filtered_out"] = str(filtered_out)
        if excluded_collab is not None:
            mapping["excluded_collab"] = str(excluded_collab)
        if tweets_found is not None:
            mapping["tweets_found"] = str(tweets_found)
        await client.hset(key, mapping=mapping)
        await client.expire(key, _TERMINAL_TTL_SECONDS)
    except Exception:
        _logger.exception(
            "twitter fetch progress: mark_failed write failed (non-fatal; error=%s)",
            error,
            extra={"tenant_id": str(tenant_id), "job_id": str(job_id)},
        )


async def read_job(tenant_id: UUID, job_id: UUID) -> TwitterFetchJobSnapshot | None:
    """``GET .../jobs/{job_id}`` için anlık durumu oku. HASH hiç yoksa
    (hiç var olmadı ya da TTL doldu) ``None`` — route bunu 404'e
    çevirir. Redis'in kendisi ulaşılamazsa istisna PROPAGATE eder: bu
    uç için Redis tek gerçek kaynaktır, sessizce None dönmek "iş yok"
    ile "okunamadı"yı karıştırırdı."""
    client = get_redis_client()
    raw = await client.hgetall(_key(tenant_id, job_id))
    if not raw:
        return None
    decoded = {_dec_bytes(k): _dec_bytes(v) for k, v in raw.items()}
    return TwitterFetchJobSnapshot(
        status=decoded.get("status") or "queued",
        stage=_dec_opt_str(decoded.get("stage", "")),
        requested=_dec_int(decoded.get("requested", "")),
        tweets_found=_dec_int(decoded.get("tweets_found", "")),
        pages_done=_dec_int(decoded.get("pages_done", "")),
        fetched_total=_dec_int(decoded.get("fetched_total", "")),
        filtered_out=_dec_int(decoded.get("filtered_out", "")),
        excluded_collab=_dec_int(decoded.get("excluded_collab", "")),
        oldest_tweet_at=_dec_opt_dt(decoded.get("oldest_tweet_at", "")),
        newest_tweet_at=_dec_opt_dt(decoded.get("newest_tweet_at", "")),
        exhausted=_dec_opt_bool(decoded.get("exhausted", "")),
        kept_after_filter=_dec_opt_int(decoded.get("kept_after_filter", "")),
        filtered_by_ai=_dec_opt_int(decoded.get("filtered_by_ai", "")),
        ai_check_skipped=_dec_opt_bool(decoded.get("ai_check_skipped", "")),
        batch_job_id=(UUID(decoded["batch_job_id"]) if decoded.get("batch_job_id") else None),
        error=_dec_opt_str(decoded.get("error", "")),
    )


# ===========================================================================
# İşin kendisi
# ===========================================================================


@dataclass(frozen=True, slots=True)
class TwitterFetchPayload:
    """arq üzerinden taşınan (ya da APScheduler yedeğinde doğrudan
    geçirilen) sabit girdi. ``twitterapi_io_key`` BİLEREK burada değil
    — bir sır Redis'in iş kuyruğunda kalıcı yazılmaz; arq yolunda
    işçi kendi ortam değişkeninden okur (bkz. ``process_twitter_fetch_task``),
    APScheduler yedeğinde route zaten elindeki değeri doğrudan
    ``process_twitter_fetch_job``'a ayrı bir argüman olarak geçirir."""

    term: str
    count: int
    exclude_handle: str | None
    auto_create_tickets: bool
    relevance_check: bool
    brand_summary: str | None
    actor_user_id: UUID
    client_ip: str | None


async def process_twitter_fetch_job(
    job_id: UUID,
    tenant_id: UUID,
    payload: TwitterFetchPayload,
    context: WorkerContext,
    *,
    api_key: str,
) -> None:
    """``routes/tenant_twitter.py``'nin eski senkron gövdesinin arka
    plan karşılığı: fetch → (açıksa) hakem → CSV → ``AnalyzeBatchJob``
    → alt batch analizini kuyrukla. Her adım kendi hata kodunu
    ``mark_failed``e yazar; sınıflandırılamayan herhangi bir istisna
    ``internal_error`` olarak yakalanır + loglanır + RAISE edilir (arq
    kendi retry/görünürlük mekanizması için — ``process_batch_task``
    ile aynı sözleşme)."""
    try:
        await _run(job_id, tenant_id, payload, context, api_key=api_key)
    except Exception:
        _logger.exception(
            "twitter fetch job: unhandled failure",
            extra={"tenant_id": str(tenant_id), "job_id": str(job_id)},
        )
        await mark_failed(tenant_id, job_id, error="internal_error")
        raise


async def _run(
    job_id: UUID,
    tenant_id: UUID,
    payload: TwitterFetchPayload,
    context: WorkerContext,
    *,
    api_key: str,
) -> None:
    terms = parse_search_terms(payload.term)
    brand = terms.positive[0] if terms.positive else payload.term.strip()

    async def _on_page(progress: TwitterFetchProgress) -> None:
        await update_fetch_progress(
            tenant_id,
            job_id,
            stage="fetching",
            tweets_found=progress.tweets_found,
            pages_done=progress.pages_done,
            fetched_total=progress.fetched_total,
            filtered_out=progress.filtered_out,
            excluded_collab=progress.excluded_collab,
            oldest_tweet_at=progress.oldest_tweet_at,
            newest_tweet_at=progress.newest_tweet_at,
        )

    await update_fetch_progress(
        tenant_id,
        job_id,
        stage="fetching",
        tweets_found=0,
        pages_done=0,
        fetched_total=0,
        filtered_out=0,
        excluded_collab=0,
        oldest_tweet_at=None,
        newest_tweet_at=None,
    )

    try:
        result = await fetch_tweets(
            api_key=api_key,
            term=payload.term,
            count=payload.count,
            exclude_handle=payload.exclude_handle,
            on_page=_on_page,
        )
    except TwitterFetchError:
        _logger.warning(
            "twitter fetch job: fetch failed for term=%r (tenant=%s)",
            payload.term,
            tenant_id,
        )
        await mark_failed(tenant_id, job_id, error="fetch_failed")
        return

    if not result.tweets:
        await mark_failed(
            tenant_id,
            job_id,
            error="no_results",
            fetched_total=result.fetched_total,
            filtered_out=result.filtered_out,
            excluded_collab=result.excluded_collab,
            tweets_found=0,
        )
        return

    tweets: list[TwitterTweet] = list(result.tweets)
    filtered_by_ai = 0
    ai_check_skipped = False

    # Bu yazım KOŞULSUZ: gerçek fetch_tweets zaten on_page ile aynı
    # sayıları yazmış olur, ama test'lerdeki sahte fetch_tweets'ler
    # on_page'i hiç çağırmayabilir — Redis'in fetch-aşaması son
    # durumu her koşulda ``result``'un kendisinden doğru yansımalı.
    # ``tweets_found`` burada DONAR: relevance_check açıksa hakem
    # başlamadan ÖNCEKİ sayı, kapalıysa zaten nihai sayı (ikisi de
    # ``len(tweets)`` bu noktada — hakem henüz tweets'i filtrelemedi).
    await update_fetch_progress(
        tenant_id,
        job_id,
        stage="judging" if payload.relevance_check else "fetching",
        tweets_found=len(tweets),
        pages_done=result.pages,
        fetched_total=result.fetched_total,
        filtered_out=result.filtered_out,
        excluded_collab=result.excluded_collab,
        oldest_tweet_at=result.oldest_tweet_at,
        newest_tweet_at=result.newest_tweet_at,
    )

    if payload.relevance_check:
        try:
            async with context.app_session_factory() as session, session.begin():
                await set_current_tenant(session, tenant_id)
                verdict = await judge_tweet_relevance(
                    session,
                    tenant_id,
                    brand=brand,
                    brand_summary=(payload.brand_summary or "").strip() or None,
                    include=list(terms.positive),
                    exclude=list(terms.negative),
                    handle=payload.exclude_handle,
                    tweets=[t.raw_text or t.text for t in tweets],
                    actor_user_id=payload.actor_user_id,
                )
        except NoCredentialsError:
            ai_check_skipped = True
            _logger.info(
                "twitter fetch job: tenant=%s has no LLM key; AI relevance check skipped",
                tenant_id,
            )
        else:
            if verdict.batches and verdict.failed_batches == verdict.batches:
                ai_check_skipped = True
            tweets = [t for t, ok in zip(tweets, verdict.relevant, strict=True) if ok]
            filtered_by_ai = verdict.dropped

    await update_judge_progress(
        tenant_id,
        job_id,
        kept_after_filter=len(tweets),
        filtered_by_ai=filtered_by_ai,
        ai_check_skipped=ai_check_skipped,
    )

    if not tweets:
        # tweets_found BURADA 0 DEĞİL: hakem çalışmadan önce
        # ``len(result.tweets)`` kadar gönderi vardı, hepsini hakem
        # eledi — "kaç çekildi ama hiçbiri alakalı çıkmadı" mesajı
        # (analyze.twitter.noRelevantError) bu sayıyı okur, 0 değil.
        await mark_failed(
            tenant_id,
            job_id,
            error="no_relevant_results",
            fetched_total=result.fetched_total,
            filtered_out=result.filtered_out,
            excluded_collab=result.excluded_collab,
            tweets_found=len(result.tweets),
        )
        return

    # Şablonla birebir aynı kolonlar — bkz. eski route gövdesindeki
    # aynı yorum (tenant_twitter.py git geçmişi, 2026-09-02 öncesi).
    dir_id = job_id
    job_dir = context.settings.upload_dir / str(tenant_id) / str(dir_id)
    job_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", brand.lower()).strip("-") or "arama"
    file_name = f"twitter-{slug}.csv"
    file_path = job_dir / file_name
    with file_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            ["yorum", "tarih", "kaynak", "bağlantı", "beğeni", "retweet", "yanıt", "görüntülenme"]
        )
        for tweet in tweets:
            posted = tweet.created_at.isoformat() if tweet.created_at else ""
            writer.writerow(
                [
                    tweet.text,
                    posted,
                    "twitter",
                    tweet.url or "",
                    tweet.like_count if tweet.like_count is not None else "",
                    tweet.retweet_count if tweet.retweet_count is not None else "",
                    tweet.reply_count if tweet.reply_count is not None else "",
                    tweet.view_count if tweet.view_count is not None else "",
                ]
            )
    file_size = file_path.stat().st_size

    async with context.app_session_factory() as session, session.begin():
        await set_current_tenant(session, tenant_id)
        service = BatchAnalyzeService(session, AuditService(session))
        batch_job = await service.create_job(
            tenant_id=tenant_id,
            triggered_by_user_id=payload.actor_user_id,
            file_name=file_name,
            file_size_bytes=file_size,
            file_path=str(file_path),
            text_column="yorum",
            source_column="kaynak",
            auto_create_tickets=payload.auto_create_tickets,
            total_rows=len(tweets),
            ip_address=payload.client_ip,
        )
        batch_job_id = batch_job.id

    # İkinci aşama kuyruklama — ``_enqueue_root_cause_auto_gen`` ile
    # birebir aynı çağrı şekli (bkz. modül docstring'i). arq bağlı
    # değilse en-iyi-çaba NO-OP: bu iş satırı Postgres'e zaten yazıldı,
    # yalnız kimse tetiklemez (aynı sınır root-cause auto-gen'de de
    # var).
    if context.arq_pool is not None:
        try:
            dispatched = await context.arq_pool.enqueue_job(
                "process_batch_task",
                str(batch_job_id),
                str(tenant_id),
                _job_id=f"batch:{batch_job_id}",
                _queue_name="imga-batch",
            )
        except Exception:
            _logger.exception(
                "twitter fetch job: downstream batch enqueue failed (non-fatal)",
                extra={"tenant_id": str(tenant_id), "batch_job_id": str(batch_job_id)},
            )
        else:
            if dispatched is not None:
                worker_job_id = getattr(dispatched, "job_id", None)
                queued_at = datetime.now(UTC)
                async with context.app_session_factory() as session, session.begin():
                    await set_current_tenant(session, tenant_id)
                    await session.execute(
                        update(AnalyzeBatchJob)
                        .where(AnalyzeBatchJob.id == batch_job_id)
                        .values(worker_job_id=worker_job_id, queued_at=queued_at)
                    )
    else:
        _logger.warning(
            "twitter fetch job: no arq_pool wired; AnalyzeBatchJob %s created "
            "but not dispatched (non-arq deploy — requires manual/scheduled "
            "processing)",
            batch_job_id,
            extra={"tenant_id": str(tenant_id)},
        )

    _logger.info(
        "twitter fetch job done: tenant=%s term=%r found=%d/%d pages=%d "
        "fetched=%d filtered_out=%d excluded_collab=%d filtered_by_ai=%d "
        "ai_skipped=%s batch_job_id=%s",
        tenant_id,
        payload.term,
        len(tweets),
        payload.count,
        result.pages,
        result.fetched_total,
        result.filtered_out,
        result.excluded_collab,
        filtered_by_ai,
        ai_check_skipped,
        batch_job_id,
    )
    await mark_done(
        tenant_id,
        job_id,
        batch_job_id=batch_job_id,
        requested=payload.count,
        found=len(tweets),
        exhausted=result.exhausted,
        fetched_total=result.fetched_total,
        filtered_out=result.filtered_out,
        excluded_collab=result.excluded_collab,
        filtered_by_ai=filtered_by_ai,
        ai_check_skipped=ai_check_skipped,
    )


async def process_twitter_fetch_task(
    ctx: dict[str, Any],
    job_id: str,
    tenant_id: str,
    term: str,
    count: int,
    exclude_handle: str | None,
    auto_create_tickets: bool,
    relevance_check: bool,
    brand_summary: str | None,
    actor_user_id: str,
    client_ip: str | None,
) -> None:
    """arq görev girişi — ``process_batch_task`` ile aynı ince
    sarmalayıcı şekli (``arq_worker.py``). ``twitterapi_io_key``
    işçinin KENDİ ortamından okunur (``Settings.from_env()``) — arq
    argümanları Redis'e yazılır, bir sır orada kalıcı taşınmaz."""
    worker_context: WorkerContext = ctx["worker_context"]
    jid = UUID(job_id)
    tid = UUID(tenant_id)
    api_key = Settings.from_env().twitterapi_io_key
    if not api_key:
        _logger.error(
            "arq twitter-fetch task: IMGA_TWITTERAPI_IO_KEY not set in worker "
            "environment despite route-time check passing",
            extra={"job_id": job_id, "tenant_id": tenant_id},
        )
        await mark_failed(tid, jid, error="internal_error")
        return
    payload = TwitterFetchPayload(
        term=term,
        count=count,
        exclude_handle=exclude_handle,
        auto_create_tickets=auto_create_tickets,
        relevance_check=relevance_check,
        brand_summary=brand_summary,
        actor_user_id=UUID(actor_user_id),
        client_ip=client_ip,
    )
    try:
        await process_twitter_fetch_job(jid, tid, payload, worker_context, api_key=api_key)
    except Exception:
        _logger.exception(
            "arq twitter-fetch task failed",
            extra={"job_id": job_id, "tenant_id": tenant_id},
        )
        raise


__all__ = [
    "TwitterFetchJobSnapshot",
    "TwitterFetchPayload",
    "init_job",
    "mark_done",
    "mark_failed",
    "process_twitter_fetch_job",
    "process_twitter_fetch_task",
    "read_job",
    "update_fetch_progress",
    "update_judge_progress",
]
