"""taxonomy edit support + sla_rules + F18 canonical seed

Revision ID: 0020
Revises: 0019
Create Date: 2026-01-20 00:00:00

Sprint 8.3.7-A. Three migrations bundled because they ship as one
deployable unit:

  1. ``category_taxonomies.parent_code`` (nullable VARCHAR) — optional
     hierarchy hint for the Sprint 8.3.7+ tree UI. No FK constraint:
     the taxonomy uniqueness is on ``(tenant_id, code)``, so a real FK
     would need a composite. Application validates the reference.
     ``is_default_seed`` already covers the "system-protected" concept
     the master prompt called ``is_system`` — kept the existing column
     name to avoid two columns with identical semantics; the API
     surface exposes it as ``is_system``.

  2. ``taxonomy_edit_audit`` — append-only audit trail for every
     create/update/delete/restore on category_taxonomies. before_state
     and after_state are JSONB snapshots so the UI can render diffs
     without joining back to the live row. RLS+FORCE on tenant_id like
     every tenant-scoped table since 0001.

  3. ``sla_rules`` — tenant-configurable SLA threshold rules. Match
     conditions on priority / taxonomy / company-perspective / NPS;
     thresholds on response time and/or resolution time; action_type
     is initially limited to ``warn_only`` (Sprint 8.3.9 wires
     ``create_ticket``, Sprint 8.6 wires ``notify_email``). RLS+FORCE
     and a CHECK that requires at least one threshold be set so a
     "matches everything, does nothing" rule can't sneak in.

Forward-only (Sprint 8.3.5.2 dersi). The downgrade path drops tables
and the column but does NOT touch the F18 keyword backfill — those
already shipped in 0019 and can't be cleanly reverted.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

# revision identifiers
revision: str = "0020"
down_revision: str | Sequence[str] | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# F18 canonical tense-variant patches. These shipped in 0019 as a
# one-off JSONB || patch; 0020 mirrors them so the migration history
# carries the canonical set in one place a future maintainer can grep
# for. Idempotent re-apply: any tenant created between 0019 and 0020
# gets the same coverage; tenants who already have the patches see no
# change because each ``-`` then ``||`` step composes to identity.
_F18_CANONICAL_PATCHES: dict[str, list[str]] = {
    "shipment_not_arrived": [
        "gelmiyor", "ulaşamıyorum", "ulaşamadı", "ulaşmıyor",
    ],
    "broken_damaged": ["kırılmış", "deforme olmuş"],
    "refund_not_received": ["param yatmıyor", "iade gelmedi henüz"],
    "cancel_request": ["iptal istiyorum", "iptal edebilir miyim"],
    "address_change": [
        "adresimi değiştirebilir miyim", "yanlış adres yazdım",
    ],
    "how_to_return": ["nasıl iade edeceğim", "iade prosedürü"],
}


def upgrade() -> None:
    # 1. category_taxonomies — parent_code + is_active --------------------
    op.add_column(
        "category_taxonomies",
        sa.Column("parent_code", sa.String(length=64), nullable=True),
    )
    # is_active is the soft-delete flag the DELETE endpoint flips to
    # ``false``. Existing rows stay active by default; the
    # NOT NULL + server_default combo backfills cleanly for live
    # tables without a manual UPDATE.
    op.add_column(
        "category_taxonomies",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )

    # 2. taxonomy_edit_audit ----------------------------------------------
    op.create_table(
        "taxonomy_edit_audit",
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
        sa.Column(
            # NULL when an automated path (seeding, migration backfill)
            # mutates the row — UI-driven edits always carry a user.
            "user_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            # No FK on taxonomy_id: a hard delete (future) wouldn't
            # cascade-clear audit rows. The id is meaningful even after
            # the row is gone.
            "taxonomy_id",
            PG_UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column(
            "before_state",
            JSONB(),
            nullable=True,
        ),
        sa.Column(
            "after_state",
            JSONB(),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "action IN ('create', 'update', 'delete', 'restore')",
            name="ck_taxonomy_audit_action",
        ),
    )
    op.create_index(
        "ix_taxonomy_edit_audit_tenant_created",
        "taxonomy_edit_audit",
        ["tenant_id", sa.text("created_at DESC")],
    )

    op.execute("ALTER TABLE taxonomy_edit_audit ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE taxonomy_edit_audit FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON taxonomy_edit_audit "
        "USING (tenant_id = current_setting('app.current_tenant_id')::uuid)"
    )

    # 3. sla_rules --------------------------------------------------------
    op.create_table(
        "sla_rules",
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
        sa.Column("name", sa.String(length=128), nullable=False),
        # Match conditions — NULL means "any" for that dimension.
        sa.Column("match_priority", sa.String(length=16), nullable=True),
        sa.Column(
            "match_taxonomy_codes",
            sa.ARRAY(sa.String(length=64)),
            nullable=True,
        ),
        sa.Column(
            "match_company_perspective_codes",
            sa.ARRAY(sa.String(length=64)),
            nullable=True,
        ),
        sa.Column("match_nps_score_max", sa.Integer(), nullable=True),
        # Thresholds — at least one must be set (CHECK below).
        sa.Column("response_sla_minutes", sa.Integer(), nullable=True),
        sa.Column("resolution_sla_minutes", sa.Integer(), nullable=True),
        # Action.
        sa.Column("action_type", sa.String(length=32), nullable=False),
        sa.Column(
            "action_config",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
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
            "response_sla_minutes IS NOT NULL OR "
            "resolution_sla_minutes IS NOT NULL",
            name="ck_sla_rules_threshold_required",
        ),
        sa.CheckConstraint(
            "action_type IN ("
            "'warn_only', 'create_ticket', 'escalate', 'notify_email')",
            name="ck_sla_rules_action_type",
        ),
        sa.CheckConstraint(
            "match_priority IS NULL OR match_priority IN ("
            "'low', 'normal', 'high', 'urgent')",
            name="ck_sla_rules_match_priority",
        ),
    )
    op.create_index(
        "ix_sla_rules_tenant_active",
        "sla_rules",
        ["tenant_id", "is_active"],
    )

    op.execute("ALTER TABLE sla_rules ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE sla_rules FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON sla_rules "
        "USING (tenant_id = current_setting('app.current_tenant_id')::uuid)"
    )

    # 4. F18 canonical re-apply (idempotent) ------------------------------
    # Strip the patch keywords first (handles any stray duplicates from
    # 0019), then append. ``-`` ignores missing elements. Same pattern
    # as 0019.
    bind = op.get_bind()
    for code, patches in _F18_CANONICAL_PATCHES.items():
        for kw in patches:
            bind.execute(
                sa.text(
                    "UPDATE category_taxonomies "
                    "SET keywords = keywords - :kw, "
                    "    updated_at = now() "
                    "WHERE code = :code "
                    "  AND keywords @> CAST(:kw_array AS jsonb)"
                ),
                {
                    "code": code,
                    "kw": kw,
                    "kw_array": json.dumps([kw]),
                },
            )
        bind.execute(
            sa.text(
                "UPDATE category_taxonomies "
                "SET keywords = keywords || CAST(:patch AS jsonb), "
                "    updated_at = now() "
                "WHERE code = :code"
            ),
            {
                "code": code,
                "patch": json.dumps(patches),
            },
        )


def downgrade() -> None:
    # F18 patches not reverted — see module docstring.
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON sla_rules")
    op.execute("ALTER TABLE sla_rules DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_sla_rules_tenant_active", table_name="sla_rules")
    op.drop_table("sla_rules")

    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation ON taxonomy_edit_audit"
    )
    op.execute(
        "ALTER TABLE taxonomy_edit_audit DISABLE ROW LEVEL SECURITY"
    )
    op.drop_index(
        "ix_taxonomy_edit_audit_tenant_created",
        table_name="taxonomy_edit_audit",
    )
    op.drop_table("taxonomy_edit_audit")

    op.drop_column("category_taxonomies", "is_active")
    op.drop_column("category_taxonomies", "parent_code")


__all__: list[Any] = []
