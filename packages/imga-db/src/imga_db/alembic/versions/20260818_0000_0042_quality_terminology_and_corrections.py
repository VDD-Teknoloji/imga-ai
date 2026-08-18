"""veri kalitesi bayrakları + kurum terim sözlüğü + düzeltme genişletmesi

Revision ID: 0042
Revises: 0041
Create Date: 2026-08-18 00:00:00

2026-08-18 "büyük paket" çalışmasının DB ayağı (bkz.
``docs/analysis/2026-08-18-buyuk-paket-plan.md``). Tek revizyonda
sekiz bağımsız değişiklik:

  1. ``reviews.quality_flag`` — düşük kaliteli veri işareti
     ('duplicate' | 'empty' | 'informational' | 'meaningless'), NULL =
     geçerli satır. CHECK + kısmi indeks 0041'deki
     ``experience_type`` deseniyle birebir aynı.

     BACKFILL: eski satırlardan ``decision='skipped_dedup'`` olanlar
     deterministik biçimde 'duplicate' damgalanır — LLM'in yeni ``q``
     alanı yalnızca yazım-anı kararı verebilir (informational/
     meaningless), dedup kararı zaten decision kolonunda vardı ve
     geriye dönük türetilebilir. empty/informational/meaningless için
     backfill YOK: eski satırlarda bu ayrım hiç üretilmedi, yeniden
     analiz (Dalga kapanışı) gerçek değeri getirecek.

  2. ``reviews.entered_by`` — yorumu kuruma giren çalışanın adı,
     yükleme dosyasından okunur. Nullable Text; iş dilinde
     ``tenant_business_dimensions``'ın 5. boyutu (bkz. 6).

  3. ``reviews.source`` — şablondaki 'kaynak' kolonu bugüne kadar
     parse edilip düşürülüyordu; artık kalıcı. Nullable Text.

  4. ``ck_reviews_decision`` genişler — ``skipped_quality`` eklenir
     (empty içerik artık ticket köprüsüne hiç girmeden bu decision'la
     satır olarak yazılıyor). Yazım-yolu tüketicisi Dalga 2 kapsamı;
     bu migration yalnızca DB'nin değeri kabul etmesini sağlar.

  5. ``tenants.terminology`` — sektör terim sözlüğü, ``list[{term,
     note}]``. ``language_directive`` desenine paralel
     ``terminology_directive`` prompt enjeksiyonunun veri kaynağı
     (Dalga 2/3 kapsamı). Nullable JSONB, backfill yok — mevcut
     kurumlar boş sözlükle başlar.

  6. ``review_corrections`` — ``new_score`` (Float), ``new_experience``
     (CHECK IS NULL OR IN dijital/operasyonel), ``new_perspective``
     (Text). Skor/deneyim/perspektif düzeltmelerinin
     ``patch_analysis_with_decision`` tarafından tekrar uygulanabilmesi
     için (Dalga 2 kapsamı — bu migration yalnızca depolama alanı açar).

  7. ``ck_tenant_business_dimensions_key`` yeniden yaratılır —
     ``entered_by`` beşinci değer olarak kümeye eklenir (drop + create
     constraint; mevcut CHECK ``tenant_business_dimension.py:39-43``'te
     tanımlıydı).
     NOT: eğer downgrade, bu migration sonrası dimension='entered_by'
     satırı yazılmış bir DB'de çalıştırılırsa CHECK ihlaliyle patlar —
     0041/0035'teki aynı best-effort simetri kabulü geçerli.

  8. ``analyze_batch_jobs`` kalite sayaçları — ``quality_duplicate_rows``
     / ``quality_empty_rows`` / ``quality_informational_rows`` /
     ``quality_meaningless_rows`` (Integer NOT NULL server_default '0',
     0016'daki ``rows_with_nps`` deseniyle aynı) + ``quality_summary``
     (JSONB NULL — kalite raporu LLM özeti + istatistik cache'i).

Backfill/DDL ``app.current_tenant_id`` set etmeden koşar: migration'ı
çalıştıran ``imga_owner`` superuser'dır ve RLS'i her koşulda atlar
(bkz. 0038 notu). RLS policy'lerine dokunulmaz.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers
revision: str = "0042"
down_revision: str | Sequence[str] | None = "0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ORIGINAL_DECISION_VALUES = (
    "'create','skipped_belirsiz','skipped_mode',"
    "'skipped_threshold','skipped_dedup'"
)
_NEW_DECISION_VALUES = _ORIGINAL_DECISION_VALUES + ",'skipped_quality'"

_ORIGINAL_DIMENSION_VALUES = (
    "'business_segment', 'product_line', 'channel', 'customer_tier'"
)
_NEW_DIMENSION_VALUES = _ORIGINAL_DIMENSION_VALUES + ", 'entered_by'"


def upgrade() -> None:
    # 1. reviews.quality_flag ----------------------------------------------
    op.add_column(
        "reviews",
        sa.Column("quality_flag", sa.String(16), nullable=True),
    )
    op.create_check_constraint(
        "ck_reviews_quality_flag",
        "reviews",
        "quality_flag IS NULL OR quality_flag IN "
        "('duplicate', 'empty', 'informational', 'meaningless')",
    )
    # Kalite raporu + analitik/rapor/heatmap include_flagged filtresi
    # her zaman kurum + dolu değer üzerinden gider (Dalga 2); NULL
    # (dominant, geçerli) satırlar indekse girmiyor.
    op.create_index(
        "ix_reviews_tenant_quality_flag",
        "reviews",
        ["tenant_id", "quality_flag"],
        postgresql_where=sa.text("quality_flag IS NOT NULL"),
    )
    # Deterministik backfill: eski dedup kararı zaten decision
    # kolonunda kayıtlıydı, quality_flag'e türetilir.
    op.execute(
        sa.text(
            "UPDATE reviews SET quality_flag = 'duplicate' "
            "WHERE decision = 'skipped_dedup' AND quality_flag IS NULL"
        )
    )

    # 2. reviews.entered_by --------------------------------------------------
    op.add_column(
        "reviews",
        sa.Column("entered_by", sa.Text(), nullable=True),
    )

    # 3. reviews.source -------------------------------------------------------
    op.add_column(
        "reviews",
        sa.Column("source", sa.Text(), nullable=True),
    )

    # 4. ck_reviews_decision genişlemesi (skipped_quality) --------------------
    op.drop_constraint("ck_reviews_decision", "reviews", type_="check")
    op.create_check_constraint(
        "ck_reviews_decision",
        "reviews",
        f"decision IN ({_NEW_DECISION_VALUES})",
    )

    # 5. tenants.terminology ---------------------------------------------------
    op.add_column(
        "tenants",
        sa.Column("terminology", JSONB(), nullable=True),
    )

    # 6. review_corrections — skor/deneyim/perspektif düzeltme alanları -------
    op.add_column(
        "review_corrections",
        sa.Column("new_score", sa.Float(), nullable=True),
    )
    op.add_column(
        "review_corrections",
        sa.Column("new_experience", sa.String(16), nullable=True),
    )
    op.create_check_constraint(
        "ck_review_corrections_new_experience",
        "review_corrections",
        "new_experience IS NULL OR new_experience IN ('dijital', 'operasyonel')",
    )
    op.add_column(
        "review_corrections",
        sa.Column("new_perspective", sa.Text(), nullable=True),
    )

    # 7. ck_tenant_business_dimensions_key genişlemesi (entered_by) -----------
    op.drop_constraint(
        "ck_tenant_business_dimensions_key",
        "tenant_business_dimensions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_tenant_business_dimensions_key",
        "tenant_business_dimensions",
        f"dimension IN ({_NEW_DIMENSION_VALUES})",
    )

    # 8. analyze_batch_jobs kalite sayaçları + özet ----------------------------
    for column_name in (
        "quality_duplicate_rows",
        "quality_empty_rows",
        "quality_informational_rows",
        "quality_meaningless_rows",
    ):
        op.add_column(
            "analyze_batch_jobs",
            sa.Column(
                column_name,
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )
    op.add_column(
        "analyze_batch_jobs",
        sa.Column("quality_summary", JSONB(), nullable=True),
    )


def downgrade() -> None:
    # 8.
    op.drop_column("analyze_batch_jobs", "quality_summary")
    for column_name in (
        "quality_meaningless_rows",
        "quality_informational_rows",
        "quality_empty_rows",
        "quality_duplicate_rows",
    ):
        op.drop_column("analyze_batch_jobs", column_name)

    # 7.
    op.drop_constraint(
        "ck_tenant_business_dimensions_key",
        "tenant_business_dimensions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_tenant_business_dimensions_key",
        "tenant_business_dimensions",
        f"dimension IN ({_ORIGINAL_DIMENSION_VALUES})",
    )

    # 6.
    op.drop_constraint(
        "ck_review_corrections_new_experience", "review_corrections", type_="check"
    )
    op.drop_column("review_corrections", "new_perspective")
    op.drop_column("review_corrections", "new_experience")
    op.drop_column("review_corrections", "new_score")

    # 5.
    op.drop_column("tenants", "terminology")

    # 4.
    op.drop_constraint("ck_reviews_decision", "reviews", type_="check")
    op.create_check_constraint(
        "ck_reviews_decision",
        "reviews",
        f"decision IN ({_ORIGINAL_DECISION_VALUES})",
    )

    # 3.
    op.drop_column("reviews", "source")

    # 2.
    op.drop_column("reviews", "entered_by")

    # 1.
    op.drop_index("ix_reviews_tenant_quality_flag", table_name="reviews")
    op.drop_constraint("ck_reviews_quality_flag", "reviews", type_="check")
    op.drop_column("reviews", "quality_flag")
