"""Sprint 9.3 A — LLMCallAuditor exception classifier unit tests.

The ``__aexit__`` path classifies the exception type into one of
the registry's ``error_type`` values via ``_classify_exception``.
This module pins the mapping so a future provider swap that
raises new exception classes doesn't quietly fall through to
``other`` for the cases the dashboard's filter relies on.
"""

from __future__ import annotations

import pytest

from imga_api.services.llm_audit_service import (
    ERROR_ALL_KEYS_EXHAUSTED,
    ERROR_API,
    ERROR_BLOCKED,
    ERROR_INVALID_KEY,
    ERROR_OTHER,
    ERROR_PARSE,
    ERROR_RATE_LIMIT,
    ERROR_TIMEOUT,
    ERROR_TOKEN_LIMIT,
    _classify_exception,
)


class _Mock(Exception):
    """Generic exception with a configurable name + message."""

    def __init__(self, msg: str = "") -> None:
        super().__init__(msg)


def _named(name: str, msg: str = "") -> Exception:
    cls = type(name, (Exception,), {})
    return cls(msg)


@pytest.mark.parametrize(
    "exc, expected",
    [
        (_named("RateLimitError"), ERROR_RATE_LIMIT),
        (_named("Foo", "429 Too Many Requests"), ERROR_RATE_LIMIT),
        (_named("Foo", "Quota exceeded"), ERROR_RATE_LIMIT),
        (_named("InvalidKeyError"), ERROR_INVALID_KEY),
        (_named("Foo", "API key not valid"), ERROR_INVALID_KEY),
        (_named("AllKeysExhaustedError"), ERROR_ALL_KEYS_EXHAUSTED),
        (_named("TimeoutError"), ERROR_TIMEOUT),
        (_named("Foo", "deadline exceeded"), ERROR_TIMEOUT),
        (_named("LLMResponseBlockedError", "SAFETY"), ERROR_BLOCKED),
        (_named("LLMTokenLimitError", "MAX_TOKENS reached"), ERROR_TOKEN_LIMIT),
        (_named("MalformedResponseError", "non-JSON text"), ERROR_PARSE),
        (_named("Foo", "504 Bad Gateway"), ERROR_API),
        (_named("Foo", "503 Service Unavailable"), ERROR_API),
        (_named("Foo", "completely unrelated"), ERROR_OTHER),
    ],
)
def test_classify_exception_maps_to_registry_error_type(
    exc: Exception, expected: str
) -> None:
    assert _classify_exception(exc) == expected
