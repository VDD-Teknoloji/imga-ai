import { expect, test } from "@playwright/test";

import { ALICE, loginAs } from "./fixtures";

/**
 * Manual analyze flow — Sprint 7.7.3 / Alt-Faz 7.7.3 page. Alice is
 * a tenant_admin in the Acme seed; Acme runs in semi_auto mode by
 * default which means a clearly-negative kargo complaint sails
 * through the threshold and lands a "create" decision card with a
 * "bilete git" CTA.
 *
 * The test asserts:
 *   * the page loads from the sidebar nav,
 *   * submit while text is empty is disabled (form validation),
 *   * a populated submit returns the analysis summary card,
 *   * the decision card surfaces with a recognisable Türkçe label.
 *
 * The decision branch we land on is data-dependent — the assertion
 * stays loose ("herhangi bir karar kartı render edildi mi") rather
 * than locking to "create" so a seed change doesn't break the test.
 */

test.describe("analyze", () => {
  test("alice analyzes a kargo complaint and sees a decision card", async ({
    page,
  }) => {
    await loginAs(page, ALICE.email, ALICE.password);
    await page.goto("/");

    // Sidebar item -> /analyze.
    await page.getByRole("link", { name: /^analiz$/i }).click();
    await expect(page).toHaveURL(/\/analyze$/);

    // Sayfa başlığı + ana CTA görünür.
    await expect(
      page.getByRole("heading", { name: /yorum analiz et/i }),
    ).toBeVisible();
    const submit = page.getByRole("button", { name: /^analiz et$/i });
    // Boş textarea ile submit devre dışı.
    await expect(submit).toBeDisabled();

    // Tipik bir negatif kargo yorumu — semi_auto eşik altında veya
    // üstünde olsa da bir decision card mutlaka gelir.
    await page
      .getByLabel(/yorum metni/i)
      .fill("Kargom 5 gündür gelmedi, takip numarası da çalışmıyor.");
    await expect(submit).toBeEnabled();
    await submit.click();

    // Spinner state'i çok kısa olabilir; sonuç kartının gelmesini
    // bekle. CardTitle real heading rolüne sahip değil; getByText
    // ile yakalıyoruz.
    await expect(page.getByText(/analiz sonucu/i)).toBeVisible({
      timeout: 15_000,
    });

    // Decision card 5 başlıktan herhangi biri olabilir; bunlardan
    // birini görmek yeterli.
    const decisionTitles = [
      /otomatik bilet açıldı/i,
      /aynı metin son 24 saatte zaten analiz edildi/i,
      /otomasyon modu manuel/i,
      /eşik altı/i,
      /kategori belirsiz/i,
    ];
    const found = await Promise.race(
      decisionTitles.map(async (re) => {
        try {
          await expect(page.getByText(re)).toBeVisible({ timeout: 5_000 });
          return true;
        } catch {
          return false;
        }
      }),
    );
    expect(found).toBe(true);
  });
});
