"""OpenRouter provider — OpenAI-uyumlu chat/completions üzerinden çoklu model.

Gemini sağlayıcısının (``imga_core.llm.gemini``) sözleşme aynası:

  * ``classify`` / ``health_check`` → ``LLMProvider`` protokolü.
  * ``generate_swot`` / ``generate_okr`` / ``generate_executive_briefing``
    → SWOT/OKR servislerinin rotator'la çağırdığı yapılandırılmış üretim
    yüzeyi; ``api_key`` her çağrıda parametre (çok-anahtarlı rotasyon).
  * Hatalar aynı Sprint 8.3.6 hiyerarşisine eşlenir (RateLimitError /
    InvalidKeyError / LLMProviderError / MalformedResponseError ...),
    böylece ``GeminiKeyRotator`` ve ``HybridClassifier`` hiçbir değişiklik
    olmadan bu sağlayıcıyla da çalışır.

SDK yok — httpx (zaten zorunlu bağımlılık) ile düz REST. Yapılandırılmış
çıktı ``response_format={"type": "json_schema", ...}`` ile istenir;
``strict`` bilinçli olarak kapalı: şemalarımız OpenAI strict lehçesine
göre yazılmadı (additionalProperties vs.) ve parse katmanı zaten çitli /
kirli JSON'a dayanıklı.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, cast

import httpx

from imga_core.llm.base import LLMProvider, LLMProviderError
from imga_core.llm.errors import (
    InvalidKeyError,
    LLMResponseBlockedError,
    LLMTokenLimitError,
    MalformedResponseError,
    RateLimitError,
)
from imga_core.llm.gemini import _strip_markdown_fences
from imga_core.llm.key_rotation import GeminiKey
from imga_core.llm.prompts import (
    CLASSIFICATION_RESPONSE_SCHEMA,
    build_classification_prompt,
)
from imga_core.llm.rotating_gemini import RotatingGeminiProvider
from imga_core.models import LLMClassificationResult

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
# Kurum model seçmediyse kullanılacak varsayılan. 2026-08-10 Navlungo
# benchmark'ı (docs/benchmarks/2026-08-10-navlungo-llm-benchmark.md):
# GLM 5.2 %92,8 doğruluk + tam kapsam + ~$0,24/10k yorum ile fiyat/
# performans birincisi; gpt-5-mini'nin yerini aldı.
DEFAULT_OPENROUTER_MODEL = "z-ai/glm-5.2"

# Gemini ile aynı yumuşak-retry politikası: yalnız LLMProviderError
# (ağ / 5xx) yeniden denenir; RateLimit/InvalidKey rotator'a gider.
_TRANSIENT_RETRY_ATTEMPTS = 3
_TRANSIENT_RETRY_BASE_SECONDS = 1.0

_logger = logging.getLogger(__name__)


def _attribution_headers(api_key: str) -> dict[str, str]:
    """OpenRouter, panelinde kaynak göstermek için opsiyonel Referer +
    X-Title başlıklarını okur; auth ile birlikte tek yerden kurulur."""
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://app.imga.ai",
        "X-Title": "imga.ai",
    }


def _structured_response_format(response_schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "imga_structured_output",
            "strict": False,
            "schema": response_schema,
        },
    }


class OpenRouterProvider(LLMProvider):
    """OpenRouter-backed classifier + structured generator."""

    PROVIDER_NAME = "openrouter"

    def __init__(
        self,
        api_key: str,
        model_name: str = DEFAULT_OPENROUTER_MODEL,
        # Yönlendirilen modellerin soğuk başlangıcı Gemini'den yavaş
        # olabilir; classify için 20s tavan (Gemini 10s) makul.
        timeout_seconds: float = 20.0,
    ) -> None:
        if not api_key:
            raise ValueError("OpenRouter API key is required")
        self._api_key = api_key
        self._model_name = model_name
        self._timeout = timeout_seconds

    @property
    def model_name(self) -> str:
        return self._model_name

    # ------------------------------------------------------------------
    # LLMProvider protokolü
    # ------------------------------------------------------------------

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
        payload = {
            "model": self._model_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "response_format": _structured_response_format(
                CLASSIFICATION_RESPONSE_SCHEMA
            ),
        }
        try:
            with httpx.Client(timeout=httpx.Timeout(self._timeout)) as client:
                resp = client.post(
                    f"{OPENROUTER_BASE_URL}/chat/completions",
                    headers=_attribution_headers(self._api_key),
                    json=payload,
                )
            body = _read_body(resp)
        except (RateLimitError, InvalidKeyError, LLMProviderError):
            raise
        except Exception as exc:
            raise LLMProviderError(f"OpenRouter API call failed: {exc}") from exc

        raw = _first_choice_content(body)
        token_usage = _extract_usage(body)
        return self._parse_classification(raw, available_categories, token_usage)

    def health_check(self) -> bool:
        try:
            with httpx.Client(timeout=httpx.Timeout(self._timeout)) as client:
                resp = client.get(
                    f"{OPENROUTER_BASE_URL}/key",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
            return resp.status_code == 200
        except Exception:
            return False

    def _parse_classification(
        self,
        raw: str,
        available_categories: list[str],
        token_usage: dict[str, int] | None,
    ) -> LLMClassificationResult:
        cleaned = _strip_markdown_fences(raw)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise LLMProviderError(
                f"OpenRouter returned non-JSON text: {raw!r}"
            ) from exc
        if not isinstance(data, dict):
            raise LLMProviderError(
                f"Expected JSON object, got {type(data).__name__}"
            )

        primary = data.get("primary")
        confidence = data.get("confidence")
        reasoning = data.get("reasoning", "")
        if not isinstance(primary, str) or not primary:
            raise LLMProviderError(f"Invalid 'primary' in response: {data!r}")
        if not isinstance(confidence, int | float):
            raise LLMProviderError(f"Invalid 'confidence' in response: {data!r}")
        if primary not in available_categories:
            _logger.warning(
                "OpenRouter returned unknown category %r; coercing to 'belirsiz'",
                primary,
            )
            primary = "belirsiz"

        return LLMClassificationResult(
            primary=primary,
            confidence=max(0.0, min(1.0, float(confidence))),
            reasoning=cast(str, reasoning),
            provider=self.PROVIDER_NAME,
            model=self._model_name,
            token_usage=token_usage,
        )

    # ------------------------------------------------------------------
    # Yapılandırılmış üretim (SWOT / OKR / Brifing) — Gemini aynası
    # ------------------------------------------------------------------

    async def generate_swot(
        self,
        *,
        api_key: str,
        system_prompt: str,
        user_prompt: str,
        response_schema: dict[str, Any],
        model_name: str = DEFAULT_OPENROUTER_MODEL,
        temperature: float = 0.2,
        top_p: float = 0.9,
        max_output_tokens: int = 8192,
    ) -> tuple[dict[str, Any], dict[str, int] | None]:
        return await self._generate_structured(
            api_key=api_key,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_schema=response_schema,
            model_name=model_name,
            temperature=temperature,
            top_p=top_p,
            max_output_tokens=max_output_tokens,
        )

    async def generate_okr(
        self,
        *,
        api_key: str,
        system_prompt: str,
        user_prompt: str,
        response_schema: dict[str, Any],
        model_name: str = DEFAULT_OPENROUTER_MODEL,
        temperature: float = 0.3,
        top_p: float = 0.9,
        max_output_tokens: int = 4096,
    ) -> tuple[dict[str, Any], dict[str, int] | None]:
        return await self._generate_structured(
            api_key=api_key,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_schema=response_schema,
            model_name=model_name,
            temperature=temperature,
            top_p=top_p,
            max_output_tokens=max_output_tokens,
        )

    async def generate_root_cause(
        self,
        *,
        api_key: str,
        system_prompt: str,
        user_prompt: str,
        response_schema: dict[str, Any],
        model_name: str = DEFAULT_OPENROUTER_MODEL,
        # Sprint 13.1 — gemini.py'deki eşiyle aynı gerekçe: ham
        # yorumlardan alıntı çıkarıldığı için düşük sıcaklık.
        temperature: float = 0.15,
        top_p: float = 0.9,
        max_output_tokens: int = 8192,
    ) -> tuple[dict[str, Any], dict[str, int] | None]:
        return await self._generate_structured(
            api_key=api_key,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_schema=response_schema,
            model_name=model_name,
            temperature=temperature,
            top_p=top_p,
            max_output_tokens=max_output_tokens,
        )

    async def generate_executive_briefing(
        self,
        *,
        api_key: str,
        system_prompt: str,
        user_prompt: str,
        response_schema: dict[str, Any],
        model_name: str = DEFAULT_OPENROUTER_MODEL,
        temperature: float = 0.25,
        top_p: float = 0.9,
        max_output_tokens: int = 8192,
    ) -> tuple[dict[str, Any], dict[str, int] | None]:
        return await self._generate_structured(
            api_key=api_key,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_schema=response_schema,
            model_name=model_name,
            temperature=temperature,
            top_p=top_p,
            max_output_tokens=max_output_tokens,
        )

    async def _generate_structured(
        self,
        *,
        api_key: str,
        system_prompt: str,
        user_prompt: str,
        response_schema: dict[str, Any],
        model_name: str,
        temperature: float,
        top_p: float,
        max_output_tokens: int,
    ) -> tuple[dict[str, Any], dict[str, int] | None]:
        if not api_key:
            raise InvalidKeyError("Empty api_key passed to generate_structured")
        if not user_prompt or not user_prompt.strip():
            raise MalformedResponseError("user_prompt must be non-empty")

        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": max_output_tokens,
            "response_format": _structured_response_format(response_schema),
        }
        body = await self._call_with_soft_retry(api_key=api_key, payload=payload)
        _check_finish_reason(body)
        raw = _first_choice_content(body)
        cleaned = _strip_markdown_fences(raw)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start != -1 and end > start:
                try:
                    data = json.loads(cleaned[start : end + 1])
                except json.JSONDecodeError as exc:
                    raise MalformedResponseError(
                        f"OpenRouter returned non-JSON text: {raw!r}"
                    ) from exc
            else:
                raise MalformedResponseError(
                    f"OpenRouter returned non-JSON text: {raw!r}"
                ) from None
        if not isinstance(data, dict):
            raise MalformedResponseError(
                f"Expected JSON object, got {type(data).__name__}"
            )
        return cast(dict[str, Any], data), _extract_usage(body)

    async def _call_with_soft_retry(
        self,
        *,
        api_key: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        # Yapılandırılmış üretim payload'ları classify'dan büyük; SWOT
        # brifing gövdeleri güçlü modellerde dakikaya yaklaşabilir.
        timeout = httpx.Timeout(max(self._timeout, 120.0))
        last_error: LLMProviderError | None = None
        for attempt in range(_TRANSIENT_RETRY_ATTEMPTS):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.post(
                        f"{OPENROUTER_BASE_URL}/chat/completions",
                        headers=_attribution_headers(api_key),
                        json=payload,
                    )
                return _read_body(resp)
            except (RateLimitError, InvalidKeyError):
                raise
            except LLMProviderError as mapped:
                last_error = mapped
            except Exception as exc:
                last_error = LLMProviderError(
                    f"OpenRouter API call failed: {exc}"
                )
            if attempt + 1 >= _TRANSIENT_RETRY_ATTEMPTS:
                raise last_error
            delay = _TRANSIENT_RETRY_BASE_SECONDS * (2**attempt)
            _logger.warning(
                "OpenRouter transient error (attempt %d/%d); retrying in %.1fs",
                attempt + 1,
                _TRANSIENT_RETRY_ATTEMPTS,
                delay,
            )
            await asyncio.sleep(delay)
        raise last_error or LLMProviderError(
            "OpenRouter retry loop exited unexpectedly"
        )


def _read_body(resp: httpx.Response) -> dict[str, Any]:
    """HTTP durumunu + gövde-içi error zarfını Sprint 8.3.6 hiyerarşisine
    eşle. OpenRouter bazı sağlayıcı hatalarını 200 + ``{"error": ...}``
    zarfıyla döndürür — ikisi de burada yakalanır."""
    if resp.status_code == 429:
        raise RateLimitError()
    if resp.status_code in (401, 403):
        raise InvalidKeyError(f"API key rejected: HTTP {resp.status_code}")
    if resp.status_code >= 400:
        raise LLMProviderError(
            f"OpenRouter API call failed: HTTP {resp.status_code} "
            f"{resp.text[:300]}"
        )
    try:
        body = resp.json()
    except ValueError as exc:
        raise MalformedResponseError(
            f"OpenRouter returned non-JSON body: {resp.text[:300]!r}"
        ) from exc
    if not isinstance(body, dict):
        raise MalformedResponseError(
            f"Expected JSON object body, got {type(body).__name__}"
        )
    error = body.get("error")
    if isinstance(error, dict):
        code = error.get("code")
        message = str(error.get("message") or error)
        if code == 429:
            raise RateLimitError()
        if code in (401, 403):
            raise InvalidKeyError(f"API key rejected: {message}")
        raise LLMProviderError(f"OpenRouter API call failed: {message}")
    return body


def _first_choice_content(body: dict[str, Any]) -> str:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise MalformedResponseError(
            f"OpenRouter response has no choices: {body!r}"
        )
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise MalformedResponseError("Empty response text from OpenRouter")
    return content


def _check_finish_reason(body: dict[str, Any]) -> None:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        return
    first = choices[0] if isinstance(choices[0], dict) else {}
    reason = str(first.get("finish_reason") or "").lower()
    if reason == "length":
        _logger.error(
            "OpenRouter response truncated (finish_reason=length); "
            "bump max_tokens or shorten the prompt."
        )
        raise LLMTokenLimitError(
            "Model yanıtı token sınırına takıldı; raporu tekrar "
            "oluşturun veya dönemi daraltın."
        )
    if reason == "content_filter":
        _logger.error("OpenRouter response blocked: finish_reason=content_filter")
        raise LLMResponseBlockedError("Model yanıtı engellendi (content_filter).")


class RotatingOpenRouterProvider(RotatingGeminiProvider):
    """Çok-anahtarlı OpenRouter sınıflandırıcı.

    Rotasyon, telemetri (get_batch_stats), asyncio emniyet ağı ve
    hata eşleme mantığı RotatingGeminiProvider'dan miras alınır —
    yalnız iç sağlayıcı fabrikası değişir.
    """

    PROVIDER_NAME = "openrouter-rotating"

    def __init__(
        self,
        keys: list[GeminiKey],
        model_name: str = DEFAULT_OPENROUTER_MODEL,
        timeout_seconds: float = 20.0,
    ) -> None:
        super().__init__(
            keys, model_name=model_name, timeout_seconds=timeout_seconds
        )

    def _make_provider(
        self,
        api_key: str,
        *,
        timeout_seconds: float | None = None,
    ) -> LLMProvider:
        return OpenRouterProvider(
            api_key=api_key,
            model_name=self.model_name,
            timeout_seconds=(
                timeout_seconds if timeout_seconds is not None else 20.0
            ),
        )


def _extract_usage(body: dict[str, Any]) -> dict[str, int] | None:
    usage = body.get("usage")
    if not isinstance(usage, dict):
        return None
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    total = usage.get("total_tokens")
    if prompt is None and completion is None and total is None:
        return None
    return {
        "input": int(prompt or 0),
        "output": int(completion or 0),
        "total": int(total or 0),
    }
