"""api_tokens + admin_tokens — İmga v1 partner API auth (contract §8/§8.6).

Sprint 13 / N+1. AsakAI ⇒ İmga v1 için opak, kiracı-başına Bearer token.
Tasarım: docs/analysis/2026-07-01-apitokenrecord-migration-design.md

İki tablo:
  * api_tokens   — kiracı token'ları (scope=tenant). RLS+FORCE tenant_isolation
                   (her tenant-scoped tablo gibi, 0006 konvansiyonu). Auth-time
                   lookup imga_admin (BYPASSRLS) ile; sonra istek imga_app rolüne
                   devredilir (tasarım §4).
  * admin_tokens — VDD Ops token'ları (scope=ops, §8.6). tenant_id YOK. RLS+FORCE
                   ama policy YOK: imga_app rolü sıfır satır görür (deny-all),
                   yalnız imga_admin (BYPASSRLS) erişir — defense-in-depth.

token_hash = HMAC-SHA256(pepper, plaintext) hex; plaintext asla saklanmaz
(Invitation.token_hash deseni). Önek Stripe-style (imga_live_/imga_stg_/
imga_ops_*), cross-env enforcement app katmanında (§8.1).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0032"
down_revision: str = "0031"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # --- api_tokens: kiracı token'ları (tenant-scoped, RLS+FORCE) --------
    op.create_table(
        "api_tokens",
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
        sa.Column("token_prefix", sa.String(32), nullable=False),
        # HMAC-SHA256 hex = 64 char. plaintext asla saklanmaz.
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("last4", sa.String(4), nullable=False),
        sa.Column(
            "scope",
            sa.String(16),
            nullable=False,
            server_default=sa.text("'tenant'"),
        ),
        sa.Column("label", sa.String(64), nullable=False),
        sa.Column(
            "created_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # ölümsüz token YOK: NOT NULL; app mint'te ≤1 yıl ayarlar.
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.String(128), nullable=True),
        sa.CheckConstraint("scope = 'tenant'", name="ck_api_tokens_scope"),
    )
    op.create_index(
        "ix_api_tokens_token_hash", "api_tokens", ["token_hash"], unique=True
    )
    op.create_index("ix_api_tokens_tenant_id", "api_tokens", ["tenant_id"])
    op.execute("ALTER TABLE api_tokens ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE api_tokens FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON api_tokens
            FOR ALL
            USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
        """
    )

    # --- admin_tokens: ops token'ları (tenant YOK; deny-all RLS, §8.6) --
    op.create_table(
        "admin_tokens",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("token_prefix", sa.String(32), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("last4", sa.String(4), nullable=False),
        sa.Column(
            "scope",
            sa.String(16),
            nullable=False,
            server_default=sa.text("'ops'"),
        ),
        sa.Column("label", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.String(128), nullable=True),
        sa.CheckConstraint("scope = 'ops'", name="ck_admin_tokens_scope"),
    )
    op.create_index(
        "ix_admin_tokens_token_hash", "admin_tokens", ["token_hash"], unique=True
    )
    # RLS+FORCE, policy YOK → imga_app deny-all; imga_admin (BYPASSRLS) erişir.
    op.execute("ALTER TABLE admin_tokens ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE admin_tokens FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("ALTER TABLE admin_tokens DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_admin_tokens_token_hash", table_name="admin_tokens")
    op.drop_table("admin_tokens")

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON api_tokens")
    op.execute("ALTER TABLE api_tokens DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_api_tokens_tenant_id", table_name="api_tokens")
    op.drop_index("ix_api_tokens_token_hash", table_name="api_tokens")
    op.drop_table("api_tokens")
