"""Google Gemini provider for category classification.

Uses ``google-generativeai`` SDK with structured output (response_schema)
so the JSON parsing path is reliable. Default model: gemini-2.5-flash.
Free tier is sufficient for MVP volumes; rate / cost limits handled at
the call site (HybridClassifier).
"""

from __future__ import annotations

import json
import logging
from typing import Any, cast

from imga_core.llm.base import LLMProvider, LLMProviderError
from imga_core.llm.prompts import (
    CLASSIFICATION_RESPONSE_SCHEMA,
    build_classification_prompt,
)
from imga_core.models import LLMClassificationResult

_logger = logging.getLogger(__name__)


class GeminiProvider(LLMProvider):
    """Gemini-backed classifier.

    Lazy-imports ``google.generativeai`` at construction so the package
    works without the optional dependency installed when LLM fallback is
    disabled.
    """

    PROVIDER_NAME = "gemini"

    def __init__(
        self,
        api_key: str,
        model_name: str = "gemini-2.5-flash",
        timeout_seconds: float = 5.0,
    ) -> None:
        if not api_key:
            raise ValueError("Gemini API key is required")

        try:
            import google.generativeai as genai
        except ImportError as exc:
            raise ImportError(
                "google-generativeai is not installed. "
                "Install with: pip install 'imga-core[gemini]'"
            ) from exc

        genai.configure(api_key=api_key)
        self._genai = genai
        self._model_name = model_name
        self._model = genai.GenerativeModel(model_name)
        self._timeout = timeout_seconds

    @property
    def model_name(self) -> str:
        return self._model_name

    def classify(
        self,
        text: str,
        available_categories: list[str],
    ) -> LLMClassificationResult:
        if not text or not text.strip():
            raise LLMProviderError("Cannot classify empty text")
        if not available_categories:
            raise LLMProviderError("available_categories must be non-empty")

        prompt = build_classification_prompt(text, available_categories)
        try:
            response = self._model.generate_content(
                prompt,
                generation_config={
                    "response_mime_type": "application/json",
                    "response_schema": CLASSIFICATION_RESPONSE_SCHEMA,
                    "temperature": 0.1,
                },
                request_options={"timeout": self._timeout},
            )
        except Exception as exc:
            raise LLMProviderError(f"Gemini API call failed: {exc}") from exc

        return self._parse_response(response, available_categories)

    def health_check(self) -> bool:
        try:
            response = self._model.generate_content(
                "ping",
                request_options={"timeout": 2.0},
            )
            return getattr(response, "text", None) is not None
        except Exception:
            return False

    def _parse_response(
        self,
        response: Any,
        available_categories: list[str],
    ) -> LLMClassificationResult:
        raw = getattr(response, "text", None)
        if not raw:
            raise LLMProviderError("Empty response text from Gemini")

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LLMProviderError(f"Gemini returned non-JSON text: {raw!r}") from exc

        if not isinstance(data, dict):
            raise LLMProviderError(f"Expected JSON object, got {type(data).__name__}")

        primary = data.get("primary")
        confidence = data.get("confidence")
        reasoning = data.get("reasoning", "")

        if not isinstance(primary, str) or not primary:
            raise LLMProviderError(f"Invalid 'primary' in response: {data!r}")
        if not isinstance(confidence, int | float):
            raise LLMProviderError(f"Invalid 'confidence' in response: {data!r}")

        # Clamp confidence into [0, 1] — providers occasionally return out-of-range.
        clamped_confidence = max(0.0, min(1.0, float(confidence)))

        # Fallback when the LLM picks a code outside the allowed set.
        if primary not in available_categories:
            _logger.warning(
                "Gemini returned unknown category %r; coercing to 'belirsiz'",
                primary,
            )
            primary = "belirsiz"

        return LLMClassificationResult(
            primary=primary,
            confidence=clamped_confidence,
            reasoning=cast(str, reasoning),
            provider=self.PROVIDER_NAME,
            model=self._model_name,
        )
