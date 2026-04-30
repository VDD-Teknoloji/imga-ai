"""Category + TenantCategory models.

A single ``categories`` table holds both global (tenant_id IS NULL) and
per-tenant custom (tenant_id IS NOT NULL) rows. The 8 globals are
seeded by migration 0005; tenants extend the taxonomy by inserting
rows with their own tenant_id.

``tenant_categories`` is the join row that controls which categories
each tenant has *enabled*. Row absence means the category is not
available to that tenant; row presence with ``is_enabled=False`` means
the tenant has explicitly disabled it (and can re-enable). New global
categories added by future migrations are NOT auto-enabled for existing
tenants — opt-in by design (Sprint 7.4 review).

Note on naming: imga-core already exports a Pydantic ``CategoryDefinition``
class describing the in-memory taxonomy, so the SQLAlchemy model here is
named ``Category`` to avoid the collision in the API layer.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from imga_db.base import Base
from imga_db.models.mixins import SoftDeleteMixin, TimestampMixin


class Category(Base, TimestampMixin, SoftDeleteMixin):
    """A category row. Global when ``tenant_id`` is NULL, custom when set.

    RLS policy lets every tenant SELECT globals + own customs, but
    INSERT / UPDATE / DELETE are restricted to rows the tenant owns.
    """

    __tablename__ = "categories"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    # NULL = global; non-NULL = tenant-owned custom.
    tenant_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    label_tr: Mapped[str] = mapped_column(String(255), nullable=False)
    label_en: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class TenantCategory(Base, TimestampMixin):
    """Tenant-by-category enablement flag. Composite PK (tenant, category)."""

    __tablename__ = "tenant_categories"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
    )
    category_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("categories.id", ondelete="CASCADE"),
        primary_key=True,
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
