"""Sprint 9.0.5-A R7 follow-up — SDK timeout + thread-cancel
limitation regression coverage.

Sprint 9.1 H — migrated to the new ``google-genai`` SDK. The new
SDK's behaviour: ``http_options=HttpOptions(timeout=ms)`` caps the
per-call wall-clock at the transport layer, and the SDK does NOT
auto-retry on 5xx by default (so the explicit retry-disable from
the old SDK's ``Retry(predicate=if_exception_type())`` becomes a
no-op — the property we want is now the *default*).

This file pins three properties:

  1. ``http_options`` reaches the Client constructor with the
     timeout we configured. If the wiring breaks, R7's protective
     vector is gone (the SDK falls back to its default 60s+).
  2. The provider stays single-attempt — no retry kwargs leak into
     ``generate_content`` calls. The legacy ``request_options=...``
     argument simply doesn't exist on the new SDK; this test pins
     that we don't accidentally re-introduce a retry knob.
  3. ``asyncio.wait_for(asyncio.to_thread(...))`` returns from the
     coroutine within the timeout window, but the underlying thread
     keeps executing. Documentation test for the R7 limitation that
     survives the SDK swap unchanged (it's a CPython property).
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# --- 1. http_options reaches the Client constructor ------------------


def test_provider_constructs_client_with_http_options_timeout() -> None:
    """Sprint 9.1 H — under the new SDK the timeout is set on the
    Client via ``http_options=HttpOptions(timeout=...)``; if a
    refactor drops the kwarg, the SDK falls back to its 60+ second
    default and the 504-storm protection is gone."""
    from imga_core.llm.gemini import GeminiProvider

    with patch("imga_core.llm.gemini._genai_module") as fake_module:
        fake_module.Client.return_value = MagicMock()
        with patch("imga_core.llm.gemini._genai_types") as fake_types:
            # Stand-in HttpOptions so we can capture the timeout arg.
            fake_types.HttpOptions = MagicMock()
            GeminiProvider(api_key="k", model_name="gemini-2.5-flash")
            assert fake_types.HttpOptions.called, (
                "HttpOptions not invoked — Client will use SDK default "
                "timeout, R7 protection is bypassed"
            )
            kwargs = fake_types.HttpOptions.call_args.kwargs
            # The timeout is in milliseconds (10s -> 10000).
            assert kwargs.get("timeout") == 10_000, (
                f"Client http_options timeout = {kwargs.get('timeout')!r}; "
                "expected 10000ms (R7 default)"
            )


# --- 2. No retry knob leaks into generate_content -------------------


def test_classify_does_not_pass_legacy_retry_kwargs() -> None:
    """The new SDK accepts a ``config=GenerateContentConfig(...)`` arg;
    it does NOT take ``request_options`` (legacy) or ``retry`` /
    ``retry_options`` per-call. If a refactor reintroduces a per-call
    retry knob, the soft-retry loop in ``_call_with_soft_retry`` would
    multiply against the SDK's own retries — exactly the 504-storm
    bug R7 fixed. This pins that no retry kwargs slip in."""
    from imga_core.llm.gemini import GeminiProvider

    provider = GeminiProvider.__new__(GeminiProvider)
    provider._api_key = "k"
    provider._model_name = "gemini-2.5-flash"
    provider._timeout = 10.0
    fake_response = MagicMock()
    fake_response.text = (
        '{"primary": "ürün_kalitesi", "confidence": 0.92, "reasoning": "x"}'
    )
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = fake_response
    provider._client = fake_client

    provider.classify("test", ["ürün_kalitesi", "kargo"])

    kwargs = fake_client.models.generate_content.call_args.kwargs
    # Allowed kwargs only.
    forbidden = {"request_options", "retry", "retry_options"}
    leaked = forbidden & set(kwargs.keys())
    assert not leaked, (
        f"Forbidden retry kwargs reached generate_content: {leaked}. "
        "R7 single-attempt contract broken."
    )
    # Positive — config is passed.
    assert "config" in kwargs


# --- 3. Document: asyncio.wait_for does NOT cancel a sync thread -----


def test_asyncio_wait_for_does_not_cancel_underlying_thread() -> None:
    """Documentation regression. Pins the Python behaviour that R7's
    ``asyncio.wait_for`` cap is a coroutine-side timeout only — the
    underlying ``asyncio.to_thread`` worker keeps running in the
    executor pool until the sync function returns naturally.

    This property is independent of which SDK is wrapped — it's a
    pure CPython behaviour about how Future cancellation interacts
    with executor-bound work. Carries forward unchanged across the
    9.1 H SDK swap.
    """
    thread_finished = threading.Event()

    def long_running_sync() -> None:
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
        return -1.0, thread_finished.is_set()

    elapsed, thread_done_at_timeout = asyncio.run(_runner())

    assert elapsed > 0, "asyncio.wait_for did not fire — test premise broken"
    assert elapsed < 0.4, (
        f"asyncio.wait_for didn't fire fast enough inside the "
        f"coroutine: {elapsed:.3f}s (expected <0.4s)"
    )
    assert thread_done_at_timeout is False, (
        "asyncio.wait_for unexpectedly cancelled the underlying "
        "thread — Python's executor-future contract changed; R7's "
        "reasoning needs revisiting."
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

        def classify(self, text: str, cats: list[str]) -> Any:
            time.sleep(2.0)
            return MagicMock()

        def health_check(self) -> bool:
            return True

    monkeypatch.setattr(
        "imga_core.llm.rotating_gemini.GeminiProvider", _BlockingTooLong
    )
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
    assert not isinstance(exc_info.value, asyncio.TimeoutError)
