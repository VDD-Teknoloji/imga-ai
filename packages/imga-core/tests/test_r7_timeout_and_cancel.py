"""Sprint 9.0.5-A R7 — SDK retry disable + asyncio safety net +
mid-batch cancel + 504-vs-rate-limit regression coverage.

R7 incident recap: a 98-row LLM-bound batch on demo Tier 1 went
252 MiB -> 3.03 GiB resident with ``processed_rows=0`` while the
worker piled up futures that would never complete. The Gemini SDK's
default retry-on-5xx (3-5 attempts × 30s timeout each) turned a
single 504 into 90+ sec wall-clock per call; combined with the
8-way HybridClassifier semaphore, the in-flight chain dwarfed
incoming batches.

Sprint 9.1 H — migrated from ``google-generativeai`` to
``google-genai``. The single-attempt contract that R7 depended on
is now the SDK's *default* (the new SDK doesn't auto-retry on 5xx),
so the explicit ``Retry(predicate=...)`` plumbing is gone. We pin
the timeout-on-Client wiring instead, plus the asyncio safety net
and mid-batch cancel — those properties survive the SDK swap
unchanged.

These tests pin the four R7 fixes (post-9.1 H):

  1. ``GeminiProvider`` constructs the new SDK's Client with
     ``http_options=HttpOptions(timeout=...)`` so the per-call
     wall-clock is bounded at the transport layer.
  2. ``RotatingGeminiProvider.classify_async`` wraps the SDK call in
     ``asyncio.wait_for`` so a leaked SDK timeout still surfaces
     within ~15s; the timeout maps to ``LLMProviderError`` (not
     ``RateLimitError``) so the rotator passes it through.
  3. ``HybridClassifier`` tracks LLM tasks and cancels pending ones
     mid-batch when the breaker opens, freeing memory + wall-clock
     fast on a real outage.
  4. ``_maybe_rotate`` no longer classifies 504 / DEADLINE_EXCEEDED
     / 503 as rate-limits — they propagate so the breaker counts
     them but the rotator doesn't penalise the key.
"""

from __future__ import annotations

import asyncio
import time

import pytest
from imga_core.classifiers.base import CategoryClassifier
from imga_core.classifiers.hybrid import (
    CIRCUIT_BREAKER_FAIL_THRESHOLD,
    HybridClassifier,
)
from imga_core.llm import RotatingGeminiProvider
from imga_core.llm.base import LLMProvider, LLMProviderError
from imga_core.llm.errors import RateLimitError
from imga_core.llm.key_rotation import GeminiKey
from imga_core.models import CategoryClassification, LLMClassificationResult


def _result() -> LLMClassificationResult:
    return LLMClassificationResult(
        primary="ok",
        confidence=0.9,
        reasoning="stub",
        provider="gemini",
        model="gemini-2.5-flash",
    )


def _make_keys(*aliases: str) -> list[GeminiKey]:
    return [
        GeminiKey(id=f"id-{a}", value=f"key-{a}", label=a, priority=i)
        for i, a in enumerate(aliases)
    ]


# --- 1. SDK retry disable -------------------------------------------


def test_provider_wires_timeout_through_http_options() -> None:
    """Sprint 9.1 H — the new SDK takes the per-call timeout via
    ``http_options=HttpOptions(timeout=ms)`` on the Client. The R7
    bound is 10s; the wiring is what we actually pin (the SDK's
    no-retry default is not a knob we control on this side)."""
    from unittest.mock import MagicMock, patch

    from imga_core.llm.gemini import GeminiProvider

    with patch("imga_core.llm.gemini._genai_module") as fake_module:
        fake_module.Client.return_value = MagicMock()
        with patch("imga_core.llm.gemini._genai_types") as fake_types:
            fake_types.HttpOptions = MagicMock()
            GeminiProvider(api_key="k", timeout_seconds=10.0)
            assert fake_types.HttpOptions.called
            kwargs = fake_types.HttpOptions.call_args.kwargs
            assert kwargs.get("timeout") == 10_000  # ms
            ctor_kwargs = fake_module.Client.call_args.kwargs
            assert "http_options" in ctor_kwargs


# --- 2. asyncio safety net ------------------------------------------


class _BlockingTooLongStub:
    """Stand-in for GeminiProvider whose ``classify`` sleeps longer
    than the asyncio safety net so we can verify the wait_for fires."""

    def __init__(self, api_key: str, model_name: str = "x", **_kw: object) -> None:
        self._key = api_key

    def classify(
        self, text: str, available_categories: list[str]
    ) -> LLMClassificationResult:
        # Sleep longer than _HARD_ASYNCIO_TIMEOUT_SECONDS but short
        # enough that the test runs in seconds.
        time.sleep(20)
        return _result()

    def health_check(self) -> bool:
        return True


@pytest.mark.asyncio
async def test_classify_async_enforces_asyncio_safety_net(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sprint 9.0.5-A R7 — even if the SDK leaks past its own 10s
    timeout, ``asyncio.wait_for`` caps the wall-clock at ~15s and
    surfaces ``LLMProviderError`` (server-side, NOT a key issue)."""
    monkeypatch.setattr(
        "imga_core.llm.rotating_gemini.GeminiProvider",
        _BlockingTooLongStub,
    )
    # Speed the test up — the production safety-net is 15s but for
    # the regression we only need to prove wait_for fires before the
    # 20s sleep finishes. Patch the constant so the test runs quickly.
    monkeypatch.setattr(
        "imga_core.llm.rotating_gemini._HARD_ASYNCIO_TIMEOUT_SECONDS",
        0.3,
    )

    rp = RotatingGeminiProvider(keys=_make_keys("solo"))

    start = time.monotonic()
    with pytest.raises(LLMProviderError, match="timed out"):
        await rp.classify_async("x", ["a"])
    elapsed = time.monotonic() - start

    # Should fire well before the 20s stub sleep — 1s gives plenty
    # of margin for thread-pool scheduling.
    assert elapsed < 1.0, (
        f"asyncio safety net didn't fire: elapsed={elapsed:.2f}s"
    )


# --- 3. mid-batch cancellation --------------------------------------


class _StaggeredFailLLM(LLMProvider):
    """Mimics the smoke-test 504 storm shape: a few rows fail fast
    enough to trip the breaker, the rest are still mid-sleep when
    the breaker fires so the explicit ``task.cancel()`` path is
    exercised (mechanism 2 — distinct from the post-semaphore
    short-circuit, mechanism 1, which only catches tasks that
    haven't acquired the sem yet)."""

    def __init__(
        self,
        fast_count: int = 3,
        fast_delay: float = 0.05,
        slow_delay: float = 1.0,
    ) -> None:
        self.fast_count = fast_count
        self.fast_delay = fast_delay
        self.slow_delay = slow_delay
        self.completed = 0
        self.cancelled = 0

    def classify(
        self, text: str, available_categories: list[str]
    ) -> LLMClassificationResult:  # pragma: no cover — async path used
        return _result()

    async def classify_async(
        self, text: str, available_categories: list[str]
    ) -> LLMClassificationResult:
        # Texts come in as "row N" — read N so fast vs. slow is
        # deterministic regardless of asyncio's scheduling order.
        try:
            idx = int(text.split()[1])
        except (IndexError, ValueError):
            idx = 0
        delay = self.fast_delay if idx < self.fast_count else self.slow_delay
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        self.completed += 1
        raise LLMProviderError("simulated outage")

    def health_check(self) -> bool:
        return True


class _LowConfKeyword(CategoryClassifier):
    def classify(self, text: str) -> CategoryClassification:
        return CategoryClassification(
            primary="belirsiz",
            primary_confidence=0.1,
            primary_matched_keywords=(),
            secondaries=(),
            method="keyword",
            requires_manual_review=False,
        )


@pytest.mark.asyncio
async def test_circuit_breaker_cancels_pending_tasks_mid_batch() -> None:
    """Sprint 9.0.5-A R7 — when the circuit opens mid-batch the
    pending LLM tasks must be explicitly cancelled rather than left
    to drain. The earlier R4-only design relied on each task's
    post-semaphore circuit-check (mechanism 1) which fired only on
    rows that hadn't started yet; rows that were already inside
    ``await self.llm.classify_async`` would run to completion
    against a doomed provider, dragging out the wall-clock and
    piling up in-flight state.

    Test scenario mirrors the 504 storm shape: 20 rows total, the
    first 3 fail fast (50ms) so they trip the breaker; the
    remaining 17 sleep long (1s) so when the breaker opens they're
    still mid-sleep and the explicit ``task.cancel()`` mechanism
    has visible work to do.

    Concurrency is set high enough that all 20 tasks start in
    parallel — no semaphore queueing — so cancellation has to
    actually fire on in-flight tasks rather than relying on the
    queued-task short-circuit."""
    keyword = _LowConfKeyword()
    llm = _StaggeredFailLLM(
        fast_count=3, fast_delay=0.05, slow_delay=1.0,
    )
    classifier = HybridClassifier(
        keyword_classifier=keyword,
        llm_provider=llm,
        confidence_threshold=0.7,
        llm_concurrency=20,  # all 20 tasks in flight from the start
    )

    texts = [f"row {i}" for i in range(20)]
    start = time.monotonic()
    results = await classifier.classify_batch_async(texts)
    elapsed = time.monotonic() - start

    assert len(results) == 20
    # All rows surface for manual review (LLM failed, cancelled, or
    # short-circuited).
    assert all(r.requires_manual_review for r in results)
    # The fast 3 fail; the breaker trips. The remaining 17 are
    # mid-sleep when cancellation fires — they raise
    # CancelledError inside their classify_async sleep and tick the
    # ``cancelled`` counter. Conservative floor: at least half the
    # slow tasks should land as cancelled (some scheduler jitter
    # could let one or two extra complete before the cancel
    # broadcast catches them).
    assert llm.cancelled >= 8, (
        f"too few LLM tasks cancelled (completed={llm.completed}, "
        f"cancelled={llm.cancelled}); the explicit task.cancel() "
        "path may not be wired into classify_batch_async"
    )
    # Wall-clock should be far below the slow tail. Without cancel,
    # the run waits for the 1s sleep on every slow task -> ≥1s
    # wall-clock; with cancel, ~50ms fast fails + cancel drain.
    # Cap at 0.6s for noisy CI.
    assert elapsed < 0.6, (
        f"batch took {elapsed:.2f}s — pending in-flight tasks may "
        "not be cancelling promptly"
    )


# --- 4. 504 / DEADLINE_EXCEEDED is NOT rate-limit -------------------


@pytest.mark.parametrize(
    "msg",
    [
        "Gemini API call failed: 504 Deadline Exceeded",
        "DEADLINE_EXCEEDED",
        "Service unavailable: 503",
        "Gemini call timed out at asyncio safety net (15s)",
        "request timed out",
    ],
)
def test_maybe_rotate_treats_server_timeout_as_propagate(msg: str) -> None:
    """Sprint 9.0.5-A R7 — server-side timeouts and 5xx errors must
    NOT translate to RateLimitError. The earlier ``_maybe_rotate``
    sniff caught ``resource_exhausted`` aggressively, and certain
    SDK wrappings around 504s included that phrase — every key got
    "rate-limited" and AllKeysExhaustedError fired even though the
    real issue was a Gemini server outage."""
    from imga_core.llm.rotating_gemini import _maybe_rotate

    # No exception should be raised — _maybe_rotate returns silently
    # for non-rotator-relevant errors.
    _maybe_rotate(LLMProviderError(msg))


def test_maybe_rotate_still_translates_real_rate_limit() -> None:
    """Counter-test: messages that genuinely look like 429 / quota
    still trigger RateLimitError. The R7 expansion only ADDED
    timeout-style early exits; rate-limit detection is intact."""
    from imga_core.llm.rotating_gemini import _maybe_rotate

    with pytest.raises(RateLimitError):
        _maybe_rotate(LLMProviderError("429 Too Many Requests"))
    with pytest.raises(RateLimitError):
        _maybe_rotate(LLMProviderError("Quota exceeded for project"))
    with pytest.raises(RateLimitError):
        _maybe_rotate(
            LLMProviderError("Status: RESOURCE_EXHAUSTED on get_content")
        )


# --- 5. settings llm_concurrency default ----------------------------


def test_batch_settings_llm_concurrency_default_is_8() -> None:
    """Sprint 9.0.5-A R7 → R7 follow-up: default went 8 -> 4 -> 8.
    R7 dropped to 4 as defensive headroom during the 504-storm
    fix; py-spy Pattern A validation post-deploy confirmed the
    SDK retry-disable + asyncio safety net + mid-batch cancel
    are doing their job, so fan-out goes back to 8 to hit the
    demo's throughput target. Pin the new default so a future
    refactor that changes it again does so explicitly."""
    from imga_api.settings import BatchSettings

    assert BatchSettings().llm_concurrency == 8


def test_default_llm_concurrency_constant_is_8() -> None:
    """The module-level constant on hybrid.py mirrors the settings
    default so a HybridClassifier built without an explicit kwarg
    (e.g. tests, ad-hoc tooling) fans out the same as the
    worker-built one. R7 follow-up bumped 4 -> 8."""
    from imga_core.classifiers.hybrid import DEFAULT_LLM_CONCURRENCY

    assert DEFAULT_LLM_CONCURRENCY == 8


# Reference the threshold so its import isn't reported unused when
# this test file grows further parametrised cases.
_ = CIRCUIT_BREAKER_FAIL_THRESHOLD
