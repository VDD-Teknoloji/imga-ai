"""``/admin/system-health`` — süper-admin altyapı sağlık özeti (C2,
2026-08-20 süper-admin envanteri).

Dört sinyal: Redis erişilebilirliği, arq batch kuyruk derinliği, arq
worker health-check anahtarı, son 7 günün ``analyze_batch_jobs``
durum dağılımı. Tamamı best-effort — Redis erişilemezse Redis kaynaklı
alanlar null döner ve ``redis_ok=false`` olur, ama uç asla 500 vermez
(operatörün tam da Redis'in çöktüğü an bu sayfaya bakma ihtimali
yüksek).

arq anahtar şeması — TAHMİN DEĞİL, paketteki arq sürümünün kaynağından
doğrulandı (``arq.connections.ArqRedis.enqueue_job`` ve
``arq.worker.Worker.__init__`` + ``arq.constants``):
  * Kuyruk bir Redis ZSET'tir, anahtarı DOĞRUDAN ``queue_name``
    (``arq_worker.py``'deki ``WorkerSettings.queue_name = "imga-batch"``)
    — "arq:queue:imga-batch" gibi önekli bir desen YOK.
    ``enqueue_job``: ``pipe.zadd(_queue_name, {job_id: score})``.
  * Health-check anahtarı ``f"{queue_name}:health-check"``
    (``arq.constants.health_check_key_suffix = ":health-check"``,
    ``Worker.__init__``'te ``health_check_key`` verilmezse
    ``queue_name + health_check_key_suffix``'e düşer — arq_worker.py
    bu alanı hiç set etmiyor, yani varsayılan geçerli). Worker'ın
    kendisi bu anahtara ``health_check_interval`` (arq varsayılanı
    3600 sn) aralıklarla bir özet STRING yazar; taze bir worker'da
    ilk saat boyunca anahtar hiç yoktur — bu durumda ``workers``
    "unknown" döner (arq'nın kendisi de "worker çalışmıyor" ile
    "henüz ilk health-check turunu atmadı" arasında ayrım yapmaz).

Diğer admin uçlarıyla aynı transaction sözleşmesi: burada
``async with admin_session.begin():`` YOK, bilerek (bkz.
admin/llm_credentials.py docstring'i).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends
from imga_db.models import AnalyzeBatchJob
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import CurrentUser, require_super_admin
from imga_api.cache.redis_client import get_redis_client
from imga_api.db_deps import get_admin_session

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/system-health", tags=["Admin: System Health"])

# bkz. modül docstring'i — kaynak: arq_worker.py WorkerSettings.queue_name
# + arq.constants.health_check_key_suffix.
_ARQ_QUEUE_NAME = "imga-batch"
_ARQ_HEALTH_CHECK_KEY = f"{_ARQ_QUEUE_NAME}:health-check"

_JOBS_WINDOW_DAYS = 7


class JobStatusCount(BaseModel):
    status: str
    count: int


class SystemHealthResponse(BaseModel):
    redis_ok: bool
    arq_queue_depth: int | None
    workers: str
    jobs_by_status: list[JobStatusCount]


@router.get(
    "",
    response_model=SystemHealthResponse,
    summary="Redis + arq kuyruk/worker + son 7 gün batch job durum özeti (best-effort).",
)
async def system_health(
    _current: Annotated[CurrentUser, Depends(require_super_admin)],
    admin_session: Annotated[AsyncSession, Depends(get_admin_session)],
) -> SystemHealthResponse:
    redis_ok = False
    arq_queue_depth: int | None = None
    workers = "unknown"

    client = get_redis_client()
    try:
        await client.ping()
        redis_ok = True
    except Exception:
        _logger.warning("system-health: redis ping failed", exc_info=True)

    if redis_ok:
        try:
            arq_queue_depth = int(await client.zcard(_ARQ_QUEUE_NAME))
        except Exception:
            _logger.warning("system-health: arq queue depth read failed", exc_info=True)
            arq_queue_depth = None
        try:
            raw = await client.get(_ARQ_HEALTH_CHECK_KEY)
            if raw is not None:
                workers = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        except Exception:
            _logger.warning("system-health: arq health-check key read failed", exc_info=True)

    # Postgres tarafı Redis'ten bağımsız — çöküşü Redis'i etkilemez,
    # burayı best-effort sarmalamaya gerek yok (zaten get_admin_session
    # hata durumunda kendi rollback'ini yapar, uç 500'e düşer — bu
    # kabul edilebilir çünkü DB erişilemezse zaten platform genelinde
    # sorun var, "best-effort" yalnız Redis/arq için).
    cutoff = datetime.now(UTC) - timedelta(days=_JOBS_WINDOW_DAYS)
    stmt = (
        select(AnalyzeBatchJob.status, func.count())
        .where(AnalyzeBatchJob.created_at >= cutoff)
        .group_by(AnalyzeBatchJob.status)
    )
    rows = (await admin_session.execute(stmt)).all()
    jobs_by_status = [
        JobStatusCount(status=str(status_value), count=int(count_value))
        for status_value, count_value in rows
    ]

    return SystemHealthResponse(
        redis_ok=redis_ok,
        arq_queue_depth=arq_queue_depth,
        workers=workers,
        jobs_by_status=jobs_by_status,
    )
