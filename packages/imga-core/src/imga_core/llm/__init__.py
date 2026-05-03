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

GeminiProvider is exported but importing it requires google-generativeai
to be installed (it imports the SDK at construction time).
"""

from imga_core.llm.base import LLMProvider, LLMProviderError
from imga_core.llm.errors import (
    AllKeysExhaustedError,
    InvalidKeyError,
    LLMError,
    MalformedResponseError,
    RateLimitError,
)
from imga_core.llm.factory import create_llm_provider
from imga_core.llm.key_rotation import GeminiKey, GeminiKeyRotator

__all__ = [
    "AllKeysExhaustedError",
    "GeminiKey",
    "GeminiKeyRotator",
    "InvalidKeyError",
    "LLMError",
    "LLMProvider",
    "LLMProviderError",
    "MalformedResponseError",
    "RateLimitError",
    "create_llm_provider",
]
