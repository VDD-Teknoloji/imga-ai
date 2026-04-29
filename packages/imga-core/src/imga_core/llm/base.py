"""Abstract LLM provider for category-classification fallback."""

from __future__ import annotations

from abc import ABC, abstractmethod

from imga_core.models import LLMClassificationResult


class LLMProviderError(Exception):
    """Raised when an LLM provider call fails (network, parsing, auth)."""


class LLMProvider(ABC):
    """Provider-agnostic interface for LLM-backed category classification.

    Today only GeminiProvider implements this. Future providers (Claude,
    fine-tuned local models) plug into the same protocol so the hybrid
    classifier and pipeline don't need to know the backend.
    """

    @abstractmethod
    def classify(
        self,
        text: str,
        available_categories: list[str],
    ) -> LLMClassificationResult:
        """Classify ``text`` into one of ``available_categories``.

        Returns:
            LLMClassificationResult with primary code, confidence, and a
            short Turkish reasoning string.

        Raises:
            LLMProviderError: transient or permanent provider failure
                (network, auth, malformed response). Caller decides whether
                to retry or fall back to keyword-only classification.
        """

    @abstractmethod
    def health_check(self) -> bool:
        """Quick reachability + auth probe. Returns False on any failure."""
