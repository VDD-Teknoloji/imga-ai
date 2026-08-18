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

2026-08-18 (WS3 RAG) — tenant'ın KENDİ Gemini anahtarı yoksa (``keys``
boş), platform-seviyesi ``IMGA_EMBEDDING_FALLBACK_KEY`` ortam
değişkeni doluysa onunla embed edilir. Bilinçli tercih: fallback
SADECE ``keys`` boşken devreye girer (tenant'ın kendi anahtarları
varsa ama hepsi düşüyorsa fallback denenmez — o durum "geçici API
hatası" olarak ele alınır, "hiç anahtar yok" durumundan farklı).
AYNI MODEL ZORUNLU (gemini-embedding-001/768) — farklı bir embedding
modeli farklı bir vektör uzayı üretir ve mevcut HNSW indeksiyle
(``review_corrections.embedding``) karşılaştırılamaz hale gelir;
bu yüzden OpenRouter gibi alternatif sağlayıcılar burada
DEĞERLENDİRİLMEDİ (bkz. docs/analysis/2026-08-18-rag-mimari.md).
Fallback anahtarı yoksa davranış DEĞİŞMEZ — eski sessiz-NULL yolu
korunur.
"""

from __future__ import annotations

import asyncio
import logging
import os

from imga_core.llm.key_rotation import GeminiKey

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIM = 768
_TIMEOUT_SECONDS = 10.0
_FALLBACK_KEY_ENV = "IMGA_EMBEDDING_FALLBACK_KEY"


def _fallback_keys() -> list[GeminiKey]:
    """Platform-seviyesi yedek anahtar — yalnız tenant'ın hiç Gemini
    anahtarı yokken kullanılır (bkz. modül docstring'i)."""
    value = os.environ.get(_FALLBACK_KEY_ENV)
    if not value:
        return []
    return [
        GeminiKey(
            id="platform-fallback",
            value=value,
            label="platform-fallback",
            priority=9999,
        )
    ]


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
    None (çağıran NULL embedding ile devam eder). ``keys`` boşsa ve
    platform fallback anahtarı tanımlıysa onunla dener (bkz. modül
    docstring'i)."""
    if not texts:
        return None
    effective_keys = keys if keys else _fallback_keys()
    if not effective_keys:
        return None
    for key in effective_keys:
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
        except Exception as exc:
            logger.warning(
                "embedding call failed (key=%s): %s", key.label, exc
            )
    return None


async def embed_text(text: str, keys: list[GeminiKey]) -> list[float] | None:
    vectors = await embed_texts([text], keys)
    return vectors[0] if vectors else None
