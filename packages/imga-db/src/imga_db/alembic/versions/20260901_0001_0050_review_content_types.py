"""reviews.content_type genişlemesi — 'suggestion' | 'thanks' | 'request'
| 'escalation'

Revision ID: 0050
Revises: 0049
Create Date: 2026-09-01 00:00:00

ÜRÜN KARARI (final): migration 0049'un tek değerli ``content_type``
CHECK'i ('question') dört yeni değerle genişler:

  * ``suggestion``  — öneri (bir özellik/iyileştirme talebi).
  * ``thanks``      — teşekkür (yalnız minnettarlık, genel pozitif
    duygu DEĞİL).
  * ``request``     — somut bir eylem talebi (iade, iptal, geri ödeme,
    geri arama, bilgi/dönüş).
  * ``escalation``  — resmi eskalasyon TEHDİDİ/duyurusu (tüketici
    hakem heyeti, mahkeme/dava, avukat, savcılık, CİMER, şikayetvar,
    BTK, Ticaret Bakanlığı, "yasal yollara").

ÖNCELİK (aynı satırda birden çok kalıp eşleşirse — yazan taraf
``imga_api.services.data_quality.detect_content_type``, bkz. o
modülün docstring'i):

    escalation > request > question > suggestion > thanks

content_type ``quality_flag`` ve ``sentiment``'ten ORTOGONAL kalmaya
devam eder — bir escalation satırı aynı zamanda NEGATİF sentiment
taşıyabilir ve analitikte KALIR (0049'un aynı gerekçesi: content_type
bir "düşük kalite" işareti değil, metnin YAPISAL biçimidir).

Mekanik: 0042/0041 deseniyle birebir aynı — ``ck_reviews_content_type``
drop + create constraint ile genişletilir (bkz. o migration'daki
``_ORIGINAL_DECISION_VALUES``/``_NEW_DECISION_VALUES`` deseni).
``ix_reviews_tenant_content_type`` kısmi indeksine dokunulmaz (kolon
adı/şekli değişmedi, yalnız izin verilen değer kümesi genişledi).

BACKFILL YOK — 0049'daki ``content_type`` gerekçesiyle aynı: eski
satırlar NULL kalır, gerçek değeri yeniden analizde
(``POST /tenants/me/reviews/reanalyze-all``) alır.

Downgrade: dört yeni değeri taşıyan satırlar önce NULL'a çekilir (aksi
halde eski tek-değerli CHECK restore edilirken ihlal oluşur — 0042/0035
best-effort simetri kabulüyle aynı), sonra CHECK eski haline döner.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

# revision identifiers
revision: str = "0050"
down_revision: str | Sequence[str] | None = "0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ORIGINAL_CONTENT_TYPE_VALUES = "'question'"
_NEW_CONTENT_TYPE_VALUES = (
    _ORIGINAL_CONTENT_TYPE_VALUES + ", 'suggestion', 'thanks', 'request', 'escalation'"
)


def upgrade() -> None:
    op.drop_constraint("ck_reviews_content_type", "reviews", type_="check")
    op.create_check_constraint(
        "ck_reviews_content_type",
        "reviews",
        f"content_type IS NULL OR content_type IN ({_NEW_CONTENT_TYPE_VALUES})",
    )


def downgrade() -> None:
    op.execute(
        text(
            "UPDATE reviews SET content_type = NULL "
            "WHERE content_type IN ('suggestion', 'thanks', 'request', 'escalation')"
        )
    )
    op.drop_constraint("ck_reviews_content_type", "reviews", type_="check")
    op.create_check_constraint(
        "ck_reviews_content_type",
        "reviews",
        f"content_type IS NULL OR content_type IN ({_ORIGINAL_CONTENT_TYPE_VALUES})",
    )
