"""LLM error hierarchy for Sprint 8.3.6's SWOT/OKR generation path.

Sprint 8.3.6 / Alt-Faz 8.3.6.2.C. The legacy ``LLMProviderError`` from
``imga_core.llm.base`` covers the classification fallback path; that
caller doesn't need to distinguish "retry with a different key" from
"the key is dead" because there's only one configured key. The
SWOT/OKR rotator does — ``RateLimitError`` and ``InvalidKeyError``
are signals it must act on, while ``MalformedResponseError`` (LLM
returned bad JSON) is *not* a rotation trigger and propagates up to
the service layer.

All four classes inherit from ``LLMError`` so a service-level catch-
all works without re-listing the leaves.
"""

from __future__ import annotations


class LLMError(Exception):
    """Base for every LLM call failure under the SWOT/OKR path.

    Service layers can catch this when they don't care which leaf
    fired (e.g. logging, generic 502 responses). The rotator
    distinguishes the two rotation-relevant leaves explicitly.
    """


class RateLimitError(LLMError):
    """HTTP 429 from the provider — quota exceeded.

    Carries ``retry_after`` (seconds) when the provider surfaced it
    so an upstream rate-limiter could back off; the rotator itself
    just falls through to the next priority key without waiting.
    """

    def __init__(self, *, retry_after: int | None = None) -> None:
        self.retry_after = retry_after
        suffix = (
            f" (retry after {retry_after}s)"
            if retry_after is not None
            else ""
        )
        super().__init__(f"Rate limit exceeded{suffix}")


class InvalidKeyError(LLMError):
    """HTTP 401 / 403 — key invalid, revoked, or quota permanently
    exhausted at the account level.

    The rotator treats this as a hard failure for the offending key
    (the service layer marks ``last_failed_at`` so the UI can show
    "needs attention") and tries the next priority. Distinct from
    RateLimitError because a transient rate-limit shouldn't poison
    the key for future requests.
    """


class AllKeysExhaustedError(LLMError):
    """Every key in the rotator's priority list raised either
    ``RateLimitError`` or ``InvalidKeyError`` and there's nothing
    left to fall through to.

    Surfaces to the service layer with the last underlying error
    chained as ``__cause__`` so logs preserve the failure tail.
    """


class MalformedResponseError(LLMError):
    """Provider returned a 200 response that didn't parse to the
    expected schema (invalid JSON, missing required fields,
    structured-output violation).

    *Not* a rotation trigger: a different API key would produce the
    same broken response. The SWOT/OKR service layer surfaces this
    to the user as "model output rejected, please retry"; the
    rotator passes it through unchanged.
    """
