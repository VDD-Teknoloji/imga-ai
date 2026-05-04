"""SlaRule model — tenant-configurable SLA threshold rules.

Sprint 8.3.7-A. A rule matches an incoming review against zero or more
filter dimensions (priority, taxonomy code, company-perspective code,
NPS ceiling) and, on match, declares an SLA threshold (response and/or
resolution minutes) plus an action.

action_type values for this sprint:

  * ``warn_only`` — log + emit an SLA event, no side effects
  * ``create_ticket`` — wired in Sprint 8.3.9
  * ``escalate`` — wired in Sprint 8.3.9 (priority bump)
  * ``notify_email`` — wired in Sprint 8.6 alongside Mailcow

The DB-level CHECK constraint accepts all four values so the wire
shape is forward-compatible; the engine raises ``NotImplementedError``
on the unwired ones until those sprints land.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import ARRAY, Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from imga_db.base import Base


class SlaRule(Base):
    __tablename__ = "sla_rules"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)

    # Match dimensions — NULL means "any" for that dimension.
    match_priority: Mapped[str | None] = mapped_column(
        String(16), nullable=True
    )
    match_taxonomy_codes: Mapped[list[str] | None] = mapped_column(
        ARRAY(String(64)), nullable=True
    )
    match_company_perspective_codes: Mapped[list[str] | None] = mapped_column(
        ARRAY(String(64)), nullable=True
    )
    match_nps_score_max: Mapped[int | None] = mapped_column(
        Integer(), nullable=True
    )

    # Thresholds — at least one must be set (DB CHECK enforces).
    response_sla_minutes: Mapped[int | None] = mapped_column(
        Integer(), nullable=True
    )
    resolution_sla_minutes: Mapped[int | None] = mapped_column(
        Integer(), nullable=True
    )

    # Action.
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    action_config: Mapped[dict[str, Any]] = mapped_column(
        JSONB(), nullable=False, default=dict
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean(), nullable=False, default=True
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
