import { expect, test } from "@playwright/test";

import { ALICE } from "./fixtures";

/**
 * Sprint 9.4 hotfix — /invite/[token] is a public route. A fresh
 * browser (no auth cookie) must land on the invite form and STAY
 * there; the AuthProvider's /auth/me bootstrap used to fire on
 * every route, hit 401, run the api-client refresh-replay path,
 * fire onSessionExpired, and redirect to /login?expired=1. The
 * invitee saw the form for ~1s then bounced.
 *
 * This regression locks two contracts the fix has to keep:
 *
 *   1. URL stability — /invite/[token] does not redirect to /login
 *      within the first few seconds of mount.
 *   2. No /auth/me round-trip — public routes don't probe the
 *      session at all (saves a request AND ensures the redirect
 *      chain can't fire even if a future api-client tweak removes
 *      one of its other guards).
 */

test.describe("invite public access (Sprint 9.4 hotfix)", () => {
  test("anonymous visit to /invite/[token] does not redirect", async ({
    page,
    context,
  }) => {
    const apiBase =
      process.env.NEXT_PUBLIC_API_URL || "http://localhost:8003";

    // Mint a fresh invitation as Alice. The page.request jar shares
    // the BrowserContext jar — we'll wipe it before the actual visit.
    const loginRes = await page.request.post(`${apiBase}/auth/login`, {
      data: { email: ALICE.email, password: ALICE.password },
    });
    expect(loginRes.ok()).toBe(true);
    const tokens = (await loginRes.json()) as { access_token: string };

    const meRes = await page.request.get(`${apiBase}/auth/me`, {
      headers: { Authorization: `Bearer ${tokens.access_token}` },
    });
    expect(meRes.ok()).toBe(true);
    const me = (await meRes.json()) as {
      active_context: { tenant_id: string };
    };

    const invitee = `e2e-public-invitee-${Date.now()}@example.com`;
    const inviteRes = await page.request.post(
      `${apiBase}/admin/tenants/${me.active_context.tenant_id}/invitations`,
      {
        headers: { Authorization: `Bearer ${tokens.access_token}` },
        data: { email: invitee, role: "analyst" },
      },
    );
    expect(inviteRes.ok()).toBe(true);
    const invite = (await inviteRes.json()) as { token: string };

    // Wipe every cookie the context picked up from /auth/login so the
    // upcoming navigation is genuinely anonymous.
    await context.clearCookies();

    // Watch the network — /auth/me must NOT fire on the public route.
    const meRequestUrls: string[] = [];
    page.on("request", (req) => {
      if (req.url().endsWith("/auth/me")) {
        meRequestUrls.push(req.url());
      }
    });

    await page.goto(`/invite/${invite.token}`);

    // The invite form must render. ``invitee`` is the email the
    // invitation was minted with; the preview surfaces it verbatim.
    await expect(page.getByText(invitee)).toBeVisible({ timeout: 8_000 });

    // Hold for a beat so the AuthProvider's mount-time useEffect has
    // a chance to mis-fire. Pre-fix the redirect landed within ~1s.
    await page.waitForTimeout(2_500);

    // URL stability — still on /invite, not bounced to /login.
    expect(page.url()).toContain(`/invite/${invite.token}`);
    expect(page.url()).not.toContain("/login");

    // /auth/me must not have been called by the public bootstrap. Any
    // call here is the bug coming back.
    expect(
      meRequestUrls,
      `Public /invite route fired /auth/me — public-path allowlist is broken. ` +
        `Calls: ${meRequestUrls.join(", ")}`,
    ).toHaveLength(0);
  });

  test("anonymous visit to /login does not redirect either", async ({
    page,
    context,
  }) => {
    // Same contract for /login — it's the destination of a session-
    // expired redirect; if /login itself fires /auth/me on an empty
    // session, the user lands on a refresh loop.
    await context.clearCookies();

    const meRequestUrls: string[] = [];
    page.on("request", (req) => {
      if (req.url().endsWith("/auth/me")) {
        meRequestUrls.push(req.url());
      }
    });

    await page.goto("/login");
    await expect(page.getByLabel(/e-?posta/i)).toBeVisible();
    await page.waitForTimeout(1_500);

    expect(page.url()).toContain("/login");
    expect(meRequestUrls).toHaveLength(0);
  });
});
