"""RootCauseAnalysis model — alt kategori bazlı kök neden analizi.

Sprint 13.1. Hiyerarşik kategori drill-down'ın üçüncü seviyesi:
(ana kategori → alt kategori → kök neden). Her satır bir
(kurum, ana kategori, alt kategori, tarih penceresi) dörtlüsü için
ÜRETİLMİŞ tek bir LLM çıktısını saklar; aynı dörtlü için tekrar
üretim yeni satır açar, okuma tarafı en yenisini alır (SWOT'un
``strategic_reports`` deseni — sürüm geçmişi denetim için durur).

``perspective_code`` alt kategori kodudur; NULL perspektifli
yorumların kovası için ``__unmatched__`` sentinel'i saklanır (aynı
sentinel /reviews filtre sözleşmesinde de kullanılıyor).

SAYIM UYARISI: bu tablo yalnızca üretilmiş metni saklar. Drill-down
sayımları her zaman ``reviews`` kolonlarından hesaplanır — tarihsel
perspektif kodları ana kategoriden bağımsız atandığı için
taksonominin ``primary_category_code`` eşlemesi üzerinden sayım
almak grafik ile tıklama sonucunu birbirinden ayırır.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from imga_db.base import Base


class RootCauseAnalysis(Base):
    __tablename__ = "root_cause_analyses"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    primary_category_code: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    perspective_code: Mapped[str] = mapped_column(String(64), nullable=False)
    date_from: Mapped[date | None] = mapped_column(Date(), nullable=True)
    date_to: Mapped[date | None] = mapped_column(Date(), nullable=True)
    review_count: Mapped[int] = mapped_column(Integer(), nullable=False)
    model_provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB(), nullable=False)
    generated_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
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
