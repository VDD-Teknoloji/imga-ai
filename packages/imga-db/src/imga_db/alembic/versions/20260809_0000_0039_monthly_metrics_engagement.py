"""aylık işlem adedi + katılım oranı bantları

Revision ID: 0039
Revises: 0038
Create Date: 2026-08-09 00:00:00

İki tablo birlikte iner çünkü tek bir iş sorusunun iki yarısıdır:
"kurum bu ay kaç işlem yaptı" (payda) ve "çıkan oran iyi mi kötü mü"
(değerlendirme).

  1. ``tenant_monthly_metrics`` — kurumun kendi girdiği aylık işlem
     adedi. ``period_month`` ayın ilk günü (CheckConstraint); tek satır
     / (kurum, ay). Yorum sayısı bu tablodan okunmaz — ``reviews``
     üzerinden ``review_date`` ile aylık bucket'lanır (0038), yani
     işlem adedi girilmemiş aylar da tabloda görünür.

  2. ``tenant_engagement_settings`` — kurum başına değerlendirme
     bantları (JSONB, sıralı liste). Yalnızca süper yönetici
     düzenler: eşiğin "iyi" mi "kötü" mü olduğu sektöre bağlı bir
     yargı. Satır yoksa API varsayılan bantları döner — bu migration
     hiçbir kuruma satır AÇMAZ.

Bantların şekil doğrulaması API'de (Pydantic): artan ve tekil
``min_pct``, ilk bant 0'dan başlar, 1-8 bant, etiket 1-64 karakter.
JSONB tarafına kısıt konmadı; bant sayısı/etiketi ürün kararıdır,
şema değil — CHECK yazmak her etiket değişikliğinde migration
gerektirirdi.

Her iki tablo da kurum-kapsamlı: RLS ENABLE+FORCE + ``tenant_isolation``
politikası (0006/0026 konvansiyonu).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

# revision identifiers
revision: str = "0039"
down_revision: str | Sequence[str] | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. tenant_monthly_metrics ------------------------------------------
    op.create_table(
        "tenant_monthly_metrics",
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
        sa.Column("period_month", sa.Date(), nullable=False),
        sa.Column("transaction_count", sa.BigInteger(), nullable=False),
        sa.Column(
            "set_by_user_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
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
        sa.UniqueConstraint(
            "tenant_id",
            "period_month",
            name="uq_tenant_monthly_metrics_period",
        ),
        sa.CheckConstraint(
            "EXTRACT(DAY FROM period_month) = 1",
            name="ck_tenant_monthly_metrics_first_of_month",
        ),
        sa.CheckConstraint(
            "transaction_count >= 0",
            name="ck_tenant_monthly_metrics_count_non_negative",
        ),
    )
    # UNIQUE(tenant_id, period_month) zaten (tenant_id, period_month)
    # önekli bir B-tree kurar; listeleme sorgusu (kurum + tarih aralığı)
    # onu kullanır, ayrı indekse gerek yok.
    op.execute("ALTER TABLE tenant_monthly_metrics ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenant_monthly_metrics FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON tenant_monthly_metrics "
        "USING (tenant_id = current_setting('app.current_tenant_id')::uuid)"
    )

    # 2. tenant_engagement_settings --------------------------------------
    op.create_table(
        "tenant_engagement_settings",
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
        sa.Column(
            "bands",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "updated_by_user_id",
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
        sa.UniqueConstraint(
            "tenant_id", name="uq_tenant_engagement_settings_tenant"
        ),
    )
    op.execute(
        "ALTER TABLE tenant_engagement_settings ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        "ALTER TABLE tenant_engagement_settings FORCE ROW LEVEL SECURITY"
    )
    op.execute(
        "CREATE POLICY tenant_isolation ON tenant_engagement_settings "
        "USING (tenant_id = current_setting('app.current_tenant_id')::uuid)"
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation ON tenant_engagement_settings"
    )
    op.drop_table("tenant_engagement_settings")
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation ON tenant_monthly_metrics"
    )
    op.drop_table("tenant_monthly_metrics")
