"""Service layer: domain logic between FastAPI handlers and SQLAlchemy models."""

from imga_api.services.audit_service import AuditService
from imga_api.services.auth_service import (
    AuthError,
    AuthService,
    TokenPair,
    TokenReuseDetectedError,
)
from imga_api.services.comment_service import (
    MAX_BODY_LENGTH as COMMENT_MAX_BODY_LENGTH,
)
from imga_api.services.comment_service import (
    CommentForbiddenError,
    CommentNotFoundError,
    CommentService,
    CommentServiceError,
    TicketNotFoundForCommentError,
)
from imga_api.services.invitation_service import (
    INVITATION_TTL,
    InvitationAcceptanceError,
    InvitationEmailExistsError,
    InvitationEmailMismatchError,
    InvitationPreview,
    InvitationReauthFailedError,
    InvitationService,
)
from imga_api.services.review_service import (
    DEDUP_WINDOW,
    CategoryNotConfiguredError,
    ReviewBridgeResult,
    ReviewService,
    ReviewServiceError,
)
from imga_api.services.tenant_config_service import (
    CategoryCodeConflictError,
    CategoryNotFoundError,
    TenantConfigError,
    TenantConfigService,
)
from imga_api.services.tenant_service import (
    TenantNotFoundError,
    TenantService,
    TenantSlugTakenError,
)
from imga_api.services.ticket_filters import (
    GroupBy,
    OrderBy,
    OrderDirection,
    StatsRequest,
    TicketFilters,
)
from imga_api.services.ticket_service import (
    AutoCreateDecision,
    CancellationReasonRequiredError,
    DuplicateTicketError,
    TicketNotFoundError,
    TicketService,
    TicketServiceError,
    TicketStatsBucket,
    TicketStatsResult,
    TransitionRequest,
    UnclaimByOthersError,
    decide_auto_create_state,
)
from imga_api.services.ticket_state_machine import (
    ForbiddenTransitionError,
    InvalidTransitionError,
    WindowExpiredError,
)
from imga_api.services.user_service import TenantMember, UserService

__all__ = [
    "COMMENT_MAX_BODY_LENGTH",
    "DEDUP_WINDOW",
    "INVITATION_TTL",
    "AuditService",
    "AuthError",
    "AuthService",
    "AutoCreateDecision",
    "CancellationReasonRequiredError",
    "CategoryCodeConflictError",
    "CategoryNotConfiguredError",
    "CategoryNotFoundError",
    "CommentForbiddenError",
    "CommentNotFoundError",
    "CommentService",
    "CommentServiceError",
    "DuplicateTicketError",
    "ForbiddenTransitionError",
    "GroupBy",
    "InvalidTransitionError",
    "InvitationAcceptanceError",
    "InvitationEmailExistsError",
    "InvitationEmailMismatchError",
    "InvitationPreview",
    "InvitationReauthFailedError",
    "InvitationService",
    "OrderBy",
    "OrderDirection",
    "ReviewBridgeResult",
    "ReviewService",
    "ReviewServiceError",
    "StatsRequest",
    "TenantConfigError",
    "TenantConfigService",
    "TenantMember",
    "TenantNotFoundError",
    "TenantService",
    "TenantSlugTakenError",
    "TicketFilters",
    "TicketNotFoundError",
    "TicketNotFoundForCommentError",
    "TicketService",
    "TicketServiceError",
    "TicketStatsBucket",
    "TicketStatsResult",
    "TokenPair",
    "TokenReuseDetectedError",
    "TransitionRequest",
    "UnclaimByOthersError",
    "UserService",
    "WindowExpiredError",
    "decide_auto_create_state",
]
