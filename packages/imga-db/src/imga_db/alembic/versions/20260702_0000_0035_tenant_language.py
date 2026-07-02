"""tenants.language — kurum arayüz + AI çıktı dili (tr | en).

Kurum oluşturulurken seçilir; tenant değişince UI + AI çıktı dili buna göre
değişir. Mevcut kurumlar 'tr' backfill edilir (server_default). CHECK constraint
DB seviyesinde tr/en'i garanti eder. Tenant tablosu cross-tenant (RLS yok) —
yalnız kolon eklenir.

Revision ID: 0035
Revises: 0034
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column(
            "language",
            sa.String(length=5),
            nullable=False,
            server_default="tr",
        ),
    )
    op.create_check_constraint(
        "ck_tenants_language",
        "tenants",
        "language IN ('tr', 'en')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_tenants_language", "tenants", type_="check")
    op.drop_column("tenants", "language")
