"""Sprint 11.0 — düzeltme deposu: pipeline'ın düzeltme-bilinçli katmanı.

İş başına (batch job / tekil analiz) tenant düzeltmelerinin hafif
bir görüntüsünü taşır; üç tüketim noktası:

  1. ``exact_lookup(text_hash)`` — birebir override. Worker, satırı
     pipeline'a sokmadan düzeltilmiş kararı uygular (eski sistemin
     KB davranışının DB-bazlı, tenant-scoped hali; restart yok).
  2. ``few_shot`` — Gemini birleşik sınıflandırma prompt'una giren
     örnekler. Seçim: en güncel N/2 + (embedding varsa) sorgu
     vektörüne anlamsal en yakın N/2 (RAG).
  3. ``nearest()`` — pgvector cosine komşu araması (HNSW indeks).

Depo SNAPSHOT'tır: job başında yüklenir; job sırasında eklenen
düzeltme bir sonraki job'da görünür (bilinçli — chunk'lar arası
tutarlılık).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from uuid import UUID

from imga_db.models import ReviewCorrection
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Few-shot bütçesi: prompt'a girecek örnek tavanı. 12 örnek ≈ 1.5-3K
# token — flash free-tier TPM (250K) içinde önemsiz, isabet için
# yeterli çeşitlilik.
FEW_SHOT_LIMIT = 12
# Anlamsal komşuluk eşiği (cosine distance, pgvector `<=>`):
# distance < 0.25 (≈ benzerlik > 0.75) few-shot adayı sayılır.
NEAREST_MAX_DISTANCE = 0.25


@dataclass(frozen=True, slots=True)
class CorrectedDecision:
    sentiment_label: str
    category: str


@dataclass(frozen=True, slots=True)
class CorrectionExample:
    text: str
    sentiment_label: str
    category: str
    reason: str | None


@dataclass(frozen=True, slots=True)
class CorrectionStore:
    tenant_id: UUID
    exact: dict[str, CorrectedDecision] = field(default_factory=dict)
    recent_examples: list[CorrectionExample] = field(default_factory=list)

    def exact_lookup(self, text_hash: str) -> CorrectedDecision | None:
        return self.exact.get(text_hash)

    @property
    def has_corrections(self) -> bool:
        return bool(self.exact)


async def load_correction_store(
    session: AsyncSession, tenant_id: UUID
) -> CorrectionStore:
    """Tenant'ın düzeltmelerini tek sorguda yükler: text_hash başına
    SON karar (birebir override sözlüğü) + en güncel örnekler
    (few-shot havuzu)."""
    rows = (
        await session.execute(
            select(
                ReviewCorrection.text_hash,
                ReviewCorrection.review_text,
                ReviewCorrection.new_sentiment_label,
                ReviewCorrection.new_category,
                ReviewCorrection.reason,
            )
            .where(ReviewCorrection.tenant_id == tenant_id)
            .order_by(ReviewCorrection.created_at.desc())
            # Birebir sözlük tüm düzeltmeleri kapsamalı; pratik tavan
            # — tenant başına 10K düzeltme sözlüğü ~2-3 MB.
            .limit(10_000)
        )
    ).all()

    exact: dict[str, CorrectedDecision] = {}
    recent: list[CorrectionExample] = []
    for text_hash, text, sentiment, category, reason in rows:
        # rows created_at DESC — ilk görülen hash en güncel karardır.
        if text_hash not in exact:
            exact[text_hash] = CorrectedDecision(
                sentiment_label=sentiment, category=category
            )
            if len(recent) < FEW_SHOT_LIMIT:
                recent.append(
                    CorrectionExample(
                        text=text,
                        sentiment_label=sentiment,
                        category=category,
                        reason=reason,
                    )
                )
    return CorrectionStore(
        tenant_id=tenant_id, exact=exact, recent_examples=recent
    )


async def nearest_corrections(
    session: AsyncSession,
    tenant_id: UUID,
    query_embedding: list[float],
    *,
    k: int = 6,
) -> list[CorrectionExample]:
    """pgvector cosine komşuları (RAG). Embedding'i NULL olan
    düzeltmeler HNSW indeksinde yoktur, kendiliğinden elenir."""
    distance = ReviewCorrection.embedding.cosine_distance(query_embedding)
    rows = (
        await session.execute(
            select(
                ReviewCorrection.review_text,
                ReviewCorrection.new_sentiment_label,
                ReviewCorrection.new_category,
                ReviewCorrection.reason,
                distance.label("distance"),
            )
            .where(ReviewCorrection.tenant_id == tenant_id)
            .where(ReviewCorrection.embedding.is_not(None))
            .order_by(distance)
            .limit(k)
        )
    ).all()
    return [
        CorrectionExample(
            text=text, sentiment_label=sentiment, category=category, reason=reason
        )
        for text, sentiment, category, reason, dist in rows
        if dist is not None and float(dist) <= NEAREST_MAX_DISTANCE
    ]


def merge_few_shot(
    recent: list[CorrectionExample],
    semantic: list[CorrectionExample],
    *,
    limit: int = FEW_SHOT_LIMIT,
) -> list[CorrectionExample]:
    """Anlamsal komşular öncelikli, kalan bütçe güncel örneklerle
    dolar; metin bazında dedup."""
    merged: list[CorrectionExample] = []
    seen: set[str] = set()
    for example in [*semantic, *recent]:
        key = example.text[:120].lower()
        if key in seen:
            continue
        seen.add(key)
        merged.append(example)
        if len(merged) >= limit:
            break
    return merged
