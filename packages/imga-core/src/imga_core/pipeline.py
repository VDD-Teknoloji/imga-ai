"""End-to-end analysis pipeline: orchestrates overrides + BERT + post-processing."""

from __future__ import annotations

import logging
from pathlib import Path

from imga_core.analyzers.base import AnalyzerPrediction, SentimentAnalyzer
from imga_core.config import (
    LABEL_NEGATIVE,
    LABEL_NEUTRAL,
    LABEL_POSITIVE,
    SENTIMENT_NEGATIVE_THRESHOLD,
    SENTIMENT_POSITIVE_THRESHOLD,
)
from imga_core.models import AnalysisResult, OverrideHit
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
    ) -> None:
        self.analyzer = analyzer
        self.kb = KnowledgeBase(knowledge_base_path) if knowledge_base_path else None
        self.rules = RuleEngine(rules_path) if rules_path else None
        self.sla_params = sla_params or SLAParams()

    def analyze(self, text: str) -> AnalysisResult:
        return self.analyze_batch([text])[0]

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

        # --- assemble final results with post-BERT layers ---
        results: list[AnalysisResult] = []
        for i, text in enumerate(normalized):
            results.append(self._build_result(text, pre_overrides[i], bert_predictions.get(i)))
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
        )


def _label_from_score(score: float) -> str:
    if score < SENTIMENT_NEGATIVE_THRESHOLD:
        return LABEL_NEGATIVE
    if score > SENTIMENT_POSITIVE_THRESHOLD:
        return LABEL_POSITIVE
    return LABEL_NEUTRAL
