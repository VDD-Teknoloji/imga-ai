"""Sprint 8.3.6 / Alt-Faz 8.3.6.2.E1 — multi-key rotator unit tests.

The rotator is the load-bearing piece for the SWOT/OKR path: a
broken contract here means a tenant's primary failure either
masquerades as a system outage (rotator falls through too eagerly)
or a real outage masquerades as a key issue (rotator doesn't fall
through when it should). Seven tests pin both directions.

Pure async unit tests — no DB, no SDK, the ``operation`` callable is
a tiny inline coroutine that selects its branch from the api_key
argument.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest

from imga_core.llm import (
    AllKeysExhaustedError,
    GeminiKey,
    GeminiKeyRotator,
    InvalidKeyError,
    MalformedResponseError,
    RateLimitError,
)


def _key(*, value: str, priority: int, label: str | None = None) -> GeminiKey:
    return GeminiKey(
        id=f"id-{value}",
        value=value,
        label=label or f"Key-{value}",
        priority=priority,
    )


@pytest.mark.asyncio
async def test_single_key_success_returns_result_and_key() -> None:
    """Trivial happy path: one key, operation returns 42, rotator
    yields (42, that_key)."""
    rotator = GeminiKeyRotator([_key(value="alpha", priority=0)])

    async def op(api_key: str) -> int:
        assert api_key == "alpha"
        return 42

    result, key = await rotator.call_with_rotation(op)
    assert result == 42
    assert key.value == "alpha"
    assert key.priority == 0


@pytest.mark.asyncio
async def test_primary_rate_limit_falls_through_to_fallback() -> None:
    """RateLimitError is a transient signal — rotator must try the
    next priority and surface that key on success."""
    rotator = GeminiKeyRotator([
        _key(value="primary", priority=0),
        _key(value="fallback", priority=1),
    ])
    seen: list[str] = []

    async def op(api_key: str) -> str:
        seen.append(api_key)
        if api_key == "primary":
            raise RateLimitError(retry_after=30)
        return "ok"

    result, key = await rotator.call_with_rotation(op)
    assert result == "ok"
    assert key.value == "fallback"
    assert key.priority == 1
    assert seen == ["primary", "fallback"]


@pytest.mark.asyncio
async def test_primary_invalid_key_falls_through_to_fallback() -> None:
    """InvalidKeyError is a permanent signal for that key — same
    rotation behaviour. The service layer separately marks
    ``last_failed_at``; rotator just steps over."""
    rotator = GeminiKeyRotator([
        _key(value="bad-primary", priority=0),
        _key(value="good-fallback", priority=1),
    ])

    async def op(api_key: str) -> str:
        if api_key == "bad-primary":
            raise InvalidKeyError("revoked")
        return "ok"

    result, key = await rotator.call_with_rotation(op)
    assert result == "ok"
    assert key.value == "good-fallback"


@pytest.mark.asyncio
async def test_all_keys_exhausted_raises_with_chained_cause() -> None:
    """Three keys, all rate-limited → AllKeysExhaustedError; the
    last RateLimitError must be chained as __cause__ so logs preserve
    the failure tail."""
    rotator = GeminiKeyRotator([
        _key(value="k1", priority=0),
        _key(value="k2", priority=1),
        _key(value="k3", priority=2),
    ])

    async def op(api_key: str) -> str:
        raise RateLimitError(retry_after=int(api_key[1]) * 10)

    with pytest.raises(AllKeysExhaustedError) as excinfo:
        await rotator.call_with_rotation(op)
    # Last key was k3 → retry_after 30.
    assert isinstance(excinfo.value.__cause__, RateLimitError)
    assert excinfo.value.__cause__.retry_after == 30


@pytest.mark.asyncio
async def test_other_llm_error_propagates_without_rotation() -> None:
    """MalformedResponseError is *not* a rotation trigger — a
    different key won't produce different bad output. Rotator must
    surface the first occurrence and stop trying further keys."""
    rotator = GeminiKeyRotator([
        _key(value="primary", priority=0),
        _key(value="fallback", priority=1),
    ])
    attempts: list[str] = []

    async def op(api_key: str) -> str:
        attempts.append(api_key)
        if api_key == "primary":
            raise MalformedResponseError("bad json")
        return "ok"  # would succeed but rotator must not get here

    with pytest.raises(MalformedResponseError, match="bad json"):
        await rotator.call_with_rotation(op)
    assert attempts == ["primary"]  # fallback never tried


@pytest.mark.asyncio
async def test_priority_order_respected_on_unsorted_input() -> None:
    """Service layer might query the DB without ORDER BY; rotator
    must sort by priority itself, not trust insertion order. Pass
    keys in [2, 0, 1] order, expect 0 → 1 → 2."""
    rotator = GeminiKeyRotator([
        _key(value="c", priority=2),
        _key(value="a", priority=0),
        _key(value="b", priority=1),
    ])
    order: list[str] = []

    async def op(api_key: str) -> str:
        order.append(api_key)
        raise RateLimitError()

    with pytest.raises(AllKeysExhaustedError):
        await rotator.call_with_rotation(op)
    assert order == ["a", "b", "c"]


def test_empty_keys_list_raises_value_error() -> None:
    """Construction guard. The service layer is responsible for the
    "no keys configured" UI state; the rotator must not be
    instantiable in an invalid state."""
    with pytest.raises(ValueError, match="at least one key"):
        GeminiKeyRotator([])


# ---------------------------------------------------------------------------
# Mixed-error sanity (not in the master prompt's 7 but cheap to add)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mixed_rate_limit_then_invalid_then_success() -> None:
    """Stress the loop: primary rate-limited, fallback_1 invalid,
    fallback_2 succeeds. Rotator must walk all three."""
    rotator = GeminiKeyRotator([
        _key(value="p", priority=0),
        _key(value="f1", priority=1),
        _key(value="f2", priority=2),
    ])

    async def op(api_key: str) -> str:
        if api_key == "p":
            raise RateLimitError(retry_after=10)
        if api_key == "f1":
            raise InvalidKeyError("revoked")
        return "third-time"

    result, key = await rotator.call_with_rotation(op)
    assert result == "third-time"
    assert key.value == "f2"
    assert key.priority == 2


# Silence unused-import warning if a refactor drops one of the helpers.
_ = (Awaitable, Callable)
