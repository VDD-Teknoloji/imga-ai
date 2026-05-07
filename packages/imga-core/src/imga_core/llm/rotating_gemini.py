"""Multi-key Gemini classifier provider.

Sprint 9.0.5-A R5. The legacy ``GeminiProvider`` is single-key — the
classifier path was ENV-driven (one ``GEMINI_API_KEY``) and never
shared the SWOT/OKR rotator infrastructure built in Sprint 8.3.6.
The demo's paid Tier 1 quota is generous enough that one key is
enough today, but the operator UX promise was "add more keys, the
system rotates automatically" — and the classifier path silently
ignored extra rows in ``tenant_llm_credentials``.

This module wraps the existing ``GeminiKeyRotator`` (priority walk +
RateLimit/InvalidKey fall-through + AllKeysExhaustedError contract)
around per-call ephemeral ``GeminiProvider`` instances. Each
classification:

  1. Async rotator picks the next priority key.
  2. A short-lived ``GeminiProvider`` is constructed with that key,
     a single ``classify`` call runs through it via
     ``asyncio.to_thread`` so the event loop stays free.
  3. RateLimit / InvalidKey errors propagate to the rotator which
     falls through to the next priority.
  4. Other errors (Malformed, network 5xx, etc.) propagate unchanged.

The wrapped GeminiProvider is reused for the lifetime of one
classify_async call; we don't cache across calls because Gemini's
``genai.configure(api_key=...)`` is process-global and the rotator
swaps keys frequently. Cost: one configure() + one model
construction per call, ~ms — negligible against the network round-
trip.

Sprint 9.0.5-A R6 — the operation closure now wraps the sync
``provider.classify(...)`` in ``asyncio.to_thread``. R5 shipped
the closure as ``async def`` but the body never awaited anything,
so the GIL-holding sync SDK call (``genai.generate_content``)
blocked the event loop for the duration. Result: peer LLM calls
in HybridClassifier's batch path serialised behind each other and
the demo measured 165s on a 98-row LLM-bound batch (vs. R4's
expected 25s with 8-way parallelism).

logger.exception() in every catch path — Sprint 8.3.6.6 round-3
baseline note.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from imga_core.llm.base import LLMProvider, LLMProviderError
from imga_core.llm.errors import (
    AllKeysExhaustedError,
    InvalidKeyError,
    RateLimitError,
)
from imga_core.llm.gemini import GeminiProvider
from imga_core.llm.key_rotation import GeminiKey, GeminiKeyRotator
from imga_core.models import LLMClassificationResult

if TYPE_CHECKING:
    pass

_logger = logging.getLogger(__name__)


class RotatingGeminiProvider(LLMProvider):
    """Multi-key Gemini provider for category classification.

    Holds an immutable list of decrypted ``GeminiKey`` (loaded by the
    service layer via ``load_active_gemini_keys``). Each
    classification routes through ``GeminiKeyRotator.call_with_rotation``
    which falls through to the next priority on RateLimit /
    InvalidKey and raises ``AllKeysExhaustedError`` when every key
    has burnt.

    Single-key tenants get the same shape — rotator with one key
    produces a trivial round-robin. The HybridClassifier batch path
    cares about the rotator interface, not key count.
    """

    PROVIDER_NAME = "gemini-rotating"

    def __init__(
        self,
        keys: list[GeminiKey],
        model_name: str = "gemini-2.5-flash",
        timeout_seconds: float = 5.0,
    ) -> None:
        if not keys:
            raise ValueError(
                "RotatingGeminiProvider requires at least one GeminiKey — "
                "service layer should fall through to keyword-only "
                "classification when a tenant has no credentials"
            )
        self._rotator = GeminiKeyRotator(keys)
        self._model_name = model_name
        self._timeout_seconds = timeout_seconds
        # Sprint 9.0.5-A R6 follow-up — batch stats. Cumulative over
        # the provider's lifetime; the worker creates one provider
        # per job (via _build_tenant_classifier), so the values
        # mirror per-job totals once the job is over. Updates happen
        # exclusively on the asyncio loop thread (after to_thread
        # returns), so a plain set + int is safe without a Lock —
        # asyncio is single-threaded between awaits and the
        # mutations don't span an await point.
        self._keys_used: set[str] = set()
        self._rate_limit_events: int = 0

    @property
    def keys(self) -> list[GeminiKey]:
        """Frozen snapshot of the rotator's priority-ordered key list.
        Tests + telemetry use this; production code path goes through
        ``classify_async``."""
        return self._rotator.keys

    @property
    def model_name(self) -> str:
        return self._model_name

    def get_batch_stats(self) -> dict[str, int]:
        """Sprint 9.0.5-A R6 follow-up — return cumulative key-usage
        telemetry since this provider was constructed.

        Fields:
          * ``keys_used`` — count of distinct rotator key ids that
            successfully served at least one classify_async call.
          * ``rate_limit_events`` — total ``RateLimitError`` hits
            (each one represents one rotator fall-through; with N
            keys, at most N events fire per call).
          * ``keys_total`` — count of keys configured on the rotator
            (for log denominators: "5/12 keys touched this job").

        ``HybridClassifier.classify_batch_async`` reads this at the
        end of every batch and folds it into the per-batch summary
        log line so an operator can see live key fan-out via
        journalctl during the demo.
        """
        return {
            "keys_used": len(self._keys_used),
            "rate_limit_events": self._rate_limit_events,
            "keys_total": len(self._rotator.keys),
        }

    def reset_batch_stats(self) -> None:
        """Clear the cumulative counters. The worker doesn't call
        this in the current design (one provider per job means
        per-instance totals == per-job totals at shutdown), but the
        method exists so a future scheduler that reuses providers
        across jobs can scope the telemetry properly."""
        self._keys_used = set()
        self._rate_limit_events = 0

    def classify(
        self,
        text: str,
        available_categories: list[str],
    ) -> LLMClassificationResult:
        """Sync entry — wraps the async rotator path through
        ``asyncio.run``. Provided for legacy single-text callers
        (interactive ``/analyze`` route) but the batch path always
        prefers ``classify_async``."""
        import asyncio

        try:
            return asyncio.run(
                self.classify_async(text, available_categories)
            )
        except RuntimeError as exc:
            # asyncio.run barfs if a loop is already running on this
            # thread — that means a caller forgot to use the async
            # variant. Surface a clear error so the regression is
            # easy to spot.
            raise LLMProviderError(
                "RotatingGeminiProvider.classify cannot run inside an "
                "active event loop; use classify_async instead"
            ) from exc

    async def classify_async(
        self,
        text: str,
        available_categories: list[str],
    ) -> LLMClassificationResult:
        """Native async path — feeds the rotator's
        ``call_with_rotation`` so RateLimit / InvalidKey trigger key
        rotation transparently. Returns the LLMClassificationResult
        from whichever key produced it; logs the winning key id +
        label for operator observability."""

        async def _operation(api_key: str) -> LLMClassificationResult:
            # Per-call ephemeral provider — see module docstring for
            # the why. Construction cost is ~ms; it's the rotator's
            # only sane way to swap keys without smuggling state.
            provider = GeminiProvider(
                api_key=api_key,
                model_name=self._model_name,
                timeout_seconds=self._timeout_seconds,
            )
            try:
                # Sprint 9.0.5-A R6 — sync ``provider.classify`` runs
                # inside the Gemini SDK's blocking
                # ``generate_content`` call. Awaiting through
                # ``asyncio.to_thread`` parks the work on the
                # default executor so peer LLM tasks (parallel
                # rotator-driven calls from HybridClassifier's
                # batch path) actually overlap. The R5 build called
                # this synchronously inside an ``async def`` —
                # technically a coroutine but the body never
                # yielded, holding the loop for the duration of
                # each request and producing 165s on a 98-row
                # LLM-bound batch where 8-way parallel should land
                # in ~25s.
                return await asyncio.to_thread(
                    provider.classify, text, available_categories,
                )
            except RateLimitError:
                # Direct RateLimitError (rare — GeminiProvider's
                # SDK error mapping bubbles through LLMProviderError
                # in practice) still counts toward the telemetry
                # before the rotator falls through.
                self._rate_limit_events += 1
                raise
            except LLMProviderError as exc:
                # Map the legacy single-error type to the rotator's
                # vocabulary. The rotator only acts on RateLimitError
                # / InvalidKeyError; everything else propagates
                # unchanged. We sniff the exception text the same
                # way the SWOT path does so a 429 surfaced via
                # LLMProviderError still triggers rotation.
                try:
                    _maybe_rotate(exc)
                except RateLimitError:
                    self._rate_limit_events += 1
                    raise
                raise

        try:
            result, winning_key = await self._rotator.call_with_rotation(
                _operation
            )
        except AllKeysExhaustedError:
            # The rotator chains the last underlying error as
            # __cause__; we re-raise as LLMProviderError so the
            # HybridClassifier batch path treats it as a
            # provider-level failure (counts toward circuit breaker)
            # rather than an unknown exception.
            _logger.exception(
                "RotatingGeminiProvider: all %d keys exhausted",
                len(self._rotator.keys),
            )
            raise LLMProviderError(
                "All Gemini keys exhausted (rate-limited or invalid)"
            ) from None

        # Sprint 9.0.5-A R6 follow-up — telemetry. Recorded after
        # call_with_rotation returns success so transient
        # rate-limit fall-throughs (counted above in _operation)
        # don't pollute the "keys that actually served" set.
        self._keys_used.add(winning_key.id)
        _logger.debug(
            "RotatingGeminiProvider: served by key id=%s label=%s",
            winning_key.id,
            winning_key.label,
        )
        return result

    def health_check(self) -> bool:
        """Probe the primary key. The rotator itself doesn't have a
        single health concept (different keys can be in different
        states); the primary is the user-visible "is the integration
        configured" signal."""
        if not self._rotator.keys:
            return False
        try:
            primary = self._rotator.keys[0]
            return GeminiProvider(
                api_key=primary.value,
                model_name=self._model_name,
                timeout_seconds=2.0,
            ).health_check()
        except Exception:
            _logger.exception(
                "RotatingGeminiProvider health_check failed"
            )
            return False


def _maybe_rotate(exc: LLMProviderError) -> None:
    """Translate a legacy ``LLMProviderError`` into a rotator-relevant
    error if the message hints at a rate-limit or auth failure.
    Sprint 8.3.6 _raise_mapped_sdk_error has the canonical
    classification logic; this helper mirrors the substring sniffing
    so the classifier path triggers rotation without going through
    the SWOT/OKR-specific generate_content_async branch.

    No-op when the message looks like something else (parser /
    network / generic provider failure) — the original exception
    propagates and the rotator passes it through unchanged.
    """
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


__all__ = [
    "RotatingGeminiProvider",
]
