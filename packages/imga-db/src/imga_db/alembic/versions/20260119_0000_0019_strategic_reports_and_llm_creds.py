"""strategic_reports + tenant_llm_credentials + prompt_templates + tenant context

Revision ID: 0019
Revises: 0018
Create Date: 2026-01-19 00:00:00

Sprint 8.3.6 / Alt-Faz 8.3.6.1.D. Schema for SWOT + OKR generation:

  * ``tenants`` gains industry / company_size / business_description
    so prompt injection has tenant context (industry-specific
    strengths / weaknesses surface).
  * ``tenant_llm_credentials`` — encrypted (Fernet) per-tenant LLM
    API keys, ordered by priority for the multi-key rotator.
  * ``strategic_reports`` — historical SWOT + OKR runs, with the
    input stats hash + the output payload for replay / cache lookup.
    OKR rows that descend from a SWOT carry ``source_report_id``.
  * ``prompt_templates`` — system-level template registry. Seeded
    here with placeholders for ``swot_v1`` and ``okr_v1``; the real
    prompts + response schemas land via UPDATE in alt-faz 8.3.6.3 /
    8.3.6.4 once the prompt engineering is finalised.

RLS+FORCE on the two tenant-scoped tables (same
``app.current_tenant_id`` setting every other tenant table uses since
migration 0001 — *not* ``imga.tenant_id`` despite what the master
prompt drafted; the mismatch would break every policy lookup).
``prompt_templates`` is global (no RLS).

Bug 2 patch (Sprint 8.3.5.6 round-1 follow-up): the same
``UPDATE category_taxonomies SET keywords = keywords || ...`` block
adds the most-asked tense variants for six categories. The full fix
+ taxonomy edit UI lands in Sprint 8.3.7; this migration unblocks
the heuristic on present-tense Türkçe phrasings ("kargom gelmiyor",
"ulaşamıyorum") that the legacy past-tense seed missed.

Forward-only: ``downgrade()`` drops the new tables + columns but
cannot reconstruct which keywords were appended (the JSONB ``||`` is
non-reversible). That matches the project standard since Sprint 8.3.4.
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
revision: str = "0019"
down_revision: str | Sequence[str] | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Sprint 8.3.6.1 / Bug 2 patch — kritik tense varyantları. The full
# coverage matrix lands in Sprint 8.3.7 alongside the taxonomy edit UI;
# this dict is the minimum set so common present-tense phrasings ("...
# gelmiyor", "ulaşamıyorum") match the heuristic without users editing
# their own taxonomy.
_TENSE_VARIANT_PATCHES: dict[str, list[str]] = {
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


# Placeholder prompt templates. Real prompts + finalised schemas land
# in Sprint 8.3.6.3 (SWOT) and 8.3.6.4 (OKR) via in-place UPDATE so we
# don't have to ship a no-op schema migration just to swap a string.
_SWOT_PLACEHOLDER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "_placeholder": "Real schema lands in Sprint 8.3.6.3",
}
_OKR_PLACEHOLDER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "_placeholder": "Real schema lands in Sprint 8.3.6.4",
}


def upgrade() -> None:
    # 1. tenants extension — nullable so existing rows survive without
    # backfill; tenant onboarding flow + /settings/profile fill these
    # in (Sprint 8.3.6.6 frontend lands the form).
    op.add_column(
        "tenants",
        sa.Column("industry", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "tenants",
        sa.Column("industry_other_text", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "tenants",
        sa.Column("company_size", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "tenants",
        sa.Column("business_description", sa.String(length=500), nullable=True),
    )

    # 2. tenant_llm_credentials — encrypted_value is the Fernet token
    # bytes from imga_core.security.encryption.encrypt(). Priority 0 is
    # primary; 1+ are fallback in rotation order. Unique constraint on
    # (tenant, provider, priority) prevents two "primary" rows.
    op.create_table(
        "tenant_llm_credentials",
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
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("label", sa.String(length=64), nullable=False),
        sa.Column("encrypted_value", sa.LargeBinary(), nullable=False),
        sa.Column(
            "priority",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "last_failed_at", sa.DateTime(timezone=True), nullable=True
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
        sa.UniqueConstraint(
            "tenant_id", "provider", "priority",
            name="uq_tenant_provider_priority",
        ),
    )
    op.create_index(
        "ix_tenant_llm_credentials_tenant_priority",
        "tenant_llm_credentials",
        ["tenant_id", "priority"],
    )

    # 3. strategic_reports — historical SWOT + OKR runs. ``input_stats``
    # is the JSONB analytics snapshot the LLM was fed; ``output_payload``
    # is the structured response. ``source_report_id`` is non-null on
    # OKR rows that descended from a SWOT (chain). ``model_name`` +
    # ``token_usage`` + ``generation_duration_ms`` give us cost / latency
    # observability without a separate metrics table.
    op.create_table(
        "strategic_reports",
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
        sa.Column("report_type", sa.String(length=16), nullable=False),
        sa.Column("date_from", sa.Date(), nullable=True),
        sa.Column("date_to", sa.Date(), nullable=True),
        sa.Column("input_stats", JSONB(), nullable=False),
        sa.Column("output_payload", JSONB(), nullable=False),
        sa.Column(
            "source_report_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("strategic_reports.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("model_name", sa.String(length=64), nullable=False),
        sa.Column("token_usage", JSONB(), nullable=True),
        sa.Column(
            "generation_duration_ms", sa.Integer(), nullable=True
        ),
        sa.Column(
            "created_by_user_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_strategic_reports_tenant_type_created",
        "strategic_reports",
        ["tenant_id", "report_type", "created_at"],
    )

    # 4. prompt_templates — system-level (no RLS). One row per
    # (template_key) version; updates in place via UPDATE so the
    # service can pin the active version.
    op.create_table(
        "prompt_templates",
        sa.Column(
            "id",
            PG_UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "template_key", sa.String(length=64), nullable=False, unique=True
        ),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("user_prompt_template", sa.Text(), nullable=False),
        sa.Column("response_schema", JSONB(), nullable=False),
        sa.Column("model_name", sa.String(length=64), nullable=False),
        sa.Column(
            "temperature",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0.2"),
        ),
        sa.Column(
            "top_p",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0.9"),
        ),
        sa.Column(
            "max_output_tokens",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("8192"),
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
    )

    # 5. RLS+FORCE on the two tenant-scoped tables. Same
    # ``app.current_tenant_id`` setting every migration since 0001
    # uses; the master prompt suggested ``imga.tenant_id`` but that
    # would have broken every existing policy.
    op.execute(
        "ALTER TABLE tenant_llm_credentials ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        "ALTER TABLE tenant_llm_credentials FORCE ROW LEVEL SECURITY"
    )
    op.execute(
        "CREATE POLICY tenant_isolation ON tenant_llm_credentials "
        "USING (tenant_id = current_setting('app.current_tenant_id')::uuid)"
    )

    op.execute("ALTER TABLE strategic_reports ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE strategic_reports FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON strategic_reports "
        "USING (tenant_id = current_setting('app.current_tenant_id')::uuid)"
    )

    # 6. Tense variant patches — append to existing taxonomies. Uses
    # ``||`` JSONB concatenation; new tenants get the patches via the
    # default seed update in taxonomy_service (Alt-Faz 8.3.6.1.E).
    bind = op.get_bind()
    for code, patches in _TENSE_VARIANT_PATCHES.items():
        bind.execute(
            sa.text(
                "UPDATE category_taxonomies "
                "SET keywords = keywords || CAST(:patch AS jsonb) "
                "WHERE code = :code"
            ),
            {"code": code, "patch": json.dumps(patches)},
        )

    # 7. Placeholder prompt templates. Real prompts land in Sprint
    # 8.3.6.3 (SWOT) / 8.3.6.4 (OKR) via UPDATE.
    bind.execute(
        sa.text(
            "INSERT INTO prompt_templates ("
            " template_key, system_prompt, user_prompt_template, "
            " response_schema, model_name, is_active"
            ") VALUES ("
            " :key, :sys, :user, CAST(:schema AS jsonb), :model, false"
            ")"
        ),
        {
            "key": "swot_v1",
            "sys": "[placeholder] SWOT system prompt — Sprint 8.3.6.3",
            "user": "[placeholder] SWOT user prompt — Sprint 8.3.6.3",
            "schema": json.dumps(_SWOT_PLACEHOLDER_SCHEMA),
            "model": "gemini-2.5-pro",
        },
    )
    bind.execute(
        sa.text(
            "INSERT INTO prompt_templates ("
            " template_key, system_prompt, user_prompt_template, "
            " response_schema, model_name, is_active"
            ") VALUES ("
            " :key, :sys, :user, CAST(:schema AS jsonb), :model, false"
            ")"
        ),
        {
            "key": "okr_v1",
            "sys": "[placeholder] OKR system prompt — Sprint 8.3.6.4",
            "user": "[placeholder] OKR user prompt — Sprint 8.3.6.4",
            "schema": json.dumps(_OKR_PLACEHOLDER_SCHEMA),
            "model": "gemini-2.5-pro",
        },
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON strategic_reports")
    op.execute("ALTER TABLE strategic_reports DISABLE ROW LEVEL SECURITY")
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation ON tenant_llm_credentials"
    )
    op.execute(
        "ALTER TABLE tenant_llm_credentials DISABLE ROW LEVEL SECURITY"
    )

    op.drop_table("prompt_templates")
    op.drop_index(
        "ix_strategic_reports_tenant_type_created",
        table_name="strategic_reports",
    )
    op.drop_table("strategic_reports")
    op.drop_index(
        "ix_tenant_llm_credentials_tenant_priority",
        table_name="tenant_llm_credentials",
    )
    op.drop_table("tenant_llm_credentials")
    op.drop_column("tenants", "business_description")
    op.drop_column("tenants", "company_size")
    op.drop_column("tenants", "industry_other_text")
    op.drop_column("tenants", "industry")
    # Tense variant JSONB ``||`` patches are non-reversible — the
    # downgrade leaves the appended keywords in place. Forward-only
    # convention since Sprint 8.3.4.
