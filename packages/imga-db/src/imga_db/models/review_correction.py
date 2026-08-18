"""Kullanıcı düzeltmesi — düzeltme-geri-besleme zincirinin kaynağı.

Sprint 11.0. Yanlış model kararı düzeltildiğinde buraya bir satır
düşer; üç tüketicisi var:

  1. Birebir override — aynı ``text_hash``'li yeni yorum, son
     düzeltmenin kararını alır (pipeline'a girmeden).
  2. Few-shot — tenant'ın güncel düzeltmeleri Gemini birleşik
     sınıflandırma prompt'una örnek olarak enjekte edilir.
  3. RAG — ``embedding`` üzerinden anlamsal komşu düzeltmeler
     bulunur (pgvector cosine); few-shot seçimini isabetli kılar.

``review_text`` bilinçli denormalize: review soft-delete olsa da
düzeltme örneği yaşar ve few-shot derlemek JOIN gerektirmez.
``embedding`` best-effort — API erişilemezse NULL kalır; HNSW
indeksi NULL'ları zaten içermez, katman 1-2 etkilenmez.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import CHAR, DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from imga_db.base import Base

EMBEDDING_DIM = 768


class ReviewCorrection(Base):
    __tablename__ = "review_corrections"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    review_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("reviews.id", ondelete="CASCADE"),
        nullable=False,
    )
    # reviews.text_hash ile aynı üretim (normalize_turkish + SHA-256);
    # birebir override lookup anahtarı.
    text_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    review_text: Mapped[str] = mapped_column(Text(), nullable=False)

    old_sentiment_label: Mapped[str] = mapped_column(String(8), nullable=False)
    new_sentiment_label: Mapped[str] = mapped_column(String(8), nullable=False)
    old_category: Mapped[str] = mapped_column(String(64), nullable=False)
    new_category: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text(), nullable=True)

    # 2026-08-18 (migration 0042) — CorrectReviewRequest genişlemesi:
    # skor/deneyim/perspektif düzeltmeleri de kaydedilir ki birebir +
    # anlamsal override (patch_analysis_with_decision, Dalga 2 kapsamı)
    # tekrar karşılaşmada bu değerleri UYGULAYABİLSİN — yoksa yalnız
    # etiket düzeltmesi tekrar karşılaşmada SCORE_FOR_LABEL fallback'ine
    # düşer ve operatörün girdiği skor kaybolur. Üçü de opsiyonel; boş
    # bırakılan alan eski davranışı (fallback) korur.
    new_score: Mapped[float | None] = mapped_column(Float(), nullable=True)
    new_experience: Mapped[str | None] = mapped_column(String(16), nullable=True)
    new_perspective: Mapped[str | None] = mapped_column(Text(), nullable=True)

    corrected_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # gemini-embedding-001, output_dimensionality=768. NULL = henüz
    # embed edilmedi (API hatası ya da backfill bekliyor).
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIM), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
