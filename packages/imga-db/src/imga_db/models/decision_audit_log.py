"""DecisionAuditLog — operator action audit row.

Sprint 9.3 C. Distinct from ``llm_call_audit`` (which logs *AI*
calls) and ``action_item_events`` (which logs *action item*
state). This is the catch-all for human-driven decisions across
briefings, strategic reports, KPI goals, SLA rules, manual
webhook dispatch, and tenant settings.

``rationale`` is the optional free-text "why" the operator types
when they approve / reject — populated only when the UI surfaces a
prompt for it (e.g. strategic_report_rejected). RLS+FORCE on
tenant_id per convention.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from imga_db.base import Base


class DecisionAuditLog(Base):
    __tablename__ = "decision_audit_log"
    __table_args__ = (
        CheckConstraint(
            "decision_type IN ("
            "'briefing_acknowledged', 'briefing_dismissed', "
            "'strategic_report_approved', 'strategic_report_rejected', "
            "'action_item_assigned', 'action_item_priority_changed', "
            "'sla_rule_changed', 'kpi_goal_set', "
            "'webhook_dispatched_manually', 'tenant_setting_changed', "
            "'prompt_template_overridden')",
            name="ck_decision_audit_log_type",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    decision_type: Mapped[str] = mapped_column(Text(), nullable=False)
    related_entity_type: Mapped[str] = mapped_column(Text(), nullable=False)
    related_entity_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    rationale: Mapped[str | None] = mapped_column(Text(), nullable=True)
    request_id: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
