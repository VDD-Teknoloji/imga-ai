"""``/tenants/me/analyze/twitter-import`` — X/Twitter'dan çek, toplu analize ver.

"Twitter'dan Çek" entegrasyonu: kullanıcının verdiği arama terimiyle
twitterapi.io'dan en yeni Türkçe gönderiler çekilir, şablon uyumlu bir
CSV'ye (yorum + tarih + kaynak + bağlantı) yazılır ve NORMAL batch
pipeline'a teslim edilir — ilerleme/SSE/geçmiş/batch-filtresi olduğu gibi
çalışır. Bu uç yalnızca "dosyayı kullanıcı yerine biz üretiyoruz"
katmanıdır.

2026-08-26 — iki AI adımı (bkz. services/twitter_brand_service):
``/plan`` marka + kurum profilinden include/exclude terimleri, resmi
hesap ve marka özeti üretir (kullanıcı formda düzenler); içe aktarma
``relevance_check`` açıkken çekilen gönderileri hakeme sorup markayla
ilgisiz olanları CSV'ye yazmadan eler.
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
from imga_api.services.llm_credentials import NoCredentialsError
from imga_api.services.twitter_brand_service import (
    BrandPlanError,
    compose_term,
    judge_tweet_relevance,
    normalize_handle,
    plan_brand_search,
)
from imga_api.services.twitter_import import (
    TwitterFetchError,
    TwitterTweet,
    build_search_query,
    fetch_tweets,
    parse_search_terms,
)
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

_NO_LLM_DETAIL = {
    "code": "no_llm_credentials",
    "message": (
        "Aktif LLM API anahtarı tanımlanmamış. Ayarlar > Entegrasyonlar üzerinden ekleyin."
    ),
}


class TwitterImportRequest(BaseModel):
    """Arama terimi kurum adı / marka olabilir; sorgu dilini backend kurar.
    Virgülle birden çok terim, ``-`` ile hariç tutma (bkz.
    ``twitter_import.parse_search_terms``); ``/plan`` çıktısı bu
    sözdizimine ``compose_term`` ile çevrilir."""

    term: str = Field(min_length=2, max_length=400)
    count: int = Field(default=200, ge=10, le=1000)
    # Resmi hesabın kendi paylaşımları müşteri sesi değildir — verilirse
    # -from: ile elenir; hesaba yazılan yanıtlar korunur. Başındaki @
    # opsiyonel.
    exclude_handle: str | None = Field(default=None, max_length=50)
    auto_create_tickets: bool = False
    # AI alaka hakemi: çekilen her gönderi "bu marka hakkında mı" diye
    # sorulur, hayır olanlar elenir. Kapalıysa yalnız aşama-1 alt-dizi
    # filtresi uygulanır. Anahtar yoksa / hakem çökerse içe aktarma
    # DURMAZ — ``ai_check_skipped`` ile raporlanır.
    relevance_check: bool = True
    # ``/plan`` adımının marka özeti; hakeme bağlam. Yoksa kurum profili
    # (sektör, iş tanımı) yeter.
    brand_summary: str | None = Field(default=None, max_length=1000)


class TwitterImportResponse(BaseModel):
    job: BatchJobResponse
    requested: int
    found: int
    # True → X'te bu sorgu için daha fazla Türkçe sonuç yok; found <
    # requested ise eksik veri değil, kaynağın tamamı demektir.
    exhausted: bool
    # X'ten çekilen toplam gönderi (filtrelerden önce).
    fetched_total: int = 0
    # Aşama-1 alaka filtresinin elediği gönderi sayısı (terim metinde
    # geçmiyor ve resmi hesaba yazılmamış — çoğunlukla aynı soyadlı
    # yazarlar).
    filtered_out: int = 0
    # AI hakeminin elediği gönderi sayısı.
    filtered_by_ai: int = 0
    # True → hakem hiç çalışmadı (anahtar yok ya da tüm partiler hata).
    ai_check_skipped: bool = False


class TwitterPlanRequest(BaseModel):
    brand: str = Field(min_length=2, max_length=120)
    handle: str | None = Field(default=None, max_length=50)


class TwitterPlanResponse(BaseModel):
    brand: str
    brand_summary: str
    include: list[str]
    exclude: list[str]
    handle: str | None
    bare_name_ambiguous: bool
    notes: str | None
    # Terim alanına yazılacak hazır metin (virgül sözdizimi) + X'e
    # gidecek sorgunun önizlemesi.
    term: str
    query_preview: str


@router.post(
    "/plan",
    response_model=TwitterPlanResponse,
    summary="Marka için AI anahtar kelime planı (include/exclude/resmi hesap/özet).",
    description=(
        "Kurumun kazanan LLM sağlayıcısıyla marka adı + kurum profilinden "
        "X arama terimleri üretir. Sonuç formda düzenlenir; hiçbir şey "
        "kalıcı yazılmaz. Aktif LLM anahtarı yoksa 412."
    ),
    responses={
        412: {"description": "Aktif LLM anahtarı yok."},
        502: {"description": "LLM çağrısı başarısız."},
    },
)
async def plan_twitter_import(
    body: TwitterPlanRequest,
    current: Annotated[CurrentUser, _TenantMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> TwitterPlanResponse:
    tenant_id = _require_active_tenant(current)
    brand = " ".join(body.brand.split()).strip()
    # BrandPlanError transaction'ın İÇİNDE yakalanır: başarısızlık denetim
    # satırı istisnadan önce yazıldı, begin()'den sızarsa rollback ile
    # kaybolur. NoCredentialsError'da yazılacak satır yok, sızabilir.
    plan_error: BrandPlanError | None = None
    plan = None
    try:
        async with app_session.begin():
            await bind_tenant(app_session, current)
            try:
                plan = await plan_brand_search(
                    app_session,
                    tenant_id,
                    brand=brand,
                    handle=body.handle,
                    actor_user_id=current.user_id,
                )
            except BrandPlanError as exc:
                plan_error = exc
    except NoCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED, detail=_NO_LLM_DETAIL
        ) from exc
    if plan_error is not None or plan is None:
        log.warning(
            "twitter plan failed for brand=%r: %s (%s)",
            brand,
            plan_error,
            plan_error.error_type if plan_error else "unknown",
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Anahtar kelime planı üretilemedi; lütfen tekrar deneyin.",
        ) from plan_error

    term = compose_term(plan.include, plan.exclude)
    return TwitterPlanResponse(
        brand=plan.brand,
        brand_summary=plan.brand_summary,
        include=plan.include,
        exclude=plan.exclude,
        handle=plan.handle,
        bare_name_ambiguous=plan.bare_name_ambiguous,
        notes=plan.notes,
        term=term,
        query_preview=build_search_query(term, plan.handle),
    )


@router.post(
    "",
    response_model=TwitterImportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="X/Twitter'dan arama terimiyle gönderi çekip toplu analiz başlat.",
    description=(
        "twitterapi.io advanced_search ile en yeni Türkçe, RT'siz "
        "gönderiler çekilir (istenirse resmi hesap hariç), alaka "
        "filtresi + (açıksa) AI hakemi uygulanır, şablon uyumlu CSV "
        "üretilir ve standart batch işine kuyruklanır. İlerleme diğer "
        "yüklemelerle aynı SSE/poll yüzeyinden izlenir. Sunucuda "
        "IMGA_TWITTERAPI_IO_KEY tanımlı değilse 503."
    ),
    responses={
        422: {"description": "Sorgu için uygun gönderi bulunamadı."},
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
            detail=("Twitter entegrasyonu bu sunucuda yapılandırılmamış (IMGA_TWITTERAPI_IO_KEY)."),
        )

    term = body.term.strip()
    terms = parse_search_terms(term)
    if len(term) < 2 or not terms.positive:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "En az 2 karakterlik bir arama terimi gerekli "
                "(yalnız '-' ile başlayan hariç tutma terimleri yetmez)."
            ),
        )
    handle = normalize_handle(body.exclude_handle)

    try:
        result = await fetch_tweets(
            api_key=settings.twitterapi_io_key,
            term=term,
            count=body.count,
            exclude_handle=handle,
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
                f'"{term}" için uygun gönderi bulunamadı: X\'ten '
                f"{result.fetched_total} gönderi çekildi, {result.filtered_out} "
                "tanesi alaka filtresinde elendi. Terimleri değiştirip "
                "tekrar deneyin."
            ),
        )

    tweets: list[TwitterTweet] = list(result.tweets)
    filtered_by_ai = 0
    ai_check_skipped = False
    if body.relevance_check:
        try:
            async with app_session.begin():
                await bind_tenant(app_session, current)
                verdict = await judge_tweet_relevance(
                    app_session,
                    tenant_id,
                    brand=terms.positive[0],
                    brand_summary=(body.brand_summary or "").strip() or None,
                    include=list(terms.positive),
                    exclude=list(terms.negative),
                    handle=handle,
                    tweets=[t.raw_text or t.text for t in tweets],
                    actor_user_id=current.user_id,
                )
        except NoCredentialsError:
            ai_check_skipped = True
            log.info(
                "twitter import: tenant=%s has no LLM key; AI relevance check skipped", tenant_id
            )
        else:
            if verdict.batches and verdict.failed_batches == verdict.batches:
                ai_check_skipped = True
            tweets = [t for t, ok in zip(tweets, verdict.relevant, strict=True) if ok]
            filtered_by_ai = verdict.dropped
        if not tweets:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"{len(result.tweets)} gönderi çekildi ama AI alaka kontrolü "
                    "hiçbirini markayla ilişkilendiremedi. Terimleri daraltın "
                    "ya da AI kontrolünü kapatıp tekrar deneyin."
                ),
            )

    # Şablonla birebir aynı kolonlar: yorum (zorunlu) + tarih + kaynak,
    # artı ``bağlantı`` (tweet URL'si — parser otomatik tanır,
    # Review.source_url'e iner). ``tarih`` tweet'in atılma anıdır —
    # parser bunu Review.review_date olarak çözer, böylece analizler
    # gerçek gönderim tarihine oturur (çekim anına değil). Tarih
    # çözülemeyen tweet boş bırakılır.
    # Migration 0049 — dört etkileşim sayacı kolonu ``bağlantı``dan
    # sonra: parser bunları ``_META_INT_HEADERS`` ile otomatik tanır ve
    # Review.source_meta'ya yazar. Sayaç yoksa hücre boş bırakılır
    # (None ≠ 0 — "bilinmiyor" ile "sıfır etkileşim" karıştırılmaz).
    # Dosya normal yüklemelerle aynı dizin düzenine iner;
    # retention/reaper cron'ları ekstra kural olmadan kapsar.
    dir_id = uuid4()
    job_dir = settings.batch.upload_dir / str(tenant_id) / str(dir_id)
    job_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", terms.positive[0].lower()).strip("-") or "arama"
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
            total_rows=len(tweets),
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
        "twitter import queued: tenant=%s term=%r found=%d/%d pages=%d "
        "fetched=%d filtered_out=%d filtered_by_ai=%d ai_skipped=%s",
        tenant_id,
        term,
        len(tweets),
        body.count,
        result.pages,
        result.fetched_total,
        result.filtered_out,
        filtered_by_ai,
        ai_check_skipped,
    )
    return TwitterImportResponse(
        job=view,
        requested=body.count,
        found=len(tweets),
        exhausted=result.exhausted,
        fetched_total=result.fetched_total,
        filtered_out=result.filtered_out,
        filtered_by_ai=filtered_by_ai,
        ai_check_skipped=ai_check_skipped,
    )
