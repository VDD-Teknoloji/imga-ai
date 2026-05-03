"""Sprint 8.3.6 / Alt-Faz 8.3.6.2.E2 — Gemini SWOT/OKR provider tests.

Mocks the google.generativeai SDK at the same import path the existing
classification tests use (``imga_core.llm.gemini``) so the structured-
output methods stay hermetic. Five tests pin:

  * happy-path JSON parse
  * 429 → RateLimitError
  * 401/403 → InvalidKeyError
  * malformed JSON → MalformedResponseError
  * OKR happy path with the OKR-specific defaults

Async tests use pytest-asyncio (already enabled in this package).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from imga_core.llm.errors import (
    InvalidKeyError,
    MalformedResponseError,
    RateLimitError,
)
from imga_core.llm.gemini import GeminiProvider

_SWOT_SCHEMA = {"type": "object", "_placeholder": "swot_v1"}
_OKR_SCHEMA = {"type": "object", "_placeholder": "okr_v1"}


@pytest.fixture
def provider() -> tuple[GeminiProvider, MagicMock]:
    """Build a GeminiProvider without running its real __init__ (which
    imports the SDK + calls genai.configure). Returns the provider
    plus the genai mock so individual tests can wire the model
    response."""
    p = GeminiProvider.__new__(GeminiProvider)
    genai_mock = MagicMock()
    p._genai = genai_mock
    p._model_name = "gemini-2.5-flash"
    p._timeout = 5.0
    return p, genai_mock


def _wire_response(
    genai_mock: MagicMock,
    *,
    text: str | None = None,
    raises: Exception | None = None,
) -> MagicMock:
    """Configure the genai mock so a generate_content_async call
    returns ``text`` (or raises ``raises``). Returns the model mock
    so callers can assert on call args."""
    model_mock = MagicMock()
    if raises is not None:
        model_mock.generate_content_async = AsyncMock(side_effect=raises)
    else:
        response = MagicMock()
        response.text = text
        model_mock.generate_content_async = AsyncMock(return_value=response)
    genai_mock.GenerativeModel.return_value = model_mock
    return model_mock


@pytest.mark.asyncio
async def test_generate_swot_returns_parsed_dict(
    provider: tuple[GeminiProvider, MagicMock],
) -> None:
    """Happy path: 200 with valid JSON. Provider returns the parsed
    dict; SDK was called with response_mime_type=application/json +
    response_schema."""
    p, genai_mock = provider
    payload = {
        "strengths": [{"title": "Hızlı kargo", "description": "...", "evidence": "..."}],
        "weaknesses": [],
        "opportunities": [],
        "threats": [],
        "strategic_recommendations": [],
    }
    import json
    model = _wire_response(genai_mock, text=json.dumps(payload))

    result = await p.generate_swot(
        api_key="test-key",
        system_prompt="You are a SWOT analyst.",
        user_prompt="Analyze: 1000 reviews, 80% positive.",
        response_schema=_SWOT_SCHEMA,
    )

    assert result == payload
    # configure was called with the per-call key (not constructor key).
    genai_mock.configure.assert_called_with(api_key="test-key")
    # GenerativeModel constructed with the SWOT default model + system instruction.
    call_kwargs = genai_mock.GenerativeModel.call_args.kwargs
    assert call_kwargs["system_instruction"] == "You are a SWOT analyst."
    # generate_content_async called with structured-output config.
    cfg = model.generate_content_async.call_args.kwargs["generation_config"]
    assert cfg["response_mime_type"] == "application/json"
    assert cfg["response_schema"] == _SWOT_SCHEMA
    assert cfg["temperature"] == 0.2  # SWOT default
    assert cfg["max_output_tokens"] == 8192  # SWOT default


@pytest.mark.asyncio
async def test_generate_swot_rate_limit_maps_to_rate_limit_error(
    provider: tuple[GeminiProvider, MagicMock],
) -> None:
    """SDK surfaces 429 / quota errors with strings the mapper sniffs.
    Provider must translate to RateLimitError so the rotator can
    fall through."""
    p, genai_mock = provider
    _wire_response(
        genai_mock,
        raises=Exception("429 Too Many Requests: quota exceeded"),
    )

    with pytest.raises(RateLimitError):
        await p.generate_swot(
            api_key="rate-limited-key",
            system_prompt="x",
            user_prompt="y",
            response_schema=_SWOT_SCHEMA,
        )


@pytest.mark.asyncio
async def test_generate_swot_invalid_key_maps_to_invalid_key_error(
    provider: tuple[GeminiProvider, MagicMock],
) -> None:
    """401/403 / "API key not valid" → InvalidKeyError so the rotator
    can mark the credential as failed and walk to the next."""
    p, genai_mock = provider
    _wire_response(
        genai_mock,
        raises=Exception("403 PERMISSION_DENIED: API key not valid"),
    )

    with pytest.raises(InvalidKeyError):
        await p.generate_swot(
            api_key="revoked-key",
            system_prompt="x",
            user_prompt="y",
            response_schema=_SWOT_SCHEMA,
        )


@pytest.mark.asyncio
async def test_generate_swot_malformed_json_raises_malformed_response(
    provider: tuple[GeminiProvider, MagicMock],
) -> None:
    """200 response with non-JSON text. Rotator should NOT retry
    (different key won't produce different output) — provider raises
    MalformedResponseError, which the rotator passes through."""
    p, genai_mock = provider
    _wire_response(genai_mock, text="this is not json")

    with pytest.raises(MalformedResponseError, match="non-JSON"):
        await p.generate_swot(
            api_key="ok-key",
            system_prompt="x",
            user_prompt="y",
            response_schema=_SWOT_SCHEMA,
        )


@pytest.mark.asyncio
async def test_generate_okr_uses_okr_specific_defaults(
    provider: tuple[GeminiProvider, MagicMock],
) -> None:
    """OKR's contract: temperature 0.3 (vs SWOT 0.2), max_output_tokens
    4096 (vs 8192). Same structured-output pipeline otherwise."""
    p, genai_mock = provider
    payload = {"objectives": [{"objective": "X", "rationale": "Y", "key_results": []}]}
    import json
    model = _wire_response(genai_mock, text=json.dumps(payload))

    result = await p.generate_okr(
        api_key="okr-key",
        system_prompt="OKR system",
        user_prompt="Generate OKRs from: ...",
        response_schema=_OKR_SCHEMA,
    )

    assert result == payload
    cfg = model.generate_content_async.call_args.kwargs["generation_config"]
    assert cfg["response_schema"] == _OKR_SCHEMA
    assert cfg["temperature"] == 0.3  # OKR default — slightly higher
    assert cfg["max_output_tokens"] == 4096  # OKR tighter response


# ---------------------------------------------------------------------------
# Validation guards (small extras for completeness)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_swot_empty_api_key_raises_invalid_key(
    provider: tuple[GeminiProvider, MagicMock],
) -> None:
    """An empty key reaching the provider is a bug at the credential
    service layer (decrypt should raise before this), but the
    provider must fail fast rather than configure(api_key="") and
    let Google return a useless 400."""
    p, _ = provider
    with pytest.raises(InvalidKeyError, match="Empty api_key"):
        await p.generate_swot(
            api_key="",
            system_prompt="x",
            user_prompt="y",
            response_schema=_SWOT_SCHEMA,
        )


@pytest.mark.asyncio
async def test_generate_swot_empty_user_prompt_raises_malformed(
    provider: tuple[GeminiProvider, MagicMock],
) -> None:
    """An empty user_prompt is a service-layer bug; surface before
    burning a Gemini call. MalformedResponseError because the
    failure shape is "input bad" — not a rotation signal."""
    p, _ = provider
    with pytest.raises(MalformedResponseError, match="non-empty"):
        await p.generate_swot(
            api_key="ok-key",
            system_prompt="x",
            user_prompt="   ",
            response_schema=_SWOT_SCHEMA,
        )


_ = Any  # silence Any unused import if a future refactor drops it
