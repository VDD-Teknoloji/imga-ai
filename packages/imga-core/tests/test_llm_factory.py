"""Tests for the env-driven LLM provider factory."""

from __future__ import annotations

import pytest

from imga_core.llm import LLMProvider, create_llm_provider


def test_factory_returns_none_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("IMGA_LLM_FALLBACK_ENABLED", raising=False)
    assert create_llm_provider() is None


def test_factory_returns_none_when_explicitly_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IMGA_LLM_FALLBACK_ENABLED", "false")
    monkeypatch.setenv("GEMINI_API_KEY", "should-not-matter")
    assert create_llm_provider() is None


def test_factory_returns_none_when_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IMGA_LLM_FALLBACK_ENABLED", "true")
    monkeypatch.setenv("IMGA_LLM_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert create_llm_provider() is None


def test_factory_returns_none_when_key_is_blank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IMGA_LLM_FALLBACK_ENABLED", "true")
    monkeypatch.setenv("IMGA_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "   ")
    assert create_llm_provider() is None


def test_factory_creates_gemini_with_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IMGA_LLM_FALLBACK_ENABLED", "true")
    monkeypatch.setenv("IMGA_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    provider = create_llm_provider()
    assert provider is not None
    assert isinstance(provider, LLMProvider)
    assert provider.__class__.__name__ == "GeminiProvider"


def test_factory_respects_custom_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IMGA_LLM_FALLBACK_ENABLED", "true")
    monkeypatch.setenv("IMGA_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("IMGA_GEMINI_MODEL", "gemini-2.0-pro")

    provider = create_llm_provider()
    assert provider is not None
    assert provider.model_name == "gemini-2.0-pro"  # type: ignore[attr-defined]


def test_factory_raises_for_claude(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IMGA_LLM_FALLBACK_ENABLED", "true")
    monkeypatch.setenv("IMGA_LLM_PROVIDER", "claude")
    with pytest.raises(NotImplementedError, match="Claude"):
        create_llm_provider()


def test_factory_raises_for_unknown_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IMGA_LLM_FALLBACK_ENABLED", "true")
    monkeypatch.setenv("IMGA_LLM_PROVIDER", "openai")
    with pytest.raises(ValueError, match="Unknown IMGA_LLM_PROVIDER"):
        create_llm_provider()
