"""Tests for GeminiProvider — google-genai SDK is mocked.

Real Gemini calls go out only when GEMINI_API_KEY is set and someone
runs the provider directly; these tests must remain hermetic. Sprint
9.1 H — migrated from ``google-generativeai`` patching to
``google-genai``: the new SDK exposes a ``Client`` object whose
``models.generate_content(...)`` (sync) and
``aio.models.generate_content(...)`` (async) carry the calls.

The fixture builds a fresh provider instance and patches its
``_client.models.generate_content`` so individual tests can swap
return values / side_effects without touching the SDK.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from imga_core.llm.base import LLMProviderError
from imga_core.llm.gemini import GeminiProvider


@pytest.fixture
def fake_response() -> MagicMock:
    response = MagicMock()
    response.text = (
        '{"primary": "kargo", "confidence": 0.92, '
        '"reasoning": "Kargo gecikmesi açıkça belirtilmiş."}'
    )
    return response


@pytest.fixture
def patched_provider(fake_response: MagicMock) -> Any:
    """Build a GeminiProvider whose Client + models surface is mocked.

    We bypass __init__ entirely so the real google-genai Client never
    gets constructed; tests that need to verify __init__ wiring patch
    ``google.genai.Client`` directly (see test_init_with_valid_key_*).
    """
    provider = GeminiProvider.__new__(GeminiProvider)
    provider._api_key = "test-key"
    provider._model_name = "gemini-2.5-flash"
    provider._timeout = 5.0
    client = MagicMock()
    client.models.generate_content.return_value = fake_response
    provider._client = client
    yield provider, client.models.generate_content


# --- Construction --------------------------------------------------------


def test_init_requires_api_key() -> None:
    with pytest.raises(ValueError, match="API key is required"):
        GeminiProvider(api_key="")


def test_init_with_valid_key_constructs_client() -> None:
    """Sprint 9.1 H — patch google.genai.Client at the module-level
    import path used by gemini.py (re-exported as ``_genai_module``).
    """
    with patch("imga_core.llm.gemini._genai_module") as fake_genai:
        fake_genai.Client.return_value = MagicMock()
        provider = GeminiProvider(
            api_key="test-key", model_name="gemini-2.5-flash"
        )
        # Client constructed once with the api_key + an http_options
        # carrying the timeout (kwargs may also include other defaults).
        assert fake_genai.Client.called
        kwargs = fake_genai.Client.call_args.kwargs
        assert kwargs["api_key"] == "test-key"
        assert "http_options" in kwargs
        assert provider.model_name == "gemini-2.5-flash"


# --- Classify happy path -------------------------------------------------


def test_classify_returns_structured_result(patched_provider: Any) -> None:
    provider, _ = patched_provider
    result = provider.classify(
        "Kargom gelmedi", ["kargo", "faturalama", "belirsiz"]
    )
    assert result.primary == "kargo"
    assert result.confidence == pytest.approx(0.92)
    assert "Kargo" in result.reasoning
    assert result.provider == "gemini"
    assert result.model == "gemini-2.5-flash"


def test_classify_passes_categories_into_prompt(patched_provider: Any) -> None:
    provider, generate = patched_provider
    provider.classify("test text", ["kargo", "iade"])
    kwargs = generate.call_args.kwargs
    prompt = kwargs["contents"]
    assert "- kargo" in prompt
    assert "- iade" in prompt
    assert "test text" in prompt


def test_classify_uses_structured_output_schema(patched_provider: Any) -> None:
    """Sprint 9.1 H — schema rides on ``config=GenerateContentConfig(...)``
    in the new SDK rather than the old ``generation_config={...}`` dict.
    """
    provider, generate = patched_provider
    provider.classify("kargo gelmedi", ["kargo", "belirsiz"])
    kwargs = generate.call_args.kwargs
    assert kwargs["model"] == "gemini-2.5-flash"
    config = kwargs["config"]
    assert config.response_mime_type == "application/json"
    assert config.response_schema is not None
    assert config.temperature == 0.1


# --- Validation ----------------------------------------------------------


def test_classify_rejects_empty_text(patched_provider: Any) -> None:
    provider, _ = patched_provider
    with pytest.raises(LLMProviderError, match="empty text"):
        provider.classify("", ["kargo"])


def test_classify_rejects_empty_categories(patched_provider: Any) -> None:
    provider, _ = patched_provider
    with pytest.raises(LLMProviderError, match="non-empty"):
        provider.classify("test", [])


# --- Error paths ---------------------------------------------------------


def test_classify_wraps_sdk_exceptions(patched_provider: Any) -> None:
    provider, generate = patched_provider
    generate.side_effect = Exception("network down")
    with pytest.raises(LLMProviderError, match="Gemini"):
        provider.classify("kargo gelmedi", ["kargo"])


def test_classify_raises_on_empty_response(patched_provider: Any) -> None:
    provider, generate = patched_provider
    bad_response = MagicMock()
    bad_response.text = ""
    generate.return_value = bad_response
    with pytest.raises(LLMProviderError, match="Empty response"):
        provider.classify("kargo", ["kargo"])


def test_classify_raises_on_non_json_response(patched_provider: Any) -> None:
    provider, generate = patched_provider
    bad_response = MagicMock()
    bad_response.text = "this is not json at all"
    generate.return_value = bad_response
    with pytest.raises(LLMProviderError, match="non-JSON"):
        provider.classify("kargo", ["kargo"])


def test_classify_raises_on_missing_primary(patched_provider: Any) -> None:
    provider, generate = patched_provider
    bad_response = MagicMock()
    bad_response.text = '{"confidence": 0.5, "reasoning": "x"}'
    generate.return_value = bad_response
    with pytest.raises(LLMProviderError, match="Invalid 'primary'"):
        provider.classify("kargo", ["kargo"])


def test_classify_raises_on_missing_confidence(patched_provider: Any) -> None:
    provider, generate = patched_provider
    bad_response = MagicMock()
    bad_response.text = '{"primary": "kargo", "reasoning": "x"}'
    generate.return_value = bad_response
    with pytest.raises(LLMProviderError, match="Invalid 'confidence'"):
        provider.classify("kargo", ["kargo"])


# --- Robustness ----------------------------------------------------------


def test_classify_clamps_out_of_range_confidence(patched_provider: Any) -> None:
    provider, generate = patched_provider
    weird_response = MagicMock()
    weird_response.text = (
        '{"primary": "kargo", "confidence": 1.5, "reasoning": "ok"}'
    )
    generate.return_value = weird_response
    result = provider.classify("kargo", ["kargo", "belirsiz"])
    assert result.confidence == 1.0


def test_classify_negative_confidence_clamped_to_zero(
    patched_provider: Any,
) -> None:
    provider, generate = patched_provider
    weird_response = MagicMock()
    weird_response.text = (
        '{"primary": "kargo", "confidence": -0.3, "reasoning": "ok"}'
    )
    generate.return_value = weird_response
    result = provider.classify("kargo", ["kargo", "belirsiz"])
    assert result.confidence == 0.0


def test_classify_unknown_category_coerced_to_belirsiz(
    patched_provider: Any,
) -> None:
    provider, generate = patched_provider
    weird_response = MagicMock()
    weird_response.text = (
        '{"primary": "made_up_category", "confidence": 0.8, "reasoning": "ok"}'
    )
    generate.return_value = weird_response
    result = provider.classify("test", ["kargo", "belirsiz"])
    assert result.primary == "belirsiz"


# --- Health check --------------------------------------------------------


def test_health_check_returns_true_when_responsive(
    patched_provider: Any,
) -> None:
    provider, generate = patched_provider
    pong = MagicMock()
    pong.text = "pong"
    generate.return_value = pong
    assert provider.health_check() is True


def test_health_check_returns_false_on_exception(
    patched_provider: Any,
) -> None:
    provider, generate = patched_provider
    generate.side_effect = Exception("nope")
    assert provider.health_check() is False
