"""Sprint 11.0 — kullanıcı düzeltmesi servisi.

Yanlış model kararının düzeltilmesi tek transaction'da iki iş yapar:

  1. ``reviews`` satırı güncellenir — dashboard/analitik ANINDA yeni
     kararı görür. Skor, KB sabitleriyle eşlenir (±0.9 / 0.0) ve
     ``overrides_applied``'e ``user_correction`` izi eklenir; audit
     zinciri "bu kararı insan verdi" diye okunur.
  2. ``review_corrections``'a kayıt düşer — birebir override,
     few-shot ve RAG katmanlarının kaynağı.

Embedding burada HESAPLANMAZ — route, transaction açılmadan önce
best-effort embed eder ve hazır vektörü geçer (dış API beklerken
satır kilidi tutulmasın diye).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from imga_core.config import (
    KB_NEGATIVE_SCORE,
    KB_POSITIVE_SCORE,
)
from imga_db.models import Category, Review, ReviewCorrection
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

VALID_SENTIMENTS = ("POZITIF", "NEGATIF", "NÖTR")

SCORE_FOR_LABEL = {
    "POZITIF": KB_POSITIVE_SCORE,
    "NEGATIF": KB_NEGATIVE_SCORE,
    "NÖTR": 0.0,
}


class CorrectionError(Exception):
    """Doğrulama hatası — route 4xx'e çevirir."""


class CorrectionService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def correct_review(
        self,
        *,
        tenant_id: UUID,
        review_id: UUID,
        new_sentiment_label: str | None,
        new_category: str | None,
        reason: str | None,
        corrected_by_user_id: UUID | None,
        embedding: list[float] | None,
    ) -> ReviewCorrection:
        if new_sentiment_label is None and new_category is None:
            raise CorrectionError(
                "Düzeltme için en az bir alan gerekli: duygu veya kategori."
            )
        if (
            new_sentiment_label is not None
            and new_sentiment_label not in VALID_SENTIMENTS
        ):
            raise CorrectionError(
                f"Geçersiz duygu etiketi: {new_sentiment_label!r}. "
                f"Geçerli değerler: {', '.join(VALID_SENTIMENTS)}."
            )

        review = (
            await self._session.execute(
                select(Review)
                .where(Review.id == review_id)
                .where(Review.tenant_id == tenant_id)
                .where(Review.deleted_at.is_(None))
                .with_for_update()
            )
        ).scalar_one_or_none()
        if review is None:
            raise CorrectionError("Yorum bulunamadı.")

        if new_category is not None:
            await self._validate_category(tenant_id, new_category)

        old_sentiment = review.sentiment_label
        old_category = review.primary_category
        effective_sentiment = new_sentiment_label or old_sentiment
        effective_category = new_category or old_category

        if (
            effective_sentiment == old_sentiment
            and effective_category == old_category
        ):
            raise CorrectionError(
                "Düzeltme mevcut karardan farksız — değişiklik yok."
            )

        correction = ReviewCorrection(
            tenant_id=tenant_id,
            review_id=review.id,
            text_hash=review.text_hash,
            review_text=review.text,
            old_sentiment_label=old_sentiment,
            new_sentiment_label=effective_sentiment,
            old_category=old_category,
            new_category=effective_category,
            reason=(reason or "").strip() or None,
            corrected_by_user_id=corrected_by_user_id,
            embedding=embedding,
        )
        self._session.add(correction)

        # Review satırını yeni karara çek + insan-kararı izini düş.
        review.sentiment_label = effective_sentiment
        review.sentiment_score = SCORE_FOR_LABEL[effective_sentiment]
        review.primary_category = effective_category
        review.primary_confidence = 1.0
        trace: list[dict[str, Any]] = list(review.overrides_applied or [])
        trace.append(
            {
                "layer": "user_correction",
                "matched_keywords": [],
                "score": SCORE_FOR_LABEL[effective_sentiment],
                "detail": (
                    f"Kullanıcı düzeltmesi: {old_sentiment}/{old_category}"
                    f" -> {effective_sentiment}/{effective_category}"
                ),
            }
        )
        review.overrides_applied = trace

        await self._session.flush()
        return correction

    async def _validate_category(self, tenant_id: UUID, code: str) -> None:
        exists = (
            await self._session.execute(
                select(Category.id)
                .where(Category.code == code)
                .where(Category.deleted_at.is_(None))
                .where(
                    or_(
                        Category.tenant_id.is_(None),
                        Category.tenant_id == tenant_id,
                    )
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if exists is None:
            raise CorrectionError(f"Bilinmeyen kategori kodu: {code!r}.")
