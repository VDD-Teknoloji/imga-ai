"""hiyerarşik kategori drill-down + kök neden analizi

Revision ID: 0040
Revises: 0039
Create Date: 2026-08-09 00:00:00

Üç parça, tek iş sorusunun üç seviyesi:

  1. ``category_taxonomies.primary_category_code`` — kurum-perspektifi
     alt kategorisinin bağlı olduğu ANA kategori kodu
     (``reviews.primary_category`` ile aynı global kod uzayı).
     ``parent_code`` ile karıştırılmamalı: o aynı kurum içindeki
     başka bir taksonomi satırını gösteren kendine-referans.

     SAYIM UYARISI: bu kolon yalnızca (a) sınıflandırıcı prompt'unu
     ana kategori başına gruplamak ve (b) UI'da alt kategorileri
     ana kategori altında toplamak içindir. Drill-down SAYIMLARI
     her zaman ``reviews`` kolonlarından gelir
     (``WHERE primary_category = :x GROUP BY company_perspective_code``);
     tarihsel perspektif kodları ana kategoriden BAĞIMSIZ bir
     keyword sezgiseliyle atandığı için taksonomi eşlemesi üzerinden
     sayım almak grafikteki sayı ile tıklama sonucundaki liste
     sayısını birbirinden ayırırdı.

     Backfill: platform varsayılanı 21 satırlık seed'in kodları TÜM
     kurumlarda eşlenir (yalnız NULL olanlar — bir kurum eşlemeyi
     elle değiştirdiyse migration onu ezmez). Kuruma özel satırlar
     NULL kalır; /settings/taxonomies ekranından eşlenebilir.

  2. ``root_cause_analyses`` — (kurum, ana kategori, alt kategori,
     tarih penceresi) için üretilen LLM kök neden çıktısı. Her üretim
     yeni satır açar; okuma tarafı en yenisini alır (SWOT'un
     ``strategic_reports`` deseni). RLS ENABLE+FORCE +
     ``tenant_isolation`` (0006/0026/0039 konvansiyonu).

  3. ``ck_llm_call_audit_call_type`` — kök neden çağrıları da denetim
     tablosuna düşsün diye ``'root_cause'`` eklenir. Downgrade önce
     o satırları siler, yoksa eski kısıt mevcut satırlarda doğrulama
     hatası verir.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

# revision identifiers
revision: str = "0040"
down_revision: str | Sequence[str] | None = "0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Kod -> ana kategori. imga_db.seeds.default_company_taxonomy ile
# birebir aynı olmalı; migration SQL-only bağlamda koştuğu için
# uygulama kodundan import etmez (0017 ile aynı gerekçe).
_SEED_PRIMARY_CATEGORY: tuple[tuple[str, str], ...] = (
    ("shipment_not_arrived", "kargo"),
    ("broken_damaged", "urun_kalitesi"),
    ("poor_packaging", "kargo"),
    ("wrong_or_missing_item", "siparis_sureci"),
    ("incomplete_set", "siparis_sureci"),
    ("product_quality_material", "urun_kalitesi"),
    ("refund_not_received", "iade"),
    ("campaign_issues", "pazarlama"),
    ("ebebek_money_transfer", "faturalama"),
    ("order_status_wrong", "siparis_sureci"),
    ("cancel_request", "siparis_sureci"),
    ("address_change", "kargo"),
    ("store_return_for_online", "iade"),
    ("return_status_inquiry", "iade"),
    ("how_to_return", "iade"),
    ("return_period_exceeded", "iade"),
    ("account_membership", "teknik_destek"),
    ("invoice_request", "faturalama"),
    ("store_issues", "musteri_hizmetleri"),
    ("payment_and_campaign_issues", "faturalama"),
    ("general_other", "musteri_hizmetleri"),
)

_OLD_CALL_TYPES = (
    "'classification', 'briefing', 'strategic_report', "
    "'action_extraction', 'okr'"
)
_NEW_CALL_TYPES = _OLD_CALL_TYPES + ", 'root_cause'"


def upgrade() -> None:
    # 1. category_taxonomies.primary_category_code ------------------------
    op.add_column(
        "category_taxonomies",
        sa.Column("primary_category_code", sa.String(64), nullable=True),
    )
    for code, primary in _SEED_PRIMARY_CATEGORY:
        op.execute(
            sa.text(
                "UPDATE category_taxonomies SET primary_category_code = :p "
                "WHERE code = :c AND primary_category_code IS NULL"
            ).bindparams(p=primary, c=code)
        )
    # Drill-down UI ana kategoriye göre alt kategori listeler; sınıflandırıcı
    # prompt'u da aynı erişimi kurum başına yapar.
    op.create_index(
        "ix_category_taxonomies_tenant_primary_category",
        "category_taxonomies",
        ["tenant_id", "primary_category_code"],
    )

    # 2. root_cause_analyses ---------------------------------------------
    op.create_table(
        "root_cause_analyses",
        sa.Column(
            "id",
            PG_UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("primary_category_code", sa.String(64), nullable=False),
        sa.Column("perspective_code", sa.String(64), nullable=False),
        sa.Column("date_from", sa.Date(), nullable=True),
        sa.Column("date_to", sa.Date(), nullable=True),
        sa.Column("review_count", sa.Integer(), nullable=False),
        sa.Column("model_provider", sa.String(32), nullable=False),
        sa.Column("model_name", sa.String(128), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column(
            "generated_by_user_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "review_count >= 0", name="ck_root_cause_analyses_count_non_negative"
        ),
    )
    # GET yolu "bu dörtlü için EN YENİ satır"ı okur; UNIQUE yok çünkü
    # yeniden üretimler sürüm geçmişi olarak durur.
    op.create_index(
        "ix_root_cause_analyses_lookup",
        "root_cause_analyses",
        ["tenant_id", "primary_category_code", "perspective_code"],
    )
    op.execute("ALTER TABLE root_cause_analyses ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE root_cause_analyses FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON root_cause_analyses "
        "USING (tenant_id = current_setting('app.current_tenant_id')::uuid)"
    )

    # 3. llm_call_audit call_type -----------------------------------------
    op.execute(
        "ALTER TABLE llm_call_audit "
        "DROP CONSTRAINT IF EXISTS ck_llm_call_audit_call_type"
    )
    op.execute(
        "ALTER TABLE llm_call_audit ADD CONSTRAINT "
        f"ck_llm_call_audit_call_type CHECK (call_type IN ({_NEW_CALL_TYPES}))"
    )


def downgrade() -> None:
    # 3. Eski kısıt yeni değeri kabul etmez — önce o satırları temizle.
    op.execute("DELETE FROM llm_call_audit WHERE call_type = 'root_cause'")
    op.execute(
        "ALTER TABLE llm_call_audit "
        "DROP CONSTRAINT IF EXISTS ck_llm_call_audit_call_type"
    )
    op.execute(
        "ALTER TABLE llm_call_audit ADD CONSTRAINT "
        f"ck_llm_call_audit_call_type CHECK (call_type IN ({_OLD_CALL_TYPES}))"
    )

    # 2.
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON root_cause_analyses")
    op.drop_index("ix_root_cause_analyses_lookup", table_name="root_cause_analyses")
    op.drop_table("root_cause_analyses")

    # 1.
    op.drop_index(
        "ix_category_taxonomies_tenant_primary_category",
        table_name="category_taxonomies",
    )
    op.drop_column("category_taxonomies", "primary_category_code")
