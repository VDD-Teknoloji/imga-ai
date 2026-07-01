"""Partner analyze engine — İmga v1 (contract §4/§5). Gemini backend.

Env ``GEMINI_API_KEY`` (SİSTEM anahtarı, tenant cred değil) ile GeminiProvider
kurar, use-case system prompt + response_schema ile structured JSON üretir,
LLM hatalarını contract §5 kodlarına (502/504/429) haritalar. v1.3: tüm
use-case Gemini → processed_in="outbound".
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator

from imga_core.llm.base import LLMProviderError
from imga_core.llm.errors import (
    InvalidKeyError,
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


# SSE stream free-analyze: düz markdown (JSON şema YOK) → partial delta'ları temiz.
_STREAM_SYSTEM_PROMPT = (
    "Sen bir e-ticaret veri analiz asistanısın. Kullanıcının sorusunu verilen "
    "bağlamla Türkçe, akıcı markdown ile yanıtla. YALNIZCA cevabı yaz; JSON, "
    "başlık şablonu veya meta açıklama ekleme."
)


async def stream_free_analyze(
    user_prompt: str,
) -> AsyncIterator[tuple[str, TokenUsage | None]]:
    """free-analyze token-stream (contract §7). ``(text_delta, usage|None)`` yield
    eder; usage yalnız son chunk'ta dolu. Hata → PartnerApiError (§5). Gerçek
    Gemini ``generate_content_stream`` — SDK çağrı şekli ilk canlı istekte doğrulanır."""
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise _provider_error("llm backend not configured (GEMINI_API_KEY yok)")
    model = os.environ.get("IMGA_GEMINI_MODEL", _DEFAULT_MODEL)
    provider = GeminiProvider(
        api_key=api_key, model_name=model, timeout_seconds=10.0
    )
    try:
        async for delta, usage in provider.stream_text(
            api_key=api_key,
            system_prompt=_STREAM_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            model_name=model,
            temperature=0.5,
        ):
            tu = (
                TokenUsage(
                    prompt=usage.get("input", 0),
                    completion=usage.get("output", 0),
                )
                if usage is not None
                else None
            )
            yield delta, tu
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


__all__ = ["run_use_case", "stream_free_analyze"]
