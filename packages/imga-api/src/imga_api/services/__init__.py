"""Service layer: domain logic between FastAPI handlers and SQLAlchemy models."""

from imga_api.services.audit_service import AuditService
from imga_api.services.auth_service import (
    AuthError,
    AuthService,
    TokenPair,
    TokenReuseDetectedError,
)
from imga_api.services.invitation_service import (
    INVITATION_TTL,
    InvitationAcceptanceError,
    InvitationService,
)
from imga_api.services.tenant_config_service import (
    CategoryCodeConflictError,
    CategoryNotFoundError,
    TenantConfigError,
    TenantConfigService,
)
from imga_api.services.tenant_service import TenantService
from imga_api.services.ticket_service import (
    AutoCreateDecision,
    CancellationReasonRequiredError,
    DuplicateTicketError,
    TicketNotFoundError,
    TicketService,
    TicketServiceError,
    TransitionRequest,
    UnclaimByOthersError,
    decide_auto_create_state,
)
from imga_api.services.ticket_state_machine import (
    ForbiddenTransitionError,
    InvalidTransitionError,
    WindowExpiredError,
)
from imga_api.services.user_service import UserService

__all__ = [
    "INVITATION_TTL",
    "AuditService",
    "AuthError",
    "AuthService",
    "AutoCreateDecision",
    "CancellationReasonRequiredError",
    "CategoryCodeConflictError",
    "CategoryNotFoundError",
    "DuplicateTicketError",
    "ForbiddenTransitionError",
    "InvalidTransitionError",
    "InvitationAcceptanceError",
    "InvitationService",
    "TenantConfigError",
    "TenantConfigService",
    "TenantService",
    "TicketNotFoundError",
    "TicketService",
    "TicketServiceError",
    "TokenPair",
    "TokenReuseDetectedError",
    "TransitionRequest",
    "UnclaimByOthersError",
    "UserService",
    "WindowExpiredError",
    "decide_auto_create_state",
]
