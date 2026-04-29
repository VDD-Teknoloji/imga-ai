"""Keyword-based category classifier.

Fast, deterministic, no external dependencies. Counts substring matches per
category, ranks by hit count (alphabetic tie-break), normalises to a [0,1]
confidence by dividing by `CATEGORY_NORMALIZATION_DIVISOR`. Falls back to
the 'belirsiz' bucket when no keywords match or when the top score is below
the minimum confidence.
"""

from __future__ import annotations

from imga_core.categories.lexicons import ALL_CATEGORY_KEYWORDS
from imga_core.classifiers.base import CategoryClassifier
from imga_core.config import (
    CATEGORY_FALLBACK_CODE,
    CATEGORY_KEYWORD_MIN_CONFIDENCE,
    CATEGORY_NORMALIZATION_DIVISOR,
    CATEGORY_SECONDARY_COUNT,
)
from imga_core.models import CategoryClassification, CategoryHit
from imga_core.text_utils import normalize_turkish


class KeywordCategoryClassifier(CategoryClassifier):
    """Substring-match classifier over the per-category Turkish lexicons.

    Args:
        min_confidence: Below this, `requires_manual_review` is set so the
            hybrid layer (or operator) can decide whether to escalate.
        normalization_divisor: Hit count divided by this gives confidence,
            capped at 1.0. Default 5.0 means 5+ hits = full confidence.
    """

    def __init__(
        self,
        min_confidence: float = CATEGORY_KEYWORD_MIN_CONFIDENCE,
        normalization_divisor: float = CATEGORY_NORMALIZATION_DIVISOR,
    ) -> None:
        self.min_confidence = min_confidence
        self._divisor = normalization_divisor
        # Frozen reference; the module-level dict is never mutated.
        self._lexicons = ALL_CATEGORY_KEYWORDS

    def classify(self, text: str) -> CategoryClassification:
        if not text or not text.strip():
            return self._fallback(reason_for_review=True)

        text_lower = normalize_turkish(text)
        scores: dict[str, list[str]] = {}
        for category_code, keywords in self._lexicons.items():
            matched = sorted(kw for kw in keywords if kw in text_lower)
            if matched:
                scores[category_code] = matched

        if not scores:
            return self._fallback(reason_for_review=True)

        # (-hit_count, code) ranks: most hits first, alphabetic tie-break.
        ranked = sorted(
            scores.items(),
            key=lambda item: (-len(item[1]), item[0]),
        )

        primary_code, primary_matches = ranked[0]
        primary_confidence = self._normalize(len(primary_matches))
        requires_review = primary_confidence < self.min_confidence

        secondaries = tuple(
            CategoryHit(
                category=code,
                confidence=self._normalize(len(matches)),
                matched_keywords=tuple(matches),
            )
            for code, matches in ranked[1 : 1 + CATEGORY_SECONDARY_COUNT]
        )

        return CategoryClassification(
            primary=primary_code,
            primary_confidence=primary_confidence,
            primary_matched_keywords=tuple(primary_matches),
            secondaries=secondaries,
            method="keyword",
            requires_manual_review=requires_review,
        )

    def _normalize(self, hit_count: int) -> float:
        return min(1.0, hit_count / self._divisor)

    def _fallback(self, *, reason_for_review: bool) -> CategoryClassification:
        return CategoryClassification(
            primary=CATEGORY_FALLBACK_CODE,
            primary_confidence=0.0,
            primary_matched_keywords=(),
            secondaries=(),
            method="keyword",
            requires_manual_review=reason_for_review,
        )
