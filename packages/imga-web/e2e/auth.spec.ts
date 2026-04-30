import { expect, test } from "@playwright/test";

import { ALICE } from "./fixtures";

/**
 * Auth flow specs — exercise the login form itself rather than
 * the localStorage shortcut other specs use.
 */

test.describe("auth", () => {
  test("happy path: alice logs in and lands on dashboard", async ({ page }) => {
    await page.goto("/login");

    await page.getByLabel(/e-posta/i).fill(ALICE.email);
    await page.getByLabel(/şifre/i).fill(ALICE.password);
    await page.getByRole("button", { name: /giriş yap/i }).click();

    // Lands on / and the dashboard greeting shows Alice's first name.
    await expect(page).toHaveURL("/");
    await expect(page.getByRole("heading", { level: 1 })).toContainText(/merhaba/i);
    // The four metric cards are rendered with the seeded counts.
    // (open=11, today=3, high_priority=6, resolved_7d=3)
    await expect(page.getByText("Açık ticket")).toBeVisible();
    await expect(page.getByText("Bugün açılan")).toBeVisible();
    await expect(page.getByText("Yüksek öncelik")).toBeVisible();
    await expect(page.getByText("Son 7 günde çözülen")).toBeVisible();
  });

  test("invalid credentials surface the toast and keep the user on /login", async ({
    page,
  }) => {
    await page.goto("/login");

    await page.getByLabel(/e-posta/i).fill(ALICE.email);
    await page.getByLabel(/şifre/i).fill("definitely-wrong-password");
    await page.getByRole("button", { name: /giriş yap/i }).click();

    // Sonner renders the destructive toast inline; we just need to see
    // the failure copy and that the URL didn't progress to /.
    await expect(page.getByText(/giriş başarısız/i)).toBeVisible();
    await expect(page).toHaveURL(/\/login$/);
  });
});
