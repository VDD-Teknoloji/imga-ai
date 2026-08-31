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
from imga_api.services.root_cause_service import (
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


async def generate_root_causes_task(ctx: dict[str, Any], tenant_id: str) -> None:
    """Sprint 13.x — post-batch otomatik kök neden üretimi.

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
      4. Her çift KENDİ transaction'ında, ``force_refresh=False``
         SABİT (cache asla bypass edilmez) — bir kategori başarısız
         olursa diğerlerini etkilemez, hata loglanır + yutulur (batch
         zaten başarıyla tamamlandı, bu arka plan zenginleştirmesi onu
         asla geriye alamaz).

    ``generated_by_user_id=None`` — kolon nullable (root_cause_analysis
    modeli), tetikleyen bir kullanıcı değil bu arka plan görevi.
    """
    worker_context: WorkerContext = ctx["worker_context"]
    tid = UUID(tenant_id)
    date_from, date_to = day_rounded_window()
    # _collect_bucket'ın (root_cause_service.py) gün sınırı kuralıyla
    # aynı: kapsayıcı UTC gün sınırları, üst sınır gün SONU.
    window_from = datetime.combine(date_from, dt_time.min, tzinfo=UTC)
    window_to = datetime.combine(date_to, dt_time.max, tzinfo=UTC)

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
                        force_refresh=False,
                    )
                except Exception:
                    # İçeride: LLMCallAuditor'ın kendi savepoint'inde
                    # zaten flush ettiği hata denetim satırı, sarmalayan
                    # transaction NORMAL kapandığında COMMIT olsun diye
                    # (route katmanındaki deferred-raise deseniyle aynı
                    # gerekçe — dıştan yakalamak bu satırı rollback'e
                    # götürürdü).
                    _logger.exception(
                        "root-cause auto-gen: %s/%s failed for tenant %s (non-fatal)",
                        pick.primary_category_code,
                        pick.perspective_code,
                        tenant_id,
                    )
        except Exception:
            _logger.exception(
                "root-cause auto-gen: session-level failure for %s/%s, tenant %s (non-fatal)",
                pick.primary_category_code,
                pick.perspective_code,
                tenant_id,
            )


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
