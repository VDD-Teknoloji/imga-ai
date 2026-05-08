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

/** Sprint 9.0.6 B — auth pivoted to HttpOnly cookies. ``page.request``
 *  shares its cookie jar with the page's BrowserContext, so a POST to
 *  /auth/login here lands the auth cookies on the context; the next
 *  page.goto() navigation triggers /auth/me with credentials:include
 *  and the dashboard hydrates without the form being typed.
 */
export async function loginAs(
  page: Page,
  email: string,
  password: string,
): Promise<void> {
  const apiBase = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8003";

  const response = await page.request.post(`${apiBase}/auth/login`, {
    data: { email, password },
  });
  expect(
    response.ok(),
    `login failed: ${response.status()} ${await response.text()}`,
  ).toBe(true);
  // Cookies are now in the BrowserContext jar (host-bound to the API
  // origin). Navigate; the auth-store's initialize() reads /auth/me
  // and populates UI state.
  await page.goto("/");
}

export const ALICE = { email: "alice@acme.com", password: "dev123" } as const;
export const BOB = { email: "bob@acme.com", password: "dev123" } as const;
export const CHARLIE = { email: "charlie@acme.com", password: "dev123" } as const;
