"""LLM providers for category-classification fallback.

Public surface: LLMProvider abstract base + LLMProviderError + factory.
GeminiProvider is exported but importing it requires google-generativeai
to be installed (it imports the SDK at construction time).
"""

from imga_core.llm.base import LLMProvider, LLMProviderError
from imga_core.llm.factory import create_llm_provider

__all__ = [
    "LLMProvider",
    "LLMProviderError",
    "create_llm_provider",
]
