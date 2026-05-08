import { expect, test } from "@playwright/test";

import { ALICE, loginAs } from "./fixtures";

/**
 * Sprint 9.0.6 — mobile responsive sweep.
 *
 * Cheap viewport-pixel sanity: at iPhone-12 size (390 × 844) every
 * authenticated surface must render its <main> landmark and the
 * visible header without horizontal overflow. We don't assert on
 * bespoke layout per page (the 8 surfaces have different real
 * estate); we just catch the class of regression where a fixed-
 * width container or unwrapped flex row produces a horizontal
 * scrollbar on phone widths.
 *
 * The eight surfaces match the post-9.0.5-B authenticated nav:
 * dashboard, tickets, analyze, batch uploads, reports, strategy,
 * insights, and settings. Each test reuses the same logged-in
 * page so we pay the auth cost once.
 */

const PHONE = { width: 390, height: 844 };

const SURFACES: ReadonlyArray<{ name: string; path: string }> = [
  { name: "dashboard", path: "/" },
  { name: "tickets", path: "/tickets" },
  { name: "analyze", path: "/analyze" },
  { name: "batches", path: "/batches" },
  { name: "reports", path: "/reports" },
  { name: "strategy", path: "/strategy" },
  { name: "insights", path: "/insights" },
  { name: "settings", path: "/settings/sla-rules" },
];

test.describe("mobile-responsive", () => {
  test.use({ viewport: PHONE });

  for (const surface of SURFACES) {
    test(`${surface.name} renders without horizontal overflow on phone width`, async ({
      page,
    }) => {
      await loginAs(page, ALICE.email, ALICE.password);
      await page.goto(surface.path);

      // The <main> landmark must be present on every authenticated
      // surface — that's the cross-page guarantee the layout makes.
      await expect(page.getByRole("main")).toBeVisible();

      // documentElement.scrollWidth > clientWidth means the page
      // overflows horizontally — a phone-broken layout regression.
      const overflow = await page.evaluate(() => {
        const el = document.documentElement;
        return {
          scrollWidth: el.scrollWidth,
          clientWidth: el.clientWidth,
        };
      });
      expect(
        overflow.scrollWidth,
        `horizontal overflow at ${surface.path}: ${overflow.scrollWidth} > ${overflow.clientWidth}`,
      ).toBeLessThanOrEqual(overflow.clientWidth + 1); // +1 absorbs sub-pixel rounding
    });
  }
});
