"""factory_boy factories for imga-api integration tests.

These are *build-only* factories: they return unsaved SQLAlchemy model
instances. Tests pass them through ``admin_session.add_all(...)`` inside
a transaction. The ``factory_boy`` SQLAlchemyModelFactory variant needs
a sync session, but every session in this codebase is async — building
plain instances and letting the test orchestrate persistence keeps both
worlds happy.

The intended usage pattern:

    from tests.factories import TenantFactory, ReviewFactory, fixed_password

    async def test_batch_seeding(admin_session):
        tenant = TenantFactory.build()
        reviews = ReviewFactory.build_batch(1000, tenant_id=tenant.id)
        async with admin_session.begin():
            admin_session.add(tenant)
            admin_session.add_all(reviews)

For Sprint 8.3 batch tests these factories cover the four hot models —
Tenant, User (+ UserTenantLink), Review, Ticket — plus a single shared
argon2 hash so seeded users can log in with ``fixed_password()`` without
paying ~100ms/user for argon2 hashing during a 10k-row seed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final
from uuid import UUID, uuid4

import factory
from argon2 import PasswordHasher
from imga_core.text_utils import review_text_hash
from imga_db.models import (
    Review,
    ReviewDecision,
    Tenant,
    Ticket,
    TicketPriority,
    TicketState,
    User,
    UserTenantLink,
    UserTenantRole,
)
from imga_db.models.tenant import AutomationMode, TenantPlanTier

# Single argon2 hash computed once at module import. Every UserFactory
# instance shares it, so seeding 10k users costs one hash, not ten
# thousand. Tests that exercise the *real* signup / password-change
# flow must keep using UserService.create — this hash is only for
# fixture-built rows.
_FIXED_PASSWORD: Final[str] = "Test-Password-123!"
_FIXED_PASSWORD_HASH: Final[str] = PasswordHasher().hash(_FIXED_PASSWORD)


def fixed_password() -> str:
    """Plain-text password matching every UserFactory-built row."""
    return _FIXED_PASSWORD


class TenantFactory(factory.Factory):  # type: ignore[misc]
    class Meta:
        model = Tenant

    id = factory.LazyFunction(uuid4)
    name = factory.Sequence(lambda n: f"Test Tenant {n}")
    # Slug must be globally unique. Sequence alone collides across test
    # runs that share a DB (each pytest module starts the counter from
    # 0); the uuid suffix keeps inserts safe without per-test cleanup.
    slug = factory.LazyFunction(lambda: f"test-tenant-{uuid4().hex[:12]}")
    plan_tier = TenantPlanTier.TRIAL
    automation_mode = AutomationMode.SEMI_AUTO
    settings = factory.LazyFunction(dict)
    auto_close_resolved_days = 7
    auto_close_pending_days = 14
    resolved_regression_window_days = 7
    ticket_reopen_window_days = 30


class UserFactory(factory.Factory):  # type: ignore[misc]
    class Meta:
        model = User

    id = factory.LazyFunction(uuid4)
    email = factory.LazyFunction(
        lambda: f"user-{uuid4().hex[:12]}@test.example.com"
    )
    password_hash = _FIXED_PASSWORD_HASH
    full_name = factory.Sequence(lambda n: f"Test User {n}")
    is_active = True
    is_super_admin = False


class UserTenantLinkFactory(factory.Factory):  # type: ignore[misc]
    """Link factory; caller MUST pass ``user_id=`` and ``tenant_id=``."""

    class Meta:
        model = UserTenantLink

    user_id = factory.LazyFunction(uuid4)
    tenant_id = factory.LazyFunction(uuid4)
    role = UserTenantRole.ANALYST
    invited_by_user_id = None
    invitation_accepted_at = None


class ReviewFactory(factory.Factory):  # type: ignore[misc]
    """Review factory. Caller MUST pass ``tenant_id=`` for any row that
    will be persisted — without it the row violates RLS and the FK to
    tenants. Other fields default to a "neutral, no-ticket-created"
    decision so 10k-row seeds don't accidentally trigger ticket bridges
    in the test pipeline."""

    class Meta:
        model = Review

    id = factory.LazyFunction(uuid4)
    tenant_id = factory.LazyFunction(uuid4)
    text = factory.Sequence(lambda n: f"Test review yorumu numara {n}")
    text_hash = factory.LazyAttribute(lambda obj: review_text_hash(obj.text))
    sentiment_label = "NÖTR"
    sentiment_score = 0.0
    primary_category = "diğer"
    primary_confidence = 0.5
    automation_mode = AutomationMode.SEMI_AUTO.value
    decision = ReviewDecision.SKIPPED_THRESHOLD
    decision_reason = None
    ticket_id = None
    submitted_by_user_id = None
    analyzed_at = factory.LazyFunction(lambda: datetime.now(UTC))


class TicketFactory(factory.Factory):  # type: ignore[misc]
    """Ticket factory. Caller MUST pass ``tenant_id=`` and
    ``category_id=`` — categories are tenant-scoped via tenant_categories
    and there is no platform-default category to fall back on."""

    class Meta:
        model = Ticket

    id = factory.LazyFunction(uuid4)
    tenant_id = factory.LazyFunction(uuid4)
    review_id = None
    category_id = factory.LazyFunction(uuid4)
    state = TicketState.OPEN
    priority = TicketPriority.NORMAL
    title = factory.Sequence(lambda n: f"Test ticket konu {n}")
    summary = None
    assigned_to_user_id = None
    created_by_user_id = None
    cancellation_reason = None
    parent_ticket_id = None
    opened_at = factory.LazyFunction(lambda: datetime.now(UTC))
    last_state_change_at = factory.LazyAttribute(lambda obj: obj.opened_at)


def seed_tenant_with_user(
    *,
    role: UserTenantRole = UserTenantRole.ANALYST,
) -> tuple[Tenant, User, UserTenantLink]:
    """Build (Tenant, User, UserTenantLink) tuple wired up by id.

    Returned instances are unsaved — caller adds them to a session inside
    a transaction. Convenience for tests that just need *any* tenant and
    *any* member to exercise an endpoint.
    """
    tenant = TenantFactory.build()
    user = UserFactory.build()
    link = UserTenantLinkFactory.build(
        user_id=user.id, tenant_id=tenant.id, role=role
    )
    return tenant, user, link


def seed_reviews_for_tenant(
    tenant_id: UUID,
    *,
    count: int,
    sentiment_label: str = "NÖTR",
    sentiment_score: float = 0.0,
) -> list[Review]:
    """Build N Review rows owned by ``tenant_id``.

    Used by Sprint 8.3.1 batch tests that need 1k–10k rows. Each row
    has a unique ``text`` (so dedup hashes don't collapse) and the same
    sentiment defaults; override per-row by mutating the returned list.
    """
    return ReviewFactory.build_batch(
        count,
        tenant_id=tenant_id,
        sentiment_label=sentiment_label,
        sentiment_score=sentiment_score,
    )
