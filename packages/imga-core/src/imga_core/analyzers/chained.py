"""Sprint 11.0 — sıralı fallback analyzer zinciri.

Analiz dayanıklılık zincirinin sentiment ayağı:

    Gemini unified (pipeline'da)  →  bu zincir devreye girer:
      1. RemoteHTTPSentimentAnalyzer (Modal)  — VPS'e yük yok
      2. BertSentimentAnalyzer (lazy lokal)   — son çare; model HF
         Hub'dan ilk kullanımda iner (image'a artık bake edilmiyor)

İlk başarılı analyzer kazanır; tümü düşerse son hata yükselir.
Başarısız halka loglanır — operatör hangi katmanın devre dışı
olduğunu görür.
"""

from __future__ import annotations

import logging

from imga_core.analyzers.base import AnalyzerPrediction, SentimentAnalyzer

_logger = logging.getLogger(__name__)


class ChainedSentimentAnalyzer(SentimentAnalyzer):
    def __init__(self, links: list[tuple[str, SentimentAnalyzer]]) -> None:
        if not links:
            raise ValueError("ChainedSentimentAnalyzer requires >= 1 link")
        self._links = links

    def analyze_batch(self, texts: list[str]) -> list[AnalyzerPrediction]:
        last_error: Exception | None = None
        for name, analyzer in self._links:
            try:
                return analyzer.analyze_batch(texts)
            except Exception as exc:  # noqa: BLE001 — zincirde sıradaki
                last_error = exc
                _logger.warning(
                    "sentiment analyzer '%s' failed, falling through: %s",
                    name,
                    exc,
                )
        assert last_error is not None
        raise last_error
