"""Kategori bazlı ticket yönlendirme + e-posta outbox + global 'belirsiz'

Revision ID: 0036
Revises: 0035
Create Date: 2026-07-10 00:00:00

Üç parça:

  1. Global ``belirsiz`` kategorisi (tenant_id IS NULL). Migration 0005
     bilinçli olarak persist etmemişti; sonuç: skipped_belirsiz bir
     review manuel promote edilirken ``_resolve_category_id`` satır
     bulamıyor ve route 409 dönüyordu (HATA-03). Satır global olduğu
     için ``categories_select`` politikası her tenant'a gösterir ve
     promote kendiliğinden çözülür. ``tenant_categories`` opt-in
     seed'ine gerek yok — çözümleme enablement'a bakmıyor.

  2. ``ticket_routing_rules`` — tenant başına kategori→(e-posta,
     assignee, SLA saati) eşlemesi. Ticket mint eden üç yol
     (tekil analiz, batch worker, manuel promote) ReviewService
     üzerinden bu kurallara uğrar.

  3. ``email_outbox`` — asenkron e-posta kuyruğu. Yönlendirme motoru
     ('ticket_opened') ve SLA ihlal taraması ('sla_breach') satır
     ekler; arq cron dispatcher'ı (email_outbox_tick) gönderir.
     status/attempts/last_error/sent_at üçlüsü pending_webhook_events
     (0022) kalıbını izler.

RLS+FORCE + tenant_isolation politikası her iki yeni tabloda — 0022
kalıbı.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision: str = "0036"
down_revision: str | Sequence[str] | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Global 'belirsiz' kategorisi -------------------------------------
    # categories 0005'ten beri RLS+FORCE; INSERT politikası tenant_id'nin
    # bağlı tenant'a eşit olmasını şart koşar, migration ise tenant
    # bağlamadan koşar. FORCE'u geçici kaldırıp tablo sahibi (imga_owner)
    # olarak ekliyoruz — politika tanımlarına dokunulmaz.
    op.execute("ALTER TABLE categories NO FORCE ROW LEVEL SECURITY")
    op.execute(
        sa.text(
            """
            INSERT INTO categories (tenant_id, code, label_tr, label_en)
            VALUES (NULL, 'belirsiz', 'Belirsiz', 'Uncategorized')
            ON CONFLICT (code) WHERE tenant_id IS NULL DO NOTHING
            """
        )
    )
    op.execute("ALTER TABLE categories FORCE ROW LEVEL SECURITY")

    # 2. ticket_routing_rules ---------------------------------------------
    op.create_table(
        "ticket_routing_rules",
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
        sa.Column("category_code", sa.String(length=64), nullable=False),
        sa.Column("notify_email", sa.String(length=320), nullable=False),
        sa.Column(
            "assignee_user_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("sla_hours", sa.Integer(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
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
        sa.CheckConstraint(
            "sla_hours IS NULL OR sla_hours > 0",
            name="ck_ticket_routing_rules_sla_hours",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "category_code",
            name="uq_ticket_routing_rules_tenant_category",
        ),
    )
    op.create_index(
        "ix_ticket_routing_rules_tenant_active",
        "ticket_routing_rules",
        ["tenant_id", "is_active"],
    )
    op.execute("ALTER TABLE ticket_routing_rules ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ticket_routing_rules FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON ticket_routing_rules "
        "USING (tenant_id = current_setting('app.current_tenant_id')::uuid)"
    )

    # 3. email_outbox -------------------------------------------------------
    op.create_table(
        "email_outbox",
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
        sa.Column("to_email", sa.String(length=320), nullable=False),
        sa.Column("subject", sa.String(length=500), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column(
            "related_ticket_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("tickets.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "attempts", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "event_type IN ('ticket_opened', 'sla_breach')",
            name="ck_email_outbox_event_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'failed')",
            name="ck_email_outbox_status",
        ),
    )
    op.create_index(
        "ix_email_outbox_status_next_attempt",
        "email_outbox",
        ["status", "next_attempt_at"],
    )
    op.create_index(
        "ix_email_outbox_tenant_created",
        "email_outbox",
        ["tenant_id", sa.text("created_at DESC")],
    )
    op.execute("ALTER TABLE email_outbox ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE email_outbox FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON email_outbox "
        "USING (tenant_id = current_setting('app.current_tenant_id')::uuid)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON email_outbox")
    op.execute("ALTER TABLE email_outbox DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_email_outbox_tenant_created", table_name="email_outbox")
    op.drop_index(
        "ix_email_outbox_status_next_attempt", table_name="email_outbox"
    )
    op.drop_table("email_outbox")

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON ticket_routing_rules")
    op.execute("ALTER TABLE ticket_routing_rules DISABLE ROW LEVEL SECURITY")
    op.drop_index(
        "ix_ticket_routing_rules_tenant_active",
        table_name="ticket_routing_rules",
    )
    op.drop_table("ticket_routing_rules")

    # 'belirsiz'e bağlı ticket varsa FK RESTRICT bu DELETE'i bloklar —
    # bilinçli: downgrade veri kaybettirmez, operatör önce ticket'ları
    # taşımalı.
    op.execute("ALTER TABLE categories NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "DELETE FROM categories WHERE tenant_id IS NULL AND code = 'belirsiz'"
    )
    op.execute("ALTER TABLE categories FORCE ROW LEVEL SECURITY")
