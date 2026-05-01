import { expect, test } from "@playwright/test";

import { BOB, loginAs } from "./fixtures";

/**
 * Comments flow — Sprint 7.7.2 / Alt-Faz 4. Bob is the seeded
 * analyst in Acme; analysts can write both internal_note and
 * customer_reply. We exercise the simpler internal_note path
 * (default kind, no extra radio click) so the test stays robust
 * against future tweaks to the kind toggle UX.
 */

test.describe("comments", () => {
  test("bob posts an internal note on an open ticket", async ({ page }) => {
    await loginAs(page, BOB.email, BOB.password);

    // Seed leaves five OPEN tickets; pick the first row of the list.
    await page.goto("/tickets?state=open");
    await page
      .getByRole("link", {
        name: /kargom 5 gündür gelmedi|faturada yanlış|ürün hasarlı|eski kargo|müşteri hizmetleri/i,
      })
      .first()
      .click();

    // Detail page rendered. Comments section heading lives below the
    // timeline.
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByRole("heading", { name: /^yorumlar/i })).toBeVisible();

    const composerBody = page.getByLabel(/yorum metni/i);
    await composerBody.fill(
      "Müşteriyi aradım, kargo şirketi bilgisi şu anda eski.",
    );

    // "İç not" is selected by default; just submit.
    await page.getByRole("button", { name: /^gönder$/i }).click();

    // The new comment appears in the list (still in chronological
    // order — the most recent is at the bottom).
    await expect(
      page
        .getByText(/müşteriyi aradım, kargo şirketi bilgisi şu anda eski/i)
        .first(),
    ).toBeVisible({ timeout: 8_000 });

    // Internal note badge surfaces on the new card. JS regex i-flag
    // doesn't reliably case-fold Turkish İ, so match by exact
    // string. .first() picks the badge in the new comment card
    // (the radio label in the composer also matches).
    await expect(page.getByText("İç not").first()).toBeVisible();
  });
});
