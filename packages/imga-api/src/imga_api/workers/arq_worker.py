"""arq-backed background batch worker.

Sprint 9.0.5-A. Today's incident: a 2852-row CSV upload sat at
``processed_rows=0`` for 21 minutes while the API container itself
stopped serving /reviews / /insights — the in-process APScheduler
ran BERT inference on the same event loop as the request handlers,
and the sync transformers C extension never yielded.

The fix has two layers (both shipped this sprint):

  1. ``asyncio.to_thread`` wrap on the BERT call — the API event
     loop stays responsive even when worker + API share a process
     (tests still take this single-process path, so the ``run_worker``
     fixture exercises the freeze regression without arq).
  2. This module — production runs the worker as a separate arq
     process container. The API container only enqueues + serves
     reads; BERT inference happens elsewhere. Even a wedged worker
     process can't take the API down.

The arq task signature mirrors the legacy ``process_batch_job(job_id,
context)`` so the underlying job-execution logic stays in one place.
``WorkerContext`` is built once at worker startup with a pipeline pool
sized for ``chunk_concurrency`` parallel chunks (B3).

logger.exception() in every catch path — Sprint 8.3.6.6 round-3
baseline note.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from datetime import time as dt_time
from typing import Any
from uuid import UUID

from arq import cron
from arq.connections import RedisSettings
from cachetools import TTLCache
from imga_db import set_current_tenant
from imga_db.models import Review
from sqlalchemy import func, select

from imga_api.cache.redis_client import get_redis_client
from imga_api.dependencies import build_pipeline
from imga_api.services.root_cause_autogen import mark_finished, mark_started
from imga_api.services.root_cause_service import (
    NoCredentialsError,
    RootCauseService,
    day_rounded_window,
    pick_top_categories,
)
from imga_api.settings import Settings
from imga_api.workers.batch_analyzer import (
    WorkerContext,
    build_worker_context,
    process_batch_job,
    recover_orphans,
)
from imga_api.workers.email_outbox_worker import (
    email_outbox_tick,
    sla_breach_tick,
)
from imga_api.workers.scheduled_briefings import scheduled_briefing_tick

#: Tenant genelinde bu eşiğin altında yorum varsa auto-gen hiç
#: denenmez — küçük/yeni tenant'ta 90 günlük pencere zaten MIN_REVIEWS
#: eşiğini geçemez, sorguyu boşuna koşturmamak için erken çıkış.
_AUTO_GEN_MIN_TENANT_REVIEWS = 50
#: Bir turda en fazla kaç (kategori, perspektif) çifti üretilir.
_AUTO_GEN_TOP_N = 3
#: Tetikleyen batch'in başarılı satır sayısı bu eşiğin altındaysa
#: force_refresh HİÇBİR ZAMAN True geçilmez — küçük tekrar-yüklemeler
#: 12h cache'e çarpıp ücretsiz kalsın diye (bkz. generate_root_causes_task
#: docstring'i, "maliyet kuralı").
_AUTO_GEN_FORCE_REFRESH_MIN_ROWS = 200

_logger = logging.getLogger("imga-api.workers.arq")

# Sprint 9.0.5-A — pool size for parallel chunks. 4 BERT model
# instances ≈ 1.5 GiB; the prod api-worker container is sized at 2G
# so this fits with a margin. If a future deploy bumps this, mirror
# the change in the worker compose service's memory limit.
_DEFAULT_CHUNK_CONCURRENCY = 4


def _redis_settings() -> RedisSettings:
    """Parse REDIS_URL into the arq-shaped settings tuple. Falls back
    to the same default the cache module uses (``redis://redis:6379/0``)
    so worker + API talk to the same instance without separate env
    vars."""
    url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    return RedisSettings.from_dsn(url)


async def process_batch_task(
    ctx: dict[str, Any],
    job_id: str,
    tenant_id: str,
) -> None:
    """arq task entry. Delegates to ``process_batch_job`` with the
    long-lived WorkerContext built at startup. arq passes job ids as
    strings over Redis so we re-hydrate to UUID here.

    ``tenant_id`` is logged but not used for routing — the
    ``process_batch_job`` function reads tenant_id from the job row
    itself (single source of truth). We accept it as an arg so logs +
    arq's own job introspection can show the tenant without a DB
    lookup."""
    worker_context = ctx["worker_context"]
    try:
        await process_batch_job(UUID(job_id), worker_context)
    except Exception:
        _logger.exception(
            "arq batch task failed",
            extra={"job_id": job_id, "tenant_id": tenant_id},
        )
        raise


async def process_reanalysis_task(
    ctx: dict[str, Any],
    job_id: str,
    tenant_id: str,
) -> None:
    """2026-08-10 — yeniden analiz görevi. ``process_batch_task`` ile
    aynı sözleşme (aynı kuyruk, aynı startup'ta kurulan
    ``WorkerContext``); tek fark çağrılan işçi fonksiyonu."""
    from imga_api.workers.reanalyzer import process_reanalysis_job

    worker_context = ctx["worker_context"]
    try:
        await process_reanalysis_job(UUID(job_id), worker_context)
    except Exception:
        _logger.exception(
            "arq reanalysis task failed",
            extra={"job_id": job_id, "tenant_id": tenant_id},
        )
        raise


async def generate_root_causes_task(
    ctx: dict[str, Any],
    tenant_id: str,
    rows_succeeded: int = 0,
    batch_job_id: str | None = None,
) -> None:
    """Sprint 13.x+ — post-batch otomatik kök neden üretimi.

    ``process_batch_task`` ile aynı ``WorkerContext``'i paylaşır (arq
    startup'ta bir kez kurulur). Akış:

      1. Tenant genelinde ``_AUTO_GEN_MIN_TENANT_REVIEWS``'in altında
         yorum varsa hiç denenmez (küçük tenant'ta pencere zaten
         MIN_REVIEWS eşiğini geçemez).
      2. Gün-yuvarlanmış 90 günlük pencere (``day_rounded_window``) —
         aynı gün içindeki tekrar eden batch'ler aynı tuple'a düşer,
         böylece ``RootCauseService``'in 12s cache'i gerçekten dedup
         eder (bkz. ``day_rounded_window`` docstring'i).
      3. En fazla ``_AUTO_GEN_TOP_N`` (kategori, en kötü perspektif)
         çifti seçilir (``pick_top_categories`` — GET /root-cause/
         overview'in kullandığı AYNI sorgu). ``can_generate=False``
         (perspektif yok ya da kova eşiğin altında) olan çiftler
         atlanır.
      4. Her çift KENDİ transaction'ında; bir kategori başarısız olursa
         diğerlerini etkilemez, hata loglanır + yutulur (batch zaten
         başarıyla tamamlandı, bu arka plan zenginleştirmesi onu asla
         geriye alamaz).

    Maliyet kuralı (2026-09) — ``force_refresh`` artık SABİT False
    DEĞİL: ``rows_succeeded`` ``_AUTO_GEN_FORCE_REFRESH_MIN_ROWS``
    (200) ve üzerindeyse True geçilir, altındaysa False kalır.
    Gerekçe: ``batch_analyzer._enqueue_root_cause_auto_gen`` artık her
    yükleme için AYRI bir arq job id kullanıyor (eskiden
    tenant+gün'e göre dedup ediliyordu), yani aynı gün içindeki küçük
    tekrar-yüklemeler bile ayrı ayrı tetiklenir. ``force_refresh`` hep
    True olsaydı bu küçük yüklemeler her seferinde LLM'e gidip
    kontrolsüz bir faturaya dönüşürdü. ``RootCauseService``'in 12s
    cache'i bu durumda güvence: force_refresh=False iken cache hit'e
    düşer, LLM hiç çağrılmaz — sonuç yine doğru kalır, sadece "taze"
    değildir. Yalnızca gerçekten anlamlı miktarda yeni veri geldiğinde
    (200+ başarılı satır) cache bilerek bypass edilir.
    ``rows_succeeded`` opsiyonel + varsayılan 0 — kuyrukta 2026-09
    öncesi enqueue edilmiş (yalnız tenant_id taşıyan) eski job'lar hâlâ
    çalışabilsin diye; 0 her zaman eşiğin altında kalır, yani eski
    job'lar eskisi gibi cache-first (force_refresh=False) davranır.

    ``generated_by_user_id=None`` — kolon nullable (root_cause_analysis
    modeli), tetikleyen bir kullanıcı değil bu arka plan görevi.

    "Hazırlanıyor" bayrağı (2026-09, ``services/root_cause_autogen.py``) —
    ``batch_analyzer._enqueue_root_cause_auto_gen`` enqueue anında bu
    işin ``batch_job_id``'sini bir Redis SET'e üye ekler
    (``mark_enqueued``). Burada, KENDİ işlemeye başladığımız anda
    ``mark_started`` üyeliği YENİLER — imga-batch tek işçili FIFO
    olduğundan büyük bir batch kuyrukta öndeyse enqueue-anı TTL'i işin
    gerçek başlangıcından önce dolabilir; SADD tekrarı bu durumda
    "hazırlanıyor" durumunu erkenden kaybetmeyi önler. Sonuç ne olursa
    olsun (başarı, kısmi başarı, tam başarısızlık) ``finally``
    bloğunda ``mark_finished`` çağrılır: SADECE bu işin kendi üyeliği
    silinir (aynı tenant için kuyrukta bekleyen BAŞKA bir batch'in
    üyeliğine dokunmaz — eski tek-string tasarımın ikinci audited
    kusuruydu) ve sonucun hata kodu (``"no_credentials"`` |
    ``"failed"`` | ``None``) ayrı bir Redis anahtarına yazılır ki GET
    /root-cause/overview üretim başarısız olduğunda genel "yeterli
    veri yok" boş durumu yerine gerçek nedeni gösterebilsin.
    ``batch_job_id=None`` — bu değişiklikten ÖNCE kuyruğa alınmış eski
    işler için (yalnız tenant_id + rows_succeeded taşırlardı); böyle
    bir işin izleyecek kendi üyeliği hiç olmadığından ``mark_started``
    atlanır, ``mark_finished`` ise SET'in TAMAMINI siler (bkz.
    ``mark_finished`` docstring'i).

    Hata sınıflandırması — herhangi bir kategori ``NoCredentialsError``
    fırlatırsa (kurumda aktif LLM anahtarı yok) sonuç
    ``"no_credentials"``; aday seçimi ya da herhangi bir kategori
    BAŞKA bir istisna fırlatırsa ``"failed"``; TÜM denenen kategoriler
    başarılıysa (denenen sıfırsa — örn. eşiğin altında kalan tenant —
    da dahil) ``None``. NoCredentialsError, "failed"'dan ÖNCELİKLİDİR:
    aynı turda hem kimlik bilgisi eksikliği hem başka bir hata
    görülürse kullanıcının göreceği (aksiyona dönüştürülebilir) neden
    kazanır.
    """
    worker_context: WorkerContext = ctx["worker_context"]
    tid: UUID | None = None
    parsed_batch_job_id: UUID | None = None
    had_no_credentials = False
    had_other_failure = False
    try:
        try:
            tid = UUID(tenant_id)
            parsed_batch_job_id = UUID(batch_job_id) if batch_job_id is not None else None
            if parsed_batch_job_id is not None:
                await mark_started(tid, parsed_batch_job_id)

            date_from, date_to = day_rounded_window()
            # _collect_bucket'ın (root_cause_service.py) gün sınırı
            # kuralıyla aynı: kapsayıcı UTC gün sınırları, üst sınır
            # gün SONU.
            window_from = datetime.combine(date_from, dt_time.min, tzinfo=UTC)
            window_to = datetime.combine(date_to, dt_time.max, tzinfo=UTC)
            force_refresh = rows_succeeded >= _AUTO_GEN_FORCE_REFRESH_MIN_ROWS

            try:
                async with worker_context.app_session_factory() as session, session.begin():
                    await set_current_tenant(session, tid)
                    total = (
                        await session.execute(
                            select(func.count())
                            .select_from(Review)
                            .where(Review.tenant_id == tid)
                            .where(Review.deleted_at.is_(None))
                        )
                    ).scalar_one()
                    if int(total or 0) < _AUTO_GEN_MIN_TENANT_REVIEWS:
                        return
                    picks = await pick_top_categories(
                        session,
                        tid,
                        date_from=window_from,
                        date_to=window_to,
                        limit=_AUTO_GEN_TOP_N,
                    )
            except Exception:
                had_other_failure = True
                _logger.exception(
                    "root-cause auto-gen: candidate selection failed for tenant %s (non-fatal)",
                    tenant_id,
                )
                return

            for pick in picks:
                if not pick.can_generate or pick.perspective_code is None:
                    continue
                try:
                    async with worker_context.app_session_factory() as session, session.begin():
                        await set_current_tenant(session, tid)
                        service = RootCauseService(session, tid, None)
                        try:
                            await service.generate(
                                primary_category=pick.primary_category_code,
                                perspective_code=pick.perspective_code,
                                date_from=date_from,
                                date_to=date_to,
                                force_refresh=force_refresh,
                            )
                        except NoCredentialsError:
                            had_no_credentials = True
                            _logger.warning(
                                "root-cause auto-gen: %s/%s has no active LLM "
                                "credentials for tenant %s (non-fatal)",
                                pick.primary_category_code,
                                pick.perspective_code,
                                tenant_id,
                            )
                        except Exception:
                            # İçeride: LLMCallAuditor'ın kendi savepoint'inde
                            # zaten flush ettiği hata denetim satırı, sarmalayan
                            # transaction NORMAL kapandığında COMMIT olsun diye
                            # (route katmanındaki deferred-raise deseniyle aynı
                            # gerekçe — dıştan yakalamak bu satırı rollback'e
                            # götürürdü). Aynı gerekçe NoCredentialsError için
                            # de geçerli — yukarıdaki ayrı except dalı da bu
                            # yüzden ``async with`` bloğunun İÇİNDE.
                            had_other_failure = True
                            _logger.exception(
                                "root-cause auto-gen: %s/%s failed for tenant %s (non-fatal)",
                                pick.primary_category_code,
                                pick.perspective_code,
                                tenant_id,
                            )
                except Exception:
                    had_other_failure = True
                    _logger.exception(
                        "root-cause auto-gen: session-level failure for %s/%s, tenant %s (non-fatal)",
                        pick.primary_category_code,
                        pick.perspective_code,
                        tenant_id,
                    )
        except Exception:
            # Savunmacı üst-seviye yakalama: tenant_id/batch_job_id
            # UUID ayrıştırması ya da yukarıdaki iç try'ların dışında
            # kalan herhangi bir beklenmedik hata. Bu arka plan
            # zenginleştirmesi batch'in kendisini ASLA geriye alamaz —
            # ne olursa olsun raise etmeden burada durur, finally'nin
            # (tid biliniyorsa) temizliği yine de yapabilmesi için.
            had_other_failure = True
            _logger.exception(
                "root-cause auto-gen: unexpected failure for tenant %s (non-fatal)",
                tenant_id,
            )
    finally:
        if tid is not None:
            error_code: str | None
            if had_no_credentials:
                error_code = "no_credentials"
            elif had_other_failure:
                error_code = "failed"
            else:
                error_code = None
            await mark_finished(tid, parsed_batch_job_id, error=error_code)


async def startup(ctx: dict[str, Any]) -> None:
    # Sprint 9.0.5-B J — pin INFO on the project namespaces inside
    # the arq worker process. arq's own logging defaults leave
    # ``imga_core.*`` at WARNING, so the HybridClassifier batch
    # summary + rotator key usage logs were dropping silently in
    # production. Idempotent.
    from imga_api.logging_config import configure_logging

    configure_logging()
    return await _startup_impl(ctx)


async def _startup_impl(ctx: dict[str, Any]) -> None:
    """One-time worker process initialisation. Builds:

    * Settings (shared with the API container — same env vars).
    * Pipeline pool — N AnalysisPipeline instances so up to N
      chunks can run BERT in parallel without HF pipeline thread-
      safety races.
    * Redis client for SSE pub/sub publish.
    * WorkerContext bundling all the above.
    * Orphan recovery — a worker restart shouldn't leave PROCESSING
      rows in the DB; mark them failed so the operator can /retry.
    """
    settings = Settings.from_env()
    settings.batch.upload_dir.mkdir(parents=True, exist_ok=True)
    pipeline_count = int(
        os.environ.get("IMGA_BATCH_CHUNK_CONCURRENCY", str(_DEFAULT_CHUNK_CONCURRENCY))
    )
    pipeline_count = max(1, pipeline_count)

    _logger.info(
        "arq worker startup: building %d pipeline instances (model=%s)",
        pipeline_count,
        settings.bert_model,
    )
    pipeline_pool = [build_pipeline(settings) for _ in range(pipeline_count)]
    primary_pipeline = pipeline_pool[0]

    tenant_config_cache: TTLCache[UUID, dict[str, Any]] = TTLCache(maxsize=1000, ttl=300)

    redis_client = get_redis_client()
    try:
        await redis_client.ping()
        _logger.info("arq worker: Redis publisher reachable")
    except Exception:
        _logger.exception(
            "arq worker: Redis publisher unreachable at startup; SSE "
            "progress events will be dropped until the next reconnect"
        )

    worker_context = await build_worker_context(
        pipeline=primary_pipeline,
        tenant_config_cache=tenant_config_cache,
        settings=settings.batch,
        pipeline_pool=pipeline_pool,
        chunk_concurrency=pipeline_count,
        redis_publisher=redis_client,
        # arq sets ctx['redis'] to the worker's own ArqRedis pool
        # BEFORE calling on_startup (arq.worker.Worker.main) — reusing
        # it here means the post-batch root-cause enqueue doesn't open
        # a second Redis connection pool.
        arq_pool=ctx.get("redis"),
    )

    orphans = await recover_orphans(worker_context)
    if orphans:
        _logger.warning(
            "arq worker startup: marked %d orphaned batch jobs as failed",
            orphans,
        )

    ctx["worker_context"] = worker_context
    ctx["redis_client"] = redis_client


async def shutdown(ctx: dict[str, Any]) -> None:
    """Graceful teardown — close engine pools so PG doesn't see a
    stale-connection burst on the next start."""
    worker_context = ctx.get("worker_context")
    if worker_context is not None:
        try:
            await worker_context.dispose()
        except Exception:
            _logger.exception("arq worker: worker_context.dispose failed")
    redis_client = ctx.get("redis_client")
    if redis_client is not None:
        try:
            if hasattr(redis_client, "aclose"):
                await redis_client.aclose()
            elif hasattr(redis_client, "close"):
                maybe = redis_client.close()
                if hasattr(maybe, "__await__"):
                    await maybe
        except Exception:
            _logger.exception("arq worker: redis_client close failed")


class WorkerSettings:
    """arq picks this up via the ``arq imga_api.workers.arq_worker.WorkerSettings``
    CLI invocation in the api-worker compose service.

    ``max_jobs`` matches ``chunk_concurrency`` — one job at a time per
    worker process so the pool is fully owned. Multiple workers (a
    second container) can share the queue if throughput needs it.

    ``job_timeout`` is generous: a 10K-row batch at the parallel/
    non-blocking baseline targets 15-30 min; 25K (2026-08-09 limit
    bump) scales that to ~40-75 min, and 4h covers worst-case LLM
    retries + Postgres back-pressure. ``keep_result``
    retains arq's result record for a day so /retry can re-enqueue
    via the same job id without a stale-key warning.
    """

    functions = [
        process_batch_task,
        process_reanalysis_task,
        generate_root_causes_task,
    ]
    on_startup = staticmethod(startup)
    on_shutdown = staticmethod(shutdown)
    redis_settings = _redis_settings()
    max_jobs = 1
    job_timeout = 14400  # 4h — 25k satır worst-case payı
    keep_result = 86400  # 24h
    queue_name = "imga-batch"
    # Sprint 9.2 D — every-5-min cron tick for scheduled briefings.
    # The tick scans ``briefing_schedules`` for due rows; per-tenant
    # generation work happens inside the tick so the arq queue
    # itself isn't loaded with N enqueues per cycle.
    cron_jobs = [
        cron(
            scheduled_briefing_tick,
            minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55},
            run_at_startup=False,
        ),
        # Sprint 13+ — email outbox dispatcher (2 dk) + SLA ihlal
        # taraması (15 dk). Her ikisi de tarama tabanlı ve idempotent;
        # ayrı worker container gerekmez.
        cron(
            email_outbox_tick,
            minute=set(range(0, 60, 2)),
            run_at_startup=False,
        ),
        cron(
            sla_breach_tick,
            minute={0, 15, 30, 45},
            run_at_startup=False,
        ),
    ]


__all__ = [
    "WorkerSettings",
    "generate_root_causes_task",
    "process_batch_task",
    "process_reanalysis_task",
    "shutdown",
    "startup",
]
