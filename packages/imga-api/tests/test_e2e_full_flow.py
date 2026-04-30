"""End-to-end B2B SaaS flow test.

Reduced scope per Sprint 7.6 öncesi konsolidasyon planı (Plan B): the
test exercises the *shipped* surface from a fresh seed through every
state-changing path. Out of scope (Sprint 7.5.5 backlog):

  * Invitation send + accept HTTP routes (DB-fixture bypass instead).
  * /analyze → auto-ticket bridge (not yet wired).
  * Ticket comments table + endpoint.

The test covers:

    Auth full          login, /me, refresh rotation + chain compromise,
                       logout, switch-tenant
    Tenant config      automation_mode, category toggle, custom create
    Ticket lifecycle   create → claim → wait_customer → resume → resolve
                       → close → reopen
    Quick-resolve      claim+resolve writes 2 transitions
    Cancel/uncancel    analyst cancel from OPEN, analyst-uncancel 403,
                       admin uncancel
    Reopen             analyst-reopen 403, admin reopen
    Multi-tenant       Bob is in two tenants, switch-tenant works
    RLS isolation      Bob in Beta cannot see Acme's tickets
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from conftest import E2ESeed
from e2e_helpers import (
    create_custom_category,
    create_ticket,
    find_category_id,
    get_me,
    get_timeline,
    list_categories,
    list_tickets,
    login,
    logout,
    quick_resolve,
    refresh,
    refresh_raw,
    set_automation_mode,
    switch_tenant,
    toggle_category,
    transition,
    transition_raw,
)


def test_complete_b2b_saas_flow(
    e2e_client: TestClient,
    e2e_seed: E2ESeed,
) -> None:
    """One long narrative across the shipped surface."""
    client = e2e_client
    seed = e2e_seed

    # === FAZ A: Alice (tenant_admin) login + /me =====================
    alice = login(
        client,
        seed.alice.email,
        seed.alice.password,
        active_tenant_id=seed.acme_tenant_id,
    )
    assert alice["access_token"] and alice["refresh_token"]

    me = get_me(client, alice)
    assert me["user"]["email"] == seed.alice.email
    assert me["active_context"]["role"] == "tenant_admin"
    assert me["active_context"]["tenant_id"] == str(seed.acme_tenant_id)

    # === FAZ B: Tenant configuration ===============================
    set_automation_mode(client, alice, "semi_auto")
    cats = list_categories(client, alice)
    # 8 globals seeded by TenantService.create at fixture time.
    assert len(cats) >= 8
    assert all(c["is_global"] for c in cats)

    pazarlama_id = find_category_id(cats, "pazarlama")
    toggle_category(client, alice, pazarlama_id, enabled=False)

    # Re-list and verify the toggle landed (also exercises cache invalidation).
    cats_after = list_categories(client, alice)
    pazarlama_after = next(
        c for c in cats_after if c["code"] == "pazarlama"
    )
    assert pazarlama_after["is_enabled"] is False

    # Custom category
    vip = create_custom_category(
        client,
        alice,
        code="vip_complaint",
        label_tr="VIP Müşteri Şikayeti",
    )
    assert vip["code"] == "vip_complaint"
    assert vip["is_global"] is False

    # Pull a global category id we'll use for ticket creation.
    kargo_id = find_category_id(cats_after, "kargo")

    # === FAZ C: Bob (analyst) login + manual ticket lifecycle =====
    bob = login(
        client,
        seed.bob.email,
        seed.bob.password,
        active_tenant_id=seed.acme_tenant_id,
    )
    bob_me = get_me(client, bob)
    assert bob_me["active_context"]["role"] == "analyst"

    manual = create_ticket(
        client,
        bob,
        category_id=kargo_id,
        title="Kargom 5 gündür gelmedi",
    )
    assert manual["state"] == "open"

    # OPEN → IN_PROGRESS (claim)
    after_claim = transition(client, bob, manual["id"], "claim")
    assert after_claim["state"] == "in_progress"
    assert after_claim["assigned_to_user_id"] == str(seed.bob.user_id)

    # IN_PROGRESS → PENDING_CUSTOMER
    after_wait = transition(client, bob, manual["id"], "wait_customer")
    assert after_wait["state"] == "pending_customer"
    assert after_wait["pending_since"] is not None

    # PENDING_CUSTOMER → IN_PROGRESS (resume)
    after_resume = transition(client, bob, manual["id"], "resume")
    assert after_resume["state"] == "in_progress"
    assert after_resume["pending_since"] is None  # cleared on exit

    # IN_PROGRESS → RESOLVED
    after_resolve = transition(client, bob, manual["id"], "resolve")
    assert after_resolve["state"] == "resolved"

    # RESOLVED → CLOSED
    after_close = transition(client, bob, manual["id"], "close")
    assert after_close["state"] == "closed"
    assert after_close["closed_at"] is not None

    # === FAZ D: Quick-resolve writes 2 transitions ===============
    quick = create_ticket(
        client, bob, category_id=kargo_id, title="Quick fix"
    )
    quick_resolved = quick_resolve(client, bob, quick["id"])
    assert quick_resolved["state"] == "resolved"

    timeline = get_timeline(client, bob, quick["id"])
    state_changes = [
        t for t in timeline["transitions"]
        if t["from_state"] != t["to_state"]
    ]
    assert len(state_changes) == 2, f"expected 2 transitions, got {state_changes}"
    pairs = {(t["from_state"], t["to_state"]) for t in state_changes}
    assert pairs == {("open", "in_progress"), ("in_progress", "resolved")}

    # === FAZ E: Cancel + admin uncancel + role 403 ==============
    spam = create_ticket(
        client, bob, category_id=kargo_id, title="Spam ticket"
    )
    # Bob (analyst) cancels from OPEN — allowed
    cancelled = transition(
        client, bob, spam["id"], "cancel", cancellation_reason="spam"
    )
    assert cancelled["state"] == "cancelled"
    assert cancelled["cancellation_reason"] == "spam"

    # Bob (analyst) cannot uncancel — TENANT_ADMIN only
    bob_uncancel = transition_raw(client, bob, spam["id"], "uncancel")
    assert bob_uncancel.status_code == 403, bob_uncancel.text

    # Alice (admin) can uncancel
    uncancelled = transition(client, alice, spam["id"], "uncancel")
    assert uncancelled["state"] == "open"
    assert uncancelled["cancellation_reason"] is None  # cleared
    assert uncancelled["cancelled_at"] is None

    # === FAZ F: Reopen + role 403 ================================
    # Bob cannot reopen the closed manual ticket
    bob_reopen = transition_raw(client, bob, manual["id"], "reopen")
    assert bob_reopen.status_code == 403, bob_reopen.text

    # Alice can reopen (within the 30d default window)
    reopened = transition(client, alice, manual["id"], "reopen")
    assert reopened["state"] == "open"
    assert reopened["closed_at"] is None  # cleared

    # === FAZ G: Multi-tenant context for Bob ====================
    bob_me_acme = get_me(client, bob)
    assert len(bob_me_acme["available_tenants"]) == 2
    # Slugs are randomized in the fixture; identify tenants by id+role.
    roles_by_tenant = {t["id"]: t["role"] for t in bob_me_acme["available_tenants"]}
    assert roles_by_tenant[str(seed.acme_tenant_id)] == "analyst"
    assert roles_by_tenant[str(seed.beta_tenant_id)] == "viewer"

    # Switch to Beta
    bob_beta = switch_tenant(client, bob, seed.beta_tenant_id)
    bob_me_beta = get_me(client, bob_beta)
    assert bob_me_beta["active_context"]["tenant_id"] == str(seed.beta_tenant_id)
    assert bob_me_beta["active_context"]["role"] == "viewer"

    # === FAZ H: RLS isolation (kritik) ==========================
    # Bob is now scoped to Beta. Acme's tickets must not leak.
    beta_tickets = list_tickets(client, bob_beta)
    visible_ids = {t["id"] for t in beta_tickets["tickets"]}
    acme_ticket_ids = {manual["id"], quick["id"], spam["id"]}
    assert acme_ticket_ids.isdisjoint(visible_ids), (
        f"RLS leak — Acme ticket(s) visible in Beta: "
        f"{acme_ticket_ids & visible_ids}"
    )

    # === FAZ I: Refresh rotation + chain compromise =============
    # Use Bob's Acme token (the chain we built up in steps A-G).
    rotated = refresh(client, bob["refresh_token"])
    assert rotated["access_token"] != bob["access_token"]
    assert rotated["refresh_token"] != bob["refresh_token"]

    # Replaying the consumed refresh token must trip chain compromise →
    # 401 + the entire family revoked, including the legitimate rotated
    # token.
    replay = refresh_raw(client, bob["refresh_token"])
    assert replay.status_code == 401, replay.text

    rotated_dead = refresh_raw(client, rotated["refresh_token"])
    assert rotated_dead.status_code == 401, rotated_dead.text

    # === FAZ J: Logout idempotency ==============================
    fresh = login(
        client,
        seed.bob.email,
        seed.bob.password,
        active_tenant_id=seed.acme_tenant_id,
    )
    logout(client, fresh["refresh_token"])
    after_logout = refresh_raw(client, fresh["refresh_token"])
    assert after_logout.status_code == 401, after_logout.text
