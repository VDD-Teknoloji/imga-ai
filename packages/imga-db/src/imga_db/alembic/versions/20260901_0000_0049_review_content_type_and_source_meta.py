"""reviews.content_type ('question') + reviews.source_meta

Revision ID: 0049
Revises: 0048
Create Date: 2026-09-01 00:00:00

İki bağımsız, nullable kolon — Twitter'dan Çek dalgasının (0047/0048)
devamı, "soru" içeriğin ve kaynak-özel sayaçların analitikten
düşürülmeden görünür olması için:

  1. ``content_type`` — metnin YAPISAL biçimi ('question' | NULL).
     Deterministik Türkçe heuristik (``imga_api.services.data_quality.
     detect_content_type``, LLM'e hiç dokunmaz) yazar. Bilinçli olarak
     genişletilebilir enum — ``experience_type``/0041 deseniyle birebir
     aynı: tek bir CHECK değeri bugün, ileride 'sikayet'/'talep' gibi
     başka biçimler eklenebilir.

     KRİTİK — content_type ``quality_flag`` DEĞİLDİR, bu YENİ bir kolon
     olmasının nedeni de bu: bir NEGATİF şikayetin soru biçiminde
     yazılması ("Kargom nerede, ilgilenir misiniz?") hâlâ gerçek bir
     şikayettir ve analitikte KALMALIDIR. ``quality_flag`` dolu
     satırlar heatmap/rapor/trend'den VARSAYILAN olarak dışlanır
     (``include_flagged=False`` — bkz. migration 0042); content_type'ı
     quality_flag'in bir değeri yapmak böyle bir soru-şikayeti sessizce
     gömerdi (2026-08-18 adversarial incelemenin FX1 sınıfı riskiyle
     birebir aynı hata deseni). İkisi ORTOGONAL: aynı satırda ikisi de
     dolu olabilir (nadir — biri kalite bayrağı, diğeri biçim), ya da
     yalnız biri, ya da hiçbiri.

     BACKFILL YOK — 0041'deki ``experience_type`` gerekçesiyle aynı:
     eski satırlar NULL kalır, gerçek değeri yeniden analizde
     (``POST /tenants/me/reviews/reanalyze-all``) alır.

  2. ``source_meta`` — açık uçlu kaynak-özel metadata (JSONB). İlk
     tüketici: tweet etkileşim sayaçları (``like_count``/
     ``retweet_count``/``reply_count``/``view_count`` —
     ``file_parser._META_INT_HEADERS`` ile otomatik tanınan CSV
     kolonlarından ya da twitterapi.io'dan gelir). Şema sabitlenmez;
     ileride başka kaynak türleri (pazar yeri puanı vb.) aynı kolona
     farklı anahtarlarla yazabilir.

Nullable, RLS'e dokunmaz (mevcut tablo, 0047 notuyla aynı).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers
revision: str = "0049"
down_revision: str | Sequence[str] | None = "0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "reviews",
        sa.Column("content_type", sa.Text(), nullable=True),
    )
    op.create_check_constraint(
        "ck_reviews_content_type",
        "reviews",
        "content_type IS NULL OR content_type IN ('question')",
    )
    # Kalite raporu/analitik desenleriyle aynı: dominant NULL satırlar
    # indekse girmez, yalnız dolu değerler taranır.
    op.create_index(
        "ix_reviews_tenant_content_type",
        "reviews",
        ["tenant_id", "content_type"],
        postgresql_where=sa.text("content_type IS NOT NULL"),
    )

    op.add_column(
        "reviews",
        sa.Column("source_meta", JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("reviews", "source_meta")

    op.drop_index("ix_reviews_tenant_content_type", table_name="reviews")
    op.drop_constraint("ck_reviews_content_type", "reviews", type_="check")
    op.drop_column("reviews", "content_type")
