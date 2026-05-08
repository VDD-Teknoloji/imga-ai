"""Sprint 9.0.5-A R7 follow-up — SDK request_options + thread-cancel
limitation regression coverage.

R7's earlier suite (``test_r7_timeout_and_cancel.py``) leaned on
mocked ``classify_async`` paths that used ``asyncio.sleep`` —
cancellable. Production reality is that ``GeminiProvider.classify``
goes through ``model.generate_content`` (sync C extension via the
google-generativeai SDK), wrapped in ``asyncio.to_thread``. Cancelling
that coroutine does NOT cancel the underlying thread — the SDK call
runs to completion in the executor pool, only the future is dropped.

So R7's actual protective vector isn't ``asyncio.wait_for`` (which
just makes the coroutine return fast); it's the **SDK's** own
``request_options.timeout`` and the **SDK's** retry predicate. If
either of those isn't applied in production, the worker still piles
up sync threads waiting on a 504 storm.

This file pins three properties:

  1. Our ``request_options`` dict actually reaches the SDK's
     ``generate_content`` call. Mocking the call site lets us
     capture the args and assert shape; we cannot assert the SDK's
     internal honouring of those options without an integration
     deploy, but we CAN catch a regression where someone drops the
     dict.
  2. The Retry predicate returns False for the canonical 5xx /
     timeout exception classes the SDK might raise — pinning the
     ``Retry(predicate=if_exception_type())`` contract from the
     consumer side.
  3. ``asyncio.wait_for(asyncio.to_thread(...))`` returns from the
     coroutine within the timeout window, but the underlying
     thread keeps executing. This is a documentation test for the
     R7 limitation so a future refactor that assumes "wait_for
     cancels everything" is reminded of reality.

If any of these break, R7's protection is incomplete — escalate to
R8 (SDK migration to a native-async client, or a different
isolation primitive).
"""

from __future__ import annotations

import asyncio
import threading
import time
from unittest.mock import MagicMock, patch

import pytest


# --- 1. request_options reaches the SDK ------------------------------


def test_classify_passes_no_retry_request_options_to_generate_content() -> None:
    """The whole reason ``_build_no_retry_request_options`` exists
    is so the SDK's retry loop short-circuits to one attempt + the
    SDK's own timeout caps the per-call wall-clock. If the dict
    doesn't reach ``generate_content`` (regression: someone drops
    the kwarg, refactors the call site, etc.), the SDK falls back
    to its default retry-on-5xx and the 504 storm regression
    returns. This test catches that exact case."""
    from imga_core.llm.gemini import GeminiProvider

    # Build a provider against a stub model so we don't actually
    # call Gemini. The constructor does ``genai.configure`` +
    # ``GenerativeModel(...)`` which under google-generativeai is
    # in-process bookkeeping (no network), but we still patch the
    # constructed model so generate_content is observable.
    provider = GeminiProvider(api_key="test-key", model_name="gemini-2.5-flash")

    # Replace the bound model with a MagicMock so we can capture
    # the generate_content args + return a stub response.
    fake_model = MagicMock()
    fake_response = MagicMock()
    fake_response.text = (
        '{"primary": "ürün_kalitesi", '
        '"confidence": 0.92, '
        '"reasoning": "stub"}'
    )
    fake_model.generate_content.return_value = fake_response
    provider._model = fake_model

    result = provider.classify(
        "test text", ["ürün_kalitesi", "kargo"]
    )
    assert result is not None

    # Capture the call.
    fake_model.generate_content.assert_called_once()
    _args, kwargs = fake_model.generate_content.call_args

    # request_options must be present + a dict + carry the timeout
    # we configured on the provider.
    request_options = kwargs.get("request_options")
    assert request_options is not None, (
        "request_options not passed to generate_content — SDK retry "
        "+ timeout protection is bypassed"
    )
    assert isinstance(request_options, dict)
    assert request_options.get("timeout") == 10.0, (
        f"timeout in request_options is {request_options.get('timeout')!r}; "
        "expected 10.0 (R7 default)"
    )
    # The retry field is optional (only present when google-api-core
    # is importable, which it is in the test compose since arq +
    # google-generativeai both depend on it transitively). When set,
    # it must disable retry — the predicate returns False for any
    # exception.
    retry = request_options.get("retry")
    if retry is not None:
        predicate = retry._predicate
        assert predicate(Exception("anything")) is False, (
            "Retry predicate accepts a generic Exception — SDK will "
            "still retry on 5xx, defeating the no-retry contract"
        )


# --- 2. Retry predicate vs. concrete SDK exception classes -----------


def test_no_retry_predicate_rejects_canonical_5xx_classes() -> None:
    """``Retry(predicate=if_exception_type())`` (empty tuple) should
    return False for every exception. We assert the canonical
    google-api-core 5xx + timeout exception classes that show up in
    a Gemini outage so a future change to ``_build_no_retry_request_options``
    doesn't accidentally re-enable retry on a subset (e.g. by passing
    ``if_transient_error`` or anything similar)."""
    from imga_core.llm.gemini import _build_no_retry_request_options

    opts = _build_no_retry_request_options(timeout_seconds=10.0)
    retry = opts.get("retry")
    if retry is None:
        pytest.skip("google-api-core not importable; predicate untested")
        return

    # Try to import the canonical exception classes; tolerate
    # ImportError so we don't break the test if google-api-core
    # ever moves these symbols.
    try:
        from google.api_core import exceptions as gax_exceptions  # type: ignore[import-untyped]
    except ImportError:
        pytest.skip("google.api_core.exceptions not importable")
        return

    predicate = retry._predicate
    candidates = [
        ("DeadlineExceeded", gax_exceptions.DeadlineExceeded),
        ("ServiceUnavailable", gax_exceptions.ServiceUnavailable),
        ("InternalServerError", gax_exceptions.InternalServerError),
        ("ResourceExhausted", gax_exceptions.ResourceExhausted),
    ]
    for label, cls in candidates:
        # Best-effort instantiation — the SDK's exception types
        # take varying constructor signatures across versions.
        try:
            instance = cls("simulated")
        except Exception:
            try:
                instance = cls()
            except Exception:
                continue
        assert predicate(instance) is False, (
            f"Retry predicate accepts {label} — the SDK will retry "
            "on this class, breaking R7's single-attempt contract"
        )


# --- 3. Document: asyncio.wait_for does NOT cancel a sync thread -----


def test_asyncio_wait_for_does_not_cancel_underlying_thread() -> None:
    """Documentation regression. Pins the Python behaviour that R7's
    ``asyncio.wait_for`` cap is a coroutine-side timeout only — the
    underlying ``asyncio.to_thread`` worker keeps running in the
    executor pool until the sync function returns naturally. R7's
    real protection is the SDK's own ``request_options.timeout`` +
    retry-disable; ``asyncio.wait_for`` is the BACKUP that frees
    the future + coroutine, not the primary cap.

    If a future refactor swaps the sync work for an async-native
    client (e.g. google.generativeai.async_client), the
    asyncio.wait_for timeout will then ALSO cancel the actual
    request and this documentation test should be replaced with
    one that asserts cancellation works through-and-through.

    Implementation notes:
      * Timing is captured INSIDE the coroutine, before the
        TimeoutError propagates. ``asyncio.run`` on 3.11+ waits for
        the default executor on shutdown, so timing the whole
        ``asyncio.run`` call would conflate the coroutine's
        wait_for fire (fast) with the executor's drain (slow) —
        exactly the behaviour we're documenting, but the wrong
        thing to measure for the assertion.
      * ``thread_was_set_at_timeout`` is also captured inside the
        coroutine so we observe the thread's state at the moment
        the wait_for fires, not after asyncio.run drained it.
    """
    thread_finished = threading.Event()

    def long_running_sync() -> None:
        # Real time.sleep — uninterruptible by asyncio cancellation.
        # Exact analogue to ``model.generate_content`` blocking on
        # a network call.
        time.sleep(0.6)
        thread_finished.set()

    async def _runner() -> tuple[float, bool]:
        coroutine_start = time.monotonic()
        try:
            await asyncio.wait_for(
                asyncio.to_thread(long_running_sync),
                timeout=0.1,
            )
        except asyncio.TimeoutError:
            elapsed = time.monotonic() - coroutine_start
            return elapsed, thread_finished.is_set()
        # If we got here, wait_for didn't fire — return a sentinel.
        return -1.0, thread_finished.is_set()

    elapsed, thread_done_at_timeout = asyncio.run(_runner())

    # Coroutine fired its TimeoutError fast (~0.1s + small slack).
    assert elapsed > 0, "asyncio.wait_for did not fire — test premise broken"
    assert elapsed < 0.4, (
        f"asyncio.wait_for didn't fire fast enough inside the "
        f"coroutine: {elapsed:.3f}s (expected <0.4s)"
    )
    # The thread was STILL RUNNING at the moment wait_for fired —
    # that's the limitation being documented. Note: by the time
    # asyncio.run returns, Python 3.11+'s default-executor shutdown
    # has waited for the thread, so ``thread_finished`` outside this
    # test would be True. The captured-at-timeout flag is the
    # property we care about.
    assert thread_done_at_timeout is False, (
        "asyncio.wait_for unexpectedly cancelled the underlying "
        "thread — the documented Python behaviour is that to_thread "
        "futures cancel but the executor task continues to run. If "
        "this assertion fails, an underlying CPython behaviour "
        "changed and R7's reasoning needs revisiting."
    )


# --- 4. Bonus: classify_async surfaces LLMProviderError on wait_for fire


@pytest.mark.asyncio
async def test_classify_async_translates_wait_for_timeout_to_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``asyncio.wait_for`` fires (SDK leaked past its own
    deadline), ``RotatingGeminiProvider.classify_async`` must
    surface a plain ``LLMProviderError`` rather than letting
    ``asyncio.TimeoutError`` propagate. The HybridClassifier
    exception handlers don't catch TimeoutError, so a leak there
    would crash the batch instead of feeding the circuit breaker."""
    from imga_core.llm import RotatingGeminiProvider
    from imga_core.llm.base import LLMProviderError
    from imga_core.llm.key_rotation import GeminiKey

    class _BlockingTooLong:
        def __init__(self, api_key: str, **_kw: object) -> None:
            self._k = api_key

        def classify(
            self, text: str, cats: list[str]
        ) -> object:
            time.sleep(2.0)
            return MagicMock()

        def health_check(self) -> bool:
            return True

    monkeypatch.setattr(
        "imga_core.llm.rotating_gemini.GeminiProvider", _BlockingTooLong
    )
    # Patch the safety-net constant so the test runs in <1s.
    monkeypatch.setattr(
        "imga_core.llm.rotating_gemini._HARD_ASYNCIO_TIMEOUT_SECONDS",
        0.2,
    )

    rp = RotatingGeminiProvider(
        keys=[GeminiKey(id="x", value="k", label="x", priority=0)],
    )
    with pytest.raises(LLMProviderError) as exc_info:
        await rp.classify_async("text", ["a"])
    assert "timed out" in str(exc_info.value).lower()
    # The exception type must NOT be asyncio.TimeoutError — that
    # would mean classify_async let it propagate raw.
    assert not isinstance(exc_info.value, asyncio.TimeoutError)
