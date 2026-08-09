"""OpenRouterProvider — classify/structured/hata eşleme birim testleri.

Ağ yok: httpx.Client / httpx.AsyncClient modül içinden monkeypatch'lenir.
test_gemini_provider.py'nin sözleşme aynası — hata hiyerarşisi ve
token_usage şekli Gemini yoluyla birebir aynı kalmalı ki rotator +
HybridClassifier sağlayıcıdan habersiz çalışsın.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from imga_core.llm.errors import (
    InvalidKeyError,
    LLMTokenLimitError,
    MalformedResponseError,
    RateLimitError,
)
from imga_core.llm.key_rotation import GeminiKey
from imga_core.llm.openrouter import (
    DEFAULT_OPENROUTER_MODEL,
    OpenRouterProvider,
    RotatingOpenRouterProvider,
    _read_body,
)


def _response(
    status_code: int = 200, payload: dict[str, Any] | None = None
) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        json=payload if payload is not None else {},
        request=httpx.Request("POST", "https://openrouter.ai/api/v1/x"),
    )


def _chat_payload(
    content: str,
    *,
    finish_reason: str = "stop",
    usage: dict[str, int] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "choices": [
            {"message": {"content": content}, "finish_reason": finish_reason}
        ]
    }
    if usage is not None:
        body["usage"] = usage
    return body


class _FakeClient:
    """httpx.Client(timeout=...) yerine geçen sahte — tek yanıt döner."""

    response: httpx.Response

    def __init__(self, *args: Any, **kwargs: Any) -> None: ...

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, *args: Any) -> None: ...

    def post(self, *args: Any, **kwargs: Any) -> httpx.Response:
        return self.response

    def get(self, *args: Any, **kwargs: Any) -> httpx.Response:
        return self.response


def _patch_client(
    monkeypatch: pytest.MonkeyPatch, response: httpx.Response
) -> None:
    _FakeClient.response = response
    monkeypatch.setattr("imga_core.llm.openrouter.httpx.Client", _FakeClient)


# --- classify --------------------------------------------------------


def test_classify_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _chat_payload(
        json.dumps(
            {"primary": "kargo", "confidence": 0.9, "reasoning": "test"}
        ),
        usage={"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150},
    )
    _patch_client(monkeypatch, _response(200, payload))
    provider = OpenRouterProvider(api_key="sk-or-test")
    result = provider.classify("kargo gec geldi", ["kargo", "belirsiz"])
    assert result.primary == "kargo"
    assert result.confidence == 0.9
    assert result.provider == "openrouter"
    assert result.model == DEFAULT_OPENROUTER_MODEL
    assert result.token_usage == {"input": 120, "output": 30, "total": 150}


def test_classify_unknown_category_coerces_to_belirsiz(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _chat_payload(
        json.dumps({"primary": "uydurma", "confidence": 0.7, "reasoning": ""})
    )
    _patch_client(monkeypatch, _response(200, payload))
    provider = OpenRouterProvider(api_key="sk-or-test")
    result = provider.classify("metin", ["kargo", "belirsiz"])
    assert result.primary == "belirsiz"


def test_classify_markdown_fenced_json_is_parsed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fenced = (
        "```json\n"
        + json.dumps({"primary": "kargo", "confidence": 0.8, "reasoning": ""})
        + "\n```"
    )
    _patch_client(monkeypatch, _response(200, _chat_payload(fenced)))
    provider = OpenRouterProvider(api_key="sk-or-test")
    result = provider.classify("metin", ["kargo"])
    assert result.primary == "kargo"


# --- hata eşleme -----------------------------------------------------


def test_http_429_maps_to_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(monkeypatch, _response(429, {}))
    provider = OpenRouterProvider(api_key="sk-or-test")
    with pytest.raises(RateLimitError):
        provider.classify("metin", ["kargo"])


def test_http_401_maps_to_invalid_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(monkeypatch, _response(401, {}))
    provider = OpenRouterProvider(api_key="sk-or-test")
    with pytest.raises(InvalidKeyError):
        provider.classify("metin", ["kargo"])


def test_error_envelope_in_200_body_maps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_client(
        monkeypatch,
        _response(200, {"error": {"code": 429, "message": "quota"}}),
    )
    provider = OpenRouterProvider(api_key="sk-or-test")
    with pytest.raises(RateLimitError):
        provider.classify("metin", ["kargo"])


def test_read_body_non_json_raises_malformed() -> None:
    resp = httpx.Response(
        200,
        text="not json",
        request=httpx.Request("POST", "https://openrouter.ai/api/v1/x"),
    )
    with pytest.raises(MalformedResponseError):
        _read_body(resp)


# --- yapılandırılmış üretim -----------------------------------------


class _FakeAsyncClient:
    response: httpx.Response

    def __init__(self, *args: Any, **kwargs: Any) -> None: ...

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *args: Any) -> None: ...

    async def post(self, *args: Any, **kwargs: Any) -> httpx.Response:
        return self.response


def _patch_async_client(
    monkeypatch: pytest.MonkeyPatch, response: httpx.Response
) -> None:
    _FakeAsyncClient.response = response
    monkeypatch.setattr(
        "imga_core.llm.openrouter.httpx.AsyncClient", _FakeAsyncClient
    )


@pytest.mark.asyncio
async def test_generate_swot_returns_parsed_payload_and_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _chat_payload(
        json.dumps({"strengths": ["hizli kargo"]}),
        usage={"prompt_tokens": 900, "completion_tokens": 210, "total_tokens": 1110},
    )
    _patch_async_client(monkeypatch, _response(200, payload))
    provider = OpenRouterProvider(api_key="sk-or-test")
    data, usage = await provider.generate_swot(
        api_key="sk-or-real",
        system_prompt="sys",
        user_prompt="user",
        response_schema={"type": "object"},
        model_name="anthropic/claude-haiku-4.5",
    )
    assert data == {"strengths": ["hizli kargo"]}
    assert usage == {"input": 900, "output": 210, "total": 1110}


@pytest.mark.asyncio
async def test_generate_structured_length_finish_raises_token_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _chat_payload("{\"a\":", finish_reason="length")
    _patch_async_client(monkeypatch, _response(200, payload))
    provider = OpenRouterProvider(api_key="sk-or-test")
    with pytest.raises(LLMTokenLimitError):
        await provider.generate_okr(
            api_key="sk-or-real",
            system_prompt="sys",
            user_prompt="user",
            response_schema={"type": "object"},
        )


# --- rotating varyant -----------------------------------------------


def test_rotating_openrouter_builds_openrouter_inner_provider() -> None:
    rotating = RotatingOpenRouterProvider(
        keys=[GeminiKey(id="1", value="sk-or-a", label="birincil", priority=0)],
        model_name="openai/gpt-5-nano",
    )
    inner = rotating._make_provider("sk-or-a")
    assert isinstance(inner, OpenRouterProvider)
    assert inner.model_name == "openai/gpt-5-nano"
    assert rotating.PROVIDER_NAME == "openrouter-rotating"
