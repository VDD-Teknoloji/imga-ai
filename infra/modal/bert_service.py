"""imga — uzak BERT sentiment servisi (Modal).

Sprint 11.0. `savasy/bert-base-turkish-sentiment-cased` inference'ını
VPS'ten çıkarır: Modal'ın ücretsiz aylık kredisiyle ($30/ay, kart
gerekmez) serverless CPU'da koşar; istek yokken sıfıra iner (ücret
yok), istek gelince saniyeler içinde uyanır. Model ağırlıkları IMAGE
İÇİNE bake edilir — cold start'ta HF Hub indirmesi yok.

Deploy (bir defalık, geliştirici makinesinden):

    pip install modal
    modal setup                      # tarayıcıda Modal hesabı bağlar
    modal secret create imga-bert-token IMGA_BERT_TOKEN=<64-hex-random>
    modal deploy infra/modal/bert_service.py
    # Çıktıdaki URL'yi + token'ı api.env'e yaz:
    #   IMGA_REMOTE_BERT_URL=https://<workspace>--imga-bert-analyze-batch.modal.run
    #   IMGA_REMOTE_BERT_TOKEN=<aynı token>

Wire sözleşmesi (imga_core.analyzers.remote_http ile birebir):

    POST /  Body {"texts": [...]}, Bearer token
    200 {"predictions": [{"label": "POZITIF", "score": 0.91}, ...]}

Label eşlemesi packages/imga-core/src/imga_core/analyzers/bert.py
``_to_prediction`` ile AYNI tutulmalı — pozitif -> +score,
negatif -> -score, diğer -> NÖTR/0.0.
"""

from __future__ import annotations

import hmac
import os
from typing import Any

import modal
from fastapi import Header, HTTPException

MODEL_NAME = "savasy/bert-base-turkish-sentiment-cased"
MAX_LENGTH = 512
BATCH_SIZE = 128

app = modal.App("imga-bert")


def _download_model() -> None:
    """Image build adımı — ağırlıklar imaja gömülür."""
    from transformers import (
        AutoModelForSequenceClassification,
        AutoTokenizer,
    )

    AutoTokenizer.from_pretrained(MODEL_NAME)
    AutoModelForSequenceClassification.from_pretrained(MODEL_NAME)


image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "torch>=2.0,<3.0",
        extra_options="--index-url https://download.pytorch.org/whl/cpu",
    )
    .pip_install("transformers>=4.44,<5.0", "fastapi[standard]")
    .run_function(_download_model)
)


@app.cls(
    image=image,
    cpu=4.0,
    memory=3072,
    # İstek bittikten sonra konteyner 5 dk sıcak kalır — peş peşe
    # chunk'lar cold-start ödemez; sonra sıfıra iner (ücret yok).
    scaledown_window=300,
    secrets=[modal.Secret.from_name("imga-bert-token")],
)
class BertService:
    @modal.enter()
    def load(self) -> None:
        from transformers import pipeline as hf_pipeline

        self._pipeline = hf_pipeline(
            "sentiment-analysis",
            model=MODEL_NAME,
            truncation=True,
            max_length=MAX_LENGTH,
        )

    @modal.fastapi_endpoint(method="POST", label="imga-bert-analyze-batch")
    def analyze_batch(
        self,
        body: dict[str, Any],
        authorization: str = Header(default=""),
    ) -> dict[str, Any]:
        # Bearer token doğrulaması — sabit-zamanlı kıyas.
        expected = os.environ.get("IMGA_BERT_TOKEN", "")
        provided = (
            authorization[7:]
            if authorization.lower().startswith("bearer ")
            else ""
        )
        if not expected or not hmac.compare_digest(provided, expected):
            raise HTTPException(status_code=401, detail="invalid token")

        texts = body.get("texts")
        if not isinstance(texts, list) or not all(
            isinstance(t, str) for t in texts
        ):
            raise HTTPException(status_code=422, detail="texts: list[str] required")
        if len(texts) > 1000:
            raise HTTPException(status_code=413, detail="max 1000 texts per call")
        if not texts:
            return {"predictions": []}

        clean = [t if t else " " for t in texts]
        raw_predictions = self._pipeline(
            clean, batch_size=BATCH_SIZE, truncation=True
        )

        predictions = []
        for raw in raw_predictions:
            label = str(raw.get("label", "")).strip().lower()
            score = float(raw.get("score", 0.0))
            if label == "positive":
                predictions.append({"label": "POZITIF", "score": score})
            elif label == "negative":
                predictions.append({"label": "NEGATIF", "score": -score})
            else:
                predictions.append({"label": "NÖTR", "score": 0.0})
        return {"predictions": predictions}
