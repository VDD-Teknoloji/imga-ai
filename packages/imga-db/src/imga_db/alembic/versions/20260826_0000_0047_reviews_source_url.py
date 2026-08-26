"""reviews.source_url — yorumun kaynağındaki kalıcı bağlantı

Revision ID: 0047
Revises: 0046
Create Date: 2026-08-26 00:00:00

"Twitter'dan Çek" yalnız metin + tarih tutuyordu; arşivde bir gönderinin
markayla ilgisi bağlam olmadan anlaşılamıyordu ("karaca" araması Karaca
soyadlı yazarların gönderilerini de getirdi). Tweet URL'si artık CSV'ye
``bağlantı`` kolonu olarak iner, file_parser bunu otomatik tanır ve
buraya yazar; arşiv kartı + detay sayfası "Tweeti aç" düğmesiyle
gönderiye gider. Pazar yeri dışa aktarımlarındaki yorum linkleri de
aynı kolondan geçer.

Nullable, indekssiz, RLS'e dokunmaz (mevcut tablo). NULL = kaynakta
bağlantı yok.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "0047"
down_revision: str | Sequence[str] | None = "0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "reviews",
        sa.Column("source_url", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("reviews", "source_url")
