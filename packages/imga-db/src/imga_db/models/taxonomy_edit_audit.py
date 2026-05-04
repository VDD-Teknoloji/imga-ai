"""TaxonomyEditAudit model — append-only audit trail for taxonomy edits.

Sprint 8.3.7-A. One row per ``create`` / ``update`` / ``delete`` /
``restore`` action against ``category_taxonomies``. ``before_state`` and
``after_state`` carry the full row snapshot (JSONB) so the audit stays
self-describing — the live row may have moved on.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from imga_db.base import Base


class TaxonomyEditAudit(Base):
    """One audit row per taxonomy mutation.

    ``user_id`` is nullable so seeding paths (tenant onboarding, the
    F18 backfill) can write rows without inventing a synthetic user.
    ``taxonomy_id`` carries no FK — a future hard delete on the
    taxonomy must not cascade-clear history.
    """

    __tablename__ = "taxonomy_edit_audit"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    taxonomy_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False
    )
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    before_state: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(), nullable=True
    )
    after_state: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
