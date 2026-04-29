"""Abstract base for category classifiers.

Concrete implementations: KeywordCategoryClassifier (fast, deterministic),
GeminiCategoryClassifier (LLM-backed), HybridClassifier (keyword first, LLM
fallback on low confidence).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from imga_core.models import CategoryClassification


class CategoryClassifier(ABC):
    """Stateless contract for a category-classifying backend."""

    @abstractmethod
    def classify(self, text: str) -> CategoryClassification:
        """Classify a single text. Returns primary + secondaries + confidence."""

    def classify_batch(self, texts: list[str]) -> list[CategoryClassification]:
        """Default loop; subclasses can override for true batched calls."""
        return [self.classify(t) for t in texts]
