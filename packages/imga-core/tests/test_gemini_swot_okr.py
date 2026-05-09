"""Sprint 8.3.6 / 8.3.6.2.E2 — Gemini SWOT/OKR provider tests.

Sprint 9.1 H — migrated to mock the new ``google-genai`` SDK. The
new SDK exposes a per-instance ``Client`` whose
``aio.models.generate_content(...)`` carries the async path, so the
fixture builds a fake ``_genai_module`` whose ``Client`` returns a
mock with the ``aio.models.generate_content`` AsyncMock attached.

Five core paths still pinned:
  * happy-path JSON parse
  * 429 → RateLimitError
  * 401/403 → InvalidKeyError
  * malformed JSON → MalformedResponseError
  * OKR happy path with the OKR-specific defaults

Plus the Sprint 8.3.6.5 token_usage extraction test moved over.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from imga_core.llm.errors import (
    InvalidKeyError,
    MalformedResponseError,
    RateLimitError,
)
from imga_core.llm.gemini import GeminiProvider

_SWOT_SCHEMA = {"type": "object", "_placeholder": "swot_v1"}
_OKR_SCHEMA = {"type": "object", "_placeholder": "okr_v1"}


def _make_response(
    *, text: str | None = None, usage: dict[str, int] | None = None
) -> MagicMock:
    """Build a MagicMock shaped like a google-genai response."""
    response = MagicMock()
    response.text = text
    if usage is None:
        response.usage_metadata = None
    else:
        meta = MagicMock()
        meta.prompt_token_count = usage["input"]
        meta.candidates_token_count = usage["output"]
        meta.total_token_count = usage["total"]
        response.usage_metadata = meta
    # No finish_reason → STOP-equivalent in the provider's check.
    response.candidates = []
    return response


@pytest.fixture
def provider() -> Any:
    """Build a GeminiProvider whose constructor doesn't run (no real
    SDK Client is created). Patches ``imga_core.llm.gemini._genai_module``
    so the provider's per-call ``_build_client`` returns a fresh
    MagicMock Client; tests inject the response by configuring
    ``client.aio.models.generate_content`` on that mock."""
    p = GeminiProvider.__new__(GeminiProvider)
    p._api_key = "ctor-key"
    p._model_name = "gemini-2.5-flash"
    p._timeout = 5.0
    p._client = MagicMock()
    fake_module = MagicMock()
    # Each Client(...) call returns a fresh MagicMock; tests set the
    # response on the .aio.models.generate_content AsyncMock chain.
    with patch("imga_core.llm.gemini._genai_module", fake_module):
        yield p, fake_module


def _wire_async_response(
    fake_module: MagicMock,
    *,
    text: str | None = None,
    usage: dict[str, int] | None = None,
    raises: Exception | None = None,
) -> MagicMock:
    """Configure the fake genai module so ``Client(...).aio.models.
    generate_content`` returns ``text`` (or raises). Returns the
    Client instance so tests can introspect call args."""
    client = MagicMock()
    if raises is not None:
        client.aio.models.generate_content = AsyncMock(side_effect=raises)
    else:
        client.aio.models.generate_content = AsyncMock(
            return_value=_make_response(text=text, usage=usage)
        )
    fake_module.Client.return_value = client
    return client


@pytest.mark.asyncio
async def test_generate_swot_returns_parsed_dict(provider: Any) -> None:
    p, fake_module = provider
    payload = {
        "strengths": [
            {"title": "Hızlı kargo", "description": "...", "evidence": "..."}
        ],
        "weaknesses": [],
        "opportunities": [],
        "threats": [],
        "strategic_recommendations": [],
    }
    client = _wire_async_response(fake_module, text=json.dumps(payload))

    result, usage = await p.generate_swot(
        api_key="test-key",
        system_prompt="You are a SWOT analyst.",
        user_prompt="Analyze: 1000 reviews, 80% positive.",
        response_schema=_SWOT_SCHEMA,
    )

    assert result == payload
    assert usage is None
    # Sprint 9.1 H — the per-call key flows in through Client(api_key=...)
    # not the legacy genai.configure(...) singleton.
    fake_module.Client.assert_called_once()
    ctor_kwargs = fake_module.Client.call_args.kwargs
    assert ctor_kwargs["api_key"] == "test-key"
    # generate_content called with the system instruction + structured
    # output config.
    call_kwargs = client.aio.models.generate_content.call_args.kwargs
    assert call_kwargs["model"] == "gemini-2.5-flash"
    cfg = call_kwargs["config"]
    assert cfg.system_instruction == "You are a SWOT analyst."
    assert cfg.response_mime_type == "application/json"
    assert cfg.response_schema == _SWOT_SCHEMA
    assert cfg.temperature == 0.2
    assert cfg.max_output_tokens == 8192


@pytest.mark.asyncio
async def test_generate_swot_rate_limit_maps_to_rate_limit_error(
    provider: Any,
) -> None:
    p, fake_module = provider
    _wire_async_response(
        fake_module,
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
    provider: Any,
) -> None:
    p, fake_module = provider
    _wire_async_response(
        fake_module,
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
    provider: Any,
) -> None:
    p, fake_module = provider
    _wire_async_response(fake_module, text="this is not json")
    with pytest.raises(MalformedResponseError, match="non-JSON"):
        await p.generate_swot(
            api_key="ok-key",
            system_prompt="x",
            user_prompt="y",
            response_schema=_SWOT_SCHEMA,
        )


@pytest.mark.asyncio
async def test_generate_okr_uses_okr_specific_defaults(provider: Any) -> None:
    p, fake_module = provider
    payload = {
        "objectives": [
            {"objective": "X", "rationale": "Y", "key_results": []}
        ]
    }
    client = _wire_async_response(fake_module, text=json.dumps(payload))

    result, usage = await p.generate_okr(
        api_key="okr-key",
        system_prompt="OKR system",
        user_prompt="Generate OKRs from: ...",
        response_schema=_OKR_SCHEMA,
    )

    assert result == payload
    assert usage is None
    cfg = client.aio.models.generate_content.call_args.kwargs["config"]
    assert cfg.response_schema == _OKR_SCHEMA
    assert cfg.temperature == 0.3
    assert cfg.max_output_tokens == 4096


@pytest.mark.asyncio
async def test_generate_swot_extracts_token_usage_from_metadata(
    provider: Any,
) -> None:
    p, fake_module = provider
    payload = {
        k: []
        for k in (
            "strengths",
            "weaknesses",
            "opportunities",
            "threats",
            "strategic_recommendations",
        )
    }
    _wire_async_response(
        fake_module,
        text=json.dumps(payload),
        usage={"input": 1234, "output": 567, "total": 1801},
    )

    _result, usage = await p.generate_swot(
        api_key="ok-key",
        system_prompt="x",
        user_prompt="y",
        response_schema=_SWOT_SCHEMA,
    )
    assert usage == {"input": 1234, "output": 567, "total": 1801}


@pytest.mark.asyncio
async def test_generate_swot_returns_none_usage_when_metadata_absent(
    provider: Any,
) -> None:
    p, fake_module = provider
    payload = {
        k: []
        for k in (
            "strengths",
            "weaknesses",
            "opportunities",
            "threats",
            "strategic_recommendations",
        )
    }
    _wire_async_response(fake_module, text=json.dumps(payload))

    _result, usage = await p.generate_swot(
        api_key="ok-key",
        system_prompt="x",
        user_prompt="y",
        response_schema=_SWOT_SCHEMA,
    )
    assert usage is None


@pytest.mark.asyncio
async def test_generate_okr_extracts_token_usage_too(provider: Any) -> None:
    p, fake_module = provider
    payload = {"objectives": []}
    _wire_async_response(
        fake_module,
        text=json.dumps(payload),
        usage={"input": 800, "output": 300, "total": 1100},
    )
    _result, usage = await p.generate_okr(
        api_key="ok-key",
        system_prompt="x",
        user_prompt="y",
        response_schema=_OKR_SCHEMA,
    )
    assert usage == {"input": 800, "output": 300, "total": 1100}


@pytest.mark.asyncio
async def test_generate_swot_empty_api_key_raises_invalid_key(
    provider: Any,
) -> None:
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
    provider: Any,
) -> None:
    p, _ = provider
    with pytest.raises(MalformedResponseError, match="non-empty"):
        await p.generate_swot(
            api_key="ok-key",
            system_prompt="x",
            user_prompt="   ",
            response_schema=_SWOT_SCHEMA,
        )


_ = Any  # silence Any unused import warning under future refactors
