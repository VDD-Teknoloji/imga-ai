"""api_tenant_config + api_request_log — İmga v1 partner API (contract §4A/§6/§4.9).

Sprint 13 / N+1. AsakAI ⇒ İmga v1'in tenant config + istek/kullanım kaydı.

  * api_tenant_config — partner'a özel tenant ayarı: contact_email,
    quota_tokens_per_day (default 2M, §6), residency_locks JSONB (§4A.1).
    Mevcut ``tenants`` modelinde bu alanlar yok; ayrı 1:1 tablo.
  * api_request_log — her v1 analyze isteği: use_case, processed_in, token
    sayaçları, cost_try, status + context/response SHA-256 + 200-char özet.
    §4A.2 usage, §6 billing, §4.9 export, §4.8 silme HEPSİ bunun üstünde.
    **Ham prompt/response gövdesi SAKLANMAZ** (KVKK veri-minimizasyonu; goal
    §4 "raw body log'a yazma") — yalnız hash + özet.

İkisi de RLS+FORCE tenant_isolation (kendi tenant); ops BYPASSRLS ile yönetir.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0033"
down_revision: str = "0032"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # --- api_tenant_config (1:1 tenant) --------------------------------
    op.create_table(
        "api_tenant_config",
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
        sa.Column("contact_email", sa.String(320), nullable=True),
        sa.Column(
            "quota_tokens_per_day",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("2000000"),
        ),
        # Partial<Record<UseCase, "tr"|"outbound">> — §4A.1 (v1.3'te no-op).
        sa.Column("residency_locks", JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("tenant_id", name="uq_api_tenant_config_tenant"),
    )
    op.execute("ALTER TABLE api_tenant_config ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE api_tenant_config FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON api_tenant_config
            FOR ALL
            USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
        """
    )

    # --- api_request_log (usage / billing / export / erasure) ----------
    op.create_table(
        "api_request_log",
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
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("client_request_id", UUID(as_uuid=True), nullable=True),
        sa.Column("session_id", UUID(as_uuid=True), nullable=True),
        sa.Column("use_case", sa.String(32), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("processed_in", sa.String(16), nullable=False),
        sa.Column("tokens_prompt", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("tokens_completion", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("tokens_total", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("cost_try", sa.Numeric(12, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.String(32), nullable=False),
        # Ham gövde YOK — yalnız hash + 200-char özet (KVKK, goal §4).
        sa.Column("context_sha256", sa.String(64), nullable=True),
        sa.Column("response_sha256", sa.String(64), nullable=True),
        sa.Column("response_summary", sa.String(200), nullable=True),
    )
    op.create_index(
        "ix_api_request_log_tenant_created",
        "api_request_log",
        ["tenant_id", "created_at"],
    )
    # §4.8 silme: session bazlı.
    op.create_index(
        "ix_api_request_log_session", "api_request_log", ["session_id"]
    )
    op.execute("ALTER TABLE api_request_log ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE api_request_log FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON api_request_log
            FOR ALL
            USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON api_request_log")
    op.execute("ALTER TABLE api_request_log DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_api_request_log_session", table_name="api_request_log")
    op.drop_index("ix_api_request_log_tenant_created", table_name="api_request_log")
    op.drop_table("api_request_log")

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON api_tenant_config")
    op.execute("ALTER TABLE api_tenant_config DISABLE ROW LEVEL SECURITY")
    op.drop_table("api_tenant_config")
