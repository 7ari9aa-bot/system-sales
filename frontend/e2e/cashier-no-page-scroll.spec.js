import { expect, test } from "@playwright/test";
import { mockCashierDay } from "./support/cashierDay.js";

// The sell, return and exchange screens are fixed-height work surfaces: the page must never scroll
// vertically, even with a long invoice. Only the tables inside may scroll. Measured on the REAL
// screens (a started day is mocked), at laptop / desktop / phone sizes, after adding 40 more rows.
const SCREENS = ["/cashier/pos", "/cashier/returns", "/cashier/exchanges"];
const VIEWPORTS = [
  { name: "small laptop", width: 1280, height: 640 },
  { name: "laptop", width: 1366, height: 768 },
  { name: "wide 2xl", width: 1600, height: 900 },
  { name: "full hd", width: 1920, height: 1080 },
  { name: "phone", width: 390, height: 780 },
];

for (const vp of VIEWPORTS) {
  test(`no page scroll on sell / return / exchange at ${vp.name} (${vp.width}x${vp.height})`, async ({ page }) => {
    await page.setViewportSize({ width: vp.width, height: vp.height });
    await mockCashierDay(page);
    for (const route of SCREENS) {
      await page.goto(route, { waitUntil: "networkidle" });
      await expect(page.locator(".cashier-root tbody tr").first(), `${route} must show its real table`).toBeVisible({ timeout: 8000 });
      await page.waitForTimeout(400); // let the row-fitting settle
      const m = await page.evaluate(() => {
        document.querySelectorAll(".cashier-root tbody").forEach((tb) => {
          const tr = tb.querySelector("tr");
          if (tr) for (let i = 0; i < 40; i++) tb.appendChild(tr.cloneNode(true));
        });
        const main = document.querySelector("main:has(.cashier-root)");
        return {
          page: document.scrollingElement.scrollHeight - window.innerHeight,
          main: main.scrollHeight - main.clientHeight,
          tablesScrolling: [...document.querySelectorAll(".cashier-root *")].filter((e) => {
            const o = getComputedStyle(e).overflowY;
            return (o === "auto" || o === "scroll") && e.scrollHeight > e.clientHeight + 2;
          }).length,
        };
      });
      expect(m.page, `${route} @${vp.name}: the page scrolls by ${m.page}px`).toBeLessThanOrEqual(1);
      expect(m.main, `${route} @${vp.name}: <main> overflows by ${m.main}px`).toBeLessThanOrEqual(1);
      expect(m.tablesScrolling, `${route} @${vp.name}: long tables must scroll inside themselves`).toBeGreaterThan(0);
    }
  });
}
