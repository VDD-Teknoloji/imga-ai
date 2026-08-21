"""Operasyonel "facts" modülü — review_facts + tenant_fact_mappings.

Revision ID: 0046
Revises: 0045
Create Date: 2026-08-21 00:00:00

SLA gerçekleşmeleri, CSAT, efor, tazmin ve teslimat verilerini taşıyan
yeni bir katman — ``tenant_business_dimensions`` (migration 0027) ile
aynı ruhta ama ayrı bir tablo çifti: yorumun *iş bağlamı* (segment/
kanal/...) değil, yorumun bağlı olduğu destek talebinin *operasyonel
gerçekleşmesi* (SLA ihlali mi, memnuniyet skoru ne, ne kadar sürdü).

İki tablo:

  * ``review_facts`` — ``reviews`` ile 1:1 (PK = FK = ``review_id``).
    Her satır opsiyonel: bir yüklemede facts kolonları hiç
    eşlenmemişse hiç satır yazılmaz (worker tarafı — bkz.
    ``fact_parsing.build_fact_row``). RLS+FORCE, migration 0006:208-217
    kalıbı (USING + WITH CHECK, ``current_setting(..., true)``).
  * ``tenant_fact_mappings`` — ``tenant_business_dimensions``'ın
    kardeşi (migration 0027:222-282 kalıbı): hangi CSV başlığının
    hangi ``fact_field``'e karşılık geldiğini tutar. ``csv_column_
    mapping`` NOT NULL (dimensions'ın aksine — bir mapping satırı
    haritasız var olamaz, "eşleme yok" = satır yok).

RLS policy'si HER İKİ tabloda da migration 0006'nın tam kalıbı
kullanılır (USING + WITH CHECK, ``true`` bayraklı current_setting) —
migration 0027'nin tenant_business_dimensions için kullandığı daha
kısa (USING-only, ``true``sız) biçim BİLİNÇLİ OLARAK tekrarlanmıyor;
görev talimatı burada açıkça 0006 kalıbını istiyor.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

# revision identifiers
revision: str = "0046"
down_revision: str | Sequence[str] | None = "0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: review_facts.sla_*_status ve tenant_fact_mappings.fact_field CHECK'i
#: bu SAF DEĞER LİSTESİNİ paylaşır — imga_api.services.fact_parsing.
#: FACT_FIELDS ile BİREBİR AYNI SIRA (13 alan).
_FACT_FIELDS: tuple[str, ...] = (
    "sla_resolution_status",
    "sla_first_response_status",
    "resolution_time",
    "first_response_time",
    "csat",
    "agent_interactions",
    "customer_interactions",
    "compensation_status",
    "freight_cost",
    "goods_cost",
    "refund_reason",
    "delivery_status",
    "delivery_detail",
)


def upgrade() -> None:
    # --- review_facts -----------------------------------------------
    op.create_table(
        "review_facts",
        sa.Column(
            "review_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("reviews.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "tenant_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sla_resolution_status", sa.Text(), nullable=True),
        sa.Column("sla_first_response_status", sa.Text(), nullable=True),
        sa.Column("resolution_time_minutes", sa.Integer(), nullable=True),
        sa.Column("first_response_time_minutes", sa.Integer(), nullable=True),
        sa.Column("csat_score", sa.SmallInteger(), nullable=True),
        sa.Column("csat_raw", sa.Text(), nullable=True),
        sa.Column("agent_interactions", sa.Integer(), nullable=True),
        sa.Column("customer_interactions", sa.Integer(), nullable=True),
        sa.Column("compensation_status", sa.Text(), nullable=True),
        sa.Column("freight_cost", sa.Numeric(12, 2), nullable=True),
        sa.Column("goods_cost", sa.Numeric(12, 2), nullable=True),
        sa.Column("refund_reason", sa.Text(), nullable=True),
        sa.Column("delivery_status", sa.Text(), nullable=True),
        sa.Column("delivery_detail", sa.Text(), nullable=True),
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
            "sla_resolution_status IS NULL OR "
            "sla_resolution_status IN ('within', 'violated')",
            name="ck_review_facts_sla_resolution_status",
        ),
        sa.CheckConstraint(
            "sla_first_response_status IS NULL OR "
            "sla_first_response_status IN ('within', 'violated')",
            name="ck_review_facts_sla_first_response_status",
        ),
        sa.CheckConstraint(
            "csat_score IS NULL OR (csat_score >= 1 AND csat_score <= 5)",
            name="ck_review_facts_csat_score_range",
        ),
    )
    op.create_index(
        "ix_review_facts_tenant_id", "review_facts", ["tenant_id"]
    )
    op.create_index(
        "ix_review_facts_tenant_sla_resolution",
        "review_facts",
        ["tenant_id", "sla_resolution_status"],
        postgresql_where=sa.text("sla_resolution_status IS NOT NULL"),
    )
    op.execute("ALTER TABLE review_facts ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE review_facts FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON review_facts
            FOR ALL
            USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
        """
    )

    # --- tenant_fact_mappings -----------------------------------------
    op.create_table(
        "tenant_fact_mappings",
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
        sa.Column("fact_field", sa.Text(), nullable=False),
        sa.Column("csv_column_mapping", sa.Text(), nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("TRUE"),
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
            "tenant_id", "fact_field", name="uq_tenant_fact_mappings_field"
        ),
        sa.CheckConstraint(
            "fact_field IN ("
            + ", ".join(f"'{f}'" for f in _FACT_FIELDS)
            + ")",
            name="ck_tenant_fact_mappings_field",
        ),
    )
    op.execute(
        "ALTER TABLE tenant_fact_mappings ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        "ALTER TABLE tenant_fact_mappings FORCE ROW LEVEL SECURITY"
    )
    op.execute(
        """
        CREATE POLICY tenant_isolation ON tenant_fact_mappings
            FOR ALL
            USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation ON tenant_fact_mappings"
    )
    op.drop_table("tenant_fact_mappings")

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON review_facts")
    op.drop_index(
        "ix_review_facts_tenant_sla_resolution", table_name="review_facts"
    )
    op.drop_index("ix_review_facts_tenant_id", table_name="review_facts")
    op.drop_table("review_facts")
