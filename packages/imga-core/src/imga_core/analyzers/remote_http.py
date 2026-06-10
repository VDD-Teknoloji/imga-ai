"""Sprint 11.0 — uzak BERT sentiment analyzer'ı.

BERT inference'ı sunucudan çıkarır: ``analyze_batch`` HTTP POST ile
uzak servise (Modal'daki bert_service — bkz. infra/modal/) gider.
Arayüz ``SentimentAnalyzer`` ile birebir; pipeline/worker bu sınıfın
uzak olduğunu bilmez.

Hata sözleşmesi: ağ/timeout/5xx → ``RemoteAnalyzerError`` yükselir;
çağıran zincirde bir sonraki analyzer'a düşer (lazy lokal BERT).
Retry BURADA yapılmaz — analyzer fallback zincirinin kendisi retry
politikasıdır (Modal cold-start'ı tek retry ile beklemek yerine
lokal yola düşüp işi bitirmek kullanıcı için daha hızlı).

Wire format (bert_service.py ile sözleşme):
    POST {endpoint_url}        # IMGA_REMOTE_BERT_URL tam endpoint'tir
    Headers: Authorization: Bearer {token}
    Body: {"texts": ["...", ...]}
    200: {"predictions": [{"label": "POZITIF", "score": 0.91}, ...]}
"""

from __future__ import annotations

import logging

from imga_core.analyzers.base import AnalyzerPrediction, SentimentAnalyzer
from imga_core.config import LABEL_NEGATIVE, LABEL_NEUTRAL, LABEL_POSITIVE

_logger = logging.getLogger(__name__)

_VALID_LABELS = {LABEL_POSITIVE, LABEL_NEGATIVE, LABEL_NEUTRAL}
_TIMEOUT_SECONDS = 120.0  # Modal cold-start (~30s model load) payı dahil


class RemoteAnalyzerError(Exception):
    """Uzak analyzer erişilemedi/geçersiz cevap — zincirde sıradaki."""


class RemoteHTTPSentimentAnalyzer(SentimentAnalyzer):
    def __init__(self, endpoint_url: str, token: str | None = None) -> None:
        self._url = endpoint_url
        self._token = token

    def analyze_batch(self, texts: list[str]) -> list[AnalyzerPrediction]:
        import httpx

        if not texts:
            return []
        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            response = httpx.post(
                self._url,
                json={"texts": texts},
                headers=headers,
                timeout=_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:  # noqa: BLE001 — tek tip zincir hatası
            raise RemoteAnalyzerError(
                f"remote BERT call failed: {exc}"
            ) from exc

        raw = payload.get("predictions")
        if not isinstance(raw, list) or len(raw) != len(texts):
            raise RemoteAnalyzerError(
                "remote BERT response shape mismatch "
                f"(expected {len(texts)} predictions)"
            )
        predictions: list[AnalyzerPrediction] = []
        for entry in raw:
            label = str(entry.get("label", LABEL_NEUTRAL))
            if label not in _VALID_LABELS:
                label = LABEL_NEUTRAL
            try:
                score = max(-1.0, min(1.0, float(entry.get("score", 0.0))))
            except (TypeError, ValueError):
                score = 0.0
            predictions.append(AnalyzerPrediction(label=label, score=score))
        return predictions
