import { expect, test } from "@playwright/test";

import { ALICE, loginAs } from "./fixtures";

/**
 * Sprint 9.0.6 A — concurrent /auth/refresh coalesce.
 *
 * Without the api-client's module-level mutex, N simultaneous 401s
 * would each fire their own /auth/refresh; the second arrival would
 * post a now-consumed refresh token, trip chain-reuse detection,
 * and force a hard logout. We validate the contract by counting
 * /auth/refresh round-trips during a real dashboard render — the
 * page issues several authenticated XHRs in parallel on mount, so
 * stripping the access cookie before reload manufactures the burst
 * naturally.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8003";

test.describe("refresh-mutex", () => {
  test("dashboard mount with stripped access cookie issues one /auth/refresh", async ({
    page,
  }) => {
    await loginAs(page, ALICE.email, ALICE.password);

    // Wipe just the access cookie; keep refresh so the api-client can
    // rotate. Every page-mount XHR will 401 once and retry — the
    // mutex must coalesce those retries into a single rotation.
    const before = await page.context().cookies(API_BASE);
    expect(before.find((c) => c.name === "imga_refresh")).toBeDefined();
    await page.context().clearCookies({ name: "imga_access" });

    let refreshCount = 0;
    page.on("request", (req) => {
      if (req.url().endsWith("/auth/refresh") && req.method() === "POST") {
        refreshCount += 1;
      }
    });

    // Reload — TanStack Query fires the dashboard's initial fetches
    // (auth/me + tickets + tenants/me/... ) in parallel.
    await page.goto("/");
    // Wait until the dashboard heading is rendered, which means the
    // post-rotation replays have all settled.
    await expect(page.getByRole("heading", { level: 1 })).toContainText(/merhaba/i);

    expect(
      refreshCount,
      `mutex broke: expected 1 /auth/refresh, got ${refreshCount}`,
    ).toBe(1);
  });
});
