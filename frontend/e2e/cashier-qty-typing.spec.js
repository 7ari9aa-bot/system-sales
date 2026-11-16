import { expect, test } from "@playwright/test";
import { mockCashierDay } from "./support/cashierDay.js";

// A cashier clears the quantity box and types a number. Every keystroke used to go through the stock clamp, so clearing
// "1" and typing "5" gave 15, and typing 12 with 50 in stock jumped to 50: the till sold the wrong number of pieces.
const PRODUCT = {
  id: "p1", title: "تيشيرت", status: "active", images: [],
  variants: [{ id: "v1", sku: "TS-1", barcode: "6221234567891", is_active: true, price: "100.00", option_values: { color: "أسود", size: "M" } }],
};

async function openWithOneItem(page) {
  await mockCashierDay(page);
  // later routes win in Playwright, so these sit on top of the day mock
  await page.route("**/api/v1/products**", (r) => r.fulfill({ json: [PRODUCT] }));
  await page.route("**/api/v1/pos/stock**", (r) => r.fulfill({ json: [{ variant_id: "v1", product_id: "p1", product_title: "تيشيرت", sku: "TS-1", barcode: "6221234567891", options: { color: "أسود", size: "M" }, price: "100.00", on_hand: 50, reserved: 0 }] }));
  await page.route("**/api/v1/pos/sessions/*/items**", (r) => r.fulfill({ json: { items: [{ variant_id: "v1", available: 50, unit_price: "100.00" }], total: 1 } }));
  await page.route("**/pos/sessions/*/scan", (r) => r.fulfill({ json: { found: true, variant_id: "v1" } }));
  await page.route("**/pos/sessions/*/quote", (r) => r.fulfill({ json: { subtotal: "100.00", discount_total: "0.00", total: "100.00", lines: [] } }));
  await page.goto("/cashier/pos", { waitUntil: "networkidle" });
  const field = page.getByLabel("باركود المنتج").first();
  await expect(field).toBeVisible({ timeout: 8000 });
  await field.fill("6221234567891");
  await field.press("Enter");
  const qty = page.getByLabel(/^كمية /).first();
  await expect(qty).toBeVisible({ timeout: 8000 });
  return qty;
}

test("clearing the quantity and typing 5 gives 5, not 15", async ({ page }) => {
  const qty = await openWithOneItem(page);
  await qty.click();
  await page.keyboard.press("Backspace");
  await page.keyboard.type("5");
  await expect(qty).toHaveValue("5");
  await qty.press("Enter");
  await expect(qty).toHaveValue("5");
});

test("typing 12 with 50 in stock gives 12, not 50", async ({ page }) => {
  const qty = await openWithOneItem(page);
  await qty.click();
  await page.keyboard.press("Backspace");
  await page.keyboard.type("12");
  await expect(qty).toHaveValue("12");
  await qty.press("Enter");
  await expect(qty).toHaveValue("12");
});

test("more than the shelf holds is cut to the shelf when the box is left", async ({ page }) => {
  const qty = await openWithOneItem(page);
  await qty.click();
  await page.keyboard.type("99");
  await qty.blur();
  await expect(qty).toHaveValue("50");
});

test("leaving the box empty keeps the quantity it had", async ({ page }) => {
  const qty = await openWithOneItem(page);
  await qty.click();
  await page.keyboard.press("Backspace");
  await qty.blur();
  await expect(qty).toHaveValue("1");
});

test("the quantity box asks for a number pad and takes no letters", async ({ page }) => {
  const qty = await openWithOneItem(page);
  await expect(qty).toHaveAttribute("inputmode", "numeric");
  await qty.click();
  await page.keyboard.type("ab-3.5e");
  await expect(qty).toHaveValue("35");
});

test("the barcode box is not autocorrected or capitalised by a touch keyboard", async ({ page }) => {
  await openWithOneItem(page);
  const field = page.getByLabel("باركود المنتج").first();
  await expect(field).toHaveAttribute("autocorrect", "off");
  await expect(field).toHaveAttribute("autocapitalize", "off");
  await expect(field).toHaveAttribute("spellcheck", "false");
});

test("the invoice discount boxes ask for a decimal number pad", async ({ page }) => {
  await openWithOneItem(page);
  await expect(page.locator("#invoice-discount-pct")).toHaveAttribute("inputmode", "decimal");
  await expect(page.locator("#invoice-discount-amount")).toHaveAttribute("inputmode", "decimal");
});
