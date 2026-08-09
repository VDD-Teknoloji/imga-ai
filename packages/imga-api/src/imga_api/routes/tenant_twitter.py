"""``/tenants/me/analyze/twitter-import`` — X/Twitter'dan çek, toplu analize ver.

"Twitter'dan Çek" entegrasyonu: kullanıcının verdiği arama terimiyle
twitterapi.io'dan en yeni Türkçe gönderiler çekilir, şablon uyumlu bir
CSV'ye (yorum + tarih + kaynak) yazılır ve NORMAL batch pipeline'a teslim edilir
— ilerleme/SSE/geçmiş/batch-filtresi olduğu gibi çalışır. Bu uç yalnızca
"dosyayı kullanıcı yerine biz üretiyoruz" katmanıdır.
"""

from __future__ import annotations

import csv
import logging
import re
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from imga_db.models import AnalyzeBatchJob, UserTenantRole
from pydantic import BaseModel, Field
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import CurrentUser, bind_tenant, require_role
from imga_api.db_deps import get_app_session
from imga_api.routes.tenant_batch import (
    BatchJobResponse,
    _client_ip,
    _job_view,
    _require_active_tenant,
)
from imga_api.services import AuditService, BatchAnalyzeService
from imga_api.services.twitter_import import TwitterFetchError, fetch_tweets
from imga_api.settings import Settings
from imga_api.workers.scheduler import enqueue_batch_job

log = logging.getLogger("imga-api.routes.twitter")

router = APIRouter(prefix="/tenants/me/analyze/twitter-import", tags=["Analyze"])

_TenantMember = Depends(
    require_role(
        UserTenantRole.TENANT_ADMIN,
        UserTenantRole.ANALYST,
    )
)


class TwitterImportRequest(BaseModel):
    """Arama terimi kurum adı / marka olabilir; sorgu dilini backend kurar."""

    term: str = Field(min_length=2, max_length=80)
    count: int = Field(default=200, ge=10, le=1000)
    # Resmi hesabın kendi paylaşımları müşteri sesi değildir — verilirse
    # -from: ile elenir. Başındaki @ opsiyonel.
    exclude_handle: str | None = Field(default=None, max_length=50)
    auto_create_tickets: bool = False


class TwitterImportResponse(BaseModel):
    job: BatchJobResponse
    requested: int
    found: int
    # True → X'te bu sorgu için daha fazla Türkçe sonuç yok; found <
    # requested ise eksik veri değil, kaynağın tamamı demektir.
    exhausted: bool


@router.post(
    "",
    response_model=TwitterImportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="X/Twitter'dan arama terimiyle gönderi çekip toplu analiz başlat.",
    description=(
        "twitterapi.io advanced_search ile en yeni Türkçe, RT'siz "
        "gönderiler çekilir (istenirse resmi hesap hariç), şablon "
        "uyumlu CSV üretilir ve standart batch işine kuyruklanır. "
        "İlerleme diğer yüklemelerle aynı SSE/poll yüzeyinden izlenir. "
        "Sunucuda IMGA_TWITTERAPI_IO_KEY tanımlı değilse 503."
    ),
    responses={
        422: {"description": "Sorgu için sonuç bulunamadı."},
        502: {"description": "Twitter API'ye ulaşılamadı."},
        503: {"description": "Entegrasyon yapılandırılmamış."},
    },
)
async def import_from_twitter(
    request: Request,
    body: TwitterImportRequest,
    current: Annotated[CurrentUser, _TenantMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> TwitterImportResponse:
    tenant_id = _require_active_tenant(current)
    settings: Settings = request.app.state.settings
    if not settings.twitterapi_io_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Twitter entegrasyonu bu sunucuda yapılandırılmamış " "(IMGA_TWITTERAPI_IO_KEY)."
            ),
        )

    term = body.term.strip()
    if len(term) < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Arama terimi en az 2 karakter olmalı.",
        )

    try:
        result = await fetch_tweets(
            api_key=settings.twitterapi_io_key,
            term=term,
            count=body.count,
            exclude_handle=body.exclude_handle,
        )
    except TwitterFetchError as exc:
        log.warning("twitter fetch failed for term=%r: %s", term, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Twitter API'ye şu anda ulaşılamıyor, lütfen tekrar deneyin.",
        ) from exc

    if not result.tweets:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f'"{term}" için Türkçe gönderi bulunamadı. Terimi ' "değiştirip tekrar deneyin."
            ),
        )

    # Şablonla birebir aynı kolonlar: yorum (zorunlu) + tarih + kaynak.
    # ``tarih`` tweet'in atılma anıdır — parser bunu Review.review_date
    # olarak çözer, böylece analizler gerçek gönderim tarihine oturur
    # (çekim anına değil). Tarih çözülemeyen tweet boş bırakılır.
    # Dosya normal yüklemelerle aynı dizin düzenine iner;
    # retention/reaper cron'ları ekstra kural olmadan kapsar.
    dir_id = uuid4()
    job_dir = settings.batch.upload_dir / str(tenant_id) / str(dir_id)
    job_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", term.lower()).strip("-") or "arama"
    file_name = f"twitter-{slug}.csv"
    file_path = job_dir / file_name
    with file_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["yorum", "tarih", "kaynak"])
        for tweet in result.tweets:
            posted = tweet.created_at.isoformat() if tweet.created_at else ""
            writer.writerow([tweet.text, posted, "twitter"])
    file_size = file_path.stat().st_size

    async with app_session.begin():
        await bind_tenant(app_session, current)
        service = BatchAnalyzeService(app_session, AuditService(app_session))
        job = await service.create_job(
            tenant_id=tenant_id,
            triggered_by_user_id=current.user_id,
            file_name=file_name,
            file_size_bytes=file_size,
            file_path=str(file_path),
            text_column="yorum",
            source_column="kaynak",
            auto_create_tickets=body.auto_create_tickets,
            total_rows=len(result.tweets),
            ip_address=_client_ip(request),
        )

    worker_job_id, queued_at = await enqueue_batch_job(
        request.app,
        job_id=job.id,
        tenant_id=tenant_id,
    )
    if worker_job_id is not None or queued_at is not None:
        async with app_session.begin():
            await bind_tenant(app_session, current)
            await app_session.execute(
                update(AnalyzeBatchJob)
                .where(AnalyzeBatchJob.id == job.id)
                .values(worker_job_id=worker_job_id, queued_at=queued_at)
            )
    async with app_session.begin():
        await bind_tenant(app_session, current)
        refreshed = await app_session.get(AnalyzeBatchJob, job.id)
        view = _job_view(refreshed if refreshed is not None else job)

    log.info(
        "twitter import queued: tenant=%s term=%r found=%d/%d pages=%d",
        tenant_id,
        term,
        len(result.tweets),
        body.count,
        result.pages,
    )
    return TwitterImportResponse(
        job=view,
        requested=body.count,
        found=len(result.tweets),
        exhausted=result.exhausted,
    )
