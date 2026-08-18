"""llm_call_audit call_type CHECK'ine 'quality_report' eklenir.

Dalga 2 kalite raporu LLM özeti (QualityReportService.generate_summary)
denetim satırı yazar; 0042 döneminde CHECK genişletilemediği için geçici
olarak 'root_cause' kullanıldı — bu revizyon gerçek değeri açar (servis
aynı commit'te 'quality_report'a geçer). Desen: 0040'ın 3. adımı.

Revision ID: 0043
Revises: 0042
"""

from __future__ import annotations

from alembic import op

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None

_OLD = (
    "'classification', 'briefing', 'strategic_report', "
    "'action_extraction', 'okr', 'root_cause'"
)
_NEW = _OLD + ", 'quality_report'"


def upgrade() -> None:
    op.execute(
        "ALTER TABLE llm_call_audit "
        "DROP CONSTRAINT IF EXISTS ck_llm_call_audit_call_type"
    )
    op.execute(
        "ALTER TABLE llm_call_audit ADD CONSTRAINT "
        f"ck_llm_call_audit_call_type CHECK (call_type IN ({_NEW}))"
    )


def downgrade() -> None:
    # Eski kısıt yeni değeri kabul etmez — önce o satırları temizle.
    op.execute(
        "DELETE FROM llm_call_audit WHERE call_type = 'quality_report'"
    )
    op.execute(
        "ALTER TABLE llm_call_audit "
        "DROP CONSTRAINT IF EXISTS ck_llm_call_audit_call_type"
    )
    op.execute(
        "ALTER TABLE llm_call_audit ADD CONSTRAINT "
        f"ck_llm_call_audit_call_type CHECK (call_type IN ({_OLD}))"
    )
