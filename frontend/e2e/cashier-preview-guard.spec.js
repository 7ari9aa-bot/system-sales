import { expect, test } from "@playwright/test";

// يعمل على نسختين مبنيتين: واحدة بوضع المعاينة (CASHIER_PREVIEW_URL) وواحدة عادية (CASHIER_NORMAL_URL).
// الهدف: المعاينة تفتح الكاشير بدون backend، والنسخة العادية تظل محمية بتسجيل الدخول.
const PREVIEW = process.env.CASHIER_PREVIEW_URL;
const NORMAL = process.env.CASHIER_NORMAL_URL;

async function noBackend(page) {
  await page.route("**/api/**", (r) => r.fulfill({ status: 404, body: "Not Found" }));
  await page.route("**/auth/**", (r) => r.fulfill({ status: 404, body: "Not Found" }));
}

test("preview build opens /cashier without a backend", async ({ page }) => {
  test.skip(!PREVIEW, "CASHIER_PREVIEW_URL not set");
  await noBackend(page);
  await page.goto(`${PREVIEW}/cashier/pos`, { waitUntil: "networkidle" });
  await expect(page.locator(".cashier-root")).toBeVisible();
  expect(new URL(page.url()).pathname).toBe("/cashier/pos");
});

test("normal build still requires login for /cashier", async ({ page }) => {
  test.skip(!NORMAL, "CASHIER_NORMAL_URL not set");
  await noBackend(page);
  await page.goto(`${NORMAL}/cashier/pos`, { waitUntil: "networkidle" });
  await expect(page.locator(".cashier-root")).toHaveCount(0);
  expect(new URL(page.url()).pathname).toBe("/login");
});
