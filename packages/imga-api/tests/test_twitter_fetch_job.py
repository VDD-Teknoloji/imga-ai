"""``workers/twitter_fetch.py``'ın Redis ilerleme HASH'i — pure-unit.

2026-09-02. ``test_root_cause_autogen.py`` ile aynı desen: gerçek
Postgres/HTTP yok, ``fakeredis.aioredis.FakeRedis`` ile
``set_redis_client`` üzerinden process-singleton'ı değiştiriyoruz.
Kapsam:
  * ``init_job``/``read_job`` — başlangıç anlık durumu, eksik anahtar
    için ``None``.
  * ``update_fetch_progress``/``update_judge_progress`` — aşama
    geçişleri (queued→running, stage alanları).
  * ``mark_done``/``mark_failed`` — terminal yazımlar, opsiyonel
    sayaçların kısmi geçirilmesi.
  * "0"/"1"/"" kodlamasının None'dan ayrımı (``exhausted=False`` gibi
    "yanlış ama BİLİNEN" bir değerin None'a düşmemesi kritik).
  * en-iyi-çaba sözleşmesi: ``init_job`` bir Redis hatasını PROPAGATE
    eder (route bunu 503'e çevirir); diğer tüm yazım fonksiyonları
    yutar (arka plan işini asla durdurmaz).

Route seviyesi testler (POST 202 + GET poll akışı) ``test_twitter_
import.py``'de — bunlar Postgres (:5433) gerektirir, burada değil.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from imga_api.cache.redis_client import set_redis_client
from imga_api.workers import twitter_fetch

# ---------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------


@pytest.fixture
def fake_redis() -> Any:
    import fakeredis.aioredis as fakeredis_async

    fake = fakeredis_async.FakeRedis(decode_responses=False)
    set_redis_client(fake)
    yield fake
    set_redis_client(None)


class _BrokenRedis:
    """Her komutta patlayan sahte Redis — en-iyi-çaba/propagate
    ayrımını doğrulamak için (gerçek fakeredis'e ihtiyaç yok)."""

    async def hset(self, *args: object, **kwargs: object) -> None:
        raise RuntimeError("redis unavailable")

    async def expire(self, *args: object, **kwargs: object) -> None:
        raise RuntimeError("redis unavailable")

    async def hgetall(self, *args: object, **kwargs: object) -> None:
        raise RuntimeError("redis unavailable")


# ---------------------------------------------------------------------
# init_job / read_job
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_init_job_writes_queued_snapshot(fake_redis: Any) -> None:
    tenant_id, job_id = uuid4(), uuid4()
    await twitter_fetch.init_job(tenant_id, job_id, requested=250)
    snapshot = await twitter_fetch.read_job(tenant_id, job_id)
    assert snapshot is not None
    assert snapshot.status == "queued"
    assert snapshot.stage is None
    assert snapshot.requested == 250
    assert snapshot.tweets_found == 0
    assert snapshot.pages_done == 0
    assert snapshot.fetched_total == 0
    assert snapshot.filtered_out == 0
    assert snapshot.excluded_collab == 0
    assert snapshot.oldest_tweet_at is None
    assert snapshot.newest_tweet_at is None
    assert snapshot.exhausted is None
    assert snapshot.kept_after_filter is None
    assert snapshot.filtered_by_ai is None
    assert snapshot.ai_check_skipped is None
    assert snapshot.batch_job_id is None
    assert snapshot.error is None


@pytest.mark.asyncio
async def test_read_job_returns_none_for_missing_key(fake_redis: Any) -> None:
    assert await twitter_fetch.read_job(uuid4(), uuid4()) is None


@pytest.mark.asyncio
async def test_read_job_is_scoped_per_tenant_and_job(fake_redis: Any) -> None:
    """Farklı tenant ya da farklı job_id, aynı hash'i GÖREMEZ — GET
    ucunun 404'e düşmesi buna dayanır (bkz. route docstring'i)."""
    tenant_id, job_id = uuid4(), uuid4()
    await twitter_fetch.init_job(tenant_id, job_id, requested=10)
    assert await twitter_fetch.read_job(uuid4(), job_id) is None
    assert await twitter_fetch.read_job(tenant_id, uuid4()) is None
    assert await twitter_fetch.read_job(tenant_id, job_id) is not None


# ---------------------------------------------------------------------
# update_fetch_progress / update_judge_progress
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_fetch_progress_moves_to_running(fake_redis: Any) -> None:
    tenant_id, job_id = uuid4(), uuid4()
    await twitter_fetch.init_job(tenant_id, job_id, requested=100)
    oldest = datetime(2026, 8, 20, 10, 0, tzinfo=UTC)
    newest = datetime(2026, 8, 25, 10, 0, tzinfo=UTC)

    await twitter_fetch.update_fetch_progress(
        tenant_id,
        job_id,
        stage="fetching",
        tweets_found=5,
        pages_done=2,
        fetched_total=8,
        filtered_out=2,
        excluded_collab=1,
        oldest_tweet_at=oldest,
        newest_tweet_at=newest,
    )

    snapshot = await twitter_fetch.read_job(tenant_id, job_id)
    assert snapshot is not None
    assert snapshot.status == "running"
    assert snapshot.stage == "fetching"
    assert snapshot.tweets_found == 5
    assert snapshot.pages_done == 2
    assert snapshot.fetched_total == 8
    assert snapshot.filtered_out == 2
    assert snapshot.excluded_collab == 1
    assert snapshot.oldest_tweet_at == oldest
    assert snapshot.newest_tweet_at == newest
    # requested init_job'dan korunur — bu yazım onu ellemez.
    assert snapshot.requested == 100


@pytest.mark.asyncio
async def test_update_judge_progress_sets_finalizing_stage(fake_redis: Any) -> None:
    tenant_id, job_id = uuid4(), uuid4()
    await twitter_fetch.init_job(tenant_id, job_id, requested=10)

    await twitter_fetch.update_judge_progress(
        tenant_id, job_id, kept_after_filter=3, filtered_by_ai=2, ai_check_skipped=False
    )

    snapshot = await twitter_fetch.read_job(tenant_id, job_id)
    assert snapshot is not None
    assert snapshot.status == "running"
    assert snapshot.stage == "finalizing"
    assert snapshot.kept_after_filter == 3
    assert snapshot.filtered_by_ai == 2
    assert snapshot.ai_check_skipped is False


# ---------------------------------------------------------------------
# mark_done / mark_failed — terminal yazımlar
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_done_writes_terminal_snapshot(fake_redis: Any) -> None:
    tenant_id, job_id, batch_job_id = uuid4(), uuid4(), uuid4()
    await twitter_fetch.init_job(tenant_id, job_id, requested=10)

    await twitter_fetch.mark_done(
        tenant_id,
        job_id,
        batch_job_id=batch_job_id,
        requested=10,
        found=8,
        exhausted=True,
        fetched_total=12,
        filtered_out=3,
        excluded_collab=1,
        filtered_by_ai=0,
        ai_check_skipped=False,
    )

    snapshot = await twitter_fetch.read_job(tenant_id, job_id)
    assert snapshot is not None
    assert snapshot.status == "done"
    assert snapshot.stage is None
    assert snapshot.batch_job_id == batch_job_id
    assert snapshot.kept_after_filter == 8
    assert snapshot.exhausted is True
    assert snapshot.fetched_total == 12
    assert snapshot.filtered_out == 3
    assert snapshot.excluded_collab == 1
    assert snapshot.error is None


@pytest.mark.asyncio
async def test_mark_done_never_overwrites_frozen_tweets_found(fake_redis: Any) -> None:
    """``tweets_found`` hakem BAŞLARKEN donar (fetch-aşaması sayısı);
    ``mark_done``'un ``found`` (hakem SONRASI kalan) sayısı bu alanı
    ASLA ezmemeli — yoksa "kaç tanesi hakemde elendi" bilgisi
    (tweets_found - kept_after_filter) kaybolur. ``update_fetch_progress``
    + ``update_judge_progress`` çağrılarının GERÇEK sırasını taklit
    eder (bkz. ``workers/twitter_fetch._run``)."""
    tenant_id, job_id, batch_job_id = uuid4(), uuid4(), uuid4()
    await twitter_fetch.init_job(tenant_id, job_id, requested=10)
    # Hakem başlamadan önce: 6 gönderi fetch aşamasını geçti.
    await twitter_fetch.update_fetch_progress(
        tenant_id,
        job_id,
        stage="judging",
        tweets_found=6,
        pages_done=1,
        fetched_total=10,
        filtered_out=4,
        excluded_collab=0,
        oldest_tweet_at=None,
        newest_tweet_at=None,
    )
    # Hakem 4'ünü eledi, 2 kaldı.
    await twitter_fetch.update_judge_progress(
        tenant_id, job_id, kept_after_filter=2, filtered_by_ai=4, ai_check_skipped=False
    )
    await twitter_fetch.mark_done(
        tenant_id,
        job_id,
        batch_job_id=batch_job_id,
        requested=10,
        found=2,
        exhausted=True,
        fetched_total=10,
        filtered_out=4,
        excluded_collab=0,
        filtered_by_ai=4,
        ai_check_skipped=False,
    )

    snapshot = await twitter_fetch.read_job(tenant_id, job_id)
    assert snapshot is not None
    assert snapshot.tweets_found == 6  # donmuş, hakem öncesi
    assert snapshot.kept_after_filter == 2  # nihai, hakem sonrası


@pytest.mark.asyncio
async def test_mark_failed_writes_error_and_partial_counts(fake_redis: Any) -> None:
    tenant_id, job_id = uuid4(), uuid4()
    await twitter_fetch.init_job(tenant_id, job_id, requested=10)

    await twitter_fetch.mark_failed(
        tenant_id,
        job_id,
        error="no_results",
        fetched_total=40,
        filtered_out=40,
        excluded_collab=0,
        tweets_found=0,
    )

    snapshot = await twitter_fetch.read_job(tenant_id, job_id)
    assert snapshot is not None
    assert snapshot.status == "failed"
    assert snapshot.error == "no_results"
    assert snapshot.fetched_total == 40
    assert snapshot.filtered_out == 40
    assert snapshot.batch_job_id is None


@pytest.mark.asyncio
async def test_mark_failed_without_counts_leaves_earlier_values(fake_redis: Any) -> None:
    """``fetch_failed`` gibi ilk-sayfa hatalarında hiç sayaç yoktur —
    ``mark_failed`` bunları opsiyonel bırakır, ``init_job``'un
    sıfırladığı değerler korunur (üzerine yazılmaz)."""
    tenant_id, job_id = uuid4(), uuid4()
    await twitter_fetch.init_job(tenant_id, job_id, requested=10)

    await twitter_fetch.mark_failed(tenant_id, job_id, error="fetch_failed")

    snapshot = await twitter_fetch.read_job(tenant_id, job_id)
    assert snapshot is not None
    assert snapshot.status == "failed"
    assert snapshot.error == "fetch_failed"
    assert snapshot.fetched_total == 0


@pytest.mark.asyncio
async def test_exhausted_false_decodes_as_false_not_none(fake_redis: Any) -> None:
    """ "0"/"1"/"" kodlaması None'dan ayırt etmeli — ``exhausted=False``
    (bilinen ve YANLIŞ) ``None`` (hiç bilinmiyor) ile karışmamalı."""
    tenant_id, job_id, batch_job_id = uuid4(), uuid4(), uuid4()
    await twitter_fetch.init_job(tenant_id, job_id, requested=10)

    await twitter_fetch.mark_done(
        tenant_id,
        job_id,
        batch_job_id=batch_job_id,
        requested=10,
        found=5,
        exhausted=False,
        fetched_total=5,
        filtered_out=0,
        excluded_collab=0,
        filtered_by_ai=0,
        ai_check_skipped=False,
    )

    snapshot = await twitter_fetch.read_job(tenant_id, job_id)
    assert snapshot is not None
    assert snapshot.exhausted is False
    assert snapshot.ai_check_skipped is False


# ---------------------------------------------------------------------
# en-iyi-çaba sözleşmesi — init_job PROPAGATE eder, geri kalanı YUTAR
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_init_job_propagates_redis_failure() -> None:
    """POST'un 503'e çevirebilmesi için ``init_job`` hatası yutulmaz —
    izlenemeyen bir iş asla kuyruğa alınmamalı."""
    set_redis_client(_BrokenRedis())
    try:
        with pytest.raises(RuntimeError):
            await twitter_fetch.init_job(uuid4(), uuid4(), requested=100)
    finally:
        set_redis_client(None)


@pytest.mark.asyncio
async def test_update_fetch_progress_swallows_redis_failure() -> None:
    set_redis_client(_BrokenRedis())
    try:
        await twitter_fetch.update_fetch_progress(
            uuid4(),
            uuid4(),
            stage="fetching",
            tweets_found=1,
            pages_done=1,
            fetched_total=1,
            filtered_out=0,
            excluded_collab=0,
            oldest_tweet_at=None,
            newest_tweet_at=None,
        )
    finally:
        set_redis_client(None)


@pytest.mark.asyncio
async def test_update_judge_progress_swallows_redis_failure() -> None:
    set_redis_client(_BrokenRedis())
    try:
        await twitter_fetch.update_judge_progress(
            uuid4(), uuid4(), kept_after_filter=1, filtered_by_ai=0, ai_check_skipped=False
        )
    finally:
        set_redis_client(None)


@pytest.mark.asyncio
async def test_mark_done_swallows_redis_failure() -> None:
    """AnalyzeBatchJob zaten Postgres'e yazılmış olabilir — bir Redis
    hatası burada asla arka plan işini geç çökertmemeli."""
    set_redis_client(_BrokenRedis())
    try:
        await twitter_fetch.mark_done(
            uuid4(),
            uuid4(),
            batch_job_id=uuid4(),
            requested=1,
            found=1,
            exhausted=True,
            fetched_total=1,
            filtered_out=0,
            excluded_collab=0,
            filtered_by_ai=0,
            ai_check_skipped=False,
        )
    finally:
        set_redis_client(None)


@pytest.mark.asyncio
async def test_mark_failed_swallows_redis_failure() -> None:
    set_redis_client(_BrokenRedis())
    try:
        await twitter_fetch.mark_failed(uuid4(), uuid4(), error="internal_error")
    finally:
        set_redis_client(None)
