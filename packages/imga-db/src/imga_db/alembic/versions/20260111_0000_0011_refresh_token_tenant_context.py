"""refresh_token_records.active_tenant_id + .active_role

Revision ID: 0011
Revises: 0010
Create Date: 2026-01-11 00:00:00

Sprint 8.2 hotfix. Production ran into 400 "active tenant context
required" errors ~15 minutes after every fresh login: the access
token (15-min TTL) carried active_tenant_id correctly, but the
silent /auth/refresh rotation reissued the access token with
``active_tenant_id=None`` because the refresh path never knew which
tenant the chain was bound to.

Storing the access-token claims on the refresh record lets
``AuthService.refresh`` carry them across rotations. ``/switch-tenant``
already opens a brand new family with the new values, so per-record
(not per-family) storage is sufficient and avoids a second table.

Both columns nullable because:
  * super-admins logging in without a tenant-membership row legitimately
    have ``active_tenant_id=None``;
  * existing pre-migration rows have no claim metadata to backfill.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers
revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "refresh_token_records",
        sa.Column("active_tenant_id", UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "refresh_token_records",
        sa.Column("active_role", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("refresh_token_records", "active_role")
    op.drop_column("refresh_token_records", "active_tenant_id")
