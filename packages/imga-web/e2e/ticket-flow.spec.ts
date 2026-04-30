import { expect, test } from "@playwright/test";

import { ALICE, loginAs } from "./fixtures";

/**
 * Ticket flow spec — covers the three core dashboard surfaces: the
 * list with URL-bound filters, a state-machine transition (claim a
 * fresh OPEN ticket from the seed), and the role guard that hides
 * settings from non-admins.
 *
 * Each test is independently logged in via loginAs (no shared
 * storage state) so a failure stays local and a logout flow added
 * later doesn't poison neighbours.
 */

test.describe("tickets", () => {
  test("filter ?state=open shows only open tickets", async ({ page }) => {
    await loginAs(page, ALICE.email, ALICE.password);
    await page.goto("/tickets");

    // Open the Durum (state) filter and tick "Açık".
    await page.getByRole("button", { name: /^durum/i }).click();
    await page.getByRole("option", { name: "Açık" }).click();
    // Close the popover by clicking the page header.
    await page.getByRole("heading", { name: /ticket'lar/i }).click();

    // URL reflects the filter; CSV multi-value (single value here).
    await expect(page).toHaveURL(/\?state=open(\b|&)/);

    // Header summary shows "5 ticket / toplam 18" — five OPEN rows
    // in the seed. Use a substring rather than the exact string in
    // case the layout reformats whitespace.
    await expect(page.getByText(/5 ticket \/ toplam 18/i)).toBeVisible();
  });

  test("alice claims a fresh OPEN ticket → state badge becomes İşlemde", async ({
    page,
  }) => {
    await loginAs(page, ALICE.email, ALICE.password);

    // Land on /tickets list filtered to OPEN so we can pick one
    // deterministically. The seed leaves five OPEN tickets but only
    // three "today" ones are unassigned; pick the third (oldest)
    // open row to stay clear of the parallel actions in other tests.
    await page.goto("/tickets?state=open");

    // The first row's title link — tap it.
    await page
      .getByRole("link", { name: /kargom 5 gündür gelmedi|faturada yanlış|ürün hasarlı|eski kargo|müşteri hizmetleri/i })
      .first()
      .click();

    // Detail page rendered. Click "Üstlen" — it's the primary action
    // on an OPEN ticket per the role matrix.
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await page.getByRole("button", { name: /^üstlen$/i }).click();

    // Toast confirms; state badge in the side panel flips to
    // "İşlemde". The badge text occurs both in the side panel and
    // in the timeline event we just created — first match is fine.
    await expect(page.getByText(/üstlen işlemi tamamlandı/i)).toBeVisible();
    await expect(page.getByText(/İşlemde/).first()).toBeVisible({ timeout: 8_000 });
  });

  test("a viewer cannot reach settings — Yetkiniz yok renders", async ({ page }) => {
    // Charlie is the seeded viewer.
    await loginAs(page, "charlie@acme.com", "dev123");
    await page.goto("/settings");

    await expect(page.getByRole("heading", { name: /yetkiniz yok/i })).toBeVisible();
    await expect(page.getByText(/yalnızca yöneticiler/i)).toBeVisible();
  });
});
