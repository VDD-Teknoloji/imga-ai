"""LLM providers for category-classification fallback + Sprint 8.3.6
SWOT/OKR generation.

Public surface:

  * ``LLMProvider`` + ``LLMProviderError`` — the legacy classification
    fallback path (HybridClassifier consumer).
  * ``create_llm_provider`` — factory.
  * Sprint 8.3.6 error hierarchy (``LLMError`` + four leaves) for the
    SWOT/OKR rotator + service.
  * ``GeminiKey`` + ``GeminiKeyRotator`` — multi-key rotation with
    fall-through on RateLimit / InvalidKey.
  * ``RotatingGeminiProvider`` — Sprint 9.0.5-A R5 multi-key
    LLMProvider for the classifier batch path (HybridClassifier
    consumer), routing through the same rotator the SWOT/OKR
    services use.

GeminiProvider is exported but importing it requires google-genai
(Sprint 9.1 H — migrated from the deprecated google-generativeai)
to be installed (it imports the SDK at construction time).
"""

from imga_core.llm.base import LLMProvider, LLMProviderError
from imga_core.llm.errors import (
    AllKeysExhaustedError,
    InvalidKeyError,
    LLMError,
    LLMResponseBlockedError,
    LLMTokenLimitError,
    MalformedResponseError,
    RateLimitError,
)
from imga_core.llm.factory import create_llm_provider
from imga_core.llm.key_rotation import GeminiKey, GeminiKeyRotator
from imga_core.llm.rotating_gemini import RotatingGeminiProvider

__all__ = [
    "AllKeysExhaustedError",
    "GeminiKey",
    "GeminiKeyRotator",
    "InvalidKeyError",
    "LLMError",
    "LLMProvider",
    "LLMProviderError",
    "LLMResponseBlockedError",
    "LLMTokenLimitError",
    "MalformedResponseError",
    "RateLimitError",
    "RotatingGeminiProvider",
    "create_llm_provider",
]
