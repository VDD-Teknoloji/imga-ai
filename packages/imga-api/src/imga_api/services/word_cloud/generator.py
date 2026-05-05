"""WordCloudGenerator — frequency + sentiment-skew aggregation.

Sprint 8.3.9. The dashboard tab fires this on every URL-state change
so the cache TTL is long (6h, the analytical equivalent of
"yesterday's data is fine"). All work is plain Python over the
review rows the SQL filter pulled — there's no SQL aggregation
because tokenisation can't run inside Postgres without an extension.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import date
from typing import Any, Final, Literal
from uuid import UUID

from imga_db.models import Review
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.services.insights_cache import cache_get_or_compute
from imga_api.services.word_cloud.turkish_stopwords import TURKISH_STOPWORDS

_logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 6 * 3600

WordCloudSentiment = Literal["positive", "negative", "neutral", "all"]
ALLOWED_SENTIMENTS: frozenset[str] = frozenset(
    {"positive", "negative", "neutral", "all"}
)

# Wire-shape sentiment → DB label mapping. The Review row stores
# Türkçe sentiment_label (POZITIF / NEGATIF / NÖTR); the API surface
# uses lowercase English so a non-Türkçe-reading reviewer can sanity
# check the URL params.
_DB_LABEL_BY_WIRE: dict[str, str] = {
    "positive": "POZITIF",
    "negative": "NEGATIF",
    "neutral": "NÖTR",
}

# Token regex — keep Türkçe letters, drop digits and punctuation.
# ``\w`` in re.UNICODE matches unicode letters which already
# includes ığüşöçİĞÜŞÖÇ; explicit class is belt-and-braces against a
# future locale-flag toggle that drops Unicode by default.
_TOKEN_RE: Final[re.Pattern[str]] = re.compile(
    r"[a-zA-ZığüşöçİĞÜŞÖÇ]+",
)

_MIN_TOKEN_LEN = 3
_MIN_FREQUENCY = 3
# Bigrams emit at this rate so they don't dominate a 100-word cap.
# A bigram needs to be more frequent than a unigram to surface.
_BIGRAM_PENALTY = 0.7


def tokenize(text: str) -> list[str]:
    """Split ``text`` into Türkçe-aware lowercase tokens, stripping
    stopwords + numerics + length-< 3 noise. Used by both the
    generator and the test layer (so test inputs and real inputs
    travel through the same path).
    """
    if not text:
        return []
    lowered = text.lower()
    tokens = _TOKEN_RE.findall(lowered)
    return [
        t
        for t in tokens
        if len(t) >= _MIN_TOKEN_LEN
        and t not in TURKISH_STOPWORDS
        and not t.isdigit()
    ]


def bigrams_of(tokens: list[str]) -> list[str]:
    """Adjacent-pair bigrams; both halves must already be tokens."""
    return [f"{tokens[i]} {tokens[i + 1]}" for i in range(len(tokens) - 1)]


class WordCloudGenerator:
    """Stateless generator. Reads from the RLS-bound app session;
    caller binds the tenant before calling ``generate``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def generate(
        self,
        *,
        tenant_id: UUID,
        sentiment: WordCloudSentiment = "all",
        taxonomy_code: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        limit_words: int = 100,
        include_bigrams: bool = True,
    ) -> dict[str, Any]:
        if sentiment not in ALLOWED_SENTIMENTS:
            raise ValueError(
                f"sentiment must be one of {sorted(ALLOWED_SENTIMENTS)}"
            )
        if not 5 <= limit_words <= 500:
            raise ValueError("limit_words must be 5..500")

        cache_key = self._cache_key(
            tenant_id, sentiment, taxonomy_code,
            date_from, date_to, limit_words, include_bigrams,
        )

        async def _compute() -> dict[str, Any]:
            try:
                return await self._compute(
                    tenant_id=tenant_id,
                    sentiment=sentiment,
                    taxonomy_code=taxonomy_code,
                    date_from=date_from,
                    date_to=date_to,
                    limit_words=limit_words,
                    include_bigrams=include_bigrams,
                )
            except Exception:
                _logger.exception(
                    "word_cloud_generator failed",
                    extra={
                        "tenant_id": str(tenant_id),
                        "sentiment": sentiment,
                    },
                )
                raise

        return await cache_get_or_compute(
            cache_key,
            ttl_seconds=CACHE_TTL_SECONDS,
            compute=_compute,
            label="word_cloud",
        )

    async def _compute(
        self,
        *,
        tenant_id: UUID,
        sentiment: WordCloudSentiment,
        taxonomy_code: str | None,
        date_from: date | None,
        date_to: date | None,
        limit_words: int,
        include_bigrams: bool,
    ) -> dict[str, Any]:
        stmt = (
            select(Review.text, Review.sentiment_score)
            .where(Review.tenant_id == tenant_id)
            .where(Review.deleted_at.is_(None))
        )
        if sentiment != "all":
            stmt = stmt.where(
                Review.sentiment_label == _DB_LABEL_BY_WIRE[sentiment]
            )
        if taxonomy_code is not None:
            stmt = stmt.where(Review.primary_category == taxonomy_code)
        if date_from is not None:
            stmt = stmt.where(Review.created_at >= date_from)
        if date_to is not None:
            stmt = stmt.where(Review.created_at <= date_to)

        rows = (await self._session.execute(stmt)).all()
        total_reviews = len(rows)
        if total_reviews == 0:
            return {"words": [], "total_reviews_analyzed": 0}

        # Aggregate counts + sentiment skew per token. ``sentiment_skew``
        # is the average sentiment_score of the reviews each token
        # appeared in; weighted by review (one token vote per review,
        # not per occurrence) so a single review repeating a word 10x
        # doesn't dominate.
        unigram_counts: dict[str, int] = defaultdict(int)
        unigram_sentiment_sum: dict[str, float] = defaultdict(float)
        bigram_counts: dict[str, int] = defaultdict(int)
        bigram_sentiment_sum: dict[str, float] = defaultdict(float)

        for text, score in rows:
            tokens = tokenize(text or "")
            seen_unigrams: set[str] = set()
            for t in tokens:
                if t in seen_unigrams:
                    continue
                seen_unigrams.add(t)
                unigram_counts[t] += 1
                unigram_sentiment_sum[t] += float(score)
            if include_bigrams and len(tokens) >= 2:
                seen_bigrams: set[str] = set()
                for bg in bigrams_of(tokens):
                    if bg in seen_bigrams:
                        continue
                    seen_bigrams.add(bg)
                    bigram_counts[bg] += 1
                    bigram_sentiment_sum[bg] += float(score)

        words: list[dict[str, Any]] = []
        for token, count in unigram_counts.items():
            if count < _MIN_FREQUENCY:
                continue
            words.append(
                {
                    "text": token,
                    "weight": count,
                    "sentiment_skew": round(
                        unigram_sentiment_sum[token] / count, 3
                    ),
                    "is_bigram": False,
                }
            )
        if include_bigrams:
            for bg, count in bigram_counts.items():
                if count < _MIN_FREQUENCY:
                    continue
                # Apply the bigram penalty so single bigrams don't
                # outrank common unigrams of similar frequency.
                effective_weight = int(count * _BIGRAM_PENALTY)
                if effective_weight < _MIN_FREQUENCY:
                    continue
                words.append(
                    {
                        "text": bg,
                        "weight": effective_weight,
                        "sentiment_skew": round(
                            bigram_sentiment_sum[bg] / count, 3
                        ),
                        "is_bigram": True,
                    }
                )

        words.sort(key=lambda w: w["weight"], reverse=True)
        words = words[:limit_words]

        return {
            "words": words,
            "total_reviews_analyzed": total_reviews,
        }

    @staticmethod
    def _cache_key(
        tenant_id: UUID,
        sentiment: str,
        taxonomy_code: str | None,
        date_from: date | None,
        date_to: date | None,
        limit_words: int,
        include_bigrams: bool,
    ) -> str:
        df = date_from.isoformat() if date_from else "all"
        dt = date_to.isoformat() if date_to else "all"
        tax = taxonomy_code or "all"
        bg = "1" if include_bigrams else "0"
        return (
            f"wordcloud:{tenant_id}:{sentiment}:{tax}:"
            f"{df}:{dt}:{limit_words}:{bg}"
        )


__all__ = [
    "ALLOWED_SENTIMENTS",
    "CACHE_TTL_SECONDS",
    "WordCloudGenerator",
    "WordCloudSentiment",
    "bigrams_of",
    "tokenize",
]
