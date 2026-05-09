"""Environment-driven LLM provider construction.

Reads ``IMGA_LLM_FALLBACK_ENABLED``, ``IMGA_LLM_PROVIDER``, ``GEMINI_API_KEY``,
``IMGA_GEMINI_MODEL`` and returns the appropriate provider — or ``None`` when
the feature is disabled or unconfigured. Returning ``None`` is the graceful
default: pipelines run keyword-only and surface low-confidence rows for
manual review.
"""

from __future__ import annotations

import logging
import os

from imga_core.llm.base import LLMProvider

_logger = logging.getLogger(__name__)


def create_llm_provider() -> LLMProvider | None:
    """Build an LLMProvider from environment variables, or None.

    Returns None when:
      - IMGA_LLM_FALLBACK_ENABLED is not 'true'
      - The selected provider has no credentials configured
    Raises:
      - NotImplementedError if the selected provider is not yet implemented
        (e.g. 'claude')
      - ValueError on unknown provider names
    """
    if os.environ.get("IMGA_LLM_FALLBACK_ENABLED", "false").lower() != "true":
        return None

    provider_name = os.environ.get("IMGA_LLM_PROVIDER", "gemini").lower()

    if provider_name == "gemini":
        return _build_gemini()

    if provider_name == "claude":
        raise NotImplementedError(
            "Claude provider is not yet implemented. "
            "Set IMGA_LLM_PROVIDER=gemini or unset IMGA_LLM_FALLBACK_ENABLED."
        )

    raise ValueError(f"Unknown IMGA_LLM_PROVIDER: {provider_name!r}")


def _build_gemini() -> LLMProvider | None:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        _logger.info(
            "IMGA_LLM_FALLBACK_ENABLED=true but GEMINI_API_KEY is empty; "
            "falling back to keyword-only classification."
        )
        return None

    model_name = os.environ.get("IMGA_GEMINI_MODEL", "gemini-2.5-flash")

    # Imported here so the package works when google-genai isn't
    # installed and LLM fallback is disabled (Sprint 9.1 H — migrated
    # from google-generativeai).
    from imga_core.llm.gemini import GeminiProvider

    return GeminiProvider(api_key=api_key, model_name=model_name)
