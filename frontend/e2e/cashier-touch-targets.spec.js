import { expect, test } from "@playwright/test";
import { mockCashierDay } from "./support/cashierDay.js";

// A cashier taps these with a finger on a till tablet. The filter panel's toggle and its reset
// button are on every table screen, so a target a finger cannot hit reliably is a daily annoyance.
// 32px is the floor we hold (WCAG 2.2's minimum is 24px; the comfortable size is larger).
const MIN = 32;
// every screen that mounts a FilterPanel
const SCREENS = [
  "/cashier/inventory", "/cashier/inventory/movements", "/cashier/activity-log", "/cashier/exchanges/log",
  "/cashier/expenses", "/cashier/labels", "/cashier/purchases", "/cashier/reports", "/cashier/returns/log",
  "/cashier/shifts", "/cashier/supplier-returns", "/cashier/suppliers",
];

for (const route of SCREENS) {
  test(`${route}: filter panel buttons are at least ${MIN}px tall`, async ({ page }) => {
    await page.setViewportSize({ width: 1024, height: 700 });
    await mockCashierDay(page);
    await page.goto(route, { waitUntil: "networkidle" });
    const sizes = await page.evaluate(() =>
      [...document.querySelectorAll(".cashier-root button")]
        // the panel's own controls: its toggle and its header reset button. (The reset button in an
        // empty-table state is a separate, secondary `Button size="sm"` used all over the cashier.)
        .filter((b) => b.closest("[data-state]") && (/فلاتر البحث/.test(b.textContent) || (/مسح الفلاتر/.test(b.textContent) && b.closest(".card-soft"))))
        .map((b) => { const r = b.getBoundingClientRect(); return { name: b.textContent.trim().slice(0, 14), h: Math.round(r.height), w: Math.round(r.width) }; }),
    );
    expect(sizes.length, `${route}: no filter panel button found, so this screen is not being checked`).toBeGreaterThan(0);
    for (const s of sizes) expect(s.h, `${route}: "${s.name}" is ${s.w}x${s.h}`).toBeGreaterThanOrEqual(MIN);
  });
}

test("the filter toggle still opens and closes the panel", async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 700 });
  await mockCashierDay(page);
  await page.goto("/cashier/inventory", { waitUntil: "networkidle" });
  const toggle = page.getByRole("button", { name: /فلاتر البحث/ }).first();
  await expect(toggle).toHaveAttribute("data-state", "open");
  await toggle.click();
  await expect(toggle).toHaveAttribute("data-state", "closed");
  await toggle.click();
  await expect(toggle).toHaveAttribute("data-state", "open");
});
