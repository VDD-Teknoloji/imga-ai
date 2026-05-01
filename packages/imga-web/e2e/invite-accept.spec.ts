import { expect, test } from "@playwright/test";

import { ALICE } from "./fixtures";

/**
 * Invite accept flow (new user) — Sprint 7.7.3 / Alt-Faz 7.7.3
 * public page. Setup:
 *   1. Authenticated request to /auth/login as Alice (tenant_admin).
 *   2. Authenticated request to /admin/tenants/{acme}/invitations
 *      with a fresh email — captures the plaintext token.
 *   3. Visit /invite/{token} as anonymous (no localStorage tokens).
 *   4. Fill the new-user form, submit, expect redirect to /.
 *
 * The test creates a unique invitation per run (timestamp suffix on
 * the email) so re-runs against the same DB don't collide with each
 * other or with seed users. Cleanup is best-effort: the new user
 * row stays in the DB; subsequent runs use a fresh email.
 */

test.describe("invite accept", () => {
  test("new user accepts a freshly minted invitation", async ({ page }) => {
    const apiBase =
      process.env.NEXT_PUBLIC_API_URL || "http://localhost:8003";

    // Step 1 — login as Alice via the API and grab her access token
    // + active tenant id.
    const loginRes = await page.request.post(`${apiBase}/auth/login`, {
      data: { email: ALICE.email, password: ALICE.password },
    });
    expect(loginRes.ok()).toBe(true);
    const tokens = (await loginRes.json()) as {
      access_token: string;
      refresh_token: string;
    };

    const meRes = await page.request.get(`${apiBase}/auth/me`, {
      headers: { Authorization: `Bearer ${tokens.access_token}` },
    });
    expect(meRes.ok()).toBe(true);
    const me = (await meRes.json()) as {
      active_context: { tenant_id: string };
    };
    const tenantId = me.active_context.tenant_id;

    // Step 2 — mint an invitation for a fresh email.
    const invitee = `e2e-invitee-${Date.now()}@example.com`;
    const inviteRes = await page.request.post(
      `${apiBase}/admin/tenants/${tenantId}/invitations`,
      {
        headers: { Authorization: `Bearer ${tokens.access_token}` },
        data: { email: invitee, role: "analyst" },
      },
    );
    expect(
      inviteRes.ok(),
      `invite create failed: ${inviteRes.status()} ${await inviteRes.text()}`,
    ).toBe(true);
    const invite = (await inviteRes.json()) as { token: string };

    // Step 3 — visit /invite/{token} as anonymous. Clear any stored
    // tokens first so the page renders the public flow rather than
    // re-using Alice's session.
    await page.goto("/login");
    await page.evaluate(() => window.localStorage.clear());

    await page.goto(`/invite/${invite.token}`);

    // Preview header: tenant name + invited email visible. CardTitle
    // doesn't expose a real heading role, so getByText is the right
    // matcher for the brand line.
    await expect(page.getByText(invitee)).toBeVisible({ timeout: 8_000 });
    await expect(page.getByText(/imga\.ai/i).first()).toBeVisible();

    // email_exists=false → new-account form. Fill it.
    await page.getByLabel(/tam adınız/i).fill("E2E Invitee");
    // Two password fields with identical accessible names; index by
    // their distinct label text instead.
    await page.getByLabel(/^şifre$/i).fill("E2e-Pass-Word-1");
    await page.getByLabel(/şifre tekrar/i).fill("E2e-Pass-Word-1");

    await page.getByRole("button", { name: /daveti kabul et/i }).click();

    // Lands on / with the dashboard rendered for the new user.
    await expect(page).toHaveURL("/", { timeout: 10_000 });
    await expect(page.getByText(/açık ticket/i)).toBeVisible();
  });
});
