"""tenant_llm_credentials.model — kurum başına LLM model seçimi

Revision ID: 0037
Revises: 0036
Create Date: 2026-08-09 00:00:00

OpenRouter entegrasyonu: kimlik kaydı artık hangi modelin
kullanılacağını da taşır (örn. "openai/gpt-5-mini",
"anthropic/claude-sonnet-4.5"). NULL → sağlayıcının kod içi
varsayılanı (Gemini: gemini-3-flash-preview, OpenRouter:
DEFAULT_OPENROUTER_MODEL). ``provider`` kolonu 0019'dan beri
serbest-string olduğu için şema değişikliği gerektirmiyor —
"openrouter" değeri doğrudan yazılabilir.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0037"
down_revision: str | Sequence[str] | None = "0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tenant_llm_credentials",
        sa.Column("model", sa.String(length=128), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tenant_llm_credentials", "model")
