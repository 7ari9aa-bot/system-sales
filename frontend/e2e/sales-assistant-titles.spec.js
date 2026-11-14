import { expect, test } from "@playwright/test";
import { LONG_TITLE, OLD_TITLE, mockAssistantDay } from "./support/assistantDay.js";

// A chat title must be readable in the list: whole, not cut to "…". It wraps to two lines at most
// (the model is asked for a short one, so two lines is the ceiling), and the row stays tidy.
async function open(page, { size = { width: 1366, height: 800 }, lang = "ar" } = {}) {
  await page.setViewportSize(size);
  await mockAssistantDay(page, { lang });
  await page.goto("/sales-assistant");
  await page.waitForLoadState("networkidle");
}
const row = (page) => page.getByTestId("assistant-threads-scroll").locator("li", { hasText: LONG_TITLE }).first();
const label = (page) => row(page).getByTestId("thread-title");

test("a long title is shown in full, not cut with an ellipsis", async ({ page }) => {
  await open(page);
  await expect(label(page)).toHaveText(LONG_TITLE);
  const cut = await label(page).evaluate((n) => n.scrollWidth > n.clientWidth + 1 || n.scrollHeight > n.clientHeight + 1);
  expect(cut, "the title is clipped").toBe(false);
  expect(await label(page).evaluate((n) => getComputedStyle(n).textOverflow)).not.toBe("ellipsis");
});

test("it wraps to at most two lines", async ({ page }) => {
  await open(page);
  const lines = await label(page).evaluate((n) => Math.round(n.getBoundingClientRect().height / parseFloat(getComputedStyle(n).lineHeight)));
  expect(lines).toBeGreaterThanOrEqual(2);
  expect(lines).toBeLessThanOrEqual(2);
});

test("a short title stays on one line and the rows stay aligned", async ({ page }) => {
  await open(page);
  const short = page.getByTestId("assistant-threads-scroll").locator("li", { hasText: "محادثة رقم 1" }).first();
  const h = await short.getByTestId("thread-title").evaluate((n) => Math.round(n.getBoundingClientRect().height / parseFloat(getComputedStyle(n).lineHeight)));
  expect(h).toBe(1);
});

test("the icon, text and time stay inside the row with no horizontal overflow", async ({ page }) => {
  await open(page);
  const r = await row(page).boundingBox();
  for (const sel of ["thread-title", "thread-time"]) {
    const b = await row(page).getByTestId(sel).boundingBox();
    expect(b.x).toBeGreaterThanOrEqual(r.x - 1);
    expect(b.x + b.width).toBeLessThanOrEqual(r.x + r.width + 1);
  }
  expect(await page.getByTestId("assistant-threads-scroll").evaluate((n) => n.scrollWidth <= n.clientWidth + 1)).toBe(true);
});

test("the icon sits at the top beside the first line, not floating in the middle", async ({ page }) => {
  await open(page);
  const icon = await row(page).getByTestId("thread-icon").boundingBox();
  const title = await label(page).boundingBox();
  expect(Math.abs(icon.y - title.y), "the icon is not aligned with the first line").toBeLessThanOrEqual(8);
});

test("hovering shows the actions without squeezing the title", async ({ page }) => {
  await open(page);
  const before = await label(page).boundingBox();
  await row(page).hover();
  const after = await label(page).boundingBox();
  expect(Math.abs(after.width - before.width), "the title reflowed on hover").toBeLessThanOrEqual(1);
  await expect(row(page).getByTitle("إعادة تسمية")).toBeVisible();
});

test("mobile: a long title in the sheet is whole and does not overflow", async ({ page }) => {
  await open(page, { size: { width: 390, height: 800 } });
  await page.getByRole("button", { name: "المحادثات" }).first().click();
  const li = page.locator("li", { hasText: LONG_TITLE }).locator("visible=true").first();
  await expect(li.getByTestId("thread-title")).toHaveText(LONG_TITLE);
  const b = await li.boundingBox();
  expect(b.x + b.width).toBeLessThanOrEqual(390);
  expect(await li.getByTestId("thread-title").evaluate((n) => n.scrollHeight <= n.clientHeight + 1), "clipped on mobile").toBe(true);
});

test("an older, longer title is cut after two lines with an ellipsis, never overflowing the row", async ({ page }) => {
  await open(page);
  const old = page.getByTestId("assistant-threads-scroll").locator("li", { hasText: "قارنلي مبيعات" }).first().getByTestId("thread-title");
  const lines = await old.evaluate((n) => Math.round(n.getBoundingClientRect().height / parseFloat(getComputedStyle(n).lineHeight)));
  expect(lines).toBeLessThanOrEqual(2);
  expect(await old.evaluate((n) => n.scrollWidth <= n.clientWidth + 1)).toBe(true);
});
