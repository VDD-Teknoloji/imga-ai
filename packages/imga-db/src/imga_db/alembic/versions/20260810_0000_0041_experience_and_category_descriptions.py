"""reviews.experience_type + global kategori açıklamalarının backfill'i

Revision ID: 0041
Revises: 0040
Create Date: 2026-08-10 00:00:00

İki parça, 2026-08-10 sınıflandırma kalite çalışmasının DB ayağı:

  1. ``reviews.experience_type`` — temas noktasının DİJİTAL mi
     OPERASYONEL mi olduğu. Kategoriden TÜRETİLMEZ: birleşik LLM her
     yorum için ayrı karar verir ("uygulamada kargo statüsü yanlış
     görünüyor" → kategori kargo, deneyim dijital). Frontend'deki
     ``lib/experience.ts`` kategori-eşlemesi bundan sonra yalnızca
     eski satırlar için yedek yol.

     BACKFILL YOK. Eski satırlar NULL kalır ve yeniden analizde
     (``POST /tenants/me/reviews/reanalyze-all``) gerçek değeri alır;
     kategori eşlemesiyle doldurmak modelin kararı gibi görünen ama
     olmayan bir veri üretirdi. Okuma tarafı NULL'ı SQL'de eski
     eşlemeye düşürür.

  2. ``categories.description`` backfill — kolon 0005'ten beri var ama
     boştu. Sınıflandırıcı prompt'una giden kod TANIMLARI
     ``imga_core.categories.taxonomy.CATEGORY_DESCRIPTIONS_TR``'de
     yaşıyor; global 9 satıra (tenant_id IS NULL) o metinler yazılır.
     Migration uygulama kodundan import ETMEZ (0017/0040 ile aynı
     gerekçe) — metinler literal olarak burada durur, ikisi elle
     senkron tutulur.

     Yalnız ``description IS NULL`` satırlar güncellenir; bir operatör
     tanımı elle değiştirdiyse migration onu ezmez. Downgrade de
     simetrik: yalnız hâlâ bu literal'e eşit olan satırları NULL'lar.

Backfill/DDL ``app.current_tenant_id`` set etmeden koşar: migration'ı
çalıştıran ``imga_owner`` superuser'dır ve RLS'i her koşulda atlar
(bkz. 0038 notu).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "0041"
down_revision: str | Sequence[str] | None = "0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# imga_core.categories.taxonomy.CATEGORY_DESCRIPTIONS_TR ile BİREBİR
# aynı olmalı. Migration import edemez (SQL-only bağlam), bu yüzden
# metinler burada literal duruyor.
_CATEGORY_DESCRIPTIONS_TR: tuple[tuple[str, str], ...] = (
    (
        "kargo",
        "Taşıma ve teslimatın kendisi: gecikme, kayıp, hareketsiz gönderi, "
        "yanlış/eksik teslimat, takip statüsü tutarsızlığı, gümrükte bekleme "
        "ve gümrük evrak süreci, taşıyıcı (FedEx/UPS vb.) süreçleri ve "
        "taşıyıcı bilgilendirme e-postaları, servis kapsamı soruları.",
    ),
    (
        "faturalama",
        "Ücret ve para: fiyat farkı, fatura kesimi/düzeltmesi, vergi ve "
        "gümrük ÜCRETLERİ tartışması, iade edilen paranın gecikmesi, "
        "tahsilat. (Gümrükte bekleme kargo'dur; gümrük vergisi itirazı "
        "faturalamadır.)",
    ),
    (
        "urun_kalitesi",
        "Ürünün fiziksel durumu: hasarlı, kırık, eksik parça, yanlış ürün, "
        "ambalaj kaynaklı hasar.",
    ),
    (
        "musteri_hizmetleri",
        "Destek deneyiminin KENDİSİ: cevapsızlık, geç dönüş, yanlış bilgi, "
        "ilgisizlik ya da destek ekibine övgü. Konu başka bir kategoriyse ve "
        "şikayet desteğin tutumuna değilse o kategori seçilir.",
    ),
    (
        "iade",
        "İade/değişim SÜRECİ: iade talebi, onayı, geri gönderim, değişim, "
        "reklamasyon formları. (İade parasının gecikmesi faturalama; iade "
        "kargosunun kaybolması kargo.)",
    ),
    (
        "teknik_destek",
        "Yazılım/platform arızası: site veya uygulama hatası, giriş "
        "yapamama, takip kodunun sistemde çalışmaması, entegrasyon/API, "
        "buton/ekran hatası.",
    ),
    (
        "siparis_sureci",
        "Sipariş oluşturma/işleme: sipariş verememe, yanlış kayıt, "
        "etiket/konşimento oluşturma, gönderi kaydı düzeltmeleri, evrak "
        "talepleri.",
    ),
    (
        "pazarlama",
        "Kampanya, indirim, duyuru, tanıtım içeriği ve bunlarla ilgili "
        "soru/şikayet.",
    ),
    (
        "belirsiz",
        "YALNIZCA anlamlı konu taşımayan metin (boşa yakın, bağlamsız, "
        "anlaşılamayan). Konusu olan mesaj belirsiz OLAMAZ; emin değilsen "
        "en yakın kategoriyi düşük cc ile seç.",
    ),
)


def upgrade() -> None:
    # 1. reviews.experience_type ------------------------------------------
    op.add_column(
        "reviews",
        sa.Column("experience_type", sa.String(16), nullable=True),
    )
    op.create_check_constraint(
        "ck_reviews_experience_type",
        "reviews",
        "experience_type IS NULL OR experience_type IN ('dijital', 'operasyonel')",
    )
    # Deneyim dağılımı sorgusu her zaman kurum + dolu değer üzerinden
    # gider; NULL satırlar (eski kayıtlar) SQL tarafında kategori
    # eşlemesine düştüğü için indekse girmelerine gerek yok.
    op.create_index(
        "ix_reviews_tenant_experience_type",
        "reviews",
        ["tenant_id", "experience_type"],
        postgresql_where=sa.text("experience_type IS NOT NULL"),
    )

    # 2. categories.description backfill (yalnız global satırlar) ---------
    for code, description in _CATEGORY_DESCRIPTIONS_TR:
        op.execute(
            sa.text(
                "UPDATE categories SET description = :d "
                "WHERE tenant_id IS NULL AND code = :c "
                "AND description IS NULL"
            ).bindparams(d=description, c=code)
        )


def downgrade() -> None:
    # 2. Yalnız migration'ın yazdığı metin geri alınır; operatörün
    # değiştirdiği tanım yerinde kalır.
    for code, description in _CATEGORY_DESCRIPTIONS_TR:
        op.execute(
            sa.text(
                "UPDATE categories SET description = NULL "
                "WHERE tenant_id IS NULL AND code = :c "
                "AND description = :d"
            ).bindparams(d=description, c=code)
        )

    # 1.
    op.drop_index("ix_reviews_tenant_experience_type", table_name="reviews")
    op.drop_constraint("ck_reviews_experience_type", "reviews", type_="check")
    op.drop_column("reviews", "experience_type")
