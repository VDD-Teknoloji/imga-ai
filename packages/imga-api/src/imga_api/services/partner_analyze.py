"""Partner analyze engine — İmga v1 (contract §4/§5). Gemini backend.

Env ``GEMINI_API_KEY`` (SİSTEM anahtarı, tenant cred değil) ile GeminiProvider
kurar, use-case system prompt + response_schema ile structured JSON üretir,
LLM hatalarını contract §5 kodlarına (502/504/429) haritalar. v1.3: tüm
use-case Gemini → processed_in="outbound".
"""

from __future__ import annotations

import asyncio
import os

from imga_core.llm.errors import (
    InvalidKeyError,
    LLMProviderError,
    LLMResponseBlockedError,
    LLMTokenLimitError,
    MalformedResponseError,
    RateLimitError,
)
from imga_core.llm.gemini import GeminiProvider

from imga_api.v1.envelope import TokenUsage
from imga_api.v1.errors import PartnerApiError
from imga_api.v1.prompts import PROMPTS

# Contract §1: non-stream client ≤30s bekler → 28s hard deadline, aşımı 504.
_DEADLINE_SECONDS = 28.0
_DEFAULT_MODEL = "gemini-3-flash-preview"


def _provider_error(message: str) -> PartnerApiError:
    return PartnerApiError(status_code=502, code="provider_error", message=message)


async def run_use_case(
    *, use_case: str, user_prompt: str
) -> tuple[dict, TokenUsage, str]:
    """(response_payload, token_usage, real_model) döndür. Hata → PartnerApiError."""
    prompt = PROMPTS[use_case]
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise _provider_error("llm backend not configured (GEMINI_API_KEY yok)")
    model = os.environ.get("IMGA_GEMINI_MODEL", _DEFAULT_MODEL)
    provider = GeminiProvider(
        api_key=api_key, model_name=model, timeout_seconds=10.0
    )
    try:
        async with asyncio.timeout(_DEADLINE_SECONDS):
            data, usage = await provider._generate_structured(  # noqa: SLF001 — generic yol
                api_key=api_key,
                system_prompt=prompt.system_prompt,
                user_prompt=user_prompt,
                response_schema=prompt.response_schema,
                model_name=model,
                temperature=prompt.temperature,
                top_p=0.9,
                max_output_tokens=prompt.max_output_tokens,
            )
    except TimeoutError as exc:
        raise PartnerApiError(
            status_code=504, code="timeout", message="llm timeout"
        ) from exc
    except RateLimitError as exc:
        raise PartnerApiError(
            status_code=429,
            code="rate_limit",
            message="llm rate limit",
            retry_after_seconds=30,
        ) from exc
    except (
        InvalidKeyError,
        LLMTokenLimitError,
        LLMResponseBlockedError,
        MalformedResponseError,
        LLMProviderError,
    ) as exc:
        raise _provider_error(f"llm error: {type(exc).__name__}") from exc

    u = TokenUsage(
        prompt=(usage or {}).get("input", 0),
        completion=(usage or {}).get("output", 0),
    )
    return data, u, model


__all__ = ["run_use_case"]
