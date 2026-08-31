"""Yeniden analiz işçisi — mevcut ``reviews`` satırlarını birleşik
LLM yolundan yeniden geçirir.

2026-08-10. Sınıflandırma kalitesi (kategori tanımları + temas noktası
kararı) elden geçirildi; arşivdeki eski satırların yeni modeli
görmesi için ayrı bir "yeniden analiz" işi var. Mimari karar: YENİ
tablo/kolon açılmaz — ``analyze_batch_jobs`` makinesi olduğu gibi
kullanılır. İşin türü ``file_path``'teki ``reanalysis:<kapsam>``
işaretinden anlaşılır; ilerleme/checkpoint/iptal/yeniden-dene
kolonları birebir aynı anlamı taşır, dolayısıyla mevcut geçmiş ve
ilerleme arayüzü bu işi de normal bir iş gibi gösterir.

Üç sözleşme farkı yükleme işçisinden:

  * **BERT yedeği YOK.** Bayrak ne olursa olsun yeniden analiz
    yalnız birleşik yoldan koşar; motor kurulamaz ya da bir parça
    kalıcı çökerse iş net gerekçeyle FAILED olur (2026-08-10
    kararı: sessiz kalite düşüşü kabul edilmez).
  * **İnsan düzeltmesi dokunulmaz.** ``overrides_applied`` içinde
    ``user_correction`` / ``user_correction_kb`` /
    ``user_correction_semantic`` izi olan satırlar aday listesine
    hiç girmez.
  * **Satırlar yerinde güncellenir.** Yeni ``reviews`` satırı
    açılmaz; ``review_date`` / NPS / ticket bağlantısı / ``decision``
    korunur — yeniden analiz kararı değil, SINIFLANDIRMAYI tazeler.

2026-08-18 adversarial inceleme FX1 — ``quality_flag`` de artık burada
backfill edilir: ``'empty'`` satırlar zaten aday sorgusuna hiç girmez
(``_not_empty_quality`` — boş metni LLM'e göndermek israf), ``'duplicate'``
korunur (yalnız yükleme işçisinin dedup kararı bu bayrağı yazabilir),
diğer tüm satırlarda ``data_quality.classify_data_quality`` yeniden
koşar (``None`` dahil — eski yanlış bayrağı temizler). Düzeltme KB
eşleşmesi olan satırlarda (``_apply_corrections``'ın döndürdüğü
``correction_overrides``) hem ``quality_flag`` hem ``experience_type``/
``company_perspective_code`` insan kararından yazılır — LLM'in kendi
tahmini yalnız eşleşme YOKSA kazanır (``batch_analyzer._process_chunk``
ile birebir parite).
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any
from uuid import UUID

from imga_db import set_current_tenant
from imga_db.models import BatchJobStatus, Review
from sqlalchemy import (
    ColumnElement,
    Select,
    delete,
    func,
    not_,
    or_,
    select,
    text,
)
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.services.audit_service import AuditService
from imga_api.services.batch_service import BatchAnalyzeService, BatchProgress
from imga_api.services.data_quality import classify_data_quality, detect_content_type
from imga_api.workers.batch_analyzer import (
    WorkerContext,
    _apply_corrections,
    _build_unified_context,
    _commit_progress,
    _few_shot_for_chunk,
    _is_cancelled,
    _load_taxonomy_payload,
    _publish_terminal,
    _read_tenant_id,
    _record_catastrophic_failure,
    normalize_experience_type,
)

if TYPE_CHECKING:
    from imga_core import AnalysisResult

log = logging.getLogger("imga-api.workers.reanalysis")

# Yeniden analiz işini normal yüklemeden ayıran işaret. ``file_path``
# NOT NULL olduğu için sahte bir yol yerine anlamlı bir işaretçi
# konur: ``reanalysis:all`` ya da ``reanalysis:<kaynak job uuid>``.
REANALYSIS_PATH_PREFIX = "reanalysis:"
REANALYSIS_SCOPE_ALL = "all"

# Parça boyutu yükleme işçisinden bağımsız sabit: burada dosya
# akışı yok, aday listesi baştan biliniyor ve tek maliyet LLM
# çağrısı — 200 satır bir batch çağrı setine denk düşer.
REANALYSIS_CHUNK_SIZE = 200

# İnsan kararı taşıyan üç katman. Biri bile varsa satır yeniden
# analiz edilmez (aksi halde LLM insanın düzeltmesini ezerdi).
_CORRECTION_LAYERS = (
    "user_correction",
    "user_correction_kb",
    "user_correction_semantic",
)


# ---------------------------------------------------------------------------
# İş satırı işaretleri
# ---------------------------------------------------------------------------


def reanalysis_file_path(source_batch_job_id: UUID | None) -> str:
    scope = str(source_batch_job_id) if source_batch_job_id else REANALYSIS_SCOPE_ALL
    return f"{REANALYSIS_PATH_PREFIX}{scope}"


def is_reanalysis_job(file_path: str | None) -> bool:
    return bool(file_path) and str(file_path).startswith(REANALYSIS_PATH_PREFIX)


def reanalysis_scope(file_path: str) -> UUID | None:
    """``file_path`` işaretinden kaynak yükleme işini çözer. ``None``
    = tüm kurum. Bozuk/eski bir değer de ``None``'a düşer — kapsamı
    daraltamamak, işi patlatmaktan iyidir."""
    raw = str(file_path)[len(REANALYSIS_PATH_PREFIX) :]
    if raw == REANALYSIS_SCOPE_ALL:
        return None
    try:
        return UUID(raw)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Aday sorgusu — route (sayım) ve işçi (liste) AYNI yüklemi kullanır
# ---------------------------------------------------------------------------


def _not_human_corrected() -> ColumnElement[bool]:
    """İnsan düzeltmesi taşımayan satırlar.

    ``overrides_applied`` NULL olan satırlar (0014 öncesi analizler)
    kritik: ``NOT (col @> ...)`` bu satırlarda NULL üretir ve
    WHERE onları sessizce eler — oysa yeniden analize en çok
    ihtiyacı olanlar tam da onlar. NULL dalı bu yüzden açıkça
    yazılır."""
    contains = [
        Review.overrides_applied.op("@>")(text(f'\'[{{"layer": "{layer}"}}]\'::jsonb'))
        for layer in _CORRECTION_LAYERS
    ]
    return or_(
        Review.overrides_applied.is_(None),
        not_(or_(*contains)),
    )


def _not_empty_quality() -> ColumnElement[bool]:
    """2026-08-18 adversarial inceleme FX1 (a) — ``quality_flag=
    'empty'`` satırlar aday DEĞİLDİR. Bu satırlar zaten sabit NÖTR/0.0/
    'belirsiz'/0.0 değerleriyle yazıldı (bkz. batch_analyzer.
    _write_empty_reviews) ve metinleri gerçekten boş — LLM'e göndermek
    saf israf, sınıflandırılacak bir içerik yok. NULL dalı
    ``_not_human_corrected`` ile aynı gerekçeyle açıkça yazılır (NOT
    (col = 'empty') NULL satırları sessizce elerdi)."""
    return or_(
        Review.quality_flag.is_(None),
        Review.quality_flag != "empty",
    )


def candidate_stmt(
    *,
    tenant_id: UUID,
    source_batch_job_id: UUID | None,
) -> Select[tuple[UUID]]:
    """Yeniden analiz adaylarının id'leri, id sırasına göre.

    Sıralama sabit olmalı: ilerleme checkpoint'i satır KİMLİĞİ değil
    bu listedeki İNDEKS sayısıdır (yükleme işçisinde row_number ne
    ise burada o), retry aynı sırayı yeniden üretip baştaki N adayı
    atlar."""
    stmt = (
        select(Review.id)
        .where(Review.tenant_id == tenant_id)
        .where(Review.deleted_at.is_(None))
        .where(_not_human_corrected())
        .where(_not_empty_quality())
        .order_by(Review.id)
    )
    if source_batch_job_id is not None:
        stmt = stmt.where(Review.batch_job_id == source_batch_job_id)
    return stmt


async def count_candidates(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    source_batch_job_id: UUID | None,
) -> int:
    """İş satırının ``total_rows``'u. Route bunu kullanır; işçi aynı
    yüklemle listeyi çeker — ikisi ayrışırsa ilerleme çubuğu asla
    %100'e varmaz."""
    stmt = candidate_stmt(tenant_id=tenant_id, source_batch_job_id=source_batch_job_id).order_by(
        None
    )
    count_stmt = select(func.count()).select_from(stmt.subquery())
    return int((await session.execute(count_stmt)).scalar_one() or 0)


class NoReanalysisCandidatesError(Exception):
    """Kapsamda yeniden analiz edilecek satır yok (hepsi insan
    düzeltmeli ya da kapsam boş). Anında COMPLETED'a düşecek sahte
    bir iş açmak yerine route 400 döner."""


async def create_reanalysis_job(
    session: AsyncSession,
    audit: AuditService,
    *,
    tenant_id: UUID,
    triggered_by_user_id: UUID,
    source_batch_job_id: UUID | None,
    ip_address: str | None = None,
) -> Any:
    """Yeniden analiz işini ``analyze_batch_jobs``'a yazar.

    Yeni kolon yok: iş türü ``file_path`` işaretinden, kapsamı da
    aynı işaretten okunur. ``total_rows`` aday sayısıdır — ilerleme
    yüzdesi bu yüzden işçi tarafındaki aynı yüklemle tutarlı."""
    total = await count_candidates(
        session, tenant_id=tenant_id, source_batch_job_id=source_batch_job_id
    )
    if total <= 0:
        raise NoReanalysisCandidatesError(
            "Bu kapsamda yeniden analiz edilecek yorum yok. (İnsan "
            "düzeltmesi yapılmış yorumlar bilinçli olarak dışarıda "
            "bırakılır.)"
        )
    label = str(source_batch_job_id) if source_batch_job_id else REANALYSIS_SCOPE_ALL
    return await BatchAnalyzeService(session, audit).create_job(
        tenant_id=tenant_id,
        triggered_by_user_id=triggered_by_user_id,
        file_name=f"yeniden-analiz: {label}"[:256],
        file_size_bytes=0,
        file_path=reanalysis_file_path(source_batch_job_id),
        text_column="yorum",
        source_column=None,
        auto_create_tickets=False,
        total_rows=total,
        ip_address=ip_address,
    )


# ---------------------------------------------------------------------------
# Ana giriş — arq / scheduler buradan çağırır
# ---------------------------------------------------------------------------


async def process_reanalysis_job(job_id: UUID, context: WorkerContext) -> None:
    """``process_batch_job``'ın yeniden analiz ikizi. Aynı eşzamanlılık
    biletleri alınır: kurumun yüklemesi ile yeniden analizi aynı anda
    LLM bütçesine ve aynı satırlara yüklenmesin."""
    tenant_id = await _read_tenant_id(job_id, context.admin_session_factory)
    if tenant_id is None:
        log.warning("reanalysis worker: job %s missing or already gone", job_id)
        return

    async with context.global_semaphore, context.lock_for(tenant_id):
        log.info("reanalysis worker: starting job %s (tenant %s)", job_id, tenant_id)
        try:
            await _run_reanalysis(job_id, tenant_id, context)
        except Exception as exc:
            log.exception("reanalysis worker: job %s crashed: %s", job_id, exc)
            await _record_catastrophic_failure(job_id, tenant_id, context, reason=str(exc))
            # Çökme anına kadar commit edilen chunk'lar satırları
            # güncellemiş olabilir — önbellekler bayat kalmasın.
            await _bust_stale_caches(tenant_id, context)


async def _run_reanalysis(job_id: UUID, tenant_id: UUID, context: WorkerContext) -> None:
    job_started_at = time.monotonic()

    async with context.admin_session_factory() as admin_session, admin_session.begin():
        await set_current_tenant(admin_session, tenant_id)
        audit = AuditService(admin_session)
        job = await BatchAnalyzeService(admin_session, audit).mark_processing(job_id)
        if job.status != BatchJobStatus.PROCESSING:
            log.info(
                "reanalysis worker: job %s already terminal (%s); skipping",
                job_id,
                job.status,
            )
            return
        source_batch_job_id = reanalysis_scope(job.file_path)
        resume_from_index = int(job.last_checkpoint_row or 0)

    # Birleşik motor + düzeltme deposu + kategori tanımları. Yeniden
    # analizde klasik yol YOK: motor kurulamıyorsa iş burada, aksiyon
    # alınabilir bir mesajla biter.
    unified_ctx = await _build_unified_context(tenant_id, context)
    if unified_ctx is None:
        await _record_catastrophic_failure(
            job_id,
            tenant_id,
            context,
            reason=(
                "Yeniden analiz yapay zekâ sınıflandırmasını gerektirir; "
                "kurumda aktif LLM anahtarı yok ya da birleşik yol kapalı. "
                "Yeniden analiz BERT yedeğine DÜŞMEZ — anahtarı tanımlayıp "
                "işi Yeniden Dene ile başlatın."
            ),
        )
        return

    async with context.admin_session_factory() as admin_session, admin_session.begin():
        await set_current_tenant(admin_session, tenant_id)
        taxonomy_snapshot = await _load_taxonomy_payload(admin_session, tenant_id)
        candidate_ids = list(
            (
                await admin_session.execute(
                    candidate_stmt(
                        tenant_id=tenant_id,
                        source_batch_job_id=source_batch_job_id,
                    )
                )
            )
            .scalars()
            .all()
        )

    # Retry: baştaki ``resume_from_index`` aday zaten işlenmiş.
    # Sıralama id'ye göre sabit olduğundan indeks güvenilir; tek
    # kayma kaynağı, önceki koşuda anlamsal düzeltme damgası yiyen
    # bir satırın aday listesinden düşmesidir (o durumda en fazla
    # bir satır ikinci kez işlenir — idempotent).
    pending_ids = candidate_ids[resume_from_index:]
    processed_index = resume_from_index

    for offset in range(0, len(pending_ids), REANALYSIS_CHUNK_SIZE):
        chunk_ids = pending_ids[offset : offset + REANALYSIS_CHUNK_SIZE]
        if await _is_cancelled(job_id, tenant_id, context):
            log.info("reanalysis worker: job %s cancelled", job_id)
            # İptal noktasına kadar işlenen chunk'lar satırları çoktan
            # güncelledi — temizlik başarı dalıyla aynı, yoksa binlerce
            # güncel satıra karşın snapshot/brifing bayat kalır.
            await _bust_stale_caches(tenant_id, context)
            await _publish_terminal(job_id, tenant_id, context)
            return
        processed_index += len(chunk_ids)
        try:
            succeeded, failed = await _process_reanalysis_chunk(
                job_id=job_id,
                tenant_id=tenant_id,
                chunk_ids=chunk_ids,
                context=context,
                unified_ctx=unified_ctx,
                taxonomy_labels=taxonomy_snapshot.labels,
            )
        except Exception as exc:
            # LLM kalıcı olarak çöktü. Chunk-başı "satırları failed
            # say, devam et" geçidi YOK: yüzlerce parça tek tek
            # başarısızlık kaydına dönmesin diye iş burada durur ve
            # checkpoint'e kadarki güncellemeler kalıcı olur.
            log.exception("reanalysis worker: chunk failed permanently: %s", exc)
            await _record_catastrophic_failure(
                job_id,
                tenant_id,
                context,
                reason=(
                    "Yeniden analiz bu parçada kalıcı olarak başarısız "
                    f"oldu (BERT yedeğine düşülmez): {exc}"
                ),
            )
            # Checkpoint'e kadarki güncellemeler kalıcı — önbellekler de
            # onlara göre tazelenmeli.
            await _bust_stale_caches(tenant_id, context)
            return
        await _commit_progress(
            job_id=job_id,
            tenant_id=tenant_id,
            context=context,
            progress=BatchProgress(
                processed_delta=len(chunk_ids),
                succeeded_delta=succeeded,
                failed_delta=failed,
                checkpoint_row=processed_index,
            ),
        )

    async with context.admin_session_factory() as admin_session, admin_session.begin():
        await set_current_tenant(admin_session, tenant_id)
        audit = AuditService(admin_session)
        await BatchAnalyzeService(admin_session, audit).mark_completed(job_id)
    await _bust_stale_caches(tenant_id, context)
    await _publish_terminal(job_id, tenant_id, context)
    log.info(
        "reanalysis completed",
        extra={
            "batch_job_id": str(job_id),
            "tenant_id": str(tenant_id),
            "candidates": len(candidate_ids),
            "processed": processed_index,
            "duration_sec": round(time.monotonic() - job_started_at, 2),
        },
    )


async def _process_reanalysis_chunk(
    *,
    job_id: UUID,
    tenant_id: UUID,
    chunk_ids: list[UUID],
    context: WorkerContext,
    unified_ctx: Any,
    taxonomy_labels: dict[str, str],
) -> tuple[int, int]:
    """Bir parçayı sınıflandır ve satırları YERİNDE güncelle.

    LLM çağrısı bilinçli olarak transaction DIŞINDA: metinler kısa bir
    okuma işleminde alınır, çağrı boyunca satır kilidi tutulmaz, yazma
    ayrı bir işlemde yapılır (yükleme işçisiyle aynı sözleşme).
    """
    async with context.app_session_factory() as session, session.begin():
        await set_current_tenant(session, tenant_id)
        rows = (
            await session.execute(
                select(Review.id, Review.text).where(Review.id.in_(chunk_ids)).order_by(Review.id)
            )
        ).all()
    if not rows:
        return 0, 0

    ids = [r.id for r in rows]
    texts = [r.text for r in rows]

    few_shot, semantic_hits = await _few_shot_for_chunk(unified_ctx, texts, context, tenant_id)
    perspectives: list[str | None] = []
    experiences: list[str | None] = []
    stats_sink: dict[str, int] = {}
    analyses: list[AnalysisResult] = await context.pipeline.analyze_batch_unified_async(
        texts,
        engine=unified_ctx.engine,
        available_categories=unified_ctx.available_categories,
        few_shot=few_shot,
        stats_sink=stats_sink,
        perspective_options=unified_ctx.perspective_options,
        perspective_sink=perspectives,
        category_descriptions=unified_ctx.category_descriptions,
        experience_sink=experiences,
    )
    # 2026-08-18 adversarial inceleme FX1 (b) — ``_apply_corrections``
    # (analyses, correction_overrides) tuple'ı döner (bkz.
    # batch_analyzer.py). Önceki kod bu ikinci elemanı atıyordu ve
    # experience_type/perspective_code'u YALNIZ LLM sink'lerinden
    # (perspectives/experiences) okuyordu — insan kararı bir düzeltme
    # KB eşleşmesi (birebir ya da anlamsal) üzerinden gelse bile LLM'in
    # kendi tahmini onun üzerine YAZILIYORDU. Artık aşağıdaki döngü
    # correction_overrides'ı tüketir; batch_analyzer._process_chunk
    # (satır ~1154-1197) davranışıyla birebir parite.
    analyses, correction_overrides = _apply_corrections(analyses, texts, unified_ctx, semantic_hits)

    model_name = str(unified_ctx.engine.model_name)
    succeeded = 0
    async with context.app_session_factory() as session, session.begin():
        await set_current_tenant(session, tenant_id)
        objects = (await session.execute(select(Review).where(Review.id.in_(ids)))).scalars().all()
        by_id = {obj.id: obj for obj in objects}
        for index, review_id in enumerate(ids):
            review = by_id.get(review_id)
            if review is None:
                # RLS ya da eşzamanlı silme; sessizce atla (aşağıdaki
                # failed sayımına düşer).
                continue
            analysis = analyses[index]
            review.sentiment_label = analysis.sentiment_label
            review.sentiment_score = float(analysis.sentiment_score)
            if analysis.categorization is not None:
                review.primary_category = analysis.categorization.primary
                review.primary_confidence = float(analysis.categorization.primary_confidence)
            # 2026-08-18 adversarial inceleme FX1 (b) — insan kararı
            # (düzeltme KB eşleşmesi) LLM'in kendi tahmininin ÖNÜNE
            # geçer; batch_analyzer._process_chunk (satır ~1154-1197)
            # ile birebir parite. Perspektifte, LLM yolunun aksine,
            # taksonomi üyeliği KONTROL EDİLMEZ — insan kararı koşulsuz
            # güvenilir (batch_analyzer'daki aynı asimetri).
            correction_override = (
                correction_overrides[index] if index < len(correction_overrides) else None
            )
            llm_perspective = perspectives[index] if index < len(perspectives) else None
            correction_perspective = (
                correction_override.perspective_code if correction_override is not None else None
            )
            if correction_perspective is not None:
                review.company_perspective_code = correction_perspective
            elif llm_perspective is not None and llm_perspective in taxonomy_labels:
                review.company_perspective_code = llm_perspective
            review.experience_type = normalize_experience_type(
                correction_override.experience_type
                if correction_override is not None
                and correction_override.experience_type is not None
                else (experiences[index] if index < len(experiences) else None)
            )
            # 2026-08-18 adversarial inceleme FX1 (a) — quality_flag
            # backfill. 'duplicate' bayrağı yalnız yükleme işçisinin
            # dedup kararı yazabilir; yeniden analiz onu asla ezmez.
            # Düzeltme eşleşen satırda insan kararı = gerçek yorum ->
            # None (2. maddeyle tutarlı, bkz. batch_analyzer._process_
            # chunk). Diğer tüm satırlarda heuristik YENİDEN koşar
            # (None dahil — ilk tasarımın yanlış pozitiflerini taşıyan
            # eski bayrağı temizler).
            if review.quality_flag != "duplicate":
                review.quality_flag = (
                    None if correction_override is not None else classify_data_quality(review.text)
                )
            # Migration 0049 — content_type quality_flag'in İKİ guard'ına
            # (yukarıdaki 'duplicate' korunumu VE düzeltme eşleşen
            # satırlarda None'a sabitleme) TABİ DEĞİLDİR: tanımlayıcı bir
            # biçim işareti, kalite yargısı değil. 'duplicate' bayraklı
            # bir satır da, insan tarafından düzeltilmiş bir satır da
            # hâlâ soru biçiminde yazılmış olabilir — her iki durumda da
            # koşulsuz yeniden hesaplanır.
            review.content_type = detect_content_type(review.text)
            # JSONB listesi MutableList değil — yerinde append ORM'e
            # görünmez, satır kirli sayılmaz ve UPDATE hiç çıkmaz.
            # Yeni liste ATANIR.
            review.overrides_applied = _rewritten_overrides(
                review.overrides_applied, analysis, model_name
            )
            succeeded += 1

    log.info(
        "reanalysis chunk processed",
        extra={
            "batch_job_id": str(job_id),
            "tenant_id": str(tenant_id),
            "rows": len(ids),
            "rows_succeeded": succeeded,
            "llm_calls": stats_sink.get("llm_calls", 0),
        },
    )
    return succeeded, len(chunk_ids) - succeeded


def _rewritten_overrides(
    existing: list[dict[str, object]] | None,
    analysis: AnalysisResult,
    model_name: str,
) -> list[dict[str, object]]:
    """İz TAMAMEN yeniden yazılır: skoru yeni analiz belirledi, eski
    kural-katmanı izleri ve eski reanalysis işaretleri artık onu tarif
    etmiyor — atılırlar (tekrar koşularda dedupe'suz şişmeyi de keser).
    user_correction* girdileri savunma amaçlı korunur; aday sorgusu bu
    satırları normalde zaten dışlar."""
    kept: list[dict[str, object]] = [
        entry
        for entry in (existing or [])
        if isinstance(entry, dict) and str(entry.get("layer", "")).startswith("user_correction")
    ]
    return [
        *kept,
        *(hit.model_dump() for hit in analysis.overrides_applied),
        {"layer": "reanalysis", "detail": model_name},
    ]


# ---------------------------------------------------------------------------
# Önbellek temizliği
# ---------------------------------------------------------------------------


async def _bust_stale_caches(tenant_id: UUID, context: WorkerContext) -> None:
    """Üç terminal dalda da (başarı, iptal, kalıcı hata) koşar: iptal/
    hata yolunda da checkpoint'e kadarki satırlar güncellenmiş durumda.
    Tamamı best-effort — önbellek hijyeni iş durumunu değiştirmemeli;
    terminal durum yazıldıktan SONRA çağrılır ve buradan istisna sızarsa
    catch-all COMPLETED/CANCELLED bir işi FAILED'a çevirebilirdi."""
    try:
        async with context.admin_session_factory() as session, session.begin():
            await set_current_tenant(session, tenant_id)
            await _bust_snapshot_cache(session, tenant_id)
    except Exception:
        log.warning(
            "reanalysis: snapshot cache bust failed (non-fatal)",
            extra={"tenant_id": str(tenant_id)},
        )
    await _bust_redis_caches(tenant_id)


async def _bust_snapshot_cache(session: AsyncSession, tenant_id: UUID) -> None:
    """Yeniden analiz GEÇMİŞİ değiştirir (herhangi bir ``review_date``),
    bu yüzden ``SnapshotService.invalidate`` (yalnız bugün) yetmez —
    kurumun tüm anlık görüntüleri düşer, bir sonraki okuma taze
    hesaplar."""
    from imga_db.models import ExecutiveSnapshot

    await session.execute(delete(ExecutiveSnapshot).where(ExecutiveSnapshot.tenant_id == tenant_id))


# Yorumlardan türeyen Redis önbelleklerinin anahtar önekleri; hepsi
# ``{etiket}:{tenant_id}:...`` şemasını izler (executive_briefing_service,
# cohort_analyzer, heatmap_generator, word_cloud.generator). SWOT
# bilinçli dışarıda: anahtarı istatistik hash'i içerir, veri değişince
# kendiliğinden ıskalar ve eski girdi TTL ile düşer.
_REDIS_CACHE_PREFIXES = ("briefing", "cohort", "heatmap", "wordcloud")


async def _bust_redis_caches(tenant_id: UUID) -> None:
    """Redis'teki yorum-türevi analitik önbellekler (yönetici brifingi,
    cohort, heatmap, kelime bulutu). Best-effort: Redis erişilemezse iş
    durumu değişmez, en fazla TTL dolana kadar bayat veri görünür."""
    from imga_api.cache.redis_client import get_redis_client

    try:
        client = get_redis_client()
        keys = [
            key
            for prefix in _REDIS_CACHE_PREFIXES
            async for key in client.scan_iter(f"{prefix}:{tenant_id}:*")
        ]
        if keys:
            await client.delete(*keys)
    except Exception:
        log.warning(
            "reanalysis: redis cache bust failed (non-fatal)",
            extra={"tenant_id": str(tenant_id)},
        )


__all__ = [
    "REANALYSIS_CHUNK_SIZE",
    "REANALYSIS_PATH_PREFIX",
    "REANALYSIS_SCOPE_ALL",
    "NoReanalysisCandidatesError",
    "candidate_stmt",
    "count_candidates",
    "create_reanalysis_job",
    "is_reanalysis_job",
    "process_reanalysis_job",
    "reanalysis_file_path",
    "reanalysis_scope",
]
