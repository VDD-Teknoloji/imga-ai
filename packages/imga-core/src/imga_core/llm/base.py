"""Abstract LLM provider for category-classification fallback."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod

from imga_core.models import LLMClassificationResult


class LLMProviderError(Exception):
    """Raised when an LLM provider call fails (network, parsing, auth)."""


class LLMProvider(ABC):
    """Provider-agnostic interface for LLM-backed category classification.

    Today the implementations are GeminiProvider (single-key, ENV-driven)
    and RotatingGeminiProvider (multi-key, tenant-scoped, with the
    Sprint 8.3.6 GeminiKeyRotator under the hood). Future providers
    (Claude, fine-tuned local models) plug into the same protocol so
    the hybrid classifier and pipeline don't need to know the backend.

    Sprint 9.0.5-A R5 — added ``classify_async``. Callers in the batch
    path (HybridClassifier.classify_batch_async) prefer the async
    variant so multi-key implementations can use the async rotator
    natively without a redundant ``to_thread`` hop. The default
    implementation here covers single-key sync providers — they get
    the async surface for free.
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

    async def classify_async(
        self,
        text: str,
        available_categories: list[str],
    ) -> LLMClassificationResult:
        """Async variant of ``classify``. Default implementation runs
        the sync method on a worker thread so existing single-key
        providers (GeminiProvider) gain the async surface without any
        change. Override this for providers that have a native async
        path (RotatingGeminiProvider routes through the async
        ``GeminiKeyRotator``)."""
        return await asyncio.to_thread(
            self.classify, text, available_categories
        )

    @abstractmethod
    def health_check(self) -> bool:
        """Quick reachability + auth probe. Returns False on any failure."""
