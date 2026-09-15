import { expect, test, type Page } from "@playwright/test";
import { ALICE, CHARLIE, loginAs } from "./fixtures";

async function noPageOverflow(page: Page) {
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1),
  ).toBe(true);
}

test("PRD saves answers, advances questions, survives navigation and exports", async ({ page }) => {
  await loginAs(page, ALICE.email, ALICE.password);
  await page.goto("/prd?section=problem");
  await expect(
    page.getByRole("heading", { name: "Ürün gereksinimleri", exact: true }),
  ).toBeVisible();
  await page
    .getByLabel("Yanıt / kapsam dışı gerekçesi")
    .fill("Pilot: teslimat şikâyetinin sorumlu ekibe yanlış yönlendirilmesi.");
  await page.getByRole("button", { name: "Taslağı kaydet", exact: true }).click();
  await expect(page.getByText("Kaydedilmemiş değişiklikler", { exact: true })).not.toBeVisible();
  await expect(page.getByText("Son kayıttaki sorular", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: /2\. Vizyon/ }).click();
  await expect(page).toHaveURL(/section=vision/);
  await page.reload();
  await expect(page.getByLabel("Başlık", { exact: true }).last()).toHaveValue(
    "Vizyon ve stratejik uyum",
  );
  await page.goBack();
  await expect(page.getByLabel("Yanıt / kapsam dışı gerekçesi")).toHaveValue(/Pilot:/);
  await noPageOverflow(page);
  await page.screenshot({
    path: "test-results/intelligence-prd-editor-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await noPageOverflow(page);
  await page.screenshot({
    path: "test-results/intelligence-prd-editor-mobile.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 1280, height: 720 });
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Markdown indir", exact: true }).click();
  expect((await downloadPromise).suggestedFilename()).toBe("imga-prd.md");
  await page.getByRole("button", { name: "Sürüm geçmişi", exact: true }).click();
  await expect(page.locator("details")).not.toHaveCount(0);
  await noPageOverflow(page);
  await page.screenshot({ path: "test-results/intelligence-prd-desktop.png", fullPage: true });
});

test("company publishes MENA context and retains a draft independently", async ({ page }) => {
  await loginAs(page, ALICE.email, ALICE.password);
  await page.goto("/company");
  await page.getByLabel("Ad", { exact: true }).fill("Acme MENA Pilot");
  await page.getByLabel("Yorum analiz profili").selectOption("mena");
  await page.getByLabel("Yapay zeka rapor dili").selectOption("ar");
  await page.getByRole("button", { name: "Onayla ve yayınla", exact: true }).click();
  await expect(page.getByText("Kaydedilmemiş değişiklikler", { exact: true })).not.toBeVisible();
  await page.getByRole("tab", { name: "Organizasyon", exact: true }).click();
  await expect(page).toHaveURL(/tab=organization/);
  await page.getByRole("button", { name: "Birim ekle", exact: true }).click();
  await page.getByLabel("Birim", { exact: true }).last().fill("Müşteri operasyonları");
  await page.getByLabel("Hesap veren rol", { exact: true }).last().fill("Operasyon yöneticisi");
  await page.getByRole("button", { name: "Taslağı kaydet", exact: true }).click();
  await expect(page.getByText("Kaydedilmemiş değişiklikler", { exact: true })).not.toBeVisible();
  await page.reload();
  await expect(page.getByRole("tab", { name: "Organizasyon", exact: true })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await page.getByRole("tab", { name: "Bulgular", exact: true }).click();
  await expect(page.getByText(/Analizde kullanılan onaylı sürüm/)).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await noPageOverflow(page);
  await page.screenshot({ path: "test-results/intelligence-company-mobile.png", fullPage: true });
});

test("customer risk, unknown data, history and filters work on desktop and mobile", async ({
  page,
}) => {
  await loginAs(page, ALICE.email, ALICE.password);
  await page.goto("/churn");
  await page.getByRole("button", { name: "Müşteri ekle", exact: true }).click();
  const dialog = page.getByRole("dialog");
  const id = "e2e_" + Date.now();
  await dialog.getByLabel("CRM müşteri kimliği").fill(id);
  await dialog.getByRole("textbox", { name: "Ad", exact: true }).fill("عميل تجريبي");
  await dialog.getByLabel("Veri kaynağı").fill("E2E fixture");
  await dialog.getByLabel("Verinin gözlem tarihi").fill(new Date().toISOString().slice(0, 10));
  await dialog.getByLabel("İlişkiyi sonlandırma talebi").selectOption("true");
  await dialog.getByLabel("Sorumlu", { exact: true }).fill("Account team");
  await dialog.getByRole("button", { name: "Müşteriyi kaydet", exact: true }).click();
  await expect(dialog).not.toBeVisible();
  await page.getByLabel("Kimlik, ad veya segment ara").fill(id);
  await page.getByLabel("Risk düzeyi", { exact: true }).selectOption("critical");
  await expect(page.getByRole("row").filter({ hasText: id })).toContainText("60");
  await page.reload();
  await expect(page.getByLabel("Risk düzeyi", { exact: true })).toHaveValue("critical");
  await expect(page.getByLabel("Kimlik, ad veya segment ara")).toHaveValue(id);
  await page.getByLabel("Risk düzeyi", { exact: true }).selectOption("all");
  await expect(page).not.toHaveURL(/band=critical/);
  await page.goBack();
  await expect(page).toHaveURL(/band=critical/);
  await expect(page.getByLabel("Risk düzeyi", { exact: true })).toHaveValue("critical");
  await noPageOverflow(page);
  await page.screenshot({ path: "test-results/intelligence-churn-desktop.png", fullPage: true });
  await page.getByRole("button", { name: "عميل تجريبي", exact: true }).click();
  await expect(dialog.getByText("Kaynak sistemde açık iptal talebi var.")).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await noPageOverflow(page);
  await page.screenshot({ path: "test-results/intelligence-customer-mobile.png", fullPage: true });
  await dialog.getByLabel("İlişkiyi sonlandırma talebi").selectOption("unknown");
  await dialog.getByRole("button", { name: "Müşteriyi kaydet", exact: true }).click();
  await expect(dialog).not.toBeVisible();
  await page.getByLabel("Risk düzeyi", { exact: true }).selectOption("unknown");
  await expect(page.getByRole("row").filter({ hasText: id })).toContainText("Yetersiz veri");
  await page.getByRole("button", { name: "عميل تجريبي", exact: true }).click();
  await dialog.getByText("Sürüm geçmişi", { exact: true }).click();
  await expect(dialog.getByText(/Sürüm 2/)).toBeVisible();
  page.once("dialog", (confirmation) => confirmation.accept());
  await dialog.getByRole("button", { name: "Sil", exact: true }).click();
  await expect(dialog).not.toBeVisible();
});

test("viewer cannot edit new workspaces", async ({ page }) => {
  await loginAs(page, CHARLIE.email, CHARLIE.password);
  await page.goto("/prd");
  await expect(page.getByText("Salt okunur", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Taslağı kaydet", exact: true })).toHaveCount(0);
  await expect(page.getByLabel("Yanıt / kapsam dışı gerekçesi")).toBeDisabled();
  await page.goto("/churn");
  await expect(page.getByRole("button", { name: "Müşteri ekle", exact: true })).toHaveCount(0);
});
