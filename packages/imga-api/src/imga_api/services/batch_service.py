"""BatchAnalyzeService — CRUD over analyze_batch_jobs.

Sprint 8.3.1. The route layer uses this for create / list / get / cancel;
the worker uses it for status transitions and progress updates. Service
keeps no per-instance state — it's just SQL behind a thin shape.

Why a separate service from ReviewService: the bridge logic
(``record_and_decide``) is the "one decision per text" entry point and
already deals with tenant config / dedup / ticket creation. The batch
worker calls into that for every row, but the *job lifecycle* (queued
→ processing → completed) is orthogonal — keeping it here means the
worker can tick progress without dragging the bridge in.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from imga_core.llm import (
    AllKeysExhaustedError,
    GeminiKeyRotator,
    InvalidKeyError,
    LLMError,
)
from imga_db.models import AnalyzeBatchJob, BatchJobStatus, Review
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.llm.prompts.quality_report_v1 import (
    QUALITY_REPORT_RESPONSE_SCHEMA,
    QUALITY_REPORT_SYSTEM_PROMPT,
    render_quality_report_user_prompt,
)
from imga_api.services.audit_service import AuditService
from imga_api.services.llm_credentials import (
    NoCredentialsError,
    load_active_llm_keys,
    mark_keys_failed,
)
from imga_api.services.llm_provider_factory import (
    StructuredProvider,
    build_structured_provider,
    resolve_model_name,
)


class BatchServiceError(Exception):
    """Generic batch-service failure."""


class BatchJobNotFoundError(BatchServiceError):
    """Job missing or hidden by RLS."""


class BatchJobNotCancellableError(BatchServiceError):
    """Caller tried to cancel a job already in a terminal state."""


@dataclass(frozen=True, slots=True)
class BatchProgress:
    """Mutation payload for the worker's per-chunk progress update.

    Counts are *deltas* — service adds them onto the row to avoid
    losing concurrent ticket-bridge writes that race the chunk update.
    Use 0 for fields that didn't change in the current chunk.

    ``checkpoint_row`` is *absolute* — the row_number of the last row
    processed in the chunk. The service stores ``max(existing, new)``
    so retries can resume from the next row instead of replaying from
    the start (Sprint 9.0). 0 means "no advance" (chunk had no valid
    rows or the worker doesn't track checkpoints yet).
    """

    processed_delta: int = 0
    succeeded_delta: int = 0
    failed_delta: int = 0
    tickets_created_delta: int = 0
    duplicates_skipped_delta: int = 0
    rows_with_nps_delta: int = 0
    error_entries: list[dict[str, Any]] | None = None
    checkpoint_row: int = 0
    # 2026-08-18 (migration 0042) WS2 — veri kalitesi bayrak sayaçları.
    # Bu dördü ``succeeded_delta``'nın ALT KÜMESİDİR (bayraklı satırlar
    # da başarıyla bir Review olarak yazılır); worker her flag türünü
    # ayrı sayıp buraya taşır.
    quality_duplicate_delta: int = 0
    quality_empty_delta: int = 0
    quality_informational_delta: int = 0
    quality_meaningless_delta: int = 0


class BatchAnalyzeService:
    """Job CRUD on the imga_app or imga_admin session, depending on the
    caller. Routes use the RLS-bound app session; the worker uses the
    admin session (which still calls ``set_current_tenant`` for FORCE-
    aware visibility) so cross-tenant scheduler queries work."""

    def __init__(self, session: AsyncSession, audit: AuditService) -> None:
        self._session = session
        self._audit = audit

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    async def create_job(
        self,
        *,
        tenant_id: UUID,
        triggered_by_user_id: UUID,
        file_name: str,
        file_size_bytes: int,
        file_path: str,
        text_column: str,
        source_column: str | None,
        auto_create_tickets: bool,
        total_rows: int,
        ip_address: str | None = None,
    ) -> AnalyzeBatchJob:
        now = datetime.now(UTC)
        job = AnalyzeBatchJob(
            tenant_id=tenant_id,
            triggered_by_user_id=triggered_by_user_id,
            status=BatchJobStatus.QUEUED,
            file_name=file_name,
            file_size_bytes=file_size_bytes,
            file_path=file_path,
            text_column=text_column,
            source_column=source_column,
            auto_create_tickets=auto_create_tickets,
            total_rows=total_rows,
            error_summary=[],
            created_at=now,
        )
        self._session.add(job)
        await self._session.flush()
        await self._audit.log(
            action="batch.created",
            resource_type="batch_job",
            resource_id=job.id,
            tenant_id=tenant_id,
            actor_user_id=triggered_by_user_id,
            ip_address=ip_address,
            details={
                "file_name": file_name,
                "total_rows": total_rows,
                "auto_create_tickets": auto_create_tickets,
            },
        )
        return job

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_job(self, job_id: UUID) -> AnalyzeBatchJob:
        job = await self._session.get(AnalyzeBatchJob, job_id)
        if job is None:
            raise BatchJobNotFoundError(f"batch job {job_id} not found")
        return job

    async def list_jobs(
        self,
        *,
        tenant_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AnalyzeBatchJob]:
        stmt = (
            select(AnalyzeBatchJob)
            .where(AnalyzeBatchJob.tenant_id == tenant_id)
            .order_by(desc(AnalyzeBatchJob.created_at))
            .limit(limit)
            .offset(offset)
        )
        return list((await self._session.execute(stmt)).scalars())

    async def has_active_job(self, *, tenant_id: UUID) -> bool:
        """True if the tenant already has a queued/processing job. The
        scheduler uses this to enforce per-tenant concurrency: incoming
        uploads still create their job row but wait on the in-memory
        lock."""
        stmt = (
            select(AnalyzeBatchJob.id)
            .where(AnalyzeBatchJob.tenant_id == tenant_id)
            .where(
                AnalyzeBatchJob.status.in_(
                    [BatchJobStatus.QUEUED, BatchJobStatus.PROCESSING]
                )
            )
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none() is not None

    # ------------------------------------------------------------------
    # Status transitions
    # ------------------------------------------------------------------

    async def mark_processing(self, job_id: UUID) -> AnalyzeBatchJob:
        job = await self.get_job(job_id)
        if job.status != BatchJobStatus.QUEUED:
            return job  # idempotent — worker may retry
        job.status = BatchJobStatus.PROCESSING
        job.started_at = datetime.now(UTC)
        await self._session.flush()
        await self._audit.log(
            action="batch.processing",
            resource_type="batch_job",
            resource_id=job.id,
            tenant_id=job.tenant_id,
        )
        return job

    async def mark_completed(self, job_id: UUID) -> AnalyzeBatchJob:
        job = await self.get_job(job_id)
        if job.status in (
            BatchJobStatus.COMPLETED,
            BatchJobStatus.FAILED,
            BatchJobStatus.CANCELLED,
        ):
            return job
        job.status = BatchJobStatus.COMPLETED
        job.completed_at = datetime.now(UTC)
        await self._session.flush()
        await self._audit.log(
            action="batch.completed",
            resource_type="batch_job",
            resource_id=job.id,
            tenant_id=job.tenant_id,
            details={
                "succeeded_rows": job.succeeded_rows,
                "failed_rows": job.failed_rows,
                "tickets_created": job.tickets_created,
                "duplicates_skipped": job.duplicates_skipped,
            },
        )
        return job

    async def mark_failed(self, job_id: UUID, *, reason: str) -> AnalyzeBatchJob:
        job = await self.get_job(job_id)
        if job.status in (BatchJobStatus.COMPLETED, BatchJobStatus.CANCELLED):
            return job
        job.status = BatchJobStatus.FAILED
        job.completed_at = datetime.now(UTC)
        # Append the catastrophic reason onto error_summary so the UI
        # can surface it without a separate column.
        existing = list(job.error_summary or [])
        existing.append({"row": None, "error": reason})
        job.error_summary = existing[:100]
        # Sprint 9.0 — job-level last_error so the /batches detail UI
        # can show a single human message at the top instead of forcing
        # users to scroll error_summary.
        job.last_error = reason[:2048]
        await self._session.flush()
        await self._audit.log(
            action="batch.failed",
            resource_type="batch_job",
            resource_id=job.id,
            tenant_id=job.tenant_id,
            details={"reason": reason},
        )
        return job

    async def cancel_job(
        self,
        *,
        job_id: UUID,
        actor_user_id: UUID,
        ip_address: str | None = None,
    ) -> AnalyzeBatchJob:
        """Flag the job as cancelled. The worker checks this at every
        chunk boundary and stops; if the job is already done the call
        raises BatchJobNotCancellableError so the API can return 409."""
        job = await self.get_job(job_id)
        if job.status not in (BatchJobStatus.QUEUED, BatchJobStatus.PROCESSING):
            raise BatchJobNotCancellableError(
                f"job {job_id} is in terminal state {job.status}"
            )
        job.status = BatchJobStatus.CANCELLED
        job.cancelled_at = datetime.now(UTC)
        job.completed_at = job.cancelled_at
        await self._session.flush()
        await self._audit.log(
            action="batch.cancelled",
            resource_type="batch_job",
            resource_id=job.id,
            tenant_id=job.tenant_id,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
        )
        return job

    # ------------------------------------------------------------------
    # Progress (worker-only)
    # ------------------------------------------------------------------

    async def apply_progress(
        self,
        *,
        job_id: UUID,
        progress: BatchProgress,
    ) -> AnalyzeBatchJob:
        job = await self.get_job(job_id)
        job.processed_rows += progress.processed_delta
        job.succeeded_rows += progress.succeeded_delta
        job.failed_rows += progress.failed_delta
        job.tickets_created += progress.tickets_created_delta
        job.duplicates_skipped += progress.duplicates_skipped_delta
        job.rows_with_nps += progress.rows_with_nps_delta
        job.quality_duplicate_rows += progress.quality_duplicate_delta
        job.quality_empty_rows += progress.quality_empty_delta
        job.quality_informational_rows += progress.quality_informational_delta
        job.quality_meaningless_rows += progress.quality_meaningless_delta
        # Sprint 9.0 — checkpoint advances monotonically. Take max so
        # a late-arriving progress write from a stale chunk can't
        # rewind a later checkpoint that's already landed.
        if progress.checkpoint_row > job.last_checkpoint_row:
            job.last_checkpoint_row = progress.checkpoint_row
        if progress.error_entries:
            current = list(job.error_summary or [])
            for entry in progress.error_entries:
                if len(current) >= 100:
                    break
                current.append(entry)
            job.error_summary = current
        await self._session.flush()
        return job

    # ------------------------------------------------------------------
    # Retry (Sprint 9.0)
    # ------------------------------------------------------------------

    async def retry_job(
        self,
        *,
        job_id: UUID,
        actor_user_id: UUID,
        ip_address: str | None = None,
    ) -> AnalyzeBatchJob:
        """Re-queue a FAILED / CANCELLED job. The worker resumes from
        ``last_checkpoint_row`` so already-processed rows aren't double-
        counted. Counters preserved (succeeded_rows etc. stay frozen at
        the failure-time values); ``retry_count`` increments so the UI
        can flag chronic failures.

        Raises BatchJobNotCancellableError when the job is in a state
        from which retry doesn't make sense (queued / processing /
        completed).
        """
        job = await self.get_job(job_id)
        if job.status not in (
            BatchJobStatus.FAILED,
            BatchJobStatus.CANCELLED,
        ):
            raise BatchJobNotCancellableError(
                f"job {job_id} is not retryable in state {job.status}"
            )
        previous_error = job.last_error
        job.status = BatchJobStatus.QUEUED
        job.completed_at = None
        job.cancelled_at = None
        job.retry_count = (job.retry_count or 0) + 1
        # Eski hata özeti retry sonrasında UI'da "hâlâ bozuk" izlenimi
        # veriyordu (2026-08-09 OOM vakası) — satırdaki hata temizlenir,
        # denetim izi aşağıdaki batch.retry audit kaydında saklanır;
        # yeni hatalar worker'dan taze gelir.
        job.last_error = None
        job.error_summary = []
        await self._session.flush()
        await self._audit.log(
            action="batch.retry",
            resource_type="batch_job",
            resource_id=job.id,
            tenant_id=job.tenant_id,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            details={
                "retry_count": job.retry_count,
                "resume_from_row": job.last_checkpoint_row,
                "previous_error": previous_error,
            },
        )
        return job


# ---------------------------------------------------------------------------
# Quality report (2026-08-18, migration 0042, WS2)
# ---------------------------------------------------------------------------

#: En çok tekrarlanan metin listesinde tutulan üst sınır.
_TOP_REPEATED_TEXTS_LIMIT = 10
#: entered_by kırılımında tutulan üst sınır (savunma amaçlı — normalde
#: kurumun çalışan sayısı kadar, birkaç düzine).
_ENTERED_BY_BREAKDOWN_LIMIT = 100
#: Örnek metin kısaltma sınırı (rapor + LLM prompt'u şişmesin).
_SAMPLE_TEXT_MAX_CHARS = 200


class QualityReportResponseInvalidError(BatchServiceError):
    """LLM 200 döndü ama 'assessment' alanı boş/eksik."""


class QualityReportService:
    """Bir batch job'ın veri kalitesi raporu: sayaç okuma (LLM'siz) +
    TEK cached LLM özeti üretimi.

    ``build_report`` salt-okunurdur — job kolonlarındaki dört sayaç +
    ``reviews`` tablosundan iki agregasyon sorgusu (en çok tekrarlanan
    metinler, çalışan bazlı kırılım). ``generate_summary`` bunun
    üstüne TEK bir LLM çağrısı ekler ve sonucu ``job.quality_summary``
    JSONB'sine cache'ler — cache doluysa (force_refresh olmadan) LLM'e
    hiç dokunmaz, POST endpoint'i tekrar tekrar çağrılsa bile maliyet
    tek seferliktir.

    LLM çağrısı SWOT/OKR/kök-neden servisleriyle aynı desen (tenant'ın
    kazanan LLM kimliği + ``GeminiKeyRotator`` + ``LLMCallAuditor``).
    ``generate_root_cause`` metodu buradaki vekil: imga-core'daki
    ``_generate_structured``'a ince bir sarmalayıcı ve response_schema
    tamamen serbest — yeni bir ``generate_quality_report`` metodu
    eklemek imga-core'a dokunmayı gerektirirdi (bu dalganın kapsamı
    dışında), mevcut vekillerden birini generic olarak kullanmak aynı
    sonucu migration'sız verir. Denetim satırı ``call_type=
    'quality_report'`` ile yazılır (kısıt migration 0043 ile açıldı);
    ``related_entity_type='analyze_batch_job'`` + ``related_entity_id=
    job.id`` işi rapora bağlar.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        actor_user_id: UUID | None = None,
        provider: StructuredProvider | None = None,
    ) -> None:
        self._session = session
        self._actor_user_id = actor_user_id
        # Test izolasyonu için enjekte edilir; üretimde sağlayıcı
        # kurumun kazanan kimlik kaydına bağlı olduğundan
        # generate_summary() içinde kurulur (root_cause_service ile
        # aynı gerekçe).
        self._provider = provider

    async def build_report(self, job: AnalyzeBatchJob) -> dict[str, Any]:
        counts = {
            "duplicate": job.quality_duplicate_rows,
            "empty": job.quality_empty_rows,
            "informational": job.quality_informational_rows,
            "meaningless": job.quality_meaningless_rows,
        }
        top_repeated = await self._top_repeated_texts(job.id)
        entered_by = await self._entered_by_breakdown(job.id)
        return {
            "job_id": str(job.id),
            "total_rows": job.total_rows,
            "succeeded_rows": job.succeeded_rows,
            "counts": counts,
            "top_repeated_texts": top_repeated,
            "entered_by_breakdown": entered_by,
            "summary": job.quality_summary,
        }

    async def generate_summary(
        self,
        job: AnalyzeBatchJob,
        *,
        tenant_id: UUID,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """Cache doluysa ve ``force_refresh=False`` ise LLM'e hiç
        dokunmadan mevcut raporu döner. Aksi halde tek bir yapılandırılmış
        çağrı yapar ve sonucu kalıcı cache'ler.

        Raises:
            NoCredentialsError: kurumun aktif LLM anahtarı yok.
            AllKeysExhaustedError / LLMError: sağlayıcı çağrısı başarısız.
            QualityReportResponseInvalidError: LLM 200 döndü ama şema
                dolduramadı.
        """
        report = await self.build_report(job)
        if report["summary"] is not None and not force_refresh:
            return report

        key_selection = await load_active_llm_keys(self._session, tenant_id)
        if key_selection is None:
            raise NoCredentialsError(
                "Tenant has no active LLM API keys configured"
            )
        keys = key_selection.keys
        rotator = GeminiKeyRotator(keys)
        provider_name = key_selection.provider
        model_name = resolve_model_name(provider_name, key_selection.model)
        provider = self._provider or build_structured_provider(provider_name)

        user_prompt = render_quality_report_user_prompt(
            {
                "total_rows": report["total_rows"],
                "succeeded_rows": report["succeeded_rows"],
                "quality_duplicate_rows": report["counts"]["duplicate"],
                "quality_empty_rows": report["counts"]["empty"],
                "quality_informational_rows": report["counts"]["informational"],
                "quality_meaningless_rows": report["counts"]["meaningless"],
                "top_repeated_texts": report["top_repeated_texts"],
                "entered_by_breakdown": report["entered_by_breakdown"],
            }
        )

        failed_invalid_key_ids: list[UUID] = []

        async def _call(
            api_key: str,
        ) -> tuple[dict[str, Any], dict[str, int] | None]:
            try:
                return await provider.generate_root_cause(
                    api_key=api_key,
                    system_prompt=QUALITY_REPORT_SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                    response_schema=QUALITY_REPORT_RESPONSE_SCHEMA,
                    model_name=model_name,
                    temperature=0.2,
                    # 2048 canliya cikinca "token sinirina takildi" ile
                    # dusuyordu — GLM'in muhakeme token'lari da tavana
                    # sayiliyor; diger stratejik cagrilarin varsayilaniyla
                    # hizalandi.
                    max_output_tokens=8192,
                )
            except InvalidKeyError:
                for k in keys:
                    if k.value == api_key:
                        failed_invalid_key_ids.append(UUID(k.id))
                        break
                raise

        from imga_api.services.llm_audit_service import (
            CALL_TYPE_QUALITY_REPORT,
            LLMCallAuditor,
            LLMCallContext,
        )

        audit_ctx = LLMCallContext(
            tenant_id=tenant_id,
            call_type=CALL_TYPE_QUALITY_REPORT,
            model_name=model_name,
            model_provider=provider_name,
            prompt_template_key="quality_report",
            prompt_template_version="v1",
            actor_user_id=self._actor_user_id,
            related_entity_type="analyze_batch_job",
            related_entity_id=job.id,
        )
        auditor = LLMCallAuditor(self._session, audit_ctx, prompt=user_prompt)
        token_usage: dict[str, int] | None = None
        response: dict[str, Any] = {}
        try:
            async with auditor:
                try:
                    (response, token_usage), _key_used = (
                        await rotator.call_with_rotation(_call)
                    )
                except AllKeysExhaustedError as exc:
                    auditor.record_failure(
                        error_type="all_keys_exhausted",
                        error_message=str(exc.__cause__ or exc)[:1024],
                    )
                    raise
                except LLMError as exc:
                    auditor.record_failure(
                        error_type="api_error",
                        error_message=str(exc)[:1024],
                    )
                    raise
                except Exception as exc:
                    auditor.record_failure(
                        error_type="other",
                        error_message=f"{type(exc).__name__}: {exc}"[:1024],
                    )
                    raise
                auditor.record_success(
                    input_tokens=(
                        token_usage.get("input") if token_usage else None
                    ),
                    output_tokens=(
                        token_usage.get("output") if token_usage else None
                    ),
                )
        except AllKeysExhaustedError:
            await mark_keys_failed(self._session, failed_invalid_key_ids)
            raise
        except LLMError:
            raise

        if failed_invalid_key_ids:
            await mark_keys_failed(self._session, failed_invalid_key_ids)

        assessment = str(response.get("assessment", "")).strip()
        if not assessment:
            raise QualityReportResponseInvalidError(
                "quality report response missing 'assessment'"
            )

        summary_payload = {
            "assessment": assessment,
            "model_provider": provider_name,
            "model_name": model_name,
            "generated_at": datetime.now(UTC).isoformat(),
            # Özet metni bu anki sayılara/tekrarlara dayanıyordu — job'un
            # sayaçları ileride değişirse (yeni bir generate çağrısı
            # olmadan) hangi girdiye göre yazıldığı belirsizleşmesin diye
            # anlık görüntü de cache'e biner (kolon yorumundaki "istatistik
            # cache'i" vaadi).
            "input_snapshot": {
                "counts": report["counts"],
                "top_repeated_texts": report["top_repeated_texts"],
                "entered_by_breakdown": report["entered_by_breakdown"],
            },
        }
        job.quality_summary = summary_payload
        await self._session.flush()
        report["summary"] = summary_payload
        return report

    # --- private aggregation queries ------------------------------------

    async def _top_repeated_texts(self, job_id: UUID) -> list[dict[str, Any]]:
        stmt = (
            select(
                Review.text_hash,
                func.count().label("cnt"),
                func.min(Review.text).label("sample_text"),
            )
            .where(Review.batch_job_id == job_id)
            .where(Review.deleted_at.is_(None))
            .group_by(Review.text_hash)
            .having(func.count() > 1)
            .order_by(func.count().desc())
            .limit(_TOP_REPEATED_TEXTS_LIMIT)
        )
        rows = (await self._session.execute(stmt)).all()
        out: list[dict[str, Any]] = []
        for text_hash, cnt, sample_text in rows:
            trimmed = (
                sample_text
                if len(sample_text) <= _SAMPLE_TEXT_MAX_CHARS
                else sample_text[:_SAMPLE_TEXT_MAX_CHARS] + "…"
            )
            out.append(
                {
                    "text_hash": text_hash,
                    "count": int(cnt),
                    "sample_text": trimmed,
                }
            )
        return out

    async def _entered_by_breakdown(self, job_id: UUID) -> list[dict[str, Any]]:
        stmt = (
            select(
                Review.entered_by,
                func.count().label("total"),
                func.count()
                .filter(Review.quality_flag == "duplicate")
                .label("duplicate"),
                func.count()
                .filter(Review.quality_flag == "empty")
                .label("empty"),
                func.count()
                .filter(Review.quality_flag == "informational")
                .label("informational"),
                func.count()
                .filter(Review.quality_flag == "meaningless")
                .label("meaningless"),
            )
            .where(Review.batch_job_id == job_id)
            .where(Review.deleted_at.is_(None))
            .group_by(Review.entered_by)
            .order_by(func.count().desc())
            .limit(_ENTERED_BY_BREAKDOWN_LIMIT)
        )
        rows = (await self._session.execute(stmt)).all()
        return [
            {
                "entered_by": r.entered_by,
                "total": int(r.total),
                "duplicate": int(r.duplicate),
                "empty": int(r.empty),
                "informational": int(r.informational),
                "meaningless": int(r.meaningless),
            }
            for r in rows
        ]


__all__ = [
    "BatchAnalyzeService",
    "BatchJobNotCancellableError",
    "BatchJobNotFoundError",
    "BatchProgress",
    "BatchServiceError",
    "QualityReportResponseInvalidError",
    "QualityReportService",
]
