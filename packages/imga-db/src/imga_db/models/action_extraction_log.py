"""ActionItemExtractionLog — idempotency ledger for action extraction.

Sprint 9.0.5-B G. The action-extraction pipeline used to mint a
fresh batch of ActionItem rows every time the route fired, so a
re-render of the same SWOT report or executive briefing produced
duplicate follow-up tasks. This table is the dedupe key:

    UNIQUE (tenant_id, source_type, source_id, extraction_fingerprint)

Service uses INSERT ... ON CONFLICT to make extraction idempotent:
the second call returns the existing ``action_item_ids`` instead
of creating new rows.

``extraction_fingerprint`` is computed by the service as
``sha256(canonical_source_text + extraction_version)`` — a content
edit (e.g. operator regenerated the SWOT) yields a new fingerprint
and re-extracts; an unchanged re-render is a no-op.

Tenant-scoped via RLS+FORCE; same convention as 0006 / 0019 / 0021.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from imga_db.base import Base


class ActionItemExtractionLog(Base):
    __tablename__ = "action_items_extraction_log"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    # 'strategic_report' | 'executive_briefing' — DB CHECK constraint
    # enforces in migration 0024.
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False
    )
    extraction_fingerprint: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    action_item_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=False, default=list
    )
    extracted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
