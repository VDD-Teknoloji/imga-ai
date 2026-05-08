import { expect, test } from "@playwright/test";

import { ALICE, loginAs } from "./fixtures";

/**
 * Sprint 9.0.6 B — HttpOnly cookie auth.
 *
 * Verifies the contract from the browser's perspective:
 *   1. /auth/login lands two HttpOnly cookies on the API host
 *      (``imga_access`` + ``imga_refresh``). They must NOT be
 *      readable from JS — that's the whole XSS-mitigation point.
 *   2. /auth/me with no Authorization header succeeds (the cookie
 *      carries the session).
 *   3. /auth/logout clears both cookies and a follow-up /auth/me
 *      401s.
 *
 * No localStorage assertion: that path was intentionally removed
 * in 9.0.6 B; tokenStorage is gone.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8003";

test.describe("cookie-auth", () => {
  test("login sets HttpOnly cookies that authenticate /auth/me", async ({
    page,
    context,
  }) => {
    await loginAs(page, ALICE.email, ALICE.password);

    const cookies = await context.cookies(API_BASE);
    const access = cookies.find((c) => c.name === "imga_access");
    const refresh = cookies.find((c) => c.name === "imga_refresh");

    expect(access, "imga_access cookie must be set on /auth/login").toBeDefined();
    expect(refresh, "imga_refresh cookie must be set on /auth/login").toBeDefined();
    expect(access?.httpOnly).toBe(true);
    expect(refresh?.httpOnly).toBe(true);

    // Same context: a /auth/me hit with no Authorization header should
    // succeed because the cookie rides on credentials:include.
    const me = await page.request.get(`${API_BASE}/auth/me`);
    expect(me.ok()).toBe(true);
    const body = (await me.json()) as { user: { email: string } };
    expect(body.user.email.toLowerCase()).toBe(ALICE.email.toLowerCase());
  });

  test("logout clears cookies and subsequent /auth/me 401s", async ({
    page,
    context,
  }) => {
    await loginAs(page, ALICE.email, ALICE.password);

    const out = await page.request.post(`${API_BASE}/auth/logout`, {
      data: {},
    });
    expect(out.status()).toBe(204);

    const after = await context.cookies(API_BASE);
    expect(after.find((c) => c.name === "imga_access")).toBeUndefined();
    expect(after.find((c) => c.name === "imga_refresh")).toBeUndefined();

    const me = await page.request.get(`${API_BASE}/auth/me`);
    expect(me.status()).toBe(401);
  });

  test("localStorage holds no auth tokens after login", async ({ page }) => {
    await loginAs(page, ALICE.email, ALICE.password);
    const stored = await page.evaluate(() => {
      const out: Record<string, string | null> = {};
      for (const key of [
        "imga_access_token",
        "imga_refresh_token",
        "access_token",
        "refresh_token",
      ]) {
        out[key] = window.localStorage.getItem(key);
      }
      return out;
    });
    for (const v of Object.values(stored)) {
      expect(v).toBeNull();
    }
  });
});
