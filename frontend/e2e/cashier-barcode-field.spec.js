import { expect, test } from "@playwright/test";
import { mockCashierDay } from "./support/cashierDay.js";

// A cashier types or scans a full EAN-13 and must SEE all of it. The barcode column used to be a percentage of the table,
// so below 1366px wide a 13-digit code was cut off and the cashier could not check what had been entered.
const VIEWPORTS = [[1024, 576], [1280, 640], [1366, 768], [1920, 1080]];
const EAN13 = "6221234567891";

for (const [w, h] of VIEWPORTS) {
  test(`a full 13-digit barcode is fully visible in the entry field at ${w}x${h}`, async ({ page }) => {
    await page.setViewportSize({ width: w, height: h });
    await mockCashierDay(page);
    await page.goto("/cashier/pos", { waitUntil: "networkidle" });
    const field = page.getByLabel("باركود المنتج").first();
    await expect(field).toBeVisible({ timeout: 8000 });
    await field.fill(EAN13);
    const fit = await field.evaluate((el) => ({ shown: el.scrollWidth <= el.clientWidth + 1, height: el.getBoundingClientRect().height }));
    expect(fit.shown, `@${w}: the barcode is cut off inside its field`).toBe(true);
    expect(fit.height, `@${w}: the barcode field is too short to read comfortably`).toBeGreaterThanOrEqual(30);
  });
}
