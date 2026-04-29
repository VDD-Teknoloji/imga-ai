"""Tests for GeminiProvider — google-generativeai SDK is mocked.

Real Gemini calls go out only when GEMINI_API_KEY is set and someone runs
the provider directly; these tests must remain hermetic. We patch
``google.generativeai.GenerativeModel`` at the import path used inside the
provider module.
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
def patched_genai(fake_response: MagicMock) -> Any:
    """Patch genai.GenerativeModel + genai.configure used inside the module."""
    with patch("imga_core.llm.gemini.GeminiProvider.__init__", lambda self, **kwargs: None):
        provider = GeminiProvider.__new__(GeminiProvider)
        provider._genai = MagicMock()
        provider._model_name = "gemini-2.5-flash"
        provider._timeout = 5.0
        model_mock = MagicMock()
        model_mock.generate_content.return_value = fake_response
        provider._model = model_mock
        yield provider, model_mock


# --- Construction --------------------------------------------------------


def test_init_requires_api_key() -> None:
    with pytest.raises(ValueError, match="API key is required"):
        GeminiProvider(api_key="")


def test_init_with_valid_key_constructs_model() -> None:
    with patch("google.generativeai.configure") as cfg, patch(
        "google.generativeai.GenerativeModel"
    ) as model_cls:
        provider = GeminiProvider(api_key="test-key", model_name="gemini-2.5-flash")
        cfg.assert_called_once_with(api_key="test-key")
        model_cls.assert_called_once_with("gemini-2.5-flash")
        assert provider.model_name == "gemini-2.5-flash"


# --- Classify happy path -------------------------------------------------


def test_classify_returns_structured_result(patched_genai: Any) -> None:
    provider, _ = patched_genai
    result = provider.classify("Kargom gelmedi", ["kargo", "faturalama", "belirsiz"])
    assert result.primary == "kargo"
    assert result.confidence == pytest.approx(0.92)
    assert "Kargo" in result.reasoning
    assert result.provider == "gemini"
    assert result.model == "gemini-2.5-flash"


def test_classify_passes_categories_into_prompt(patched_genai: Any) -> None:
    provider, model_mock = patched_genai
    provider.classify("test text", ["kargo", "iade"])
    call_args = model_mock.generate_content.call_args
    prompt = call_args[0][0]
    assert "- kargo" in prompt
    assert "- iade" in prompt
    assert "test text" in prompt


def test_classify_uses_structured_output_schema(patched_genai: Any) -> None:
    provider, model_mock = patched_genai
    provider.classify("kargo gelmedi", ["kargo", "belirsiz"])
    cfg = model_mock.generate_content.call_args.kwargs["generation_config"]
    assert cfg["response_mime_type"] == "application/json"
    assert "response_schema" in cfg
    assert cfg["temperature"] == 0.1


# --- Validation ----------------------------------------------------------


def test_classify_rejects_empty_text(patched_genai: Any) -> None:
    provider, _ = patched_genai
    with pytest.raises(LLMProviderError, match="empty text"):
        provider.classify("", ["kargo"])


def test_classify_rejects_empty_categories(patched_genai: Any) -> None:
    provider, _ = patched_genai
    with pytest.raises(LLMProviderError, match="non-empty"):
        provider.classify("test", [])


# --- Error paths ---------------------------------------------------------


def test_classify_wraps_sdk_exceptions(patched_genai: Any) -> None:
    provider, model_mock = patched_genai
    model_mock.generate_content.side_effect = Exception("network down")
    with pytest.raises(LLMProviderError, match="Gemini API call failed"):
        provider.classify("kargo gelmedi", ["kargo"])


def test_classify_raises_on_empty_response(patched_genai: Any) -> None:
    provider, model_mock = patched_genai
    bad_response = MagicMock()
    bad_response.text = ""
    model_mock.generate_content.return_value = bad_response
    with pytest.raises(LLMProviderError, match="Empty response"):
        provider.classify("kargo", ["kargo"])


def test_classify_raises_on_non_json_response(patched_genai: Any) -> None:
    provider, model_mock = patched_genai
    bad_response = MagicMock()
    bad_response.text = "this is not json at all"
    model_mock.generate_content.return_value = bad_response
    with pytest.raises(LLMProviderError, match="non-JSON"):
        provider.classify("kargo", ["kargo"])


def test_classify_raises_on_missing_primary(patched_genai: Any) -> None:
    provider, model_mock = patched_genai
    bad_response = MagicMock()
    bad_response.text = '{"confidence": 0.5, "reasoning": "x"}'
    model_mock.generate_content.return_value = bad_response
    with pytest.raises(LLMProviderError, match="Invalid 'primary'"):
        provider.classify("kargo", ["kargo"])


def test_classify_raises_on_missing_confidence(patched_genai: Any) -> None:
    provider, model_mock = patched_genai
    bad_response = MagicMock()
    bad_response.text = '{"primary": "kargo", "reasoning": "x"}'
    model_mock.generate_content.return_value = bad_response
    with pytest.raises(LLMProviderError, match="Invalid 'confidence'"):
        provider.classify("kargo", ["kargo"])


# --- Robustness ----------------------------------------------------------


def test_classify_clamps_out_of_range_confidence(patched_genai: Any) -> None:
    provider, model_mock = patched_genai
    weird_response = MagicMock()
    weird_response.text = (
        '{"primary": "kargo", "confidence": 1.5, "reasoning": "ok"}'
    )
    model_mock.generate_content.return_value = weird_response
    result = provider.classify("kargo", ["kargo", "belirsiz"])
    assert result.confidence == 1.0


def test_classify_negative_confidence_clamped_to_zero(patched_genai: Any) -> None:
    provider, model_mock = patched_genai
    weird_response = MagicMock()
    weird_response.text = (
        '{"primary": "kargo", "confidence": -0.3, "reasoning": "ok"}'
    )
    model_mock.generate_content.return_value = weird_response
    result = provider.classify("kargo", ["kargo", "belirsiz"])
    assert result.confidence == 0.0


def test_classify_unknown_category_coerced_to_belirsiz(patched_genai: Any) -> None:
    provider, model_mock = patched_genai
    weird_response = MagicMock()
    weird_response.text = (
        '{"primary": "made_up_category", "confidence": 0.8, "reasoning": "ok"}'
    )
    model_mock.generate_content.return_value = weird_response
    result = provider.classify("test", ["kargo", "belirsiz"])
    assert result.primary == "belirsiz"


# --- Health check --------------------------------------------------------


def test_health_check_returns_true_when_responsive(patched_genai: Any) -> None:
    provider, model_mock = patched_genai
    pong = MagicMock()
    pong.text = "pong"
    model_mock.generate_content.return_value = pong
    assert provider.health_check() is True


def test_health_check_returns_false_on_exception(patched_genai: Any) -> None:
    provider, model_mock = patched_genai
    model_mock.generate_content.side_effect = Exception("nope")
    assert provider.health_check() is False
