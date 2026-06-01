"""Sprint 9.7 — trial tenant + trial_analyses

Revision ID: 0030
Revises: 0029
Create Date: 2026-06-01 00:00:00

Adds the "trial" tenant + ``trial_analyses`` table feeding the public
trial endpoint (POST /public/trial/analyze) that the imga.ai marketing
site proxies into. The endpoint runs ≤100-row analyses for email-
verified visitors and surfaces a teaser (sentiment dist, top
categories, sample reviews, NPS estimate) — full reports require a
sales contact.

Two design calls worth pinning at the migration layer:

  1. **Deterministic trial tenant_id** — uuid
     ``00000000-0000-0000-0000-000000000777``. Code that runs trial
     analyses references this constant directly (no slug-lookup
     round-trip); the migration seeds the row at known coordinates
     so dev / staging / prod all share the id. plan_tier='trial',
     automation_mode='full_auto' (no human review on demo data).

  2. **KVKK posture** — ``trial_analyses`` carries only the
     aggregated result payload (sentiment distribution, top
     categories, *sampled* review excerpts). No row-level review
     persistence. ``expires_at`` is created_at + 24h; the
     endpoint deletes expired rows lazily on every new request, so
     no GC worker is needed. The aggregate payload during the
     24h idempotency window is the only piece of trial-user
     content we hold.

Adds an index on ``expires_at`` for the lazy GC sweep + a partial
UNIQUE on ``(email)`` so duplicate trials hit the idempotency
return path rather than INSERTing a second row.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID as PyUUID

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0030"
down_revision: str | Sequence[str] | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Sprint 9.7 — well-known trial tenant id, mirrored in
# imga_api.services.trial_analysis_service so the code path doesn't
# need to look it up by slug.
TRIAL_TENANT_ID = PyUUID("00000000-0000-0000-0000-000000000777")


def upgrade() -> None:
    # Seed the trial tenant. ON CONFLICT DO NOTHING keeps the
    # migration idempotent on a re-run; the seed is by id, not
    # autoincrement, so a re-apply doesn't create a second row.
    # Bind as uuid (not VARCHAR) so the asyncpg driver picks the
    # right OID. Without the explicit cast the param is sent as a
    # character varying and postgres throws "column 'id' is of type
    # uuid but expression is of type character varying".
    op.execute(
        sa.text(
            """
            INSERT INTO tenants (id, name, slug, plan_tier, automation_mode)
            VALUES (
                CAST(:tid AS uuid),
                'İmga Trial (public demo)',
                'trial',
                'trial',
                'full_auto'
            )
            ON CONFLICT (id) DO NOTHING
            """
        ).bindparams(tid=str(TRIAL_TENANT_ID))
    )

    op.create_table(
        "trial_analyses",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column(
            "request_id",
            UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("file_name", sa.Text(), nullable=True),
        sa.Column("total_rows", sa.Integer(), nullable=False),
        sa.Column(
            "sentiment_distribution",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "top_categories",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "sample_reviews",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("nps_estimate", sa.Integer(), nullable=True),
        sa.Column("processing_time_ms", sa.Integer(), nullable=True),
        sa.Column("trial_user_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_trial_analyses_tenant_id", "trial_analyses", ["tenant_id"]
    )
    op.create_index(
        "ix_trial_analyses_email_unique",
        "trial_analyses",
        ["email"],
        unique=True,
    )
    op.create_index(
        "ix_trial_analyses_expires_at",
        "trial_analyses",
        ["expires_at"],
    )

    # RLS+FORCE, matching every other tenant-scoped table in the
    # schema (Sprint 6.0 baseline + Sprint 9.5.1 invitation tweaks).
    # The trial tenant is the only tenant_id ever inserted here, but
    # the policy still reads current_setting so a sloppy session
    # without context can't accidentally cross-read.
    op.execute("ALTER TABLE trial_analyses ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE trial_analyses FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON trial_analyses
            FOR ALL
            USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON trial_analyses")
    op.execute("ALTER TABLE trial_analyses DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_trial_analyses_expires_at", table_name="trial_analyses")
    op.drop_index(
        "ix_trial_analyses_email_unique", table_name="trial_analyses"
    )
    op.drop_index("ix_trial_analyses_tenant_id", table_name="trial_analyses")
    op.drop_table("trial_analyses")
    # Note: we do NOT delete the trial tenant on downgrade. The row
    # has no FKs left after the table drop and removing it would
    # break a re-apply of this migration on a partial state.
