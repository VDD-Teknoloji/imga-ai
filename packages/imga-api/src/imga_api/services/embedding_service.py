"""Sprint 11.0 — düzeltme-RAG embedding yardımcısı.

``gemini-embedding-001`` ile 768 boyutlu vektör üretir
(``review_corrections.embedding`` kolonuyla aynı boyut —
``output_dimensionality=768``). Tenant'ın kayıtlı Gemini key'leri
sırayla denenir; hepsi düşerse None döner — embedding her zaman
BEST-EFFORT'tur: NULL embedding'li düzeltme birebir-override ve
few-shot katmanlarında çalışmaya devam eder, yalnızca anlamsal
komşu aramasının dışında kalır (HNSW indeksi NULL içermez).

Çağıran taraf bu fonksiyonu DB transaction'ı DIŞINDA çağırmalı —
dış API beklerken satır kilidi tutulmaz.
"""

from __future__ import annotations

import asyncio
import logging

from imga_core.llm.key_rotation import GeminiKey

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIM = 768
_TIMEOUT_SECONDS = 10.0


def _embed_sync(api_key: str, texts: list[str]) -> list[list[float]]:
    from google import genai
    from google.genai import types as genai_types

    client = genai.Client(api_key=api_key)
    response = client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=texts,
        config=genai_types.EmbedContentConfig(
            output_dimensionality=EMBEDDING_DIM,
            task_type="SEMANTIC_SIMILARITY",
        ),
    )
    embeddings = response.embeddings or []
    return [list(e.values or []) for e in embeddings]


async def embed_texts(
    texts: list[str], keys: list[GeminiKey]
) -> list[list[float]] | None:
    """Metinleri embed'ler; ilk başarılı key kazanır, hepsi düşerse
    None (çağıran NULL embedding ile devam eder)."""
    if not texts or not keys:
        return None
    for key in keys:
        try:
            vectors = await asyncio.wait_for(
                asyncio.to_thread(_embed_sync, key.value, texts),
                timeout=_TIMEOUT_SECONDS,
            )
            if len(vectors) == len(texts) and all(
                len(v) == EMBEDDING_DIM for v in vectors
            ):
                return vectors
            logger.warning(
                "embedding shape mismatch (key=%s): got %d vectors",
                key.label,
                len(vectors),
            )
        except Exception as exc:  # noqa: BLE001 — best-effort: sıradaki key
            logger.warning(
                "embedding call failed (key=%s): %s", key.label, exc
            )
    return None


async def embed_text(text: str, keys: list[GeminiKey]) -> list[float] | None:
    vectors = await embed_texts([text], keys)
    return vectors[0] if vectors else None
