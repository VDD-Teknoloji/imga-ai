import { defineConfig, devices } from "@playwright/test";

/**
 * Sprint 7.6.6 E2E config.
 *
 * Single browser (chromium) is enough for our acceptance: cross-
 * browser bug surface stays small for a B2B dashboard targeting
 * one user persona. We can add firefox/webkit when/if a customer
 * reports a non-Chromium issue.
 *
 * The config does NOT auto-start the API or postgres — those run
 * out-of-band (uvicorn + Docker). The Next.js web server starts
 * automatically via `webServer` so a local `npm run test:e2e`
 * works without the developer pre-launching `npm run dev`.
 *
 * Storage state file (.auth/alice.json) caches alice's logged-in
 * cookies so the bulk of tests skip the login form. Logged-in
 * tests reuse it; the auth-flow specs run unauthenticated.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false, // tests share a tenant; serialize to avoid races
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? "list" : [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: "http://localhost:3000",
    trace: "retain-on-failure",
    actionTimeout: 10_000,
    navigationTimeout: 20_000,
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: {
    command: "npm run dev",
    url: "http://localhost:3000",
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
