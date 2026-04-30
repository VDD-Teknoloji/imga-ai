/**
 * Shared Playwright fixtures.
 *
 * Each test that needs an authenticated session uses the
 * `loginAs(page, email, password, tenantId?)` helper rather than
 * a global storage state — that way logout / role-switch tests
 * don't pollute each other and the seed data stays the source of
 * truth for which users exist.
 *
 * Tests assume `make seed-dev` has already run; the assertions
 * lock the dashboard counts (open=11, today=3, ...) to that
 * fixture's distribution.
 */

import { expect, type Page } from "@playwright/test";

/** Bypass the login form by writing the JWT pair directly into
 * localStorage, then navigate to /. Faster than typing the form
 * for every test, and keeps the auth flow tests focused on the
 * form itself. */
export async function loginAs(
  page: Page,
  email: string,
  password: string,
): Promise<void> {
  // Hit /auth/login on the API directly to mint a token pair, then
  // seed localStorage. Going through the UI in every test would slow
  // the suite ~5×.
  const apiBase = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8003";

  const response = await page.request.post(`${apiBase}/auth/login`, {
    data: { email, password },
  });
  expect(response.ok(), `login failed: ${response.status()} ${await response.text()}`).toBe(true);
  const tokens = (await response.json()) as { access_token: string; refresh_token: string };

  // Visit any same-origin page first so localStorage is reachable, then
  // seed the tokens and reload to pick them up.
  await page.goto("/login");
  await page.evaluate((pair) => {
    window.localStorage.setItem("imga_access_token", pair.access);
    window.localStorage.setItem("imga_refresh_token", pair.refresh);
  }, { access: tokens.access_token, refresh: tokens.refresh_token });
  await page.goto("/");
}

export const ALICE = { email: "alice@acme.com", password: "dev123" } as const;
export const BOB = { email: "bob@acme.com", password: "dev123" } as const;
export const CHARLIE = { email: "charlie@acme.com", password: "dev123" } as const;
