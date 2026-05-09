"""Sprint 9.3 — LLM governance, business dimensions, decision audit, prompt templates v2

Revision ID: 0027
Revises: 0026
Create Date: 2026-05-20 00:00:00

Final demo-prep sprint. Four C-Level deliverables share Migration
0027 because they form a single contract: every LLM call is logged
(governance), every review can be tagged with business impact
dimensions, every operator decision lands in an audit log, and
every prompt is overrideable per tenant.

  1. ``llm_call_audit`` — high-volume row-per-call log with prompt
     hash, model meta, token usage, error metadata. RLS+FORCE on
     tenant_id; partial index on errors for quick "show me last
     week's failures" queries. Comment notes the future
     yearly-partition path; we ship a regular table now and let
     pg_partman / a Sprint 10 migration take over once volumes
     warrant.

  2. Business impact dimensions — four nullable columns on
     ``reviews`` (business_segment / product_line / channel /
     customer_tier) plus a ``tenant_business_dimensions`` config
     table. Existing rows stay NULL (online-safe ALTER TABLE);
     new uploads get the values via the tenant's CSV column
     mapping. The four partial indexes keep the dashboard's
     ``GROUP BY dimension`` queries narrow.

  3. ``decision_audit_log`` — operator action audit (briefing
     acknowledged, strategic report approved, KPI goal set, ...).
     Distinct from ``llm_call_audit``: this is the human side of
     the audit story.

  4. ``prompt_templates`` extension — adds ``version``,
     ``tenant_id``, ``is_default``, ``required_variables``,
     ``created_by_user_id``. Existing rows back-fill ``version='v1'``
     + ``tenant_id=NULL`` (global) + ``is_default=true`` so
     SwotService / OkrService keep finding their templates
     unchanged. RLS+FORCE so tenant overrides stay isolated.
     ``is_active`` is preserved (existing service code reads it);
     the new ``is_default`` is for "which version of this
     template_key fires today".

Forward-only — Sprint 8.3.5.2 dersi.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision: str = "0027"
down_revision: str | Sequence[str] | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_LLM_CALL_TYPES = (
    "classification",
    "briefing",
    "strategic_report",
    "action_extraction",
    "okr",
)
_LLM_ERROR_TYPES = (
    "timeout",
    "rate_limit",
    "api_error",
    "parse_error",
    "invalid_key",
    "all_keys_exhausted",
    "blocked",
    "token_limit",
    "other",
)
_DIMENSION_KEYS = (
    "business_segment",
    "product_line",
    "channel",
    "customer_tier",
)
_DECISION_TYPES = (
    "briefing_acknowledged",
    "briefing_dismissed",
    "strategic_report_approved",
    "strategic_report_rejected",
    "action_item_assigned",
    "action_item_priority_changed",
    "sla_rule_changed",
    "kpi_goal_set",
    "webhook_dispatched_manually",
    "tenant_setting_changed",
    "prompt_template_overridden",
)


def upgrade() -> None:
    # 1. llm_call_audit ------------------------------------------------
    op.create_table(
        "llm_call_audit",
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
        sa.Column("call_type", sa.Text(), nullable=False),
        sa.Column("related_entity_type", sa.Text(), nullable=True),
        sa.Column("related_entity_id", PG_UUID(as_uuid=True), nullable=True),
        sa.Column("prompt_template_key", sa.Text(), nullable=True),
        sa.Column("prompt_template_version", sa.Text(), nullable=True),
        sa.Column("prompt_hash", sa.Text(), nullable=False),
        sa.Column("model_name", sa.Text(), nullable=False),
        sa.Column("model_provider", sa.Text(), nullable=False),
        sa.Column("model_temperature", sa.Numeric(), nullable=True),
        sa.Column("model_max_tokens", sa.Integer(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column(
            "total_tokens",
            sa.Integer(),
            sa.Computed(
                "COALESCE(input_tokens, 0) + COALESCE(output_tokens, 0)",
                persisted=True,
            ),
            nullable=True,
        ),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("error_type", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "fallback_used",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
        sa.Column(
            "actor_user_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "call_type IN ("
            + ", ".join(f"'{t}'" for t in _LLM_CALL_TYPES)
            + ")",
            name="ck_llm_call_audit_call_type",
        ),
        sa.CheckConstraint(
            "error_type IS NULL OR error_type IN ("
            + ", ".join(f"'{t}'" for t in _LLM_ERROR_TYPES)
            + ")",
            name="ck_llm_call_audit_error_type",
        ),
    )
    op.create_index(
        "idx_llm_call_audit_tenant_type",
        "llm_call_audit",
        ["tenant_id", "call_type", sa.text("created_at DESC")],
    )
    op.create_index(
        "idx_llm_call_audit_entity",
        "llm_call_audit",
        ["related_entity_type", "related_entity_id"],
    )
    op.create_index(
        "idx_llm_call_audit_errors",
        "llm_call_audit",
        ["tenant_id", sa.text("created_at DESC")],
        postgresql_where=sa.text("success = FALSE"),
    )
    op.execute(
        "COMMENT ON TABLE llm_call_audit IS "
        "'Sprint 9.3 A — high-volume LLM call log. Future: "
        "partition by created_at year via pg_partman.'"
    )
    op.execute("ALTER TABLE llm_call_audit ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE llm_call_audit FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON llm_call_audit "
        "USING (tenant_id = current_setting('app.current_tenant_id')::uuid)"
    )

    # 2. business dimensions -----------------------------------------
    op.add_column(
        "reviews",
        sa.Column("business_segment", sa.Text(), nullable=True),
    )
    op.add_column(
        "reviews", sa.Column("product_line", sa.Text(), nullable=True)
    )
    op.add_column("reviews", sa.Column("channel", sa.Text(), nullable=True))
    op.add_column(
        "reviews", sa.Column("customer_tier", sa.Text(), nullable=True)
    )
    for col in ("business_segment", "product_line", "channel", "customer_tier"):
        op.create_index(
            f"idx_reviews_{col}",
            "reviews",
            ["tenant_id", col],
            postgresql_where=sa.text(f"{col} IS NOT NULL"),
        )

    op.create_table(
        "tenant_business_dimensions",
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
        sa.Column("dimension", sa.Text(), nullable=False),
        sa.Column("display_label", sa.Text(), nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("TRUE"),
        ),
        sa.Column(
            "allowed_values",
            ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("ARRAY[]::text[]"),
        ),
        sa.Column("csv_column_mapping", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint(
            "tenant_id", "dimension", name="uq_tenant_business_dimensions_dim"
        ),
        sa.CheckConstraint(
            "dimension IN ("
            + ", ".join(f"'{d}'" for d in _DIMENSION_KEYS)
            + ")",
            name="ck_tenant_business_dimensions_key",
        ),
    )
    op.execute(
        "ALTER TABLE tenant_business_dimensions ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        "ALTER TABLE tenant_business_dimensions FORCE ROW LEVEL SECURITY"
    )
    op.execute(
        "CREATE POLICY tenant_isolation ON tenant_business_dimensions "
        "USING (tenant_id = current_setting('app.current_tenant_id')::uuid)"
    )

    # 3. decision_audit_log ------------------------------------------
    op.create_table(
        "decision_audit_log",
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
        sa.Column("decision_type", sa.Text(), nullable=False),
        sa.Column("related_entity_type", sa.Text(), nullable=False),
        sa.Column(
            "related_entity_id", PG_UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "actor_user_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "payload",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "decision_type IN ("
            + ", ".join(f"'{d}'" for d in _DECISION_TYPES)
            + ")",
            name="ck_decision_audit_log_type",
        ),
    )
    op.create_index(
        "idx_decision_audit_tenant_actor",
        "decision_audit_log",
        ["tenant_id", "actor_user_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "idx_decision_audit_entity",
        "decision_audit_log",
        [
            "related_entity_type",
            "related_entity_id",
            sa.text("created_at DESC"),
        ],
    )
    op.execute("ALTER TABLE decision_audit_log ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE decision_audit_log FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON decision_audit_log "
        "USING (tenant_id = current_setting('app.current_tenant_id')::uuid)"
    )

    # 4. prompt_templates extension (versioning + tenant override) ---
    # Drop the legacy UNIQUE on template_key alone; replace with a
    # composite (template_key, version, tenant_id) so a tenant can
    # have a v2 override while the global v1 still serves other
    # tenants.
    op.drop_constraint(
        "prompt_templates_template_key_key",
        "prompt_templates",
        type_="unique",
    )
    op.add_column(
        "prompt_templates",
        sa.Column(
            "version",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'v1'"),
        ),
    )
    op.add_column(
        "prompt_templates",
        sa.Column(
            "tenant_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.add_column(
        "prompt_templates",
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("TRUE"),
        ),
    )
    op.add_column(
        "prompt_templates",
        sa.Column(
            "required_variables",
            ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("ARRAY[]::text[]"),
        ),
    )
    op.add_column(
        "prompt_templates",
        sa.Column(
            "created_by_user_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    # Existing rows are global defaults — tenant_id stays NULL,
    # version='v1' (server_default). The composite UNIQUE permits
    # multiple non-default versions for the same key + tenant.
    op.create_unique_constraint(
        "uq_prompt_templates_key_version_tenant",
        "prompt_templates",
        ["template_key", "version", "tenant_id"],
        postgresql_nulls_not_distinct=True,
    )
    # Single default per (template_key, tenant_id). Postgres EXCLUDE
    # constraint with COALESCE handles the NULL tenant_id case so a
    # global default and a tenant override can both exist as defaults
    # for the same template_key.
    op.execute(
        "CREATE UNIQUE INDEX uq_prompt_templates_default "
        "ON prompt_templates(template_key, COALESCE(tenant_id::text, '')) "
        "WHERE is_default = TRUE"
    )
    op.create_index(
        "idx_prompt_templates_lookup",
        "prompt_templates",
        ["template_key", "tenant_id", "is_default"],
        postgresql_where=sa.text("is_active = TRUE"),
    )

    # RLS — global rows (tenant_id IS NULL) readable by everyone;
    # tenant-overrides isolated. Writes are tenant-scoped (admin
    # routes set the tenant context before insert).
    op.execute("ALTER TABLE prompt_templates ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE prompt_templates FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY prompt_templates_read ON prompt_templates "
        "FOR SELECT "
        "USING (tenant_id IS NULL "
        "OR tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    )
    op.execute(
        "CREATE POLICY prompt_templates_write ON prompt_templates "
        "FOR ALL "
        "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    )


def downgrade() -> None:
    raise NotImplementedError("Sprint 9.3 is forward-only")
