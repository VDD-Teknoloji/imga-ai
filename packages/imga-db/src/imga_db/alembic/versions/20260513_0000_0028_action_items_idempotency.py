"""Sprint 9.5 B2 — action_items idempotency

Revision ID: 0028
Revises: 0027
Create Date: 2026-05-13 00:00:00

Adds an ``idempotency_key`` column + partial UNIQUE index to
``action_items`` so retries of ``POST /tenants/me/action-items``
with the same HTTP ``Idempotency-Key`` header return the row
that already exists instead of inserting a duplicate. Pattern
mirrors the Stripe / Idempotency-Key RFC (draft) shape: the
column is nullable (legacy + non-idempotent clients land NULL)
and the UNIQUE is partial — ``WHERE idempotency_key IS NOT
NULL`` — so NULL rows don't collide with each other and only
the genuinely-keyed rows participate in the constraint.

The other half of Sprint 9.5 B2 — refactoring
``extract_from_report`` to route through ActionExtractionService
instead of its current manual INSERT loop — is a code-only
change that doesn't need a migration; the existing
``action_extraction_log`` table from migration 0024 already
covers that path's dedup.

Note on numbering: the Sprint 9.5 master prompt assigned
``0028`` to the invitation-hijack fix and ``0029`` to this
migration. Sprint 9.5 ships Faz 2 (B-cluster, this commit)
before Faz 3 (A-cluster, invitation hijack), so the alembic
chain follows commit order: 0028 here, 0029 = invitation
hijack. The prompt's two slots stay, just swapped — no
schema-content change.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "action_items",
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
    )
    op.create_index(
        "uq_action_items_tenant_idempotency_key",
        "action_items",
        ["tenant_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_action_items_tenant_idempotency_key",
        table_name="action_items",
    )
    op.drop_column("action_items", "idempotency_key")
