"""SQLAlchemy 2.0 models for the imga platform."""

from imga_db.models.action_extraction_log import ActionItemExtractionLog
from imga_db.models.action_item import ActionItem, ActionItemEvent
from imga_db.models.assignment_history import TicketAssignmentEvent
from imga_db.models.audit import AuditLog
from imga_db.models.batch_job import AnalyzeBatchJob, BatchJobStatus
from imga_db.models.briefing_schedule import BriefingSchedule
from imga_db.models.category import Category, TenantCategory
from imga_db.models.category_taxonomy import CategoryTaxonomy
from imga_db.models.comment import TicketComment, TicketCommentKind
from imga_db.models.executive_briefing import ExecutiveBriefing
from imga_db.models.executive_snapshot import ExecutiveSnapshot
from imga_db.models.invitation import Invitation
from imga_db.models.metric_definition import MetricDefinition
from imga_db.models.mixins import SoftDeleteMixin, TenantOwnedMixin, TimestampMixin
from imga_db.models.pending_webhook import (
    PendingWebhookEvent,
    PendingWebhookStatus,
    PendingWebhookTarget,
)
from imga_db.models.prompt_template import PromptTemplate
from imga_db.models.refresh_token import RefreshTokenRecord
from imga_db.models.report_job import (
    ReportFormat,
    ReportJob,
    ReportStatus,
    ReportType,
)
from imga_db.models.review import Review, ReviewDecision
from imga_db.models.sla_rule import SlaRule
from imga_db.models.strategic_report import StrategicReport
from imga_db.models.taxonomy_edit_audit import TaxonomyEditAudit
from imga_db.models.tenant import (
    AutomationMode,
    SlaWebhookDispatchMode,
    Tenant,
    TenantPlanTier,
)
from imga_db.models.tenant_kpi_goal import TenantKpiGoal
from imga_db.models.tenant_llm_credential import TenantLlmCredential
from imga_db.models.trend_alert import TrendAlert
from imga_db.models.ticket import (
    CancellationReason,
    Ticket,
    TicketPriority,
    TicketState,
    TicketStateTransition,
)
from imga_db.models.user import User, UserTenantLink, UserTenantRole

__all__ = [
    "ActionItem",
    "ActionItemEvent",
    "ActionItemExtractionLog",
    "AnalyzeBatchJob",
    "AuditLog",
    "AutomationMode",
    "BatchJobStatus",
    "BriefingSchedule",
    "CancellationReason",
    "Category",
    "CategoryTaxonomy",
    "ExecutiveBriefing",
    "ExecutiveSnapshot",
    "Invitation",
    "MetricDefinition",
    "PendingWebhookEvent",
    "PendingWebhookStatus",
    "PendingWebhookTarget",
    "PromptTemplate",
    "RefreshTokenRecord",
    "ReportFormat",
    "ReportJob",
    "ReportStatus",
    "ReportType",
    "Review",
    "ReviewDecision",
    "SlaRule",
    "SlaWebhookDispatchMode",
    "SoftDeleteMixin",
    "StrategicReport",
    "TaxonomyEditAudit",
    "Tenant",
    "TenantCategory",
    "TenantKpiGoal",
    "TenantLlmCredential",
    "TenantOwnedMixin",
    "TenantPlanTier",
    "Ticket",
    "TicketAssignmentEvent",
    "TicketComment",
    "TicketCommentKind",
    "TicketPriority",
    "TicketState",
    "TicketStateTransition",
    "TimestampMixin",
    "TrendAlert",
    "User",
    "UserTenantLink",
    "UserTenantRole",
]
