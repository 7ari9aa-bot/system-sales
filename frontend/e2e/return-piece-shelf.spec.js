import { expect, test } from "@playwright/test";
import { mockCashierDay } from "./support/cashierDay.js";

// The return screen lets the cashier decide the shelf for each piece. Only HTTP is mocked: what is
// checked is what the screen actually sends to the returns endpoint.
async function openReturn(page, { restockDefault = true } = {}) {
  await mockCashierDay(page, { restockDefault });
  const sent = [];
  await page.route(/\/pos\/sessions\/[^/]+\/returns$/, (route) => {
    sent.push(route.request().postDataJSON());
    return route.fulfill({ json: { receipt_number: "POS-RET-1", refunded_total: "100.00", restocked: true, lines: [] } });
  });
  await page.goto("/cashier/returns", { waitUntil: "networkidle" });
  const main = page.locator("main:has(.cashier-root)");
  // The cashier finds the sale first; the mock holds one 30-line invoice.
  const search = main.getByRole("textbox", { name: "بحث عن الفاتورة الأصلية" });
  await search.fill("INV-1");
  await search.press("Enter");
  await expect(main.getByRole("button", { name: "إرجاع صنف 1", exact: true })).toBeVisible({ timeout: 8000 });
  return { main, sent };
}

async function pick(main, name) {
  await main.getByRole("button", { name: `إرجاع ${name}`, exact: true }).click();
}

test("each picked piece has its own shelf box, starting from the shop's default", async ({ page }) => {
  const { main } = await openReturn(page);
  await pick(main, "صنف 1");
  await pick(main, "صنف 2");
  await expect(main.getByRole("checkbox", { name: "إرجاع صنف 1 للرف" })).toBeChecked();
  await expect(main.getByRole("checkbox", { name: "إرجاع صنف 2 للرف" })).toBeChecked();
});

test("a piece can be kept off the shelf while the others go back, and only that piece says so", async ({ page }) => {
  const { main, sent } = await openReturn(page);
  await pick(main, "صنف 1");
  await pick(main, "صنف 2");
  await main.getByRole("checkbox", { name: "إرجاع صنف 2 للرف" }).uncheck();
  await expect(main.getByRole("checkbox", { name: "إرجاع صنف 1 للرف" })).toBeChecked();
  await main.getByRole("button", { name: /اعتماد المرتجع/ }).first().click();
  await expect.poll(() => sent.length).toBe(1);
  const [line1, line2] = sent[0].lines;
  expect("restock" in line1, "the untouched piece follows the whole return").toBe(false);
  expect(line2.restock, "the torn piece says no").toBe(false);
});

test("the shop's default of no starts every piece unchecked", async ({ page }) => {
  const { main } = await openReturn(page, { restockDefault: false });
  await pick(main, "صنف 1");
  await expect(main.getByRole("checkbox", { name: "إرجاع صنف 1 للرف" })).not.toBeChecked();
});

test("changing the whole-return box resets the pieces so the new choice is not silently ignored", async ({ page }) => {
  const { main } = await openReturn(page);
  await pick(main, "صنف 1");
  await main.getByRole("checkbox", { name: "إرجاع صنف 1 للرف" }).uncheck();
  const whole = main.getByRole("checkbox", { name: /إرجاع القطع للرف/ });
  await whole.uncheck();
  await whole.check();
  await expect(main.getByRole("checkbox", { name: "إرجاع صنف 1 للرف" })).toBeChecked();
});
