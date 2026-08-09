"""CategoryTaxonomy model — per-tenant company-perspective taxonomy.

Sprint 8.3.5 / Alt-Faz 8.3.5.5. Each tenant carries a list of company-
side issue categories (code + Türkçe label + keyword list). Default
seed at tenant creation is the 21-row legacy ``get_company_perspective``
catalog from cx_sentiment_dashboard. Sprint 8.3.7 ships an edit UI so
each tenant can prune / extend; until then this is read-only via
``GET /tenants/me/taxonomies``.

The heuristic reranker in ``imga-core.categorizers.company_heuristic``
consumes this list to pick a company-perspective code for an analyzed
review based on keyword presence + per-row priority.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from imga_db.base import Base


class CategoryTaxonomy(Base):
    """One row per (tenant_id, code) company-perspective entry.

    ``priority`` resolves heuristic ties: lower number wins. The legacy
    seed mirrors the if-elif order of ``get_company_perspective`` so a
    rebuilt taxonomy keeps the original "kargom ulaşmadı" -> "deforme"
    -> ... resolution.

    ``is_default_seed`` distinguishes platform-shipped rows from
    tenant-edited additions (Sprint 8.3.7 surfaces a "restore defaults"
    affordance against this flag).
    """

    __tablename__ = "category_taxonomies"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    label_tr: Mapped[str] = mapped_column(String(128), nullable=False)
    keywords: Mapped[list[str]] = mapped_column(
        JSONB(), nullable=False, default=list
    )
    priority: Mapped[int] = mapped_column(Integer(), nullable=False, default=100)
    is_default_seed: Mapped[bool] = mapped_column(
        Boolean(), nullable=False, default=False
    )
    # Sprint 8.3.7-A — optional self-reference into another taxonomy
    # row's ``code`` for hierarchy display. NULL = top-level. The
    # column is just a string (no FK): the unique constraint sits on
    # ``(tenant_id, code)``, so a real FK would need a composite. The
    # API validates that the referenced code exists in the same
    # tenant before persisting.
    parent_code: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    # Sprint 13.1 — ana kategori eşlemesi (drill-down gruplaması +
    # sınıflandırıcı prompt'u için; SAYIMLAR review kolonlarından
    # gelir). ``reviews.primary_category`` ile aynı global kod
    # uzayı (imga_core.categories GLOBAL_CATEGORY_CODES); NULL =
    # henüz eşlenmemiş. ``parent_code`` ile karıştırılmamalı: o
    # aynı tenant içi bir alt-taksonomi satırını işaret eder.
    primary_category_code: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    # Soft delete — Sprint 8.3.7-A. Rows are flipped to ``False`` via
    # the DELETE endpoint and restored via the POST /restore endpoint;
    # the heuristic reranker filters on ``is_active`` so retired rows
    # stop matching incoming reviews without losing their audit trail.
    # Backed by the same column the migration adds; default ``True``
    # mirrors the historical "every existing row is active" baseline.
    is_active: Mapped[bool] = mapped_column(
        Boolean(), nullable=False, default=True, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
