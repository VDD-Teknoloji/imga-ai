"""Contract tests only: provider mocks do not establish Arabic/Urdu accuracy."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from imga_core.analyzers.base import SentimentAnalyzer
from imga_core.language_policy import has_arabic_script
from imga_core.llm.base import LLMProviderError
from imga_core.llm.key_rotation import GeminiKey
from imga_core.llm.unified_classifier import (
    GeminiUnifiedEngine,
    UnifiedBatchStats,
    UnifiedPrediction,
    _build_prompt,
)
from imga_core.pipeline import AnalysisPipeline


def engine(**kwargs: Any) -> GeminiUnifiedEngine:
    return GeminiUnifiedEngine(
        [GeminiKey(id="test", value="not-a-key", label="test", priority=1)],
        model_name="test-model",
        analysis_profile="mena",
        **kwargs,
    )


@pytest.mark.parametrize(
    "text,expected",
    [
        ("الخدمة سيئة", True),
        ("سروس خراب ہے", True),
        ("service bohat kharab hai", False),
        ("Kargo gelmedi", False),
        ("١٢٣", False),
    ],
)
def test_script_is_not_a_language_guesser(text: str, expected: bool) -> None:
    assert has_arabic_script(text) is expected


def test_prompt_preserves_original_and_long_negation() -> None:
    original = "شكرا " * 150 + "لكن الخدمة ليست جيدة"
    prompt = _build_prompt(
        [original],
        ["kargo", "belirsiz"],
        (),
        analysis_profile="mena",
        terminology="COD = cash on delivery",
    )
    assert original.strip() in prompt
    assert "COD = cash on delivery" in prompt
    assert "Urdu" in prompt and "Arabizi" in prompt


def test_prompt_rejects_silent_truncation() -> None:
    with pytest.raises(LLMProviderError):
        _build_prompt(["ا" * 6001], ["belirsiz"], (), analysis_profile="mena")


@pytest.mark.parametrize(
    "change",
    [
        {"i": True},
        {"i": 2},
        {"s": "negative"},
        {"sc": float("nan")},
        {"cc": 1.01},
        {"l": "fa"},
        {"sc": 0.8},
    ],
)
def test_strict_response_validation(
    monkeypatch: pytest.MonkeyPatch, change: dict[str, Any]
) -> None:
    model = engine()
    row = {"i": 0, "s": "NEGATIF", "sc": -0.8, "c": "kargo", "cc": 0.9, "l": "ar", **change}
    monkeypatch.setattr(model, "_generate_raw_gemini", lambda *args: json.dumps([row]))
    with pytest.raises(LLMProviderError):
        model._generate_sync("key", "prompt", ["الخدمة سيئة"], ["kargo"], UnifiedBatchStats())


@pytest.mark.parametrize(
    "rows", [[], [{"i": 0, "s": "NEGATIF", "sc": -0.8, "c": "kargo", "cc": 0.9, "l": "ar"}] * 2]
)
def test_missing_duplicate_rows_rejected(
    monkeypatch: pytest.MonkeyPatch, rows: list[dict[str, Any]]
) -> None:
    model = engine()
    monkeypatch.setattr(model, "_generate_raw_gemini", lambda *args: json.dumps(rows))
    with pytest.raises(LLMProviderError):
        model._generate_sync(
            "key", "prompt", ["الخدمة سيئة", "سروس خراب ہے"], ["kargo"], UnifiedBatchStats()
        )


def test_unknown_language_abstains(monkeypatch: pytest.MonkeyPatch) -> None:
    model = engine()
    monkeypatch.setattr(
        model,
        "_generate_raw_gemini",
        lambda *args: json.dumps(
            [{"i": 0, "s": "NEGATIF", "sc": -0.8, "c": "kargo", "cc": 0.99, "l": "und"}]
        ),
    )
    result = model._generate_sync("key", "prompt", ["unknown"], ["kargo"], UnifiedBatchStats())
    assert result[0].category_confidence <= 0.3


class NeverAnalyze(SentimentAnalyzer):
    def analyze_batch(self, texts: list[str]) -> list[Any]:
        raise AssertionError("Turkish BERT must not run")


@pytest.mark.asyncio
async def test_mena_skips_turkish_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    model = engine()

    async def classify(
        *args: Any, **kwargs: Any
    ) -> tuple[list[UnifiedPrediction], UnifiedBatchStats]:
        return [
            UnifiedPrediction(
                sentiment_label="POZITIF",
                sentiment_score=0.9,
                category="kargo",
                category_confidence=0.8,
                language="ur",
            )
        ], UnifiedBatchStats()

    monkeypatch.setattr(model, "classify_unified_batch_async", classify)
    pipeline = AnalysisPipeline(analyzer=NeverAnalyze())
    result = (
        await pipeline.analyze_batch_unified_async(
            ["hırsızlık nahi hui"], engine=model, available_categories=["kargo"]
        )
    )[0]
    assert result.sentiment_label == "POZITIF"
    assert result.analysis_language == "ur" and result.analysis_profile == "mena"
    assert result.overrides_applied == []


@pytest.mark.asyncio
async def test_3000_rows_bounded_across_parallel_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    model = engine(concurrency=10)
    active = peak = calls = 0

    async def call(chunk: list[str], *args: Any) -> dict[int, UnifiedPrediction]:
        nonlocal active, peak, calls
        active += 1
        peak = max(peak, active)
        calls += 1
        assert len(chunk) <= 10
        await asyncio.sleep(0.001)
        active -= 1
        return {
            i: UnifiedPrediction(
                sentiment_label="NEGATIF",
                sentiment_score=-0.8,
                category="kargo",
                category_confidence=0.9,
                language="ar",
            )
            for i in range(len(chunk))
        }

    monkeypatch.setattr(model, "_call_with_rotation", call)
    batches = await asyncio.gather(
        *(
            model.classify_unified_batch_async(
                ["الخدمة سيئة"] * 100, available_categories=["kargo"]
            )
            for _ in range(30)
        )
    )
    assert sum(len(result) for result, _ in batches) == 3000
    assert calls == 300 and peak <= 3 and active == 0
