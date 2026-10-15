"""ck_llm_call_audit_call_type — 'assistant' (veri asistanı) türü.

Revision ID: 0053
Revises: 0052

Migration 0048 ile aynı desen: CHECK düşürülüp genişletilmiş listeyle
yeniden kurulur. Geri alma yeni türdeki satırları siler (denetim kaydı
kaybı kabul edilmiş; constraint aksi hâlde geri kurulamaz).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0053"
down_revision: str | Sequence[str] | None = "0052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_CALL_TYPES = (
    "'classification', 'briefing', 'strategic_report', 'action_extraction', 'okr', "
    "'root_cause', 'quality_report', 'onboarding_suggest', "
    "'twitter_keywords', 'twitter_relevance'"
)
_NEW_CALL_TYPES = _OLD_CALL_TYPES + ", 'assistant'"


def upgrade() -> None:
    op.execute("ALTER TABLE llm_call_audit DROP CONSTRAINT IF EXISTS ck_llm_call_audit_call_type")
    op.execute(
        "ALTER TABLE llm_call_audit ADD CONSTRAINT "
        f"ck_llm_call_audit_call_type CHECK (call_type IN ({_NEW_CALL_TYPES}))"
    )


def downgrade() -> None:
    op.execute("DELETE FROM llm_call_audit WHERE call_type = 'assistant'")
    op.execute("ALTER TABLE llm_call_audit DROP CONSTRAINT IF EXISTS ck_llm_call_audit_call_type")
    op.execute(
        "ALTER TABLE llm_call_audit ADD CONSTRAINT "
        f"ck_llm_call_audit_call_type CHECK (call_type IN ({_OLD_CALL_TYPES}))"
    )
