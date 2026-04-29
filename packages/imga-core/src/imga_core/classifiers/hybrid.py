"""Hybrid classifier: keyword first, LLM fallback when confidence is low.

Strategy:
    1. Run KeywordCategoryClassifier
    2. If primary_confidence >= threshold, return as-is (cheap path)
    3. Otherwise call the LLM provider; on success merge result
    4. If LLM fails or is None, return keyword result with the
       requires_manual_review flag so the operator can step in
"""

from __future__ import annotations

import logging

from imga_core.categories.taxonomy import GLOBAL_CATEGORY_CODES
from imga_core.classifiers.base import CategoryClassifier
from imga_core.classifiers.keyword import KeywordCategoryClassifier
from imga_core.config import CATEGORY_LLM_FALLBACK_THRESHOLD
from imga_core.llm.base import LLMProvider, LLMProviderError
from imga_core.models import CategoryClassification

_logger = logging.getLogger(__name__)


class HybridClassifier(CategoryClassifier):
    """Keyword + optional LLM fallback.

    Args:
        keyword_classifier: Required cheap-path classifier.
        llm_provider: Optional LLM provider. None means LLM fallback is
            disabled — low-confidence results go straight to manual review.
        confidence_threshold: Below this keyword confidence the LLM (if
            available) is consulted. Default 0.7 from config.
        available_categories: Codes the LLM is allowed to choose from. If
            None, defaults to the global taxonomy.
    """

    def __init__(
        self,
        keyword_classifier: KeywordCategoryClassifier,
        llm_provider: LLMProvider | None = None,
        confidence_threshold: float = CATEGORY_LLM_FALLBACK_THRESHOLD,
        available_categories: list[str] | None = None,
    ) -> None:
        self.keyword = keyword_classifier
        self.llm = llm_provider
        self.threshold = confidence_threshold
        self._available_categories = available_categories or list(GLOBAL_CATEGORY_CODES)

    def classify(self, text: str) -> CategoryClassification:
        keyword_result = self.keyword.classify(text)

        # Cheap path: keyword is confident enough.
        if keyword_result.primary_confidence >= self.threshold:
            return keyword_result

        # No LLM configured: surface for manual review.
        if self.llm is None:
            return keyword_result.model_copy(update={"requires_manual_review": True})

        # Skip LLM for empty / unclassifiable input — keyword classifier
        # already returned the fallback bucket and there's nothing for the
        # LLM to work with.
        if not text or not text.strip():
            return keyword_result.model_copy(update={"requires_manual_review": True})

        try:
            llm_result = self.llm.classify(text, self._available_categories)
        except LLMProviderError as exc:
            _logger.warning(
                "LLM classification failed (%s); falling back to keyword result", exc
            )
            return keyword_result.model_copy(update={"requires_manual_review": True})

        # Merge: LLM picks primary + confidence, keyword keeps secondaries.
        return CategoryClassification(
            primary=llm_result.primary,
            primary_confidence=llm_result.confidence,
            primary_matched_keywords=(),  # LLM doesn't surface keyword hits
            secondaries=keyword_result.secondaries,
            method="ensemble",
            requires_manual_review=False,
            llm_result=llm_result,
        )
