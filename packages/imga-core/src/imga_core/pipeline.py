"""End-to-end analysis pipeline: orchestrates overrides + BERT + post-processing."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from imga_core.analyzers.base import AnalyzerPrediction, SentimentAnalyzer
from imga_core.classifiers.base import CategoryClassifier
from imga_core.config import (
    LABEL_NEGATIVE,
    LABEL_NEUTRAL,
    LABEL_POSITIVE,
    SENTIMENT_NEGATIVE_THRESHOLD,
    SENTIMENT_POSITIVE_THRESHOLD,
)
from imga_core.models import AnalysisResult, CategoryClassification, OverrideHit
from imga_core.overrides import (
    KnowledgeBase,
    SLAParams,
    apply_critical_override,
    apply_sla_override,
    apply_tier1_override,
    apply_tier2_fallback,
)
from imga_core.perspectives import (
    classify_company_perspective,
    classify_customer_perspective,
)
from imga_core.rules import RuleEngine
from imga_core.summary import generate_heuristic_summary

if TYPE_CHECKING:
    from imga_core.llm.unified_classifier import (
        FewShotExample,
        GeminiUnifiedEngine,
    )

_logger = logging.getLogger(__name__)


class AnalysisPipeline:
    """Wire the override layers around a sentiment analyzer.

    Layer order per text:
        1. Knowledge base (exact-match user corrections)
        2. Critical-keyword override
        3. Tier-1 sentiment override
        4. BERT inference (batched across all non-overridden texts)
        5. SLA detection
        6. Tier-2 operational fallback
    Then per-text post-processing: summary, perspectives, risk class.
    """

    def __init__(
        self,
        analyzer: SentimentAnalyzer,
        knowledge_base_path: Path | str | None = None,
        rules_path: Path | str | None = None,
        sla_params: SLAParams | None = None,
        classifier: CategoryClassifier | None = None,
    ) -> None:
        self.analyzer = analyzer
        self.kb = KnowledgeBase(knowledge_base_path) if knowledge_base_path else None
        self.rules = RuleEngine(rules_path) if rules_path else None
        self.sla_params = sla_params or SLAParams()
        self.classifier = classifier

    def analyze(self, text: str) -> AnalysisResult:
        return self.analyze_batch([text])[0]

    async def analyze_batch_unified_async(
        self,
        texts: list[str],
        *,
        engine: "GeminiUnifiedEngine",
        available_categories: list[str],
        few_shot: tuple["FewShotExample", ...] = (),
        stats_sink: dict[str, int] | None = None,
    ) -> list[AnalysisResult]:
        """Sprint 11.0 — birleşik LLM yolu: sentiment + kategori tek
        Gemini batch çağrı setinden gelir; BERT ve keyword/LLM-fallback
        classifier hiç çalışmaz.

        Override sözleşmesi klasik yolla birebir: pre-BERT katmanları
        (KB/critical/tier1) LLM'den ÖNCE kararı kilitler; post
        katmanları (SLA/tier2) LLM sentiment'i üstünde aynı kurallarla
        oynar — LLM, BERT'in koltuğuna oturur, mimari değişmez.

        Hata sözleşmesi: motor üretemezse exception BURADAN yükselir;
        çağıran (worker/route) klasik ``analyze_batch_async``'e düşer.
        Few-shot örnekleri tenant düzeltmelerinden gelir — "modelin
        öğrenmesi" bu enjeksiyondur.
        """
        n = len(texts)
        if n == 0:
            return []
        normalized = [t if isinstance(t, str) else "" for t in texts]

        pre_overrides: list[OverrideHit | None] = [None] * n
        for i, text in enumerate(normalized):
            pre_overrides[i] = self._pre_bert_lookup(text)

        predictions, stats = await engine.classify_unified_batch_async(
            normalized,
            available_categories=available_categories,
            few_shot=few_shot,
        )
        if stats_sink is not None:
            stats_sink["llm_total_input_tokens"] = stats.input_tokens
            stats_sink["llm_total_output_tokens"] = stats.output_tokens
            stats_sink["llm_duration_ms"] = stats.duration_ms
            stats_sink["llm_calls"] = stats.calls

        results: list[AnalysisResult] = []
        for i, text in enumerate(normalized):
            unified = predictions[i]
            categorization = CategoryClassification(
                primary=unified.category,
                primary_confidence=unified.category_confidence,
                method="llm",
                requires_manual_review=unified.category_confidence < 0.3,
            )
            results.append(
                self._build_result(
                    text,
                    pre_overrides[i],
                    AnalyzerPrediction(
                        label=unified.sentiment_label,
                        score=unified.sentiment_score,
                    ),
                    categorization,
                )
            )
        return results

    async def analyze_batch_async(
        self,
        texts: list[str],
        *,
        classifier: CategoryClassifier | None = None,
        classifier_stats_sink: dict[str, int] | None = None,
    ) -> list[AnalysisResult]:
        """Sprint 9.0.5-A B2 — async variant that runs BERT inference
        and category classification in parallel.

        The two are independent (they both read ``normalized`` and
        produce disjoint outputs), so dispatching each to a thread
        via ``asyncio.to_thread`` and gathering halves the wall-clock
        for the slow steps. The pre-BERT and post-BERT passes stay
        in the calling task — they're cheap dict ops.

        Sync ``analyze_batch`` stays for legacy callers (Streamlit
        dashboard, simple scripts). The batch worker uses this async
        variant after Sprint 9.0.5-A so the event loop is also
        available to peer chunks while BERT runs in its thread.

        Sprint 9.0.5-A R5 — optional ``classifier`` override. When
        non-None, takes precedence over ``self.classifier`` for the
        duration of this call. Used by the batch worker to inject a
        per-tenant ``HybridClassifier`` whose ``RotatingGeminiProvider``
        carries the active rows from ``tenant_llm_credentials`` so
        rotation kicks in transparently as more keys land. ``None``
        keeps the legacy (lifespan-built) classifier on the pipeline.
        """
        n = len(texts)
        if n == 0:
            return []

        normalized = [t if isinstance(t, str) else "" for t in texts]
        active_classifier = (
            classifier if classifier is not None else self.classifier
        )

        pre_overrides: list[OverrideHit | None] = [None] * n
        bert_indices: list[int] = []
        for i, text in enumerate(normalized):
            hit = self._pre_bert_lookup(text)
            if hit is not None:
                pre_overrides[i] = hit
            else:
                bert_indices.append(i)

        async def _run_bert() -> dict[int, AnalyzerPrediction]:
            if not bert_indices:
                return {}
            batch_inputs = [normalized[i] for i in bert_indices]
            preds = await asyncio.to_thread(
                self.analyzer.analyze_batch, batch_inputs
            )
            return dict(zip(bert_indices, preds, strict=True))

        async def _run_classifier() -> list[CategoryClassification | None]:
            if active_classifier is None:
                return [None] * n
            # Sprint 9.0.5-A R4 — prefer classify_batch_async when the
            # classifier exposes it. HybridClassifier's async path
            # parallelises the LLM fallback (8-way bounded) which was
            # the dominant wall-clock cost on Gemini-bound batches
            # (98-row test went 161s -> ~25s). Keyword-only and
            # other classifiers fall through to the sync path via
            # to_thread (unchanged from R1's analyze_batch_async).
            async_batch = getattr(
                active_classifier, "classify_batch_async", None
            )
            if async_batch is not None and asyncio.iscoroutinefunction(async_batch):
                # Sprint 9.5.5 A — classify_batch_async now returns
                # BatchClassificationResult (a dataclass envelope
                # around the classifications list + LLM token/duration
                # aggregates). Other classifiers' classify_batch + the
                # sync fallback still return a bare list. The pipeline
                # keeps its own return contract (``list[AnalysisResult]``)
                # backward-compat, but forwards the LLM aggregates via
                # the optional ``classifier_stats_sink`` out-param so
                # the batch worker's audit row can record real token
                # usage + duration instead of 0/NULL. None on the sink
                # means the caller didn't ask for the stats (e.g. the
                # /analyze single-review route).
                result = await async_batch(normalized)
                if classifier_stats_sink is not None:
                    classifier_stats_sink["llm_total_input_tokens"] = (
                        result.llm_total_input_tokens
                    )
                    classifier_stats_sink["llm_total_output_tokens"] = (
                        result.llm_total_output_tokens
                    )
                    classifier_stats_sink["llm_duration_ms"] = (
                        result.llm_duration_ms
                    )
                return list(result.classifications)
            sync_result = await asyncio.to_thread(
                active_classifier.classify_batch, normalized
            )
            return list(sync_result)

        bert_predictions, categorizations = await asyncio.gather(
            _run_bert(), _run_classifier()
        )

        results: list[AnalysisResult] = []
        for i, text in enumerate(normalized):
            results.append(
                self._build_result(
                    text,
                    pre_overrides[i],
                    bert_predictions.get(i),
                    categorizations[i],
                )
            )
        return results

    def analyze_batch(self, texts: list[str]) -> list[AnalysisResult]:
        n = len(texts)
        if n == 0:
            return []

        normalized = [t if isinstance(t, str) else "" for t in texts]

        pre_overrides: list[OverrideHit | None] = [None] * n
        bert_indices: list[int] = []

        # --- pre-BERT pass: KB -> critical -> tier1 ---
        for i, text in enumerate(normalized):
            hit = self._pre_bert_lookup(text)
            if hit is not None:
                pre_overrides[i] = hit
            else:
                bert_indices.append(i)

        # --- BERT batch ---
        bert_predictions: dict[int, AnalyzerPrediction] = {}
        if bert_indices:
            batch_inputs = [normalized[i] for i in bert_indices]
            preds = self.analyzer.analyze_batch(batch_inputs)
            for idx, pred in zip(bert_indices, preds, strict=True):
                bert_predictions[idx] = pred

        # --- category classification (batched, parallel to sentiment) ---
        categorizations: list[CategoryClassification | None]
        if self.classifier is not None:
            categorizations = list(self.classifier.classify_batch(normalized))
        else:
            categorizations = [None] * n

        # --- assemble final results with post-BERT layers ---
        results: list[AnalysisResult] = []
        for i, text in enumerate(normalized):
            results.append(
                self._build_result(
                    text,
                    pre_overrides[i],
                    bert_predictions.get(i),
                    categorizations[i],
                )
            )
        return results

    # -- internals ----------------------------------------------------------

    def _pre_bert_lookup(self, text: str) -> OverrideHit | None:
        if self.kb is not None:
            hit = self.kb.lookup(text)
            if hit is not None:
                return hit
        if (hit := apply_critical_override(text)) is not None:
            return hit
        if (hit := apply_tier1_override(text)) is not None:
            return hit
        return None

    def _build_result(
        self,
        text: str,
        pre_hit: OverrideHit | None,
        bert_pred: AnalyzerPrediction | None,
        categorization: CategoryClassification | None,
    ) -> AnalysisResult:
        overrides: list[OverrideHit] = []
        score: float
        label: str
        sla_detail: str | None = None

        if pre_hit is not None:
            overrides.append(pre_hit)
            score = pre_hit.score
            label = _label_from_score(score)
        elif bert_pred is not None:
            score = bert_pred.score
            label = bert_pred.label
        else:
            score = 0.0
            label = LABEL_NEUTRAL

        # Post-BERT layers fire only when the result came from BERT (not a
        # hard pre-override). This matches legacy behavior at app.py:404-446.
        if pre_hit is None and bert_pred is not None:
            sla_hit = apply_sla_override(text, self.sla_params)
            if sla_hit is not None:
                overrides.append(sla_hit)
                score = sla_hit.score
                label = _label_from_score(score)
                sla_detail = sla_hit.detail

            if sla_hit is None:
                t2_hit = apply_tier2_fallback(text, score)
                if t2_hit is not None:
                    overrides.append(t2_hit)
                    score = t2_hit.score
                    label = _label_from_score(score)

        customer = (self.rules.classify_customer(text) if self.rules else None) or \
            classify_customer_perspective(text)
        company = (self.rules.classify_company(text) if self.rules else None) or \
            classify_company_perspective(text)

        return AnalysisResult(
            text=text,
            sentiment_label=label,  # type: ignore[arg-type]
            sentiment_score=score,
            overrides_applied=overrides,
            summary=generate_heuristic_summary(text) or None,
            customer_perspective=customer,
            company_perspective=company,
            risk_class=label,  # type: ignore[arg-type]
            sla_detected=sla_detail,
            categorization=categorization,
        )


def _label_from_score(score: float) -> str:
    if score < SENTIMENT_NEGATIVE_THRESHOLD:
        return LABEL_NEGATIVE
    if score > SENTIMENT_POSITIVE_THRESHOLD:
        return LABEL_POSITIVE
    return LABEL_NEUTRAL
