"""category_taxonomies — per-tenant company-perspective heuristic source

Revision ID: 0017
Revises: 0016
Create Date: 2026-01-17 00:00:00

Sprint 8.3.5 / Alt-Faz 8.3.5.5. Per-tenant taxonomy of "company
perspective" categories — code, Türkçe label, keywords list. Each
fresh tenant inherits the 21-row default seed (the legacy
cx_sentiment_dashboard's get_company_perspective heuristic, ground
truth at app.py:646-740 — categories #9 and #10 dropped per a
"Deleted separate 9 and 10" comment in the original code).

Edit UI lands in Sprint 8.3.7. This sprint ships the table, the seed,
and a read-only list endpoint so the heuristic reranker
(``imga-core.categorizers.company_heuristic``) has data to reason
against.

RLS+FORCE on tenant_id, identical convention to migrations 0006 / 0008
/ 0010 / 0012 / 0013. The composite ``(tenant_id, priority)`` index
keeps the heuristic's "highest priority wins on tie" lookup cheap.

Data backfill at the bottom of upgrade() seeds the 21 defaults for
every existing tenant — production rows in tenants pre-date this
sprint and would otherwise come up empty until they hit the
TenantService.create path.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

# revision identifiers
revision: str = "0017"
down_revision: str | Sequence[str] | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Default 21-row seed — extracted verbatim from
# cx_sentiment_dashboard/app.py:657-740. ``code`` is a snake_case ASCII
# rendering of the Türkçe label; ``priority`` mirrors the original if-
# elif order so a tie on keyword match resolves to the legacy winner.
# ``keywords`` is the exact list each ``if any(kw in t for kw in [...])``
# guard used in the legacy code.
_DEFAULT_TAXONOMY: list[dict[str, object]] = [
    {
        "code": "shipment_not_arrived",
        "label_tr": "Kargom ulaşmadı",
        "keywords": [
            "kargom nerede", "gelmedi", "teslim edilmedi",
            "ulaşmadı", "gecikti", "teslimat sorunu",
        ],
        "priority": 1,
    },
    {
        "code": "broken_damaged",
        "label_tr": "Deforme-Kırık Ürün",
        "keywords": [
            "kırık", "deforme", "ezik", "hasarlı",
            "parçalanmış", "yırtık ürün", "defolu", "ayıplı",
        ],
        "priority": 2,
    },
    {
        "code": "poor_packaging",
        "label_tr": "Özensiz Paketleme",
        "keywords": ["paket", "özensiz", "yırtık paket", "kutu ezik", "ambalaj"],
        "priority": 3,
    },
    {
        "code": "wrong_or_missing_item",
        "label_tr": "Yanlış-Eksik Ürün",
        "keywords": [
            "yanlış ürün", "farklı ürün", "eksik ürün",
            "sipariş ettiğimden farklı", "başka ürün",
        ],
        "priority": 4,
    },
    {
        "code": "incomplete_set",
        "label_tr": "Ürünümde takım eksik geldi",
        "keywords": ["takım", "parça eksik", "altı yok", "üstü yok", "seti bozuk"],
        "priority": 5,
    },
    {
        "code": "product_quality_material",
        "label_tr": "Ürün kalite - Ana Malzeme",
        "keywords": [
            "kumaş", "pamuklanma", "tüylenme", "çekme", "solma",
            "kalite", "dikiş", "yırtılma", "ince", "naylon",
        ],
        "priority": 6,
    },
    {
        "code": "refund_not_received",
        "label_tr": "İade Ücretim Hesaba Geçmedi",
        "keywords": [
            "ücret iadesi", "param yatmadı", "hesap",
            "geri ödeme", "tutar iadesi", "bakiye",
        ],
        "priority": 7,
    },
    {
        "code": "campaign_issues",
        "label_tr": "Kampanya Sorunları",
        "keywords": [
            "çark", "çevir", "indirim çarkı", "hediye çarkı", "kazanıyorum",
            "puan", "money", "kazanç", "kupon", "indirim kodu",
        ],
        "priority": 8,
    },
    # 9, 10 deliberately skipped (legacy "Deleted separate 9 and 10").
    {
        "code": "ebebek_money_transfer",
        "label_tr": "E-bebek Para Aktarımı olmadı",
        "keywords": ["ebebek para", "lcw para", "cüzdan", "aktarım", "yükleme"],
        "priority": 11,
    },
    {
        "code": "order_status_wrong",
        "label_tr": "Siparişimin statüsü doğru değil",
        "keywords": [
            "statü", "kargoya verildi yazıyor", "hazırlanıyor", "hala", "durum",
        ],
        "priority": 12,
    },
    {
        "code": "cancel_request",
        "label_tr": "Sipariş iptal talebi",
        "keywords": [
            "iptal etmek istiyorum", "yanlışlıkla verdim",
            "vazgeçtim", "siparişi iptal",
        ],
        "priority": 13,
    },
    {
        "code": "address_change",
        "label_tr": "Teslimat adresini değiştirebilir miyim?",
        "keywords": [
            "adres değişikliği", "yanlış adres", "kargo adresi", "adresi değiştir",
        ],
        "priority": 14,
    },
    {
        "code": "store_return_for_online",
        "label_tr": "İnternetten aldığım ürünü mağazadan iade etmek istiyorum",
        "keywords": [
            "mağazadan iade", "şubeden iade", "internetten aldım mağazaya",
        ],
        "priority": 15,
    },
    {
        "code": "return_status_inquiry",
        "label_tr": "İnternet satış iadem nerede/sonucu ne oldu",
        "keywords": [
            "iadem ne durumda", "iade sonucu", "inceleniyor", "iade işlemleri",
        ],
        "priority": 16,
    },
    {
        "code": "how_to_return",
        "label_tr": "İade nasıl yapılır",
        "keywords": [
            "iade kodu", "nasıl iade ederim", "iade işlemi", "iade etmek istiyorum",
        ],
        "priority": 17,
    },
    {
        "code": "return_period_exceeded",
        "label_tr": "İade Süresi Aşımı",
        "keywords": [
            "iade süresi", "14 gün", "30 gün", "zamanı geçti", "süre doldu",
        ],
        "priority": 18,
    },
    {
        "code": "account_membership",
        "label_tr": "Üyelik ve Hesap Yönetimi",
        "keywords": [
            "üyelik", "giriş yapamıyorum", "şifre", "hesap",
            "güncelleme", "sms", "kod", "login",
        ],
        "priority": 19,
    },
    {
        "code": "invoice_request",
        "label_tr": "Fatura Talebi",
        "keywords": ["fatura", "e-fatura", "kurumsal fatura", "fatura gelmedi"],
        "priority": 20,
    },
    {
        "code": "store_issues",
        "label_tr": "Mağaza Sorunları",
        "keywords": [
            "mağaza", "personel", "çalışan", "kabin", "kasa",
            "sıra", "reyon", "etiket fiyatı", "güvenlik",
        ],
        "priority": 21,
    },
    {
        "code": "payment_and_campaign_issues",
        "label_tr": "Ödeme ve Kampanya Sorunları",
        "keywords": ["ödeme", "kredi kartı", "çekim", "taksit", "provizyon"],
        "priority": 22,
    },
    {
        "code": "general_other",
        "label_tr": "Genel ve Diğer Sorunlar",
        # Legacy fallback had no keywords — empty list keeps the row
        # in the UI but never wins on the heuristic match.
        "keywords": [],
        "priority": 999,
    },
]


def upgrade() -> None:
    op.create_table(
        "category_taxonomies",
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
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("label_tr", sa.String(length=128), nullable=False),
        sa.Column(
            "keywords",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "priority",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("100"),
        ),
        sa.Column(
            "is_default_seed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "tenant_id", "code", name="uq_category_taxonomies_tenant_code"
        ),
    )

    op.create_index(
        "ix_category_taxonomies_tenant_priority",
        "category_taxonomies",
        ["tenant_id", "priority"],
    )

    # RLS+FORCE — same convention as every tenant-scoped table since
    # migration 0001. imga_owner bypasses; imga_app and imga_admin
    # respect the policy.
    op.execute("ALTER TABLE category_taxonomies ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE category_taxonomies FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON category_taxonomies "
        "USING (tenant_id = current_setting('app.current_tenant_id')::uuid)"
    )

    # --- Backfill: seed every existing tenant with the 21 defaults ---
    # Bypasses the policy via imga_owner (Alembic runs as owner).
    bind = op.get_bind()
    tenant_rows = bind.execute(sa.text("SELECT id FROM tenants")).fetchall()
    for tenant_row in tenant_rows:
        tenant_id = tenant_row[0]
        for entry in _DEFAULT_TAXONOMY:
            bind.execute(
                sa.text(
                    "INSERT INTO category_taxonomies "
                    "(tenant_id, code, label_tr, keywords, priority, "
                    " is_default_seed) "
                    "VALUES (:tenant_id, :code, :label_tr, "
                    " CAST(:keywords AS jsonb), :priority, true) "
                    "ON CONFLICT (tenant_id, code) DO NOTHING"
                ),
                {
                    "tenant_id": str(tenant_id),
                    "code": entry["code"],
                    "label_tr": entry["label_tr"],
                    "keywords": json.dumps(entry["keywords"]),
                    "priority": entry["priority"],
                },
            )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON category_taxonomies")
    op.execute("ALTER TABLE category_taxonomies DISABLE ROW LEVEL SECURITY")
    op.drop_index(
        "ix_category_taxonomies_tenant_priority", table_name="category_taxonomies"
    )
    op.drop_table("category_taxonomies")
