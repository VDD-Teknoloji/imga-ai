"""``POST /tenants/me/analyze`` — tenant-scoped analyze + auto-ticket bridge.

The anonymous ``/analyze`` endpoint stays as-is for panel preview /
SDK use. This route is the production ingestion path: bearer auth,
tenant-bound RLS session, every call lands a row in ``reviews`` and
(on the CREATE branch) mints a ticket.

Five decision branches are surfaced verbatim to the client so the
frontend can show "ticket created" vs "skipped (mode/threshold/
belirsiz/dedup)" without inferring from heuristics. The decision is
also written to the audit log via ReviewService — see Sprint 7.5.5
Alt-Faz 3 design notes.

2026-08-18 (bulgu FX3) — the handler used to run inside ONE open RLS
transaction from ``bind_tenant`` all the way through the classify
call, the correction lookups, and the final write. A single provider
outage could hold that transaction (and its Postgres connection) for
up to ~17 minutes (4 rotation attempts x 240s OpenRouter hard-timeout
+ 5/15/30s inter-attempt sleeps, see
``imga_core.llm.unified_classifier.GeminiUnifiedEngine._call_with_rotation``)
— ~15 concurrent manual-analyze requests during an outage exhausts the
whole API's connection pool. The handler is now split into short
DB-only transactions with the external calls (embed, classify) running
outside any transaction, mirroring ``tenant_reviews.correct_review``
and ``workers/reanalyzer._process_reanalysis_chunk``:

  Faz 1 (short tx)  — bind tenant, build the unified context, load
                       embedding keys, recent correction examples, and
                       the exact (text_hash) correction lookup. DB
                       reads only.
  Faz 2 (no tx)     — one best-effort embed call for the review text,
                       reused for both the few-shot semantic examples
                       and the correction semantic lookup.
  Faz 3 (short tx)  — semantic reads (pgvector, indexed — no external
                       API), only if Faz 2 produced a vector.
  Faz 4 (no tx)     — classification. The unified attempt is capped at
                       ``_MANUAL_UNIFIED_TIMEOUT_SECONDS`` via
                       ``asyncio.wait_for`` so a single interactive
                       request never rides the engine's own multi-
                       minute rotation ladder; on timeout/failure it
                       falls back to the classic pipeline (unchanged
                       behaviour otherwise).
  (in-memory)       — apply the winning correction (exact > semantic)
                       to the analysis. Pure, no I/O.
  Faz 5 (write tx)  — audit row (retroactive, duration measured around
                       Faz 4 — same pattern as batch_analyzer's
                       chunk_auditor), perspective/experience
                       resolution, ``record_and_decide``, and the
                       business-dimension UPDATE.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from imga_core import AnalysisPipeline, AnalysisResult
from imga_core.llm.unified_classifier import (
    FewShotExample,
    GeminiUnifiedEngine,
    PerspectiveOptions,
)
from imga_db.models import Review, ReviewCorrection, UserTenantRole
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import CurrentUser, bind_tenant, require_role
from imga_api.db_deps import get_app_session
from imga_api.dependencies import get_pipeline, get_review_service
from imga_api.services import (
    CategoryNotConfiguredError,
    ReviewService,
)
from imga_api.services.executive_briefing_service import DEFAULT_MODEL_NAME
from imga_api.services.llm_audit_service import (
    CALL_TYPE_CLASSIFICATION,
    LLMCallAuditor,
    LLMCallContext,
)
from imga_api.workers.batch_analyzer import normalize_experience_type

if TYPE_CHECKING:
    from imga_api.services.correction_store import CorrectedDecision, CorrectionExample

log = logging.getLogger("imga-api.routes.tenant_analyze")

router = APIRouter(prefix="/tenants/me", tags=["Analyze"])

_AnyMember = Depends(require_role(
    UserTenantRole.TENANT_ADMIN,
    UserTenantRole.ANALYST,
    UserTenantRole.VIEWER,
))
# Sprint 13 yetki denetimi: analiz reviews'a satır yazar ve auto-ticket
# açabilir — salt-okuma viewer'ın işi değil.
_WriteMember = Depends(require_role(
    UserTenantRole.TENANT_ADMIN,
    UserTenantRole.ANALYST,
))


# --- request / response models -----------------------------------------


class TenantAnalyzeRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "text": "Kargom 5 gündür gelmedi, takip numarası da çalışmıyor.",
                "nps_score": 3,
                "business_segment": "premium",
                "channel": "mobile",
            }
        },
    )
    text: str = Field(..., min_length=1, max_length=10_000)
    # Sprint 8.3.5. Optional NPS (0–10). When the caller also captured
    # the customer's "would you recommend us?" score, pass it through
    # so the review row carries it into analytics. Skipping is fine —
    # the pipeline ignores the value, only persistence reads it.
    nps_score: int | None = Field(default=None, ge=0, le=10)
    # Sprint 9.3 B — business impact dimensions. All four optional;
    # the analyze endpoint passes them straight onto the Review row
    # for downstream analytics breakdown. No validation against the
    # tenant's ``allowed_values`` here — that's a route-layer policy
    # the next sprint can layer on top.
    business_segment: str | None = Field(default=None, max_length=128)
    product_line: str | None = Field(default=None, max_length=128)
    channel: str | None = Field(default=None, max_length=64)
    customer_tier: str | None = Field(default=None, max_length=64)


class TenantAnalyzeResponse(BaseModel):
    """Wire shape for /tenants/me/analyze.

    ``decision`` is one of: ``create`` / ``skipped_belirsiz`` /
    ``skipped_mode`` / ``skipped_threshold`` / ``skipped_dedup``.
    ``ticket_id`` is set on ``create`` (newly minted) and
    ``skipped_dedup`` (the existing ticket the dedup window pointed
    at); other branches leave it null.
    """

    review_id: UUID
    decision: str
    decision_reason: str | None
    ticket_id: UUID | None
    analyzed_at: datetime
    analysis: AnalysisResult
    # Sprint 8.3.5.6 — heuristic company-perspective match. Both fields
    # None when the heuristic didn't fire / taxonomy is empty.
    company_perspective_code: str | None = None
    company_perspective_label_tr: str | None = None


def _apply_correction_priority(
    analysis: AnalysisResult,
    *,
    exact: CorrectedDecision | None,
    semantic: CorrectedDecision | None,
) -> tuple[AnalysisResult, CorrectedDecision | None]:
    """Pure — no I/O. Birebir (``exact``) her zaman anlamsal
    (``semantic``) düzeltmeden önceliklidir (Sprint 11.3 sözleşmesi,
    batch worker'la aynı). ``exact``/``semantic`` çağıranın (route)
    AYRI fazlarda (Faz 1 / Faz 3) önceden okuduğu sonuçlardır — bu
    fonksiyon yalnız hangisinin kazandığına karar verip
    ``patch_analysis_with_decision``'ı çağırır; DB'ye ya da dış API'ye
    hiç dokunmaz."""
    from imga_api.services.correction_store import patch_analysis_with_decision

    if exact is not None:
        patched = patch_analysis_with_decision(
            analysis,
            exact,
            layer="user_correction_kb",
            detail_prefix="Tenant düzeltme sözlüğü",
        )
        return patched, exact
    if semantic is not None:
        patched = patch_analysis_with_decision(
            analysis,
            semantic,
            layer="user_correction_semantic",
            detail_prefix="Anlamsal düzeltme eşleşmesi (≥0.95)",
        )
        return patched, semantic
    return analysis, None


def _resolve_experience_and_perspective(
    *,
    correction_decision: CorrectedDecision | None,
    llm_perspective_code: str | None,
    llm_experience_type: str | None,
    perspective_labels: dict[str, str],
) -> tuple[str | None, tuple[str, str] | None]:
    """Pure — no I/O. 2026-08-18 (bulgu) — öncelik: insan düzeltmesi >
    birleşik motorun KENDİ tahmini (``perspective_sink``/
    ``experience_sink`` — bkz. ``_classify_manual_analysis``) > None
    (o zaman çağıran ``record_and_decide``'ın kendi heuristiğine/NULL'a
    düşer). Bu, batch worker'ın ``_process_chunk`` per-satır
    döngüsündeki ``correction_override`` > ``llm_perspective`` >
    heuristik önceliğiyle BİREBİR aynı.

    Eskiden bu route yalnız ``correction_decision``'ı okuyordu —
    birleşik motor aktifken bile LLM'in KENDİ perspektif/deneyim
    kararı (bir insan düzeltmesi olmadıkça) hiç Review satırına
    yazılmıyor, sessizce çöpe gidiyordu.

    Döner: ``(experience_type, perspective_override)`` —
    ``perspective_override`` ``None`` ise çağıran kendi heuristiğini/
    ``NULL``'ı uygular; dolu ise onun ÖNÜNE geçer."""
    correction_perspective = (
        correction_decision.perspective_code
        if correction_decision is not None
        else None
    )
    perspective_override: tuple[str, str] | None = None
    if correction_perspective is not None:
        perspective_override = (
            correction_perspective,
            perspective_labels.get(correction_perspective, correction_perspective),
        )
    elif (
        llm_perspective_code is not None
        and llm_perspective_code in perspective_labels
    ):
        perspective_override = (
            llm_perspective_code,
            perspective_labels[llm_perspective_code],
        )

    experience_source = (
        correction_decision.experience_type
        if correction_decision is not None
        and correction_decision.experience_type is not None
        else llm_experience_type
    )
    experience_type = normalize_experience_type(experience_source)
    return experience_type, perspective_override


@dataclass(slots=True)
class _ManualUnifiedContext:
    """2026-08-18 (WS3) — manuel tek-yorum analizi için istek-ömürlü
    birleşik sınıflandırma bağlamı. ``batch_analyzer.UnifiedJobContext``
    ile aynı fikir; iş(job)-ömürlü ``WorkerContext`` yerine tek bir
    RLS-bağlı ``app_session`` üzerine kurulu — HTTP isteği zaten kendi
    transaction'ını taşıyor, ayrı bir admin engine/tenant lock'a
    gerek yok."""

    engine: GeminiUnifiedEngine
    available_categories: list[str]
    perspective_options: PerspectiveOptions
    category_descriptions: dict[str, str]
    perspective_labels: dict[str, str]
    embedding_keys: list[Any]  # list[GeminiKey] — embed çağrıları için


async def _build_manual_unified_context(
    session: AsyncSession, tenant_id: UUID
) -> _ManualUnifiedContext | None:
    """Tenant'ın aktif LLM anahtarı varsa birleşik motoru kurar
    (``batch_analyzer._build_unified_context`` ile aynı sözleşme,
    ``WorkerContext`` yerine tek bir ``AsyncSession`` üzerinden);
    yoksa ``None`` — çağıran (route) klasik ``pipeline.analyze``'a
    düşer.

    Batch'in aksine BERT yedeği burada asla bayrakla KAPATILMAZ: tek
    etkileşimli bir istek için ("kurulamadıysa iş dursun") toplu
    işin gerekçeleri (sessiz kalite düşüşü binlerce satıra yayılır,
    worker OOM'u) geçerli değil — motor kurulamazsa/düşerse zaten var
    olan klasik yol (mevcut davranış) hiç değişmeden devreye girer.

    Yalnız DB okur — dış API çağrısı yapmaz (route'un Faz 1'inde,
    açık kısa bir transaction içinde çağrılır)."""
    from imga_api.workers.batch_analyzer import (
        _load_taxonomy_payload,
        _load_tenant_category_snapshot,
        _unified_enabled,
        _unified_model_name,
    )

    if not _unified_enabled():
        return None

    from imga_api.services.llm_credentials import (
        load_active_gemini_keys,
        load_active_llm_keys,
    )

    try:
        selection = await load_active_llm_keys(session, tenant_id)
        # 2026-08-18 — kısa-devre EN erken noktada: tenant'ın aktif
        # LLM anahtarı yoksa (en yaygın durum — anahtarsız tenant'lar
        # her manuel analiz isteğinde bu yola girer) kategori/taksonomi/
        # embedding-key/prompt-override sorgularının HİÇBİRİ çalışmaz.
        # Batch'te bu maliyet iş başına bir kez; burada istek başına —
        # aynı sıralama hatası (eskiden bu kontrol try bloğunun SONUNDA
        # idi) prod'da her anahtarsız manuel analiz çağrısına ~4 gereksiz
        # sorgu bindiriyordu.
        if selection is None:
            log.info(
                "manual analyze: no LLM keys; unified classifier disabled "
                "for this request (classic path)",
                extra={"tenant_id": str(tenant_id)},
            )
            return None
        embedding_keys = await load_active_gemini_keys(session, tenant_id)
        category_snapshot = await _load_tenant_category_snapshot(
            session, tenant_id
        )
        taxonomy_snapshot = await _load_taxonomy_payload(session, tenant_id)
        # /settings/prompts override'ı — batch worker'la aynı, kendi
        # try'ında: override OPSİYONEL, şablon sorgusu patlarsa
        # unified yolun tamamı feda edilmez.
        system_prompt_override: str | None = None
        try:
            from imga_api.services.prompt_resolver import PromptResolver

            template_row = await PromptResolver(session).resolve_template(
                template_key="unified_classifier", tenant_id=tenant_id
            )
            if template_row is not None:
                system_prompt_override = template_row.system_prompt
        except Exception:
            log.warning(
                "manual analyze: unified prompt override lookup failed; "
                "using code default system prompt",
                extra={"tenant_id": str(tenant_id)},
            )
    except Exception:
        log.exception(
            "manual analyze: unified context build failed; classic path",
            extra={"tenant_id": str(tenant_id)},
        )
        return None

    from imga_api.services.llm_provider_factory import resolve_model_name

    if selection.provider == "openrouter":
        unified_model = resolve_model_name("openrouter", selection.model)
    else:
        unified_model = selection.model or _unified_model_name()

    engine = GeminiUnifiedEngine(
        selection.keys,
        model_name=unified_model,
        system_prompt=system_prompt_override,
        provider=selection.provider,
    )
    return _ManualUnifiedContext(
        engine=engine,
        available_categories=category_snapshot.codes,
        perspective_options=taxonomy_snapshot.perspective_options,
        category_descriptions=category_snapshot.descriptions,
        perspective_labels=taxonomy_snapshot.labels,
        embedding_keys=embedding_keys,
    )


async def _load_recent_correction_examples(
    session: AsyncSession, tenant_id: UUID
) -> list[CorrectionExample]:
    """Faz 1'in few-shot okuma adımı: tenant'ın en güncel
    ``FEW_SHOT_LIMIT`` düzeltmesi (batch worker'ın
    ``store.recent_examples``'ıyla aynı sorgu şekli). Yalnız DB okur —
    dış API çağrısı yok, ``unified is not None`` olduğu bilinen bir
    çağrı yerinden (route Faz 1) çağrılmalı (few-shot yalnız birleşik
    motor aktifken anlamlı, bkz. rag-mimari.md §2)."""
    from imga_api.services.correction_store import FEW_SHOT_LIMIT, CorrectionExample

    rows = (
        await session.execute(
            select(
                ReviewCorrection.review_text,
                ReviewCorrection.new_sentiment_label,
                ReviewCorrection.new_category,
                ReviewCorrection.reason,
            )
            .where(ReviewCorrection.tenant_id == tenant_id)
            .order_by(ReviewCorrection.created_at.desc())
            .limit(FEW_SHOT_LIMIT)
        )
    ).all()
    return [
        CorrectionExample(text=t, sentiment_label=s, category=c, reason=r)
        for t, s, c, r in rows
    ]


# 2026-08-18 (bulgu FX3) — manuel tek-yorum analizinde birleşik motoru
# TEK TUR dener: rotasyon merdivenine (4 deneme × 240s OpenRouter hard-
# timeout + 5/15/30s uykular, bkz. imga_core.llm.unified_classifier.
# GeminiUnifiedEngine._call_with_rotation / _ROTATION_RETRY_DELAYS)
# asla girmeden ~60s içinde ya sonuç ya da klasik fallback. imga-core
# bu dalga donduruldu — motor imzasında retry sayısını kapatan bir
# parametre yok (yalnız modül-özel sabitler), bu yüzden tavan burada
# (route katmanında, asyncio.wait_for ile) uygulanır. Tek yorumluk
# interaktif bir istek için 4×240s retry merdiveni anlamsız — ~17
# dakika bağlantı/transaction tutma riskini taşır (bkz. modül
# docstring'i). Fonksiyon gövdesinde okunur (parametre varsayılanı
# DEĞİL) ki testler ``monkeypatch.setattr`` ile değiştirebilsin.
_MANUAL_UNIFIED_TIMEOUT_SECONDS = 60.0


async def _classify_manual_analysis(
    text: str,
    pipeline: AnalysisPipeline,
    unified: _ManualUnifiedContext | None,
    few_shot: tuple[FewShotExample, ...],
) -> tuple[AnalysisResult, bool, str, str, str | None, str | None]:
    """Sınıflandırma: birleşik motor mevcutsa öncelik onun (few-shot
    enjeksiyonu YALNIZ bu yoldan mümkün — ``HybridClassifier``'ın
    klasik yolu few-shot desteklemiyor, bkz. rag-mimari.md §2); motor
    yoksa, tekil çağrısı düşerse YA DA ``_MANUAL_UNIFIED_TIMEOUT_
    SECONDS`` aşarsa klasik BERT+keyword/LLM hibrit yoluna (mevcut
    davranış, değişmedi) düşülür — batch'in aksine BERT yedeği burada
    asla bayrakla KAPATILMAZ (tek etkileşimli istek, toplu işin OOM/
    sessiz-kalite-yayılması gerekçeleri geçerli değil).

    Döner: ``(analysis, llm_used, audit_model_name, audit_provider,
    llm_perspective_code, llm_experience_type)``. Son iki alan
    birleşik motorun KENDİ (düzeltmeden bağımsız) alt kategori/temas
    noktası tahmini — ``pipeline.analyze_batch_unified_async``'ın
    ``perspective_sink``/``experience_sink`` out-param deseni (bkz. o
    fonksiyonun docstring'i); daha önce bu route'ta hiç geçilmiyordu.
    Klasik yola düşülürse ikisi de ``None`` — çağıran heuristik/NULL'a
    düşer."""
    if unified is not None:
        perspective_sink: list[str | None] = []
        experience_sink: list[str | None] = []
        try:
            results = await asyncio.wait_for(
                pipeline.analyze_batch_unified_async(
                    [text],
                    engine=unified.engine,
                    available_categories=unified.available_categories,
                    few_shot=few_shot,
                    perspective_options=unified.perspective_options,
                    category_descriptions=unified.category_descriptions,
                    perspective_sink=perspective_sink,
                    experience_sink=experience_sink,
                ),
                timeout=_MANUAL_UNIFIED_TIMEOUT_SECONDS,
            )
            return (
                results[0],
                True,
                unified.engine.model_name,
                unified.engine.provider,
                perspective_sink[0] if perspective_sink else None,
                experience_sink[0] if experience_sink else None,
            )
        except TimeoutError:
            log.warning(
                "manual analyze: unified classify exceeded %.0fs safety "
                "cap; falling back to classic pipeline without waiting "
                "for the engine's own rotation ladder (up to ~17min)",
                _MANUAL_UNIFIED_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            log.warning(
                "manual analyze: unified classify failed; falling back "
                "to classic pipeline: %s",
                exc,
            )
    analysis = await asyncio.to_thread(pipeline.analyze, text)
    llm_used = (
        analysis.categorization is not None
        and analysis.categorization.llm_result is not None
    )
    return analysis, llm_used, DEFAULT_MODEL_NAME, "gemini", None, None


def _require_active_tenant(current: CurrentUser) -> UUID:
    if current.active_tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="active tenant context required for this endpoint",
        )
    return current.active_tenant_id


# --- endpoint ----------------------------------------------------------


@router.post(
    "/analyze",
    response_model=TenantAnalyzeResponse,
    summary="Analyze a review and apply the auto-ticket bridge.",
    description=(
        "Runs the analysis pipeline against ``text`` and writes a row "
        "to ``reviews`` capturing the result + bridge decision. The "
        "decision is one of five branches — see the response schema "
        "for the enum. ``ticket_id`` is non-null on ``create`` (new "
        "ticket) and on ``skipped_dedup`` (pointer to the ticket the "
        "earlier identical text already produced within 24h)."
    ),
    responses={
        500: {"description": "Classifier returned an unconfigured category."},
    },
)
async def tenant_analyze(
    body: TenantAnalyzeRequest,
    current: Annotated[CurrentUser, _WriteMember],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    pipeline: Annotated[AnalysisPipeline, Depends(get_pipeline)],
    reviews: Annotated[ReviewService, Depends(get_review_service)],
) -> TenantAnalyzeResponse:
    """Tenant-scoped analyze with bridge wired.

    2026-08-18 (bulgu FX3) — multi-phase now (see module docstring):
    short DB-only transactions around the external embed/classify
    calls instead of one transaction spanning the whole request. A
    classifier exception raised during Faz 4 (outside any transaction)
    simply propagates as a 500 before any row is touched — nothing to
    roll back yet, unlike the old single-transaction design."""
    from imga_core.text_utils import review_text_hash

    tenant_id = _require_active_tenant(current)
    text_hash = review_text_hash(body.text)

    # --- Faz 1 (KISA ön-transaction): bağlam + anahtarlar + son
    # düzeltme örnekleri + birebir düzeltme araması. DB okuma dışında
    # HİÇBİR şey yok.
    async with app_session.begin():
        await bind_tenant(app_session, current)

        unified = await _build_manual_unified_context(app_session, tenant_id)
        embedding_keys: list[Any]
        if unified is not None:
            embedding_keys = unified.embedding_keys
        else:
            from imga_api.services.llm_credentials import (
                load_active_gemini_keys,
            )

            embedding_keys = await load_active_gemini_keys(
                app_session, tenant_id
            )

        from imga_api.services.correction_store import latest_exact_correction

        exact = await latest_exact_correction(app_session, tenant_id, text_hash)
        # Few-shot yalnız unified aktifken anlamlı — HybridClassifier'ın
        # klasik yolu few-shot desteklemiyor (bkz. rag-mimari.md §2).
        # Eski davranışla aynı kısa-devre: unified None ise bu sorgu
        # HİÇ çalışmaz (klasik-yol + birebir-eşleşme isteğinde gereksiz
        # bir DB okuması eklenmesin).
        recent: list[CorrectionExample] = []
        if unified is not None:
            recent = await _load_recent_correction_examples(
                app_session, tenant_id
            )

    # --- Faz 2 (transaction DIŞINDA): TEK embed çağrısı — hem few-shot
    # anlamsal örnekleri hem düzeltme anlamsal araması metnin AYNI
    # vektörünü kullanır (tek istek için tek satır — chunk-centroid
    # değil). Ne few-shot'ta ne birebir-dışı düzeltme aramasında
    # ihtiyaç yoksa embed API'sine HİÇ dokunulmaz (batch'teki ``if
    # recent:`` geçidiyle aynı tasarruf).
    need_vector = bool(recent) or exact is None
    vector: list[float] | None = None
    if need_vector:
        try:
            from imga_api.services.embedding_service import embed_text

            vector = await embed_text(body.text, embedding_keys)
        except Exception as exc:
            log.warning("manual analyze: embed call failed: %s", exc)
            vector = None

    # --- Faz 3 (KISA tx, yalnız vektör varsa): pgvector indeksli
    # okumalar — dış API YOK.
    semantic_examples: list[CorrectionExample] = []
    semantic_decision: CorrectedDecision | None = None
    if vector is not None:
        async with app_session.begin():
            await bind_tenant(app_session, current)
            from imga_api.services.correction_store import (
                nearest_corrections,
                semantic_override_lookup,
            )

            if recent:
                semantic_examples = await nearest_corrections(
                    app_session, tenant_id, vector
                )
            if exact is None:
                semantic_decision = await semantic_override_lookup(
                    app_session, tenant_id, vector
                )

    from imga_api.services.correction_store import merge_few_shot

    merged = merge_few_shot(recent, semantic_examples)
    few_shot = tuple(
        FewShotExample(
            text=e.text,
            sentiment_label=e.sentiment_label,
            category=e.category,
            reason=e.reason,
        )
        for e in merged
    )

    # --- Faz 4 (transaction DIŞINDA): sınıflandırma. Süre elle
    # ölçülür — auditor artık çağrıyı SARMIYOR (Faz 5'te retroaktif
    # kayıt, batch_analyzer'ın chunk_auditor deseniyle aynı: "The BERT/
    # LLM call already ran outside the transaction; this block is a
    # no-op body whose only job is to flip the auditor flags").
    classify_started = time.monotonic()
    (
        analysis,
        llm_used,
        audit_model_name,
        audit_provider,
        llm_perspective_code,
        llm_experience_type,
    ) = await _classify_manual_analysis(body.text, pipeline, unified, few_shot)
    classify_duration_ms = int((time.monotonic() - classify_started) * 1000)

    # --- Bellek-içi (I/O YOK): birebir > anlamsal düzeltme önceliği.
    analysis, correction_decision = _apply_correction_priority(
        analysis, exact=exact, semantic=semantic_decision
    )

    # --- Faz 5 (AYRI yazma transaction'ı): retroaktif audit satırı +
    # perspektif/deneyim çözümü + record_and_decide + UPDATE.
    async with app_session.begin():
        await bind_tenant(app_session, current)

        # Sprint 9.4.3 A — her /tenants/me/analyze isteği bir
        # ``llm_call_audit`` satırı bırakır.
        audit_ctx = LLMCallContext(
            tenant_id=tenant_id,
            call_type=CALL_TYPE_CLASSIFICATION,
            model_name=audit_model_name,
            model_provider=audit_provider,
            actor_user_id=current.user_id,
        )
        auditor = LLMCallAuditor(app_session, audit_ctx, prompt=body.text)
        async with auditor:
            auditor.mark_fallback_used(not llm_used)
            auditor.record_success(duration_ms=classify_duration_ms)

        # 2026-08-18 (bulgu) — LLM'in KENDİ perspektif/deneyim
        # tahminini okumak için etiket sözlüğü gerekir: unified
        # aktifken zaten Faz 1'de yüklendi (ek sorgu yok); yalnız
        # klasik yola düşüldüyse VE bir insan düzeltmesi perspective_
        # code taşıyorsa (etiketini göstermek için) tembel okunur —
        # eski davranışla birebir aynı koşul.
        perspective_labels: dict[str, str] = {}
        if unified is not None:
            perspective_labels = unified.perspective_labels
        elif (
            correction_decision is not None
            and correction_decision.perspective_code is not None
        ):
            from imga_api.workers.batch_analyzer import _load_taxonomy_payload

            perspective_labels = (
                await _load_taxonomy_payload(app_session, tenant_id)
            ).labels

        experience_type, perspective_override = _resolve_experience_and_perspective(
            correction_decision=correction_decision,
            llm_perspective_code=llm_perspective_code,
            llm_experience_type=llm_experience_type,
            perspective_labels=perspective_labels,
        )

        try:
            result = await reviews.record_and_decide(
                tenant_id=tenant_id,
                text=body.text,
                analysis=analysis,
                actor_user_id=current.user_id,
                nps_score=body.nps_score,
                perspective_override=perspective_override,
            )
        except CategoryNotConfiguredError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(exc),
            ) from exc

        # Sprint 9.3 B — back-fill business impact dimensions on the
        # row record_and_decide just minted. The bridge service is
        # dimension-agnostic; doing the patch here keeps the bridge
        # path narrow + lets every dimension stay nullable. UPDATE
        # only when at least one is set. 2026-08-18 (bulgu) —
        # ``experience_type`` now carries the human correction OR the
        # unified engine's own prediction (see
        # ``_resolve_experience_and_perspective``), not just the
        # correction as before.
        if any(
            v is not None
            for v in (
                body.business_segment,
                body.product_line,
                body.channel,
                body.customer_tier,
                experience_type,
            )
        ):
            await app_session.execute(
                sa_update(Review)
                .where(Review.id == result.review_id)
                .values(
                    business_segment=body.business_segment,
                    product_line=body.product_line,
                    channel=body.channel,
                    customer_tier=body.customer_tier,
                    experience_type=experience_type,
                )
            )

    return TenantAnalyzeResponse(
        review_id=result.review_id,
        decision=str(result.decision),
        decision_reason=result.decision_reason,
        ticket_id=result.ticket_id,
        analyzed_at=result.analyzed_at,
        analysis=analysis,
        company_perspective_code=result.company_perspective_code,
        company_perspective_label_tr=result.company_perspective_label_tr,
    )
