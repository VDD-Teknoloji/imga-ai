"""Google Gemini provider for category classification.

Sprint 9.1 H — migrated from ``google-generativeai`` (deprecated) to
the unified ``google-genai`` SDK. The new SDK uses an explicit
``Client`` instance instead of a process-wide ``configure(api_key=...)``
singleton, which lets the multi-key rotator hold one client per key
without the configure-race the old SDK forced us to lock around.

The Sprint 9.0.5-A R7 hardening (retry disable + 10s timeout +
mid-batch cancel) is preserved on the new surface:

  * ``http_options=HttpOptions(timeout=...)`` caps the per-call
    wall-clock at the value the constructor takes (default 10s).
  * The new SDK does not auto-retry on 5xx by default — the
    ``retry_options`` field on HttpOptions is opt-in. We don't set
    it, so each call is a single attempt, matching R7's intent.
  * ``classify_async`` still routes through ``client.aio.models``
    so the HybridClassifier's mid-batch cancel keeps working.

Errors map onto the existing Sprint 8.3.6 hierarchy
(``RateLimitError`` / ``InvalidKeyError`` / ``LLMProviderError``)
through ``_raise_mapped_sdk_error`` — message-sniffing is replaced
by ``isinstance(exc, errors.ClientError) + exc.code`` checks where
the SDK exposes the HTTP status as a real attribute.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, cast

# Sprint 9.1 H — eager module-level import to mirror the bert.py
# fix. ImportError at module load surfaces immediately during install
# checks instead of mid-request.
try:
    from google import genai as _genai_module
    from google.genai import errors as _genai_errors
    from google.genai import types as _genai_types
except ImportError:  # pragma: no cover — exercised only when the
    # optional [gemini] extra isn't installed; the per-instance
    # constructor below re-raises with the install hint.
    _genai_module = None  # type: ignore[assignment]
    _genai_errors = None  # type: ignore[assignment]
    _genai_types = None  # type: ignore[assignment]

from imga_core.llm.base import LLMProvider, LLMProviderError
from imga_core.llm.errors import (
    InvalidKeyError,
    LLMResponseBlockedError,
    LLMTokenLimitError,
    MalformedResponseError,
    RateLimitError,
)
from imga_core.llm.prompts import (
    CLASSIFICATION_RESPONSE_SCHEMA,
    build_classification_prompt,
)
from imga_core.models import LLMClassificationResult

# Sprint 9.0 — soft retry policy for transient Gemini errors. Only
# LLMProviderError (network blip, 5xx) is retried; InvalidKeyError /
# RateLimitError stay rotator-routed and Malformed/TokenLimit/Blocked
# are deterministic so retry is wasted work.
_TRANSIENT_RETRY_ATTEMPTS = 3
_TRANSIENT_RETRY_BASE_SECONDS = 1.0


_logger = logging.getLogger(__name__)


def _build_http_options(timeout_seconds: float) -> Any:
    """Sprint 9.1 H — ``http_options`` carries the per-call timeout
    through the new SDK's transport layer. Sprint 9.0.5-A R7 disabled
    the old SDK's retry loop via ``retry=Retry(predicate=...)``; the
    new SDK doesn't auto-retry on 5xx unless ``retry_options`` is set,
    so retry-disable is the default — we just need the timeout."""
    if _genai_types is None:
        return None
    # The SDK's HttpOptions takes ``timeout`` in milliseconds (the
    # field name is unsuffixed; the unit is documented). Floor to int
    # so we don't pass a sub-millisecond float.
    return _genai_types.HttpOptions(timeout=int(timeout_seconds * 1000))


def _build_client(api_key: str, timeout_seconds: float) -> Any:
    """Construct a fresh Client. Cheap (~µs) — no network on init.
    The rotator path constructs one per logical call; the constructor-
    bound path keeps a single instance for the life of the provider.
    """
    if _genai_module is None:
        raise ImportError(
            "google-genai is not installed. "
            "Install with: pip install 'imga-core[gemini]'"
        )
    return _genai_module.Client(
        api_key=api_key,
        http_options=_build_http_options(timeout_seconds),
    )


class GeminiProvider(LLMProvider):
    """Gemini-backed classifier.

    Lazy-imports ``google.genai`` at construction so the package
    works without the optional dependency installed when LLM fallback is
    disabled.
    """

    PROVIDER_NAME = "gemini"

    def __init__(
        self,
        api_key: str,
        model_name: str = "gemini-2.5-flash",
        # Sprint 9.0.5-A R7 — bumped 5s -> 10s. The old SDK's retry
        # path was previously turning a single 30s timeout into a 90+s
        # wall-clock through its default exponential backoff (3-5x).
        # The new SDK doesn't auto-retry on 5xx so the wall-clock per
        # call is bounded at this timeout outright.
        timeout_seconds: float = 10.0,
    ) -> None:
        if not api_key:
            raise ValueError("Gemini API key is required")
        if _genai_module is None:
            raise ImportError(
                "google-genai is not installed. "
                "Install with: pip install 'imga-core[gemini]'"
            )

        self._api_key = api_key
        self._model_name = model_name
        self._timeout = timeout_seconds
        self._client = _build_client(api_key, timeout_seconds)

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
            response = self._client.models.generate_content(
                model=self._model_name,
                contents=prompt,
                config=_genai_types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=CLASSIFICATION_RESPONSE_SCHEMA,
                    temperature=0.1,
                ),
            )
        except Exception as exc:
            # Map first so the rotator-relevant types reach callers
            # unchanged; non-rotator errors collapse to LLMProviderError.
            try:
                self._raise_mapped_sdk_error(exc)
            except (RateLimitError, InvalidKeyError):
                raise
            except LLMProviderError:
                raise
            raise LLMProviderError(f"Gemini API call failed: {exc}") from exc

        # Sprint 9.5.5 A — extract usage_metadata alongside the parse so
        # the audit row downstream knows the real token cost of each
        # per-review classify call. Pre-9.5.5 batch rows landed with
        # NULL tokens because nothing ever pulled this off the SDK
        # response on the classify path (SWOT/OKR did, but classify
        # didn't).
        token_usage = self._extract_usage_metadata(response)
        return self._parse_response(response, available_categories, token_usage)

    def health_check(self) -> bool:
        try:
            response = self._client.models.generate_content(
                model=self._model_name,
                contents="ping",
            )
            return getattr(response, "text", None) is not None
        except Exception:
            return False

    def _parse_response(
        self,
        response: Any,
        available_categories: list[str],
        token_usage: dict[str, int] | None = None,
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

        clamped_confidence = max(0.0, min(1.0, float(confidence)))

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
            token_usage=token_usage,
        )

    # ------------------------------------------------------------------
    # Sprint 8.3.6 — SWOT + OKR generation (structured output)
    # ------------------------------------------------------------------
    #
    # These methods diverge from ``classify`` in three ways:
    #
    #   1. ``api_key`` is a per-call argument. The multi-key rotator
    #      (imga_core.llm.key_rotation) walks priorities and falls
    #      through on RateLimit/InvalidKey, so the provider must
    #      build a fresh client at each attempt. Sprint 9.1 H makes
    #      this cleaner: in the old SDK we had to lock around a global
    #      ``configure(api_key=...)`` call; the new SDK's per-Client
    #      isolation removes that race entirely.
    #   2. They're async via ``client.aio.models.generate_content``.
    #   3. They map SDK errors to the Sprint 8.3.6 ``LLMError``
    #      hierarchy (RateLimitError / InvalidKeyError /
    #      MalformedResponseError) instead of the legacy
    #      ``LLMProviderError`` so the rotator can act on them.

    async def generate_swot(
        self,
        *,
        api_key: str,
        system_prompt: str,
        user_prompt: str,
        response_schema: dict[str, Any],
        # Sprint 9.5.4 — Gemini 3 family cutover. Recent history:
        #
        #   9.5 A3: cut to gemini-2.5-pro → 6/6 504 DEADLINE_EXCEEDED
        #     on briefing payloads in prod (2026-05-12). Server-agent
        #     logs showed 2.5-flash also ~22% 504 on the same
        #     payload — the 2.5 family doesn't fit briefing's
        #     payload size inside Google's 30s infra SLA. Tier 2
        #     wouldn't help (compute-pool latency, not quota).
        #
        #   9.5.2: fell back to gemini-2.0-flash → 404 NOT_FOUND,
        #     "no longer available to new users". 2.0-flash is
        #     closed to new accounts and sunsets 2026-06-01 per
        #     Google docs.
        #
        # 3-flash-preview lives on a different compute pool; the
        # hypothesis is its SLA pattern is more forgiving for our
        # briefing-shape payloads. Experimental — if it 504s we
        # try gemini-3.1-flash-lite next (Sprint 9.5.5). If it
        # 404s the model-name string needs re-verification (the
        # "-preview" suffix is moving target territory).
        model_name: str = "gemini-3-flash-preview",
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
        model_name: str = "gemini-3-flash-preview",  # Sprint 9.5.4 cutover
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

    async def generate_executive_briefing(
        self,
        *,
        api_key: str,
        system_prompt: str,
        user_prompt: str,
        response_schema: dict[str, Any],
        model_name: str = "gemini-3-flash-preview",  # Sprint 9.5.4 cutover
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

        # Sprint 9.1 H — fresh client per call so the rotator can swap
        # keys without touching shared state. The old SDK forced us to
        # serialise around a global ``configure(api_key=...)``; the new
        # SDK's Client encapsulates auth so this is naturally
        # thread-safe.
        client = _build_client(api_key, self._timeout)

        config = _genai_types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=response_schema,
            system_instruction=system_prompt,
            temperature=temperature,
            top_p=top_p,
            max_output_tokens=max_output_tokens,
        )

        response = await self._call_with_soft_retry(
            client=client,
            model_name=model_name,
            user_prompt=user_prompt,
            config=config,
        )

        # Sprint 8.3.11 R2 — surface MAX_TOKENS / SAFETY / RECITATION
        # finish reasons as distinct, actionable errors BEFORE the
        # parser tries to read a truncated body.
        self._check_finish_reason(response)

        return (
            self._parse_structured_response(response),
            self._extract_usage_metadata(response),
        )

    async def _call_with_soft_retry(
        self,
        *,
        client: Any,
        model_name: str,
        user_prompt: str,
        config: Any,
    ) -> Any:
        last_error: LLMProviderError | None = None
        for attempt in range(_TRANSIENT_RETRY_ATTEMPTS):
            try:
                return await client.aio.models.generate_content(
                    model=model_name,
                    contents=user_prompt,
                    config=config,
                )
            except (RateLimitError, InvalidKeyError):
                raise
            except Exception as exc:
                try:
                    self._raise_mapped_sdk_error(exc)
                except (RateLimitError, InvalidKeyError):
                    raise
                except LLMProviderError as mapped:
                    last_error = mapped
                    if attempt + 1 >= _TRANSIENT_RETRY_ATTEMPTS:
                        raise
                    delay = _TRANSIENT_RETRY_BASE_SECONDS * (2 ** attempt)
                    _logger.warning(
                        "Gemini transient error (attempt %d/%d); "
                        "retrying in %.1fs",
                        attempt + 1,
                        _TRANSIENT_RETRY_ATTEMPTS,
                        delay,
                        exc_info=True,
                    )
                    await asyncio.sleep(delay)
        if last_error is not None:
            raise last_error
        raise LLMProviderError("Gemini retry loop exited unexpectedly")

    @staticmethod
    def _raise_mapped_sdk_error(exc: Exception) -> None:
        """Map a raw SDK exception to the Sprint 8.3.6 hierarchy.

        Sprint 9.1 H — the new ``google-genai`` SDK exposes structured
        error types under ``google.genai.errors``. ClientError / ServerError
        carry a ``.code`` attribute with the HTTP status, so we can
        check it directly instead of message-sniffing. We still fall
        back to message inspection for chained / wrapped exceptions
        because some SDK paths wrap the underlying error before it
        reaches us.
        """
        # Native SDK error type with HTTP code attribute.
        if _genai_errors is not None and isinstance(exc, _genai_errors.APIError):
            code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
            if code == 429:
                raise RateLimitError() from exc
            if code in (401, 403):
                raise InvalidKeyError(f"API key rejected: {exc}") from exc
            # Server-side 5xx surfaces as ServerError; treat as a
            # transient LLMProviderError so the soft-retry loop above
            # can attempt one more pass before the rotator decides.
            raise LLMProviderError(f"Gemini API call failed: {exc}") from exc

        # Wrapped / chained exception — fall back to message sniff
        # (preserves behaviour with TaskGroup / generic transport
        # errors that don't carry .code).
        text = str(exc).lower()
        if (
            "429" in text
            or "rate limit" in text
            or "resource_exhausted" in text
            or "quota" in text
        ):
            raise RateLimitError() from exc
        if (
            "401" in text
            or "403" in text
            or "api key not valid" in text
            or "permission_denied" in text
            or "invalid api key" in text
            or "unauthenticated" in text
        ):
            raise InvalidKeyError(f"API key rejected: {exc}") from exc
        raise LLMProviderError(f"Gemini SWOT/OKR call failed: {exc}") from exc

    @staticmethod
    def _check_finish_reason(response: Any) -> None:
        """Sprint 8.3.11 R2 — raise distinct errors for the two
        non-STOP finish reasons that produce truncated / blocked
        bodies. The new SDK exposes ``finish_reason`` as the same
        FinishReason enum with a ``.name`` attribute.
        """
        candidates = getattr(response, "candidates", None)
        if not candidates:
            return
        first = candidates[0]
        finish = getattr(first, "finish_reason", None)
        if finish is None:
            return
        name = getattr(finish, "name", str(finish)).upper()
        if name in {"STOP", "FINISH_REASON_UNSPECIFIED", ""}:
            return
        if name == "MAX_TOKENS":
            partial_len = len(getattr(response, "text", "") or "")
            _logger.error(
                "Gemini response truncated (MAX_TOKENS); "
                "partial_len=%d. Bump max_output_tokens or "
                "shorten the prompt.",
                partial_len,
            )
            raise LLMTokenLimitError(
                "Gemini yanıtı token sınırına takıldı; raporu "
                "tekrar oluşturun veya dönemi daraltın."
            )
        if name in {"SAFETY", "RECITATION"}:
            _logger.error(
                "Gemini response blocked: finish_reason=%s", name,
            )
            raise LLMResponseBlockedError(
                f"Gemini yanıtı engellendi ({name})."
            )
        _logger.warning(
            "Gemini finish_reason=%s (unhandled); falling through to parse",
            name,
        )

    @staticmethod
    def _parse_structured_response(response: Any) -> dict[str, Any]:
        raw = getattr(response, "text", None)
        if not raw:
            raise MalformedResponseError("Empty response text from Gemini")
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
                        f"Gemini returned non-JSON text: {raw!r}"
                    ) from exc
            else:
                raise MalformedResponseError(
                    f"Gemini returned non-JSON text: {raw!r}"
                ) from None
        if not isinstance(data, dict):
            raise MalformedResponseError(
                f"Expected JSON object, got {type(data).__name__}"
            )
        return cast(dict[str, Any], data)

    @staticmethod
    def _extract_usage_metadata(response: Any) -> dict[str, int] | None:
        usage = getattr(response, "usage_metadata", None)
        if usage is None:
            return None
        prompt = getattr(usage, "prompt_token_count", None)
        candidates = getattr(usage, "candidates_token_count", None)
        total = getattr(usage, "total_token_count", None)
        if prompt is None and candidates is None and total is None:
            return None
        return {
            "input": int(prompt) if prompt is not None else 0,
            "output": int(candidates) if candidates is not None else 0,
            "total": int(total) if total is not None else 0,
        }


# Sprint 8.3.11 — Markdown fence stripper for the executive briefing
# 502 root cause. Same regex carried over from the old SDK; Gemini
# Flash's quirk of occasionally wrapping JSON in ```json ... ``` is
# orthogonal to which SDK we use.
_MARKDOWN_FENCE_OPEN = re.compile(r"^```(?:json)?\s*\r?\n?", re.IGNORECASE)
_MARKDOWN_FENCE_CLOSE = re.compile(r"\r?\n?\s*```\s*$")


def _strip_markdown_fences(text: str) -> str:
    stripped = text.strip()
    has_open = bool(_MARKDOWN_FENCE_OPEN.match(stripped))
    has_close = bool(_MARKDOWN_FENCE_CLOSE.search(stripped))
    if has_open and has_close:
        stripped = _MARKDOWN_FENCE_OPEN.sub("", stripped, count=1)
        stripped = _MARKDOWN_FENCE_CLOSE.sub("", stripped, count=1)
    return stripped.strip()
