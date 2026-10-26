import { expect, test } from "@playwright/test";
import { mockCashierDay } from "./support/cashierDay.js";

// The row number and the line total must always be readable: a 3-digit row number and a 6-figure
// total are never clipped, and the tables never need a sideways scroll to reach the total column.
const SCREENS = ["/cashier/pos", "/cashier/returns", "/cashier/exchanges"];
const VIEWPORTS = [[1024, 576], [1280, 640], [1366, 768], [1920, 1080]];

for (const [w, h] of VIEWPORTS) {
  test(`row number and total are fully visible at ${w}x${h}`, async ({ page }) => {
    await page.setViewportSize({ width: w, height: h });
    await mockCashierDay(page);
    for (const route of SCREENS) {
      await page.goto(route, { waitUntil: "networkidle" });
      await expect(page.locator(".cashier-root tbody tr").first()).toBeVisible({ timeout: 8000 });
      const r = await page.evaluate(() =>
        [...document.querySelectorAll(".cashier-root table")].map((t) => {
          const ths = [...t.querySelectorAll("thead th")];
          const ti = ths.findIndex((th) => th.textContent.trim() === "الإجمالي");
          const rows = [...t.querySelectorAll("tbody tr")];
          rows.forEach((tr, i) => {
            const tds = tr.querySelectorAll("td");
            if (tds.length < 8) return;
            tds[0].textContent = String(100 + i);
            tds[ti].textContent = "123,456.00 ج.م";
          });
          const clipped = (td) => td.scrollWidth > td.clientWidth + 1;
          const box = t.parentElement;
          return {
            totalColumn: ti,
            rowNoClipped: rows.some((tr) => clipped(tr.querySelectorAll("td")[0])),
            totalClipped: rows.some((tr) => clipped(tr.querySelectorAll("td")[ti])),
            sideScroll: box.scrollWidth > box.clientWidth + 1,
          };
        }),
      );
      for (const t of r) {
        expect(t.totalColumn, `${route}: a table lost its الإجمالي column`).toBeGreaterThan(-1);
        expect(t.rowNoClipped, `${route} @${w}: the row number is clipped`).toBe(false);
        expect(t.totalClipped, `${route} @${w}: the total is clipped`).toBe(false);
        expect(t.sideScroll, `${route} @${w}: the table scrolls sideways`).toBe(false);
      }
    }
  });
}
