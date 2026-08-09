"""reviews.review_date — yorumun kendi tarihi (analiz ekseni)

Revision ID: 0038
Revises: 0037
Create Date: 2026-08-09 00:00:00

Bir müşteri 3 aylık yorum arşivini tek yüklemede gönderdiğinde
``created_at`` / ``analyzed_at`` hepsini aynı güne yığıyordu; aylık
trendler tek bir dikey çubuğa çöküyordu. ``review_date`` yorumun
kendi tarihidir — yükleme dosyasındaki ``tarih`` kolonundan gelir,
kolon yoksa/parse edilemezse ingest anına düşer. Tüm analitik
pencereleri/bucket'ları bu kolona taşındı; ``created_at`` "ne zaman
bize girdi" anlamını korur (dedup penceresi, "son veri girişi").

Backfill mevcut satırları ``created_at``e eşitler — eski davranışla
birebir aynı sonuç üretir, yani migration analitik geçmişini
değiştirmez.

``server_default = now()`` bilerek bırakıldı: kolonun sözleşmesi
zaten "verilmediyse ingest anı". Uygulamadaki üç insert noktası
değeri açıkça yazar; default yalnızca güvenlik ağıdır.

Backfill ``app.current_tenant_id`` set etmeden tüm kurumların
satırlarına dokunur: ``reviews`` RLS+FORCE altında (bkz. 0008) ama
migration'ı çalıştıran ``imga_owner`` superuser'dır (bkz.
``imga-db/sql/01-init-roles.sh``) ve superuser RLS'i her koşulda
atlar — FORCE yalnızca superuser/BYPASSRLS olmayan tablo sahibini
bağlar.

NPS aylık trendi de ``review_date``e geçtiği için 0015'teki kısmi
indeks (``ix_reviews_tenant_nps_created``) artık yanlış kolonda —
aynı WHERE ile ``review_date`` üzerinde yeniden kuruluyor.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "0038"
down_revision: str | Sequence[str] | None = "0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "reviews",
        sa.Column("review_date", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("UPDATE reviews SET review_date = created_at")
    op.alter_column(
        "reviews",
        "review_date",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )

    op.create_index(
        "ix_reviews_tenant_review_date",
        "reviews",
        ["tenant_id", "review_date"],
    )
    op.create_index(
        "ix_reviews_tenant_nps_review_date",
        "reviews",
        ["tenant_id", "review_date"],
        postgresql_where=sa.text("nps_score IS NOT NULL"),
    )
    op.drop_index("ix_reviews_tenant_nps_created", table_name="reviews")


def downgrade() -> None:
    op.create_index(
        "ix_reviews_tenant_nps_created",
        "reviews",
        ["tenant_id", "created_at"],
        postgresql_where=sa.text("nps_score IS NOT NULL"),
    )
    op.drop_index("ix_reviews_tenant_nps_review_date", table_name="reviews")
    op.drop_index("ix_reviews_tenant_review_date", table_name="reviews")
    op.drop_column("reviews", "review_date")
