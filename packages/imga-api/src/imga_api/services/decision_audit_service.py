"""Sprint 9.3 C — operator-decision audit log.

Every state-changing operator action that lands outside the
``action_item_events`` (Sprint 9.1 A) and ``llm_call_audit``
(Sprint 9.3 A) trails goes through this service. The
distinguishing question: "Did a *human* decide this?" If yes, the
service writes a row.

Decision types (CHECK constraint in Migration 0027 enforces):
  * briefing_acknowledged / dismissed
  * strategic_report_approved / rejected
  * action_item_assigned / priority_changed (mirrors
    action_item_events when route layer sees the request; the
    duplicate is intentional — action_item_events is item-scoped,
    decision_audit_log is tenant-scoped)
  * sla_rule_changed
  * kpi_goal_set
  * webhook_dispatched_manually
  * tenant_setting_changed
  * prompt_template_overridden

The service is session-bound; callers wrap the call in their own
``async with session.begin():`` so the audit row commits with the
state change it records.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from imga_db.models import DecisionAuditLog
from sqlalchemy.ext.asyncio import AsyncSession

_logger = logging.getLogger(__name__)


# Decision-type constants — keep in sync with Migration 0027's
# CHECK constraint. Importers reference these instead of bare
# strings so a typo surfaces as an ImportError at module load
# rather than a CHECK violation at runtime.
DECISION_BRIEFING_ACKNOWLEDGED = "briefing_acknowledged"
DECISION_BRIEFING_DISMISSED = "briefing_dismissed"
DECISION_STRATEGIC_REPORT_APPROVED = "strategic_report_approved"
DECISION_STRATEGIC_REPORT_REJECTED = "strategic_report_rejected"
DECISION_ACTION_ITEM_ASSIGNED = "action_item_assigned"
DECISION_ACTION_ITEM_PRIORITY_CHANGED = "action_item_priority_changed"
DECISION_SLA_RULE_CHANGED = "sla_rule_changed"
DECISION_KPI_GOAL_SET = "kpi_goal_set"
DECISION_WEBHOOK_DISPATCHED_MANUALLY = "webhook_dispatched_manually"
DECISION_TENANT_SETTING_CHANGED = "tenant_setting_changed"
DECISION_PROMPT_TEMPLATE_OVERRIDDEN = "prompt_template_overridden"


class DecisionAuditService:
    """Session-bound writer. Single public method
    ``record_decision`` because the read side lives on a route
    handler (``/admin/decision-audit``) that goes through SQLAlchemy
    directly."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record_decision(
        self,
        *,
        tenant_id: UUID,
        decision_type: str,
        related_entity_type: str,
        related_entity_id: UUID,
        actor_user_id: UUID | None,
        payload: dict[str, Any] | None = None,
        rationale: str | None = None,
        request_id: str | None = None,
    ) -> DecisionAuditLog:
        """Insert one audit row. Returns the row so the caller can
        attach the row id to a response (the admin timeline page
        uses this to deep-link to the specific decision).

        ``payload`` is a free-form JSONB blob — common fields
        include ``before`` / ``after`` for diff-like decisions
        (status change, priority change). Best-effort: failures
        log + propagate so the route layer's catch-all surfaces
        the issue rather than silently dropping the audit."""
        row = DecisionAuditLog(
            tenant_id=tenant_id,
            decision_type=decision_type,
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
            actor_user_id=actor_user_id,
            payload=payload or {},
            rationale=rationale,
            request_id=request_id,
        )
        self._session.add(row)
        await self._session.flush()
        return row


__all__ = [
    "DECISION_ACTION_ITEM_ASSIGNED",
    "DECISION_ACTION_ITEM_PRIORITY_CHANGED",
    "DECISION_BRIEFING_ACKNOWLEDGED",
    "DECISION_BRIEFING_DISMISSED",
    "DECISION_KPI_GOAL_SET",
    "DECISION_PROMPT_TEMPLATE_OVERRIDDEN",
    "DECISION_SLA_RULE_CHANGED",
    "DECISION_STRATEGIC_REPORT_APPROVED",
    "DECISION_STRATEGIC_REPORT_REJECTED",
    "DECISION_TENANT_SETTING_CHANGED",
    "DECISION_WEBHOOK_DISPATCHED_MANUALLY",
    "DecisionAuditService",
]
