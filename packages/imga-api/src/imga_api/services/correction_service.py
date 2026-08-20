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

2026-08-18 (migration 0042) — üç yeni ops. alan: ``new_score``
(-1..1), ``new_experience`` ('dijital'|'operasyonel'),
``new_perspective`` (tenant'ın aktif CategoryTaxonomy kodu). Üçü de
sentiment/kategoriden BAĞIMSIZ düzeltilebilir (yalnız skor ya da
yalnız perspektif düzeltmesi geçerli bir istek). Ham (None-else-
değer) haliyle ``review_corrections``'a yazılır — böylece
``patch_analysis_with_decision`` tekrar karşılaşmada "kayıtlı değer
varsa uygula, yoksa SCORE_FOR_LABEL fallback'ine düş" sözleşmesini
kurabilir (bkz. correction_store.py).

2026-08-18 (bulgu düzeltmesi) — ``review.sentiment_score`` SADECE
``new_score`` verildiyse ya da duygu etiketi FİİLEN değiştiyse yeniden
hesaplanır; yalnız kategori/deneyim/perspektif düzeltmesi mevcut skoru
KORUR (SCORE_FOR_LABEL'e koşulsuz sıfırlamaz — bkz. ``correct_review``
içindeki ``effective_score`` yorumu). ``correct_review`` bu yüzden
``(ReviewCorrection, effective_score)`` döner: ``correction.new_score``
ham alan (None kalabilir), çağıranın gerçekten yazılan skoru
yanıtlamak için ayrıca ihtiyacı var.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from imga_core.config import (
    KB_NEGATIVE_SCORE,
    KB_POSITIVE_SCORE,
)
from imga_db.models import Category, CategoryTaxonomy, Review, ReviewCorrection
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

VALID_SENTIMENTS = ("POZITIF", "NEGATIF", "NÖTR")
VALID_EXPERIENCE_TYPES = ("dijital", "operasyonel")

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
        new_score: float | None = None,
        new_experience: str | None = None,
        new_perspective: str | None = None,
    ) -> tuple[ReviewCorrection, float]:
        if (
            new_sentiment_label is None
            and new_category is None
            and new_score is None
            and new_experience is None
            and new_perspective is None
        ):
            raise CorrectionError(
                "Düzeltme için en az bir alan gerekli: duygu, kategori, "
                "skor, deneyim türü veya perspektif."
            )
        if (
            new_sentiment_label is not None
            and new_sentiment_label not in VALID_SENTIMENTS
        ):
            raise CorrectionError(
                f"Geçersiz duygu etiketi: {new_sentiment_label!r}. "
                f"Geçerli değerler: {', '.join(VALID_SENTIMENTS)}."
            )
        if (
            new_experience is not None
            and new_experience not in VALID_EXPERIENCE_TYPES
        ):
            raise CorrectionError(
                f"Geçersiz deneyim türü: {new_experience!r}. "
                f"Geçerli değerler: {', '.join(VALID_EXPERIENCE_TYPES)}."
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
        if new_perspective is not None:
            await self._validate_perspective(tenant_id, new_perspective)

        old_sentiment = review.sentiment_label
        old_category = review.primary_category
        old_score = review.sentiment_score
        old_experience = review.experience_type
        old_perspective = review.company_perspective_code
        effective_sentiment = new_sentiment_label or old_sentiment
        effective_category = new_category or old_category
        # 2026-08-18 (bulgu) — skor SADECE iki durumda yeniden
        # hesaplanır: (a) new_score verildiyse AYNEN kullanılır; (b)
        # duygu etiketi FİİLEN değiştiyse (yeni etiket eskisinden
        # farklı) SCORE_FOR_LABEL'e sıfırlanır. İkisi de değilse
        # (yalnız kategori/deneyim/perspektif düzeltmesi, ya da etiket
        # aynı değerle "yeniden onaylandıysa") mevcut skor KORUNUR.
        # Eskiden new_score None olduğunda effective_sentiment (etiket
        # değişmese bile) SCORE_FOR_LABEL'e düşüyordu — yalnız kategori
        # düzeltmesi önceden ince ayarlı bir skoru (ör. -0.35) KB
        # sabitine (-0.9) sıçratıp kriz eşiğini yanlışlıkla aşırıyordu.
        if new_score is not None:
            effective_score = new_score
        elif new_sentiment_label is not None and new_sentiment_label != old_sentiment:
            effective_score = SCORE_FOR_LABEL[effective_sentiment]
        else:
            effective_score = old_score

        # B3c — hangi alanların FİİLEN değiştiğini ayrı ayrı toplar
        # (eskiden tek bir OR'lu ``changed`` booleanıydı); Karar
        # Geçmişi'nin ``changed_fields`` payload'u bunu birebir okur
        # (tenant_profile.py:258'deki ``sorted(payload.keys())``
        # deseniyle aynı ruh — burada anahtar isimleri sabit olduğundan
        # elle listelenir).
        changed_fields: list[str] = []
        if effective_sentiment != old_sentiment:
            changed_fields.append("sentiment_label")
        if effective_category != old_category:
            changed_fields.append("primary_category")
        if new_score is not None and new_score != old_score:
            changed_fields.append("sentiment_score")
        if new_experience is not None and new_experience != old_experience:
            changed_fields.append("experience_type")
        if new_perspective is not None and new_perspective != old_perspective:
            changed_fields.append("company_perspective_code")
        if not changed_fields:
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
            new_score=new_score,
            new_experience=new_experience,
            new_perspective=new_perspective,
        )
        self._session.add(correction)

        # Review satırını yeni karara çek + insan-kararı izini düş.
        review.sentiment_label = effective_sentiment
        review.sentiment_score = effective_score
        review.primary_category = effective_category
        review.primary_confidence = 1.0
        if new_experience is not None:
            review.experience_type = new_experience
        if new_perspective is not None:
            review.company_perspective_code = new_perspective

        detail = (
            f"Kullanıcı düzeltmesi: {old_sentiment}/{old_category}"
            f" -> {effective_sentiment}/{effective_category}"
        )
        if new_score is not None:
            detail += f", skor->{new_score:.2f}"
        if new_experience is not None:
            detail += f", deneyim->{new_experience}"
        if new_perspective is not None:
            detail += f", perspektif->{new_perspective}"

        trace: list[dict[str, Any]] = list(review.overrides_applied or [])
        trace.append(
            {
                "layer": "user_correction",
                "matched_keywords": [],
                "score": effective_score,
                "detail": detail,
            }
        )
        review.overrides_applied = trace

        await self._session.flush()

        # B3c — süper-admin denetim raporu: Karar Geçmişi'ne 'review
        # corrected' eylemi. tenant_kpi_goals.py:195'teki DecisionAudit
        # Service çağrı deseniyle aynı; çağıran (routes/tenant_reviews.
        # py's ``correct_review``) zaten açık bir ``async with app_
        # session.begin():`` içinde — bu satır o transaction'a katılır.
        # ``DECISION_REVIEW_CORRECTED`` migration 0045 ile decision_
        # audit_service.py'ye ekleniyor (SA1); henüz diskte yoksa bu
        # import başarısız olur.
        from imga_api.services.decision_audit_service import (
            DECISION_REVIEW_CORRECTED,
            DecisionAuditService,
        )

        await DecisionAuditService(self._session).record_decision(
            tenant_id=tenant_id,
            decision_type=DECISION_REVIEW_CORRECTED,
            related_entity_type="review",
            related_entity_id=review.id,
            actor_user_id=corrected_by_user_id,
            payload={
                "review_id": str(review.id),
                "changed_fields": sorted(changed_fields),
                "old_sentiment_label": old_sentiment,
                "new_sentiment_label": effective_sentiment,
                "old_score": old_score,
                "new_score": effective_score,
            },
        )

        # 2026-08-18 (bulgu) — ``correction.new_score`` kayıtlı ham
        # değerdir (None'a kalabilir); çağıran (route) skor korunduğunda
        # SCORE_FOR_LABEL fallback'ine yanlışlıkla düşmesin diye
        # GERÇEKTEN yazılan skoru da döneriz.
        return correction, effective_score

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

    async def _validate_perspective(self, tenant_id: UUID, code: str) -> None:
        exists = (
            await self._session.execute(
                select(CategoryTaxonomy.id)
                .where(CategoryTaxonomy.tenant_id == tenant_id)
                .where(CategoryTaxonomy.code == code)
                .where(CategoryTaxonomy.is_active.is_(True))
                .limit(1)
            )
        ).scalar_one_or_none()
        if exists is None:
            raise CorrectionError(f"Bilinmeyen perspektif kodu: {code!r}.")
