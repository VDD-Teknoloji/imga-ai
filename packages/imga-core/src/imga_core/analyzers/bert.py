"""HuggingFace transformers-backed Turkish BERT sentiment analyzer."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from imga_core.analyzers.base import AnalyzerPrediction, SentimentAnalyzer
from imga_core.config import (
    BERT_MAX_LENGTH,
    DEFAULT_BERT_BATCH_SIZE,
    DEFAULT_BERT_MODEL,
    LABEL_NEGATIVE,
    LABEL_NEUTRAL,
    LABEL_POSITIVE,
    LEGACY_LABEL_MAP,
)

if TYPE_CHECKING:
    from transformers.pipelines.base import Pipeline

_logger = logging.getLogger(__name__)


class BertSentimentAnalyzer(SentimentAnalyzer):
    """Turkish BERT classifier wrapper.

    Loads the HuggingFace pipeline lazily on the first analyze_batch call so
    that import-time costs are zero and the model can be mocked in tests.
    """

    def __init__(
        self,
        model_name: str = DEFAULT_BERT_MODEL,
        batch_size: int = DEFAULT_BERT_BATCH_SIZE,
        max_length: int = BERT_MAX_LENGTH,
    ) -> None:
        self.model_name = model_name
        self.batch_size = batch_size
        self.max_length = max_length
        self._pipeline: Pipeline | None = None

    def _ensure_loaded(self) -> Pipeline:
        if self._pipeline is None:
            _logger.info("Loading BERT model %s", self.model_name)
            from transformers import pipeline as hf_pipeline

            self._pipeline = hf_pipeline(  # type: ignore[call-overload]
                "sentiment-analysis",
                model=self.model_name,
                truncation=True,
                max_length=self.max_length,
            )
        return self._pipeline

    def analyze_batch(self, texts: list[str]) -> list[AnalyzerPrediction]:
        if not texts:
            return []

        pipe = self._ensure_loaded()
        clean_inputs = [t if isinstance(t, str) and t else " " for t in texts]
        raw_predictions: list[dict[str, Any]] = pipe(
            clean_inputs,
            batch_size=self.batch_size,
            truncation=True,
        )
        return [_to_prediction(raw) for raw in raw_predictions]


def _to_prediction(raw: dict[str, Any]) -> AnalyzerPrediction:
    """Convert raw HF pipeline output to canonical AnalyzerPrediction.

    Mirrors legacy/app.py:122-131:
      'positive' -> ( score, "Pozitif")
      'negative' -> (-score, "Negatif")
      anything else -> (0.0, "Nötr")
    """
    raw_label = str(raw.get("label", "")).strip()
    raw_score = float(raw.get("score", 0.0))

    canonical = LEGACY_LABEL_MAP.get(raw_label, raw_label.upper())

    if canonical == LABEL_POSITIVE:
        return AnalyzerPrediction(label=LABEL_POSITIVE, score=raw_score)
    if canonical == LABEL_NEGATIVE:
        return AnalyzerPrediction(label=LABEL_NEGATIVE, score=-raw_score)
    return AnalyzerPrediction(label=LABEL_NEUTRAL, score=0.0)
