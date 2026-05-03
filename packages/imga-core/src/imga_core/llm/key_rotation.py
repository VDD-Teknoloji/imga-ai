"""Multi-key rotator for tenant LLM API keys.

Sprint 8.3.6 / Alt-Faz 8.3.6.2.D. Per-tenant keys live encrypted in
``tenant_llm_credentials`` (DB) and arrive here as plaintext + label
+ priority via the service layer. The rotator:

  * Walks the keys in ascending priority order (0 = primary).
  * Calls the caller-supplied async ``operation(api_key)`` with each
    key in turn.
  * Falls through on ``RateLimitError`` (transient) and
    ``InvalidKeyError`` (permanent for that key).
  * Lets every other ``LLMError`` propagate unchanged — the rotator
    has no opinion on ``MalformedResponseError`` (a different key
    won't fix bad output) or ``LLMProviderError`` (network / 5xx —
    service layer decides whether to retry).
  * Raises ``AllKeysExhaustedError`` when every key in the list has
    failed with a rotation-relevant error.

The rotator is in-memory only. Marking a key's ``last_failed_at`` in
the DB is the service layer's responsibility (Sprint 8.3.6.5
endpoints layer); we surface the failed key to the caller via the
returned tuple so the service knows which row to update.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

from imga_core.llm.errors import (
    AllKeysExhaustedError,
    InvalidKeyError,
    RateLimitError,
)

_logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class GeminiKey:
    """One row's worth of decrypted credential, ready for the rotator.

    ``id`` is the ``tenant_llm_credentials`` row UUID as a string —
    string here so the rotator stays free of DB types and the service
    layer can stringify whatever id type it has. ``label`` is the
    user-given name ("Birincil Hesap"), surfaced in logs so an
    operator can find the failing key without grep'ing UUIDs.
    """

    id: str
    value: str
    label: str
    priority: int


class GeminiKeyRotator:
    """In-memory rotator over a list of ``GeminiKey``.

    Stateless across calls — each ``call_with_rotation`` walks the
    full priority list. If the same rotator instance is reused for
    multiple operations and the primary keeps rate-limiting, it'll
    keep trying the primary first. That's intentional: the service
    layer marks dead keys via ``last_failed_at`` and re-fetches the
    rotation list before the next call, so a permanently-bad key
    won't return.
    """

    def __init__(self, keys: list[GeminiKey]) -> None:
        if not keys:
            raise ValueError(
                "GeminiKeyRotator requires at least one key — "
                "service layer should surface a 'configure an API key' "
                "UI state before instantiating"
            )
        # Sort by priority ascending (0 = primary, 1+ = fallback).
        # Defensive: callers may pass an unsorted list (DB query
        # without ORDER BY) and we don't want priority semantics to
        # depend on insertion order.
        self._keys: list[GeminiKey] = sorted(keys, key=lambda k: k.priority)

    @property
    def keys(self) -> list[GeminiKey]:
        """Frozen view of the priority-ordered key list. Returned as
        a fresh list each call so external code can't mutate
        rotator state."""
        return list(self._keys)

    async def call_with_rotation(
        self,
        operation: Callable[[str], Awaitable[T]],
    ) -> tuple[T, GeminiKey]:
        """Run ``operation(api_key)`` against each key in priority
        order until one succeeds.

        Returns:
            ``(result, key)`` — the operation's return value plus the
            ``GeminiKey`` that produced it. Service layer uses the
            second element to log "served by primary" vs "served by
            fallback_2" + (eventually) telemetry.

        Raises:
            AllKeysExhaustedError: every key raised RateLimit or
                InvalidKey. The last underlying error is chained as
                ``__cause__``.
            Other ``LLMError`` subclasses (MalformedResponseError,
                LLMProviderError): propagate unchanged from the first
                key that hits them. Rotation does not continue —
                another key won't produce different output.
        """
        last_error: Exception | None = None
        for key in self._keys:
            _logger.info(
                "rotator: trying key label=%s id=%s priority=%d",
                key.label, key.id, key.priority,
            )
            try:
                result = await operation(key.value)
            except RateLimitError as exc:
                _logger.info(
                    "rotator: rate limit on key id=%s, "
                    "falling through to next priority",
                    key.id,
                )
                last_error = exc
                continue
            except InvalidKeyError as exc:
                _logger.warning(
                    "rotator: invalid key id=%s label=%s — service "
                    "layer should mark last_failed_at",
                    key.id, key.label,
                )
                last_error = exc
                continue
            else:
                return result, key

        # Loop exited without a return — every key failed with a
        # rotation-relevant error.
        raise AllKeysExhaustedError(
            "All LLM keys in rotation failed (RateLimit or InvalidKey)"
        ) from last_error
