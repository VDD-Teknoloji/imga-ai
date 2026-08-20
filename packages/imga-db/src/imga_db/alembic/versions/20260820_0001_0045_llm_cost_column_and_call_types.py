"""llm_call_audit.cost_usd + call_type/decision_type CHECK genişlemesi.

Revision ID: 0045
Revises: 0044
Create Date: 2026-08-20 00:00:00

Süper-admin envanter raporu (B2/B6/B7 + C1-C4) çalışmasının DB ayağı.
Tek revizyonda üç bağımsız değişiklik:

  1. ``llm_call_audit.cost_usd`` — NUMERIC(12,6) NULL, çağrı başına
     tahmini USD maliyeti (``imga_api.services.llm_pricing.cost_usd``
     statik fiyat tablosundan hesaplanır). Eski satırlar NULL kalır —
     backfill YOK: geçmiş çağrıların hangi statik fiyatla hesaplanacağı
     belirsiz (fiyat tablosu geriye dönük değil, o anki fiyatı bilmiyoruz).
     NULL = "maliyet bilinmiyor", 0 DEĞİL — okuma tarafı (özet
     endpoint'leri) bu ayrımı korumalı.

  2. ``ck_llm_call_audit_call_type`` genişler — 'onboarding_suggest'
     eklenir (WS1 onboarding sihirbazının AI kategori önerisi çağrısı).
     Desen: 0043 (drop + recreate CHECK).

  3. ``ck_decision_audit_log_type`` genişler — dört yeni operatör-kararı
     tipi: 'batch_retried', 'reanalysis_started', 'review_corrected',
     'onboarding_categories_applied'. Migration 0027'nin kurduğu kısıt
     ilk kez burada genişliyor; aynı drop + recreate deseni.

Backfill/DDL ``app.current_tenant_id`` set etmeden koşar: migration'ı
çalıştıran ``imga_owner`` superuser'dır ve RLS'i her koşulda atlar
(bkz. 0038 notu). RLS policy'lerine dokunulmaz.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "0045"
down_revision: str | Sequence[str] | None = "0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# --- 2. call_type ------------------------------------------------------
# 0043'ün _NEW'i buranın _OLD'u — CHECK'in o revizyondan sonraki hâli.
_OLD_CALL_TYPES = (
    "'classification', 'briefing', 'strategic_report', "
    "'action_extraction', 'okr', 'root_cause', 'quality_report'"
)
_NEW_CALL_TYPES = _OLD_CALL_TYPES + ", 'onboarding_suggest'"

# --- 3. decision_type ----------------------------------------------------
# Migration 0027'nin kurduğu orijinal on bir değer (models/decision_audit_log.py
# ile birebir aynı sırada).
_OLD_DECISION_TYPES = (
    "'briefing_acknowledged', 'briefing_dismissed', "
    "'strategic_report_approved', 'strategic_report_rejected', "
    "'action_item_assigned', 'action_item_priority_changed', "
    "'sla_rule_changed', 'kpi_goal_set', "
    "'webhook_dispatched_manually', 'tenant_setting_changed', "
    "'prompt_template_overridden'"
)
_NEW_DECISION_TYPES = _OLD_DECISION_TYPES + (
    ", 'batch_retried', 'reanalysis_started', 'review_corrected', 'onboarding_categories_applied'"
)


def upgrade() -> None:
    # 1. llm_call_audit.cost_usd ------------------------------------------
    op.add_column(
        "llm_call_audit",
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=True),
    )

    # 2. ck_llm_call_audit_call_type genişlemesi --------------------------
    op.execute("ALTER TABLE llm_call_audit DROP CONSTRAINT IF EXISTS ck_llm_call_audit_call_type")
    op.execute(
        "ALTER TABLE llm_call_audit ADD CONSTRAINT "
        f"ck_llm_call_audit_call_type CHECK (call_type IN ({_NEW_CALL_TYPES}))"
    )

    # 3. ck_decision_audit_log_type genişlemesi ---------------------------
    op.execute(
        "ALTER TABLE decision_audit_log DROP CONSTRAINT IF EXISTS ck_decision_audit_log_type"
    )
    op.execute(
        "ALTER TABLE decision_audit_log ADD CONSTRAINT "
        f"ck_decision_audit_log_type CHECK (decision_type IN ({_NEW_DECISION_TYPES}))"
    )


def downgrade() -> None:
    # 3. — eski kısıt yeni değerleri kabul etmez, önce o satırları temizle.
    op.execute(
        "DELETE FROM decision_audit_log WHERE decision_type IN "
        "('batch_retried', 'reanalysis_started', 'review_corrected', "
        "'onboarding_categories_applied')"
    )
    op.execute(
        "ALTER TABLE decision_audit_log DROP CONSTRAINT IF EXISTS ck_decision_audit_log_type"
    )
    op.execute(
        "ALTER TABLE decision_audit_log ADD CONSTRAINT "
        f"ck_decision_audit_log_type CHECK (decision_type IN ({_OLD_DECISION_TYPES}))"
    )

    # 2.
    op.execute("DELETE FROM llm_call_audit WHERE call_type = 'onboarding_suggest'")
    op.execute("ALTER TABLE llm_call_audit DROP CONSTRAINT IF EXISTS ck_llm_call_audit_call_type")
    op.execute(
        "ALTER TABLE llm_call_audit ADD CONSTRAINT "
        f"ck_llm_call_audit_call_type CHECK (call_type IN ({_OLD_CALL_TYPES}))"
    )

    # 1.
    op.drop_column("llm_call_audit", "cost_usd")
