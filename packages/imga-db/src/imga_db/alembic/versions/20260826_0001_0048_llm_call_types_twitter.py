"""ck_llm_call_audit_call_type — twitter_keywords / twitter_relevance

Revision ID: 0048
Revises: 0047
Create Date: 2026-08-26 00:01:00

Twitter'dan Çek iki yeni LLM çağrısı kazandı (services/
twitter_brand_service): marka anahtar kelime planı (include/exclude/
resmi hesap/özet) ve çekilen gönderilerin marka ile alakasını
değerlendiren hakem. Her ikisi de llm_call_audit'e yazılır; CHECK
kısıtı 0045 kalıbıyla genişler (_OLD = 0045'in _NEW'i).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers
revision: str = "0048"
down_revision: str | Sequence[str] | None = "0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_CALL_TYPES = (
    "'classification', 'briefing', 'strategic_report', "
    "'action_extraction', 'okr', 'root_cause', 'quality_report', "
    "'onboarding_suggest'"
)
_NEW_CALL_TYPES = _OLD_CALL_TYPES + ", 'twitter_keywords', 'twitter_relevance'"


def upgrade() -> None:
    op.execute("ALTER TABLE llm_call_audit DROP CONSTRAINT IF EXISTS ck_llm_call_audit_call_type")
    op.execute(
        "ALTER TABLE llm_call_audit ADD CONSTRAINT "
        f"ck_llm_call_audit_call_type CHECK (call_type IN ({_NEW_CALL_TYPES}))"
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM llm_call_audit WHERE call_type IN ('twitter_keywords', 'twitter_relevance')"
    )
    op.execute("ALTER TABLE llm_call_audit DROP CONSTRAINT IF EXISTS ck_llm_call_audit_call_type")
    op.execute(
        "ALTER TABLE llm_call_audit ADD CONSTRAINT "
        f"ck_llm_call_audit_call_type CHECK (call_type IN ({_OLD_CALL_TYPES}))"
    )
