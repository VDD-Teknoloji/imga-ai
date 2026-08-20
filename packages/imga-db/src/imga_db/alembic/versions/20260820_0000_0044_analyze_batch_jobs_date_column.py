"""analyze_batch_jobs.date_column — kullanıcının elle seçtiği tarih kolonu

Revision ID: 0044
Revises: 0043
Create Date: 2026-08-20 00:00:00

Kitap1.xlsx (21.684 satır) yüklemesinde tarih kolonu yakalanamadı:
file_parser'ın otomatik tespiti YALNIZ başlık adına bakıyordu (önce
şablonun ``tarih`` kolonu birebir, sonra ~9 desenlik bir başlık
listesi); dosyanın başlığı bu listeyle örtüşmeyince sessizce None'a
düştü. Tüm satırlar yükleme anına düştü, dönem karşılaştırmaları
(ör. /compare Nisan-Mayıs) boş kaldı — kullanıcı bunu haftalar sonra
fark etti.

Aynı commit'te otomatik tespit iki yönden güçlendirildi (başlık
deseni listesi genişletildi + değer-tabanlı yedek eklendi,
bkz. workers.file_parser), ama tespit yine de YANLIŞ TAHMİN
edebilir. Bu kolon o riski tamamen ortadan kaldırır: Step-2 kolon
eşleme ekranında kullanıcı tarih kolonunu ELLE seçebilir (smart
parser'ın önerisi ön-seçili gelir). Worker'daki öncelik sırası:

  1. ``date_column`` doluysa DOĞRUDAN o başlık kullanılır — dosyada
     yoksa satırlar tarihsiz kalır ve job'a (error_summary üzerinden)
     bir uyarı düşer. İş başarısız SAYILMAZ.
  2. Boşsa mevcut (güçlendirilmiş) otomatik tespit çalışır.

``text_column`` / ``source_column`` ile aynı sözleşme: kullanıcının
seçimi, NULL = seçim yok.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "0044"
down_revision: str | Sequence[str] | None = "0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "analyze_batch_jobs",
        sa.Column("date_column", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("analyze_batch_jobs", "date_column")
