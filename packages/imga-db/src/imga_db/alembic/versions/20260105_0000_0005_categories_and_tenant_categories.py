"""categories + tenant_categories with RLS, 8 global seeds

Revision ID: 0005
Revises: 0004
Create Date: 2026-01-05 00:00:00

Sprint 7.4: per-tenant taxonomy. Two new tables:

* ``categories`` — both global (tenant_id IS NULL) and per-tenant custom
  (tenant_id IS NOT NULL) rows in one table. Eight global rows are
  seeded; the special ``belirsiz`` fallback bucket lives only in
  imga-core and is intentionally not persisted as a row.
* ``tenant_categories`` — N×M link with an ``is_enabled`` toggle. Row
  *absence* means the category is not available to that tenant; the
  presence of a row plus ``is_enabled=FALSE`` means the tenant
  explicitly turned it off and can re-enable. Opt-in semantic for
  future global additions: TenantService.create seeds the eight
  globals at tenant creation time, but a *new* global added by a later
  migration does NOT auto-enable for existing tenants.

The ``tenants.category_overrides`` JSON placeholder from migration 0001
is dropped — it was earmarked for 7.4 and never populated.

RLS on ``categories``: globals must be visible to every tenant, but a
tenant can only INSERT/UPDATE/DELETE rows that match its own tenant_id.
A single ``FOR ALL`` policy can't express that asymmetry safely (DELETE
honours USING, which would otherwise let tenants nuke globals), so we
split into command-specific policies.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers
revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_GLOBAL_CATEGORIES: tuple[tuple[str, str, str | None], ...] = (
    ("kargo", "Kargo / Lojistik", "Shipping / Logistics"),
    ("faturalama", "Faturalama / Ödeme", "Billing / Payment"),
    ("urun_kalitesi", "Ürün Kalitesi", "Product Quality"),
    ("musteri_hizmetleri", "Müşteri Hizmetleri", "Customer Service"),
    ("iade", "İade / Değişim", "Returns / Exchanges"),
    ("teknik_destek", "Teknik Destek", "Technical Support"),
    ("siparis_sureci", "Sipariş Süreci", "Order Process"),
    ("pazarlama", "Pazarlama / İletişim", "Marketing / Communication"),
)


def upgrade() -> None:
    # --- drop legacy JSON placeholder on tenants -------------------------
    op.drop_column("tenants", "category_overrides")

    # --- categories table -------------------------------------------------
    op.create_table(
        "categories",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("label_tr", sa.String(255), nullable=False),
        sa.Column("label_en", sa.String(255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_categories_tenant_id", "categories", ["tenant_id"])
    op.create_index("ix_categories_deleted_at", "categories", ["deleted_at"])
    # Globals: code unique across the whole system.
    op.create_index(
        "uq_categories_global_code",
        "categories",
        ["code"],
        unique=True,
        postgresql_where=sa.text("tenant_id IS NULL"),
    )
    # Customs: code unique per tenant. Two tenants can both have a "vip"
    # code without colliding; the global-vs-custom collision is enforced
    # at the application layer (TenantConfigService.create_custom_category).
    op.create_index(
        "uq_categories_per_tenant_code",
        "categories",
        ["tenant_id", "code"],
        unique=True,
        postgresql_where=sa.text("tenant_id IS NOT NULL"),
    )

    # --- seed 8 globals BEFORE enabling RLS ------------------------------
    # Done before RLS+FORCE so the migration (running as imga_owner) is
    # not blocked by WITH CHECK (tenant_id = current_setting(...)).
    for code, tr, en in _GLOBAL_CATEGORIES:
        op.execute(
            sa.text(
                """
                INSERT INTO categories (tenant_id, code, label_tr, label_en)
                VALUES (NULL, :code, :tr, :en)
                """
            ).bindparams(code=code, tr=tr, en=en)
        )

    # --- RLS on categories (command-specific policies) -------------------
    op.execute("ALTER TABLE categories ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE categories FORCE ROW LEVEL SECURITY")
    # SELECT: tenant sees globals + own customs.
    op.execute(
        """
        CREATE POLICY categories_select ON categories
            FOR SELECT
            USING (
                tenant_id IS NULL
                OR tenant_id = current_setting('app.current_tenant_id', true)::uuid
            )
        """
    )
    # INSERT: tenant can only insert rows tagged with its own tenant_id.
    op.execute(
        """
        CREATE POLICY categories_insert ON categories
            FOR INSERT
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
        """
    )
    # UPDATE: same — must own row both before and after.
    op.execute(
        """
        CREATE POLICY categories_update ON categories
            FOR UPDATE
            USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
        """
    )
    # DELETE: own rows only — globals stay safe even from a buggy tenant.
    op.execute(
        """
        CREATE POLICY categories_delete ON categories
            FOR DELETE
            USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
        """
    )

    # --- tenant_categories link table ------------------------------------
    op.create_table(
        "tenant_categories",
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "category_id",
            UUID(as_uuid=True),
            sa.ForeignKey("categories.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_tenant_categories_tenant_id", "tenant_categories", ["tenant_id"])

    op.execute("ALTER TABLE tenant_categories ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenant_categories FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON tenant_categories
            FOR ALL
            USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON tenant_categories")
    op.execute("ALTER TABLE tenant_categories DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_tenant_categories_tenant_id", table_name="tenant_categories")
    op.drop_table("tenant_categories")

    for name in (
        "categories_delete",
        "categories_update",
        "categories_insert",
        "categories_select",
    ):
        op.execute(f"DROP POLICY IF EXISTS {name} ON categories")
    op.execute("ALTER TABLE categories DISABLE ROW LEVEL SECURITY")
    op.drop_index("uq_categories_per_tenant_code", table_name="categories")
    op.drop_index("uq_categories_global_code", table_name="categories")
    op.drop_index("ix_categories_deleted_at", table_name="categories")
    op.drop_index("ix_categories_tenant_id", table_name="categories")
    op.drop_table("categories")

    op.add_column(
        "tenants",
        sa.Column(
            "category_overrides",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
    )
