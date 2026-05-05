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
from imga_core.llm.errors import (
    InvalidKeyError,
    MalformedResponseError,
    RateLimitError,
)
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

    # ------------------------------------------------------------------
    # Sprint 8.3.6 — SWOT + OKR generation (structured output)
    # ------------------------------------------------------------------
    #
    # These methods diverge from ``classify`` in three ways:
    #
    #   1. ``api_key`` is a per-call argument. The multi-key rotator
    #      (imga_core.llm.key_rotation) walks priorities and falls
    #      through on RateLimit/InvalidKey, so the provider must
    #      reconfigure the SDK at each attempt. ``classify`` keeps the
    #      constructor-bound key because the HybridClassifier path has
    #      a single configured tenant key.
    #   2. They're async. Service-layer callers (Sprint 8.3.6.3,
    #      8.3.6.4) live inside FastAPI request handlers; awaiting
    #      ``generate_content_async`` is straightforward there, while
    #      classify still runs sync inside the analyze pipeline's
    #      thread-bound BERT path.
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
        # Sprint 8.3.6.6 round-4 — flash is the free-tier default;
        # gemini-2.5-pro requires a paid Google AI Studio billing setup
        # (the consumer "Google AI Pro" subscription does NOT carry an
        # API quota). Flash is fast enough for SWOT/OKR with the
        # current prompt length and gives free-tier tenants a working
        # path. Tenant-level model_name override lands in Sprint 9.x.
        model_name: str = "gemini-2.5-flash",
        temperature: float = 0.2,
        top_p: float = 0.9,
        max_output_tokens: int = 8192,
    ) -> tuple[dict[str, Any], dict[str, int] | None]:
        """Generate a SWOT analysis with structured JSON output.

        ``response_schema`` is the JSON-schema dict the prompt template
        ships (Sprint 8.3.6.3 finalises it). The Gemini SDK's
        ``response_mime_type=application/json`` + ``response_schema``
        combination guarantees the model returns syntactically valid
        JSON — this method's job is to map provider-side errors to the
        rotator's hierarchy and surface the parsed dict.

        Returns:
            ``(parsed_payload, token_usage)``. ``token_usage`` is a
            ``{"input": int, "output": int, "total": int}`` dict when
            the SDK surfaced ``response.usage_metadata`` (Sprint
            8.3.6.5 lift), otherwise ``None``. The service layer
            persists it on ``strategic_reports.token_usage``.

        Raises:
            RateLimitError: HTTP 429.
            InvalidKeyError: HTTP 401 / 403.
            MalformedResponseError: 200 response that didn't parse to a
                dict, or empty ``response.text``.
            LLMProviderError: any other provider failure (network,
                timeout, 5xx). The rotator does not handle these —
                they propagate so the service layer can decide.
        """
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
        # Same free-tier flash default as ``generate_swot`` (Sprint
        # 8.3.6.6 round-4). See that method's docstring for context.
        model_name: str = "gemini-2.5-flash",
        temperature: float = 0.3,
        top_p: float = 0.9,
        max_output_tokens: int = 4096,
    ) -> tuple[dict[str, Any], dict[str, int] | None]:
        """Generate OKR proposals with structured JSON output.

        Default temperature is 0.3 (vs SWOT's 0.2) because OKRs benefit
        from a touch more variation in framing — strict deterministic
        output produces stilted "Increase X by Y" templates.
        ``max_output_tokens`` is half of SWOT's because OKR responses
        are tighter (2-4 objectives × 2-4 key results, no narrative
        recommendations).

        Same return + error contract as ``generate_swot`` — including
        the ``(payload, token_usage)`` tuple.
        """
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
        # Sprint 8.3.10 — same flash default as SWOT/OKR. Briefings
        # are short (1 paragraph + 3-5 KPIs + 2-3 insights + 3 actions)
        # so max_output_tokens stays low.
        model_name: str = "gemini-2.5-flash",
        temperature: float = 0.25,
        top_p: float = 0.9,
        max_output_tokens: int = 2048,
    ) -> tuple[dict[str, Any], dict[str, int] | None]:
        """Sprint 8.3.10 — generate a 1-page executive briefing JSON.
        Same return + error contract as ``generate_swot`` /
        ``generate_okr``. Lower temperature to keep the headline
        deterministic-ish; briefings benefit from concrete framing
        more than from variation."""
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
        """Shared structured-output call path. SWOT/OKR diverge only in
        defaults; the actual SDK plumbing is identical."""
        if not api_key:
            raise InvalidKeyError("Empty api_key passed to generate_structured")
        if not user_prompt or not user_prompt.strip():
            raise MalformedResponseError("user_prompt must be non-empty")

        # Reconfigure the SDK with this attempt's key. Sequential by
        # construction (rotator walks one key at a time), so the global
        # ``configure`` call is safe; concurrent generation across
        # tenants is out of scope for Sprint 8.3.6 (manual-only
        # trigger).
        self._genai.configure(api_key=api_key)
        model = self._genai.GenerativeModel(
            model_name,
            system_instruction=system_prompt,
        )

        try:
            response = await model.generate_content_async(
                user_prompt,
                generation_config={
                    "response_mime_type": "application/json",
                    "response_schema": response_schema,
                    "temperature": temperature,
                    "top_p": top_p,
                    "max_output_tokens": max_output_tokens,
                },
            )
        except Exception as exc:
            self._raise_mapped_sdk_error(exc)

        return (
            self._parse_structured_response(response),
            self._extract_usage_metadata(response),
        )

    @staticmethod
    def _raise_mapped_sdk_error(exc: Exception) -> None:
        """Map a raw SDK exception to the Sprint 8.3.6 hierarchy.

        ``google.generativeai`` raises a small zoo of types and the
        public ones don't expose stable HTTP status access; we sniff
        the exception message + chained context for the codes that
        matter to the rotator. Anything we can't classify falls
        through as ``LLMProviderError`` so the service layer sees
        it without the rotator swallowing it.
        """
        text = str(exc).lower()
        # 429 / quota — rate limit. The SDK sometimes surfaces a
        # ``retry_after`` header; not stable enough to parse, so we
        # leave it None.
        if (
            "429" in text
            or "rate limit" in text
            or "resource_exhausted" in text
            or "quota" in text
        ):
            raise RateLimitError() from exc
        # 401 / 403 — invalid or revoked key.
        if (
            "401" in text
            or "403" in text
            or "api key not valid" in text
            or "permission_denied" in text
            or "invalid api key" in text
            or "unauthenticated" in text
        ):
            raise InvalidKeyError(f"API key rejected: {exc}") from exc
        # Everything else propagates to the legacy provider error so
        # the service layer's catch-all logging handles it.
        raise LLMProviderError(f"Gemini SWOT/OKR call failed: {exc}") from exc

    @staticmethod
    def _parse_structured_response(response: Any) -> dict[str, Any]:
        raw = getattr(response, "text", None)
        if not raw:
            raise MalformedResponseError("Empty response text from Gemini")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise MalformedResponseError(
                f"Gemini returned non-JSON text: {raw!r}"
            ) from exc
        if not isinstance(data, dict):
            raise MalformedResponseError(
                f"Expected JSON object, got {type(data).__name__}"
            )
        return cast(dict[str, Any], data)

    @staticmethod
    def _extract_usage_metadata(response: Any) -> dict[str, int] | None:
        """Pull token usage off ``response.usage_metadata`` when the
        SDK surfaced it.

        Sprint 8.3.6.5 lift — Sprint 8.3.6.3 deferred this with a
        TODO. The SDK populates ``prompt_token_count`` /
        ``candidates_token_count`` / ``total_token_count`` for every
        successful call; some pre-2024 SDKs don't, so ``None`` is the
        correct fall-back instead of a fake-zero dict that downstream
        cost dashboards would treat as a free request.

        Returned ``{"input": int, "output": int, "total": int}`` matches
        the ``strategic_reports.token_usage`` JSONB shape the service
        layer persists.
        """
        usage = getattr(response, "usage_metadata", None)
        if usage is None:
            return None
        prompt = getattr(usage, "prompt_token_count", None)
        candidates = getattr(usage, "candidates_token_count", None)
        total = getattr(usage, "total_token_count", None)
        # If the SDK returned a usage_metadata object but with all
        # fields missing, treat as no usage rather than a {None, None,
        # None} dict the JSONB column would happily accept.
        if prompt is None and candidates is None and total is None:
            return None
        return {
            "input": int(prompt) if prompt is not None else 0,
            "output": int(candidates) if candidates is not None else 0,
            "total": int(total) if total is not None else 0,
        }
