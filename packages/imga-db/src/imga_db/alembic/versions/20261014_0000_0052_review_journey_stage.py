"""reviews.journey_stage — müşteri yolculuğu aşaması (yorum başına LLM kararı).

Revision ID: 0052
Revises: 0051

Deneyim türü (migration 0041) ile aynı desen: nullable kısa kod kolonu,
CHECK ile sabit sözlük, yalnız dolu satırları kapsayan kısmi indeks.
Kodlar ``imga_core.journey.JOURNEY_STAGES`` ile birebir aynı; eski
satırlar NULL kalır ve yeniden analizle dolar (kategori yedeği YOK —
aşama kategoriden türetilemez).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0052"
down_revision: str | Sequence[str] | None = "0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STAGES = (
    "kesif",
    "degerlendirme",
    "satin_alma",
    "teslimat",
    "kullanim",
    "destek",
    "sadakat",
    "ayrilma",
)


def upgrade() -> None:
    op.add_column("reviews", sa.Column("journey_stage", sa.String(16), nullable=True))
    allowed = ", ".join(f"'{code}'" for code in _STAGES)
    op.create_check_constraint(
        "ck_reviews_journey_stage",
        "reviews",
        f"journey_stage IS NULL OR journey_stage IN ({allowed})",
    )
    op.create_index(
        "ix_reviews_tenant_journey_stage",
        "reviews",
        ["tenant_id", "journey_stage"],
        postgresql_where=sa.text("journey_stage IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_reviews_tenant_journey_stage", table_name="reviews")
    op.drop_constraint("ck_reviews_journey_stage", "reviews", type_="check")
    op.drop_column("reviews", "journey_stage")
