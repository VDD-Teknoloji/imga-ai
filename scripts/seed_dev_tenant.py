"""Dev seed: Acme Inc tenant + three users + 18 sample tickets.

The 18 tickets are tuned to make every dashboard card non-zero and
to exercise every state in the lifecycle. Re-running the script is
a no-op: tenant + users are looked up by slug / email, and tickets
are only inserted when the tenant has zero tickets to begin with.
To refresh the tickets, delete the tenant (CASCADE handles the
rest) or run psql + ``DELETE FROM tickets WHERE tenant_id = ?`` and
re-run.

Usage:
    python scripts/seed_dev_tenant.py
    # or
    make seed-dev

Logins (each gets the same dev password):
    alice@acme.com    (tenant_admin)
    bob@acme.com      (analyst)
    charlie@acme.com  (viewer)

Distribution (validated against the dashboard hooks):
    state         open=5, in_progress=4, pending_customer=2,
                  resolved=4, closed=2, cancelled=1            -> 18 total
    category      kargo=6, faturalama=4, urun_kalitesi=3,
                  musteri_hizmetleri=3, teknik_destek=2        -> 18 total
    priority      urgent=2, high=4, normal=11, low=1            -> 18 total
    Dashboard     open=11, today=3, high_priority=6, resolved_7d=3
"""

from __future__ import annotations

import argparse
import asyncio
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

from imga_db import create_engine, create_session_factory
from imga_db.models import (
    CancellationReason,
    Category,
    Ticket,
    TicketPriority,
    TicketState,
    User,
    UserTenantLink,
    UserTenantRole,
)
from sqlalchemy import select

from imga_api.services import (
    AuditService,
    TenantService,
    TicketService,
    TransitionRequest,
    UserService,
)

SLUG = "acme"
TENANT_NAME = "Acme Inc."
DEV_PASSWORD = "dev123"  # noqa: S105 — local dev fixture only

USERS: tuple[tuple[str, str, UserTenantRole], ...] = (
    ("alice@acme.com", "Alice Admin", UserTenantRole.TENANT_ADMIN),
    ("bob@acme.com", "Bob Analyst", UserTenantRole.ANALYST),
    ("charlie@acme.com", "Charlie Viewer", UserTenantRole.VIEWER),
)

ALICE = "alice@acme.com"
BOB = "bob@acme.com"


@dataclass(frozen=True, slots=True)
class TransitionStep:
    to_state: TicketState
    occurred_offset: timedelta  # negative timedelta from now
    actor_email: str | None     # None == system actor
    cancellation_reason: CancellationReason | None = None


@dataclass(frozen=True, slots=True)
class TicketSpec:
    title: str
    category_code: str
    priority: TicketPriority
    opened_at_offset: timedelta
    transitions: tuple[TransitionStep, ...] = field(default_factory=tuple)


def _h(hours: float) -> timedelta:
    return timedelta(hours=hours)


def _d(days: float) -> timedelta:
    return timedelta(days=days)


def build_specs() -> tuple[TicketSpec, ...]:
    return (
        # === 5 OPEN ===
        TicketSpec("Kargom 5 gündür gelmedi", "kargo", TicketPriority.HIGH, _h(0)),
        TicketSpec("Faturada yanlış tutar", "faturalama", TicketPriority.NORMAL, -_h(1)),
        TicketSpec("Ürün hasarlı geldi", "urun_kalitesi", TicketPriority.NORMAL, -_h(0.5)),
        TicketSpec("Eski kargo şikayeti", "kargo", TicketPriority.NORMAL, -_d(3)),
        TicketSpec(
            "Müşteri hizmetleri yanıt vermiyor", "musteri_hizmetleri", TicketPriority.NORMAL, -_d(3)
        ),
        # === 4 IN_PROGRESS ===
        TicketSpec(
            "Acil kargo iadesi", "kargo", TicketPriority.URGENT, -_d(2),
            (TransitionStep(TicketState.IN_PROGRESS, -_d(1), ALICE),),
        ),
        TicketSpec(
            "Mükerrer faturalandırma", "faturalama", TicketPriority.URGENT, -_d(1),
            (TransitionStep(TicketState.IN_PROGRESS, -_h(12), ALICE),),
        ),
        TicketSpec(
            "Defektif iPhone", "urun_kalitesi", TicketPriority.HIGH, -_d(2),
            (TransitionStep(TicketState.IN_PROGRESS, -_d(1), BOB),),
        ),
        TicketSpec(
            "App login çalışmıyor", "teknik_destek", TicketPriority.NORMAL, -_d(1),
            (TransitionStep(TicketState.IN_PROGRESS, -_h(6), BOB),),
        ),
        # === 2 PENDING_CUSTOMER ===
        TicketSpec(
            "Sipariş takip detayı eksik", "musteri_hizmetleri", TicketPriority.NORMAL, -_d(3),
            (
                TransitionStep(TicketState.IN_PROGRESS, -_d(2), ALICE),
                TransitionStep(TicketState.PENDING_CUSTOMER, -_d(2) + _h(1), ALICE),
            ),
        ),
        TicketSpec(
            "Fatura PDF açılmıyor", "faturalama", TicketPriority.HIGH, -_d(2),
            (
                TransitionStep(TicketState.IN_PROGRESS, -_d(1), BOB),
                TransitionStep(TicketState.PENDING_CUSTOMER, -_d(1) + _h(1), BOB),
            ),
        ),
        # === 4 RESOLVED ===
        TicketSpec(
            "Kargo geç teslim", "kargo", TicketPriority.HIGH, -_d(4),
            (
                TransitionStep(TicketState.IN_PROGRESS, -_d(3), BOB),
                TransitionStep(TicketState.RESOLVED, -_d(1), BOB),
            ),
        ),
        TicketSpec(
            "Renk farkı", "urun_kalitesi", TicketPriority.NORMAL, -_d(5),
            (
                TransitionStep(TicketState.IN_PROGRESS, -_d(4), ALICE),
                TransitionStep(TicketState.RESOLVED, -_d(2), ALICE),
            ),
        ),
        TicketSpec(
            "Geri arama isteği", "musteri_hizmetleri", TicketPriority.NORMAL, -_d(3),
            (
                TransitionStep(TicketState.IN_PROGRESS, -_d(2), ALICE),
                TransitionStep(TicketState.RESOLVED, -_h(6), ALICE),
            ),
        ),
        TicketSpec(
            "Eski destek talebi", "teknik_destek", TicketPriority.NORMAL, -_d(30),
            (
                TransitionStep(TicketState.IN_PROGRESS, -_d(29), BOB),
                TransitionStep(TicketState.RESOLVED, -_d(25), BOB),
            ),
        ),
        # === 2 CLOSED — both with closed_at outside the 7-day window ===
        TicketSpec(
            "Çözülmüş kargo", "kargo", TicketPriority.NORMAL, -_d(10),
            (
                TransitionStep(TicketState.IN_PROGRESS, -_d(9), ALICE),
                TransitionStep(TicketState.RESOLVED, -_d(8), ALICE),
                TransitionStep(TicketState.CLOSED, -_d(7) - _h(1), ALICE),
            ),
        ),
        TicketSpec(
            "Eski fatura sorunu", "faturalama", TicketPriority.LOW, -_d(20),
            (
                TransitionStep(TicketState.IN_PROGRESS, -_d(19), BOB),
                TransitionStep(TicketState.RESOLVED, -_d(15), BOB),
                TransitionStep(TicketState.CLOSED, -_d(10), BOB),
            ),
        ),
        # === 1 CANCELLED — direct OPEN -> CANCELLED with reason ===
        TicketSpec(
            "Spam ticket", "kargo", TicketPriority.NORMAL, -_d(7),
            (
                TransitionStep(
                    TicketState.CANCELLED, -_d(6), ALICE,
                    cancellation_reason=CancellationReason.SPAM,
                ),
            ),
        ),
    )


_ROLE_BY_EMAIL = {
    ALICE: UserTenantRole.TENANT_ADMIN,
    BOB: UserTenantRole.ANALYST,
}


async def _reset_tenant() -> None:
    """Drop the Acme tenant outright. CASCADE handles tickets,
    categories, links, audit rows. Used by --reset.

    Runs as the imga_owner role because imga_admin's BYPASSRLS does
    not include the right to violate FK-RESTRICT (tickets→categories);
    only the table owner can issue raw DELETE on the tenants row
    that fans out via CASCADE."""
    os.environ.setdefault(
        "DATABASE_URL_OWNER",
        "postgresql+asyncpg://imga_owner:imga_dev_password@localhost:5433/imga",
    )
    from sqlalchemy import text
    engine = create_engine("owner")
    try:
        factory = create_session_factory(engine)
        async with factory() as session, session.begin():
            await session.execute(
                text("DELETE FROM tenants WHERE slug = :slug"), {"slug": SLUG}
            )
            print(f"  [-] Tenant '{SLUG}' deleted (CASCADE drops tickets, links, audit rows)")
    finally:
        await engine.dispose()


async def seed() -> None:  # noqa: PLR0915, C901 — top-level orchestration
    os.environ.setdefault(
        "DATABASE_URL_ADMIN",
        "postgresql+asyncpg://imga_admin:imga_admin_password@localhost:5433/imga",
    )

    engine = create_engine("admin")
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            audit = AuditService(session)
            tsvc = TenantService(session, audit)
            usvc = UserService(session, audit)
            ticket_svc = TicketService(session, audit)

            # --- Tenant -------------------------------------------------
            async with session.begin():
                tenant = await tsvc.get_by_slug(SLUG)
                if tenant is None:
                    tenant = await tsvc.create(name=TENANT_NAME, slug=SLUG)
                    print(f"  [+] Tenant '{SLUG}' created")
                else:
                    print(f"  [.] Tenant '{SLUG}' already exists")
            tenant_id = tenant.id

            # --- Users + tenant links ---------------------------------
            user_ids: dict[str, UUID] = {}
            for email, full_name, role in USERS:
                async with session.begin():
                    result = await session.execute(
                        select(User).where(User.email == email)
                    )
                    user = result.scalar_one_or_none()
                    if user is None:
                        user = await usvc.create(
                            email=email, password=DEV_PASSWORD, full_name=full_name
                        )
                        print(f"  [+] User {email} created")
                    else:
                        print(f"  [.] User {email} already exists")
                    user_ids[email] = user.id

                    link = await session.execute(
                        select(UserTenantLink)
                        .where(UserTenantLink.user_id == user.id)
                        .where(UserTenantLink.tenant_id == tenant_id)
                    )
                    if link.scalar_one_or_none() is None:
                        await usvc.attach_to_tenant(
                            user_id=user.id, tenant_id=tenant_id, role=role
                        )
                        print(f"      -> linked as {role.value}")

            # --- Tickets (skip if any already exist) ------------------
            async with session.begin():
                existing = (
                    await session.execute(
                        select(Ticket.id)
                        .where(Ticket.tenant_id == tenant_id)
                        .limit(1)
                    )
                ).first()
            if existing is not None:
                print(
                    "  [.] Tenant already has tickets; skipping ticket seed. "
                    "Delete the tenant or its tickets to refresh."
                )
                return

            # Build category-id map (eight global codes, NULL tenant_id).
            async with session.begin():
                cat_rows = (
                    await session.execute(
                        select(Category)
                        .where(Category.tenant_id.is_(None))
                        .where(Category.deleted_at.is_(None))
                    )
                ).scalars().all()
            category_ids = {c.code: c.id for c in cat_rows}

            now = datetime.now(UTC)
            for index, spec in enumerate(build_specs(), 1):
                opened_at = now + spec.opened_at_offset
                async with session.begin():
                    ticket = await ticket_svc.create(
                        tenant_id=tenant_id,
                        category_id=category_ids[spec.category_code],
                        title=spec.title,
                        priority=spec.priority,
                        created_by_user_id=user_ids[ALICE],
                        opened_at=opened_at,
                    )
                    for step in spec.transitions:
                        actor_id = (
                            user_ids[step.actor_email] if step.actor_email else None
                        )
                        actor_role = (
                            _ROLE_BY_EMAIL[step.actor_email]
                            if step.actor_email
                            else None
                        )
                        await ticket_svc.transition(
                            ticket_id=ticket.id,
                            request=TransitionRequest(
                                to_state=step.to_state,
                                cancellation_reason=step.cancellation_reason,
                            ),
                            actor_user_id=actor_id,
                            actor_role=actor_role,
                            now=now + step.occurred_offset,
                        )
                final_state = (
                    spec.transitions[-1].to_state
                    if spec.transitions
                    else TicketState.OPEN
                )
                print(
                    f"  [{index:2d}] {final_state.value:18s} "
                    f"{spec.priority.value:7s} "
                    f"{spec.category_code:20s} {spec.title[:46]}"
                )
    finally:
        await engine.dispose()

    print()
    print("Seed complete.")
    print(f"  Login: alice@acme.com   / {DEV_PASSWORD}  (tenant_admin)")
    print(f"         bob@acme.com     / {DEV_PASSWORD}  (analyst)")
    print(f"         charlie@acme.com / {DEV_PASSWORD}  (viewer)")
    print()
    print("Dashboard expectations:")
    print("  open=11   today=3   high_priority=6   resolved_7d=3")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Drop the Acme tenant + all its tickets before seeding.",
    )
    args = parser.parse_args()
    if args.reset:
        await _reset_tenant()
    await seed()


if __name__ == "__main__":
    asyncio.run(main())
