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

2026-09-02 — ARKA PLAN İŞİ. Fetch→hakem→CSV→kuyruklama zinciri
(``workers/twitter_fetch.py``'a taşındı) 1000 gönderilik bir çekimde
1-3+ dakika sürebiliyordu; ÖNCEDEN bu süre boyunca tarayıcı yalnız
düğme spinner'ı görüyordu. ``POST`` artık ANINDA 202 döner (``job_id``
+ Redis'te izlenen bir ilerleme kaydı); ``GET .../jobs/{job_id}`` 2sn
aralıklarla poll edilir. Yalnız iş BİTTİĞİNDE (ilerleme durumu "done")
normal batch pipeline'ın SSE/poll yüzeyi devreye girer — ``job`` alanı
artık POST yanıtında değil, ``GET`` yanıtındaki ``batch_job_id``'de.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from imga_db.models import UserTenantRole
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import CurrentUser, bind_tenant, require_role
from imga_api.db_deps import get_app_session
from imga_api.routes.tenant_batch import _client_ip, _require_active_tenant
from imga_api.services.llm_credentials import NoCredentialsError
from imga_api.services.twitter_brand_service import (
    BrandPlanError,
    compose_term,
    normalize_handle,
    plan_brand_search,
)
from imga_api.services.twitter_import import build_search_query, parse_search_terms
from imga_api.settings import Settings
from imga_api.workers.twitter_fetch import (
    TwitterFetchPayload,
    init_job,
    process_twitter_fetch_job,
    read_job,
)

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


class TwitterImportEnqueuedResponse(BaseModel):
    """``POST``'un ANINDA yanıtı — çekim/hakem/CSV/kuyruklama zinciri
    bundan sonra arka planda (``workers/twitter_fetch.py``) koşar.
    İlerleme ``GET .../jobs/{job_id}`` ile izlenir."""

    job_id: UUID
    status: str = "queued"


class TwitterFetchJobStatusResponse(BaseModel):
    """``GET .../jobs/{job_id}`` — Redis'teki ilerleme HASH'inin
    JSON görünümü (bkz. ``workers/twitter_fetch.TwitterFetchJobSnapshot``).
    Alan adları kasıtlı olarak Redis şemasıyla birebir aynı."""

    job_id: UUID
    status: str
    # Yalnız status="running" iken anlamlı.
    stage: str | None
    requested: int
    # "fetching" sırasında koşan tutulan-gönderi sayısı; hakem
    # başlar başlamaz DONAR (nihai değer kept_after_filter'dadır).
    tweets_found: int
    pages_done: int
    fetched_total: int
    # Aşama-1 alt-dizi filtresinin elediği sayı.
    filtered_out: int
    # #işbirliği/#reklam/#sponsor/#sponsorlu etiketiyle elenen sayı.
    excluded_collab: int
    # Tutulan gönderiler arasında en eski/en yeni atılma anı — "ne
    # kadar geriye gidildi" sorusunun cevabı.
    oldest_tweet_at: datetime | None
    newest_tweet_at: datetime | None
    # Aşağıdaki dördü çekim/hakem aşamaları SONLANANA kadar None kalır.
    exhausted: bool | None
    kept_after_filter: int | None
    filtered_by_ai: int | None
    ai_check_skipped: bool | None
    # Yalnız status="done" iken dolu — normal batch ilerleme/geçmiş
    # yüzeyine geçiş için (bu uç kendi başına o yüzeyi tekrarlamaz).
    batch_job_id: UUID | None
    # Yalnız status="failed" iken dolu.
    error: str | None


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
    response_model=TwitterImportEnqueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="X/Twitter'dan arama terimiyle gönderi çekmeyi arka planda başlat.",
    description=(
        "twitterapi.io advanced_search ile en yeni Türkçe, RT'siz gönderiler "
        "ARKA PLANDA çekilir (istenirse resmi hesap hariç), #işbirliği/"
        "#reklam etiketli gönderiler + alaka filtresi + (açıksa) AI hakemi "
        "uygulanır, şablon uyumlu CSV üretilir ve standart batch işine "
        "kuyruklanır. İlerleme ``GET .../jobs/{job_id}`` ile 2sn "
        "aralıklarla izlenir. Sunucuda IMGA_TWITTERAPI_IO_KEY tanımlı "
        "değilse 503."
    ),
    responses={
        422: {"description": "Arama terimi geçersiz (en az 2 karakterlik pozitif terim yok)."},
        503: {"description": "Entegrasyon yapılandırılmamış ya da ilerleme izleme başlatılamadı."},
    },
)
async def import_from_twitter(
    request: Request,
    body: TwitterImportRequest,
    current: Annotated[CurrentUser, _TenantMember],
) -> TwitterImportEnqueuedResponse:
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
    # Hem çekimin ``-from:`` dışlamasında hem hakemin bağlamında AYNI
    # normalize edilmiş değer kullanılır — bkz. TwitterFetchPayload.
    handle = normalize_handle(body.exclude_handle)

    job_id = uuid4()
    try:
        await init_job(tenant_id, job_id, requested=body.count)
    except Exception as exc:
        log.exception(
            "twitter fetch: init_job failed; refusing to enqueue an untracked job",
            extra={"tenant_id": str(tenant_id)},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Twitter içe aktarma şu anda kullanılamıyor, lütfen tekrar deneyin.",
        ) from exc

    payload = TwitterFetchPayload(
        term=term,
        count=body.count,
        exclude_handle=handle,
        auto_create_tickets=body.auto_create_tickets,
        relevance_check=body.relevance_check,
        brand_summary=body.brand_summary,
        actor_user_id=current.user_id,
        client_ip=_client_ip(request),
    )

    # Öncelik arq (prod): sır (api key) argümanlarda TAŞINMAZ — işçi
    # kendi ortamından okur (bkz. workers/twitter_fetch.py). arq
    # bağlı değilse (test / arq'sız dev-staging) mevcut batch
    # yüklemesiyle AYNI in-process APScheduler yedeğine düşülür —
    # ``enqueue_batch_job``'ın dual-path deseniyle birebir aynı fikir,
    # yalnız bu görev için scheduler.py'ye dokunulmadan route içinde.
    dispatched = False
    arq_pool = getattr(request.app.state, "arq_pool", None)
    if arq_pool is not None:
        try:
            arq_job = await arq_pool.enqueue_job(
                "process_twitter_fetch_task",
                str(job_id),
                str(tenant_id),
                term,
                body.count,
                handle,
                body.auto_create_tickets,
                body.relevance_check,
                body.brand_summary,
                str(current.user_id),
                payload.client_ip,
                _job_id=f"twitter-fetch:{job_id}",
                _queue_name="imga-batch",
            )
        except Exception:
            log.exception(
                "twitter fetch: arq enqueue failed; falling back to in-process",
                extra={"tenant_id": str(tenant_id), "job_id": str(job_id)},
            )
        else:
            dispatched = arq_job is not None
    if not dispatched:
        request.app.state.batch_scheduler.add_job(
            process_twitter_fetch_job,
            trigger="date",
            args=[job_id, tenant_id, payload, request.app.state.batch_worker_context],
            kwargs={"api_key": settings.twitterapi_io_key},
            id=f"twitter-fetch-{job_id}",
            replace_existing=True,
        )

    log.info(
        "twitter fetch queued: tenant=%s job_id=%s term=%r requested=%d dispatch=%s",
        tenant_id,
        job_id,
        term,
        body.count,
        "arq" if dispatched else "in-process",
    )
    return TwitterImportEnqueuedResponse(job_id=job_id, status="queued")


@router.get(
    "/jobs/{job_id}",
    response_model=TwitterFetchJobStatusResponse,
    summary="Arka plandaki Twitter'dan Çek işinin anlık durumu.",
    description=(
        "2sn aralıklarla poll edilir (SSE değil — bkz. modül docstring'i). "
        "Redis HASH'i hiç var olmadıysa ya da TTL'i dolduysa 404: bu içe "
        "aktarmanın BAŞARISIZ olduğu anlamına gelmez, yalnızca ilerleme "
        "izlemenin koptuğu anlamına gelir; iş arka planda sürüyor ya da "
        "bitmiş olabilir (Toplu Yüklemeler'de görünür)."
    ),
    responses={404: {"description": "İş bulunamadı ya da ilerleme izleme süresi doldu."}},
)
async def get_twitter_fetch_job(
    job_id: UUID,
    current: Annotated[CurrentUser, _TenantMember],
) -> TwitterFetchJobStatusResponse:
    tenant_id = _require_active_tenant(current)
    snapshot = await read_job(tenant_id, job_id)
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="twitter import job not found",
        )
    return TwitterFetchJobStatusResponse(job_id=job_id, **asdict(snapshot))
