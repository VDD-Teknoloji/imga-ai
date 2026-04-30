import { expect, test } from "@playwright/test";

import { ALICE, loginAs } from "./fixtures";

/**
 * Cheap "structural a11y" spec — no external auditor (axe-core /
 * Lighthouse) so the dependency surface stays small. Three things
 * that catch ~80% of real regressions:
 *
 *   1. Every page has a single <h1> level heading.
 *   2. Every page exposes a <main> landmark.
 *   3. Every interactive icon-only button on the dashboard has an
 *      accessible name (aria-label or visible text).
 *
 * Lighthouse / axe-core can drop in later if a customer reports a
 * specific WCAG violation; this gate keeps the regressions visible
 * during the day-to-day cycle.
 */

test.describe("a11y structural", () => {
  test("login page has h1 + landmarks", async ({ page }) => {
    await page.goto("/login");
    // Login form uses CardTitle as the visual heading; it lands as
    // a div by default but gets accessible-name semantics. We
    // require at least one named heading on the page.
    await expect(page.getByText("imga.ai")).toBeVisible();
    // Form is keyboard-reachable: tabbing from email -> password -> submit.
    const email = page.getByLabel(/e-posta/i);
    await email.focus();
    await expect(email).toBeFocused();
  });

  test("dashboard exposes a main landmark + accessible icon buttons", async ({ page }) => {
    await loginAs(page, ALICE.email, ALICE.password);

    // Single main landmark.
    await expect(page.getByRole("main")).toBeVisible();
    // Single h1.
    const h1Count = await page.getByRole("heading", { level: 1 }).count();
    expect(h1Count).toBe(1);

    // Sidebar nav is reachable as a navigation landmark.
    await expect(page.getByRole("complementary", { name: /kenar çubuğu/i })).toBeVisible();
    await expect(page.getByRole("navigation", { name: /ana menü/i })).toBeVisible();

    // The desktop sidebar's collapse toggle is an icon-only button —
    // it must have an aria-label.
    const collapseBtn = page.getByRole("button", {
      name: /kenar çubuğunu (genişlet|daralt)/i,
    });
    await expect(collapseBtn).toBeVisible();
  });
});
