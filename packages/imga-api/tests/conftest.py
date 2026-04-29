"""Shared fixtures: FastAPI TestClient with the BERT pipeline replaced by a stub."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from imga_core import (
    AnalysisPipeline,
    AnalyzerPrediction,
    KeywordCategoryClassifier,
    SentimentAnalyzer,
)

from imga_api.dependencies import get_classifier, get_pipeline, get_settings
from imga_api.main import app
from imga_api.settings import Settings


class StubAnalyzer(SentimentAnalyzer):
    """Deterministic analyzer: positive on 'iyi'/'güzel', negative on 'kötü', else neutral."""

    def __init__(self) -> None:
        self.calls = 0

    def analyze_batch(self, texts: list[str]) -> list[AnalyzerPrediction]:
        self.calls += 1
        out: list[AnalyzerPrediction] = []
        for t in texts:
            low = t.lower()
            if "iyi" in low or "güzel" in low:
                out.append(AnalyzerPrediction(label="POZITIF", score=0.85))
            elif "kötü" in low:
                out.append(AnalyzerPrediction(label="NEGATIF", score=-0.7))
            else:
                out.append(AnalyzerPrediction(label="NÖTR", score=0.0))
        return out


@pytest.fixture
def stub_classifier() -> KeywordCategoryClassifier:
    """Real keyword classifier — no LLM, fully deterministic for tests."""
    return KeywordCategoryClassifier()


@pytest.fixture
def stub_pipeline(stub_classifier: KeywordCategoryClassifier) -> AnalysisPipeline:
    return AnalysisPipeline(
        analyzer=StubAnalyzer(),
        classifier=stub_classifier,
    )


@pytest.fixture
def client(
    stub_pipeline: AnalysisPipeline,
    stub_classifier: KeywordCategoryClassifier,
) -> Iterator[TestClient]:
    """TestClient with dependencies overridden — lifespan not triggered."""
    settings = Settings()  # defaults, no env reads
    app.dependency_overrides[get_pipeline] = lambda: stub_pipeline
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_classifier] = lambda: stub_classifier
    try:
        c = TestClient(app)
        yield c
    finally:
        app.dependency_overrides.clear()
