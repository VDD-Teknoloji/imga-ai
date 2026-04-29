"""Abstract analyzer interface.

Concrete implementations (BERT, dummy/test fakes) live alongside this module.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AnalyzerPrediction:
    """Per-text prediction returned by a SentimentAnalyzer."""

    label: str
    score: float


class SentimentAnalyzer(ABC):
    """Stateless contract for a sentiment-classifying backend."""

    @abstractmethod
    def analyze_batch(self, texts: list[str]) -> list[AnalyzerPrediction]:
        """Classify a batch of texts. Order of outputs must match inputs."""

    def analyze(self, text: str) -> AnalyzerPrediction:
        """Convenience single-text wrapper."""
        return self.analyze_batch([text])[0]
