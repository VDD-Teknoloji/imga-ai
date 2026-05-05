"""HuggingFace transformers-backed Turkish BERT sentiment analyzer."""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any

# Sprint 9.0.5-A R2 — eager module-level import of `pipeline`.
# Previous version imported lazily inside `_ensure_loaded`; under
# Sprint 9.0.5-A B3's parallel chunk path (4 worker threads each
# building a separate BertSentimentAnalyzer) the transformers
# `_LazyModule` initialisation raced — thread 1 held the init,
# threads 2-4 saw an "import name 'pipeline' not found" ImportError
# and the entire batch crashed before a single review was inserted.
# Module-level imports complete during the single-threaded module-
# load phase, so the lazy module is fully resolved before any
# worker thread touches it. The factory lock below adds a second
# layer for the actual `hf_pipeline(...)` call (in case
# transformers' model construction itself has internal races).
from transformers import pipeline as hf_pipeline

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

# Sprint 9.0.5-A R2 — module-level Lock guarding the
# `hf_pipeline(...)` factory call. Per-chunk model instances are
# still independent (each chunk gets its own Pipeline); this lock
# only serialises construction so two threads never reach
# transformers internals concurrently while warming up the same
# model. Construction runs ~once per worker process at startup —
# four serial constructions at ~2-3s each (cached) cost a handful
# of seconds and buy us safety against any internal race we don't
# know about.
_PIPELINE_FACTORY_LOCK = threading.Lock()


class BertSentimentAnalyzer(SentimentAnalyzer):
    """Turkish BERT classifier wrapper.

    Loads the HuggingFace pipeline lazily on the first analyze_batch call so
    that import-time costs are zero and the model can be mocked in tests.

    Sprint 9.0.5-A R2 — `_ensure_loaded` is concurrency-safe via the
    module-level factory lock. Multiple instances built from
    different worker threads coexist safely; each ends up with its
    own Pipeline (the per-chunk model instance pattern Sprint
    9.0.5-A B3 relies on).
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
            with _PIPELINE_FACTORY_LOCK:
                # Double-checked under the lock — another thread may
                # have populated `self._pipeline` while this thread
                # was waiting (won't happen for distinct instances,
                # but cheap defensiveness if a future refactor moves
                # to a shared instance + lock).
                if self._pipeline is None:
                    _logger.info("Loading BERT model %s", self.model_name)
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
