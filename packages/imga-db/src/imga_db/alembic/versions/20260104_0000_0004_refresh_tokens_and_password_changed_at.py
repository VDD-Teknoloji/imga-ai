"""refresh_token_records + users.password_changed_at

Revision ID: 0004
Revises: 0003
Create Date: 2026-01-04 00:00:00

Adds the rotation-chain refresh token table and a password-change
timestamp on users. RLS is intentionally NOT enabled on
refresh_token_records: it is a global table queried by jti (PK), and
authorization is enforced at the application layer via user_id checks.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers
revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "refresh_token_records",
        sa.Column("jti", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("family_id", UUID(as_uuid=True), nullable=False),
        sa.Column("parent_jti", UUID(as_uuid=True), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.String(64), nullable=True),
    )
    op.create_index(
        "ix_refresh_token_records_user_id",
        "refresh_token_records",
        ["user_id"],
    )
    op.create_index(
        "ix_refresh_token_records_family_id",
        "refresh_token_records",
        ["family_id"],
    )
    op.create_index(
        "ix_refresh_token_records_expires_at",
        "refresh_token_records",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_refresh_token_records_expires_at", table_name="refresh_token_records")
    op.drop_index("ix_refresh_token_records_family_id", table_name="refresh_token_records")
    op.drop_index("ix_refresh_token_records_user_id", table_name="refresh_token_records")
    op.drop_table("refresh_token_records")
    op.drop_column("users", "password_changed_at")
