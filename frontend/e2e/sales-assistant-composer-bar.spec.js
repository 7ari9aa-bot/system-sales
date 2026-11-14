import { expect, test } from "@playwright/test";
import { mockAssistantDay } from "./support/assistantDay.js";

// The composer is a compact two-row bar (like ZCode): the text box on top, a thin tool row below
// with the file button on one side and mic + send on the other.
async function open(page, size = { width: 1366, height: 800 }) {
  await page.setViewportSize(size);
  const api = await mockAssistantDay(page, { lang: "ar", empty: true });
  await page.goto("/sales-assistant");
  await page.waitForLoadState("networkidle");
  return api;
}
const box = (page) => page.getByTestId("assistant-composer-field").locator("textarea");
const field = (page) => page.getByTestId("assistant-composer-field");

test("the bar is compact: short when empty, much shorter than before", async ({ page }) => {
  await open(page);
  const b = await field(page).boundingBox();
  expect(b.height, "the empty bar is too tall").toBeLessThanOrEqual(104);
  expect(b.height).toBeGreaterThanOrEqual(76);
});

test("two rows: the text box above, the tools below", async ({ page }) => {
  await open(page);
  const t = await box(page).boundingBox();
  for (const id of ["assistant-attach", "assistant-send"]) {
    const x = await page.getByTestId(id).boundingBox();
    expect(x.y, `${id} should sit under the text box`).toBeGreaterThanOrEqual(t.y + t.height - 2);
  }
});

test("the file button is on one side and send on the other", async ({ page }) => {
  await open(page);
  const a = await page.getByTestId("assistant-attach").boundingBox();
  const s = await page.getByTestId("assistant-send").boundingBox();
  expect(Math.abs(a.x - s.x)).toBeGreaterThan(200);
});

test("tool buttons are small but still comfortable to tap", async ({ page }) => {
  await open(page);
  for (const id of ["assistant-attach", "assistant-send"]) {
    const b = await page.getByTestId(id).boundingBox();
    expect(b.width).toBeGreaterThanOrEqual(32);
    expect(b.width).toBeLessThanOrEqual(40);
    expect(b.height).toBeGreaterThanOrEqual(32);
  }
});

test("the bar grows with long text up to a ceiling and keeps the tools in place", async ({ page }) => {
  await open(page);
  const before = await field(page).boundingBox();
  await box(page).fill(Array.from({ length: 12 }, (_, i) => `سطر ${i}`).join("\n"));
  const after = await field(page).boundingBox();
  expect(after.height).toBeGreaterThan(before.height);
  expect(after.height).toBeLessThanOrEqual(260);
  const s = await page.getByTestId("assistant-send").boundingBox();
  expect(s.y + s.height).toBeLessThanOrEqual(after.y + after.height + 1);
});

test("send stays disabled until there is text", async ({ page }) => {
  await open(page);
  await expect(page.getByTestId("assistant-send")).toBeDisabled();
  await box(page).fill("سؤال");
  await expect(page.getByTestId("assistant-send")).toBeEnabled();
});

test("attaching a csv puts its text in the box, labelled, and sends nothing by itself", async ({ page }) => {
  const api = await open(page);
  await page.getByTestId("assistant-file-input").setInputFiles({ name: "sales.csv", mimeType: "text/csv", buffer: Buffer.from("منتج,كمية\nجزمة,3") });
  await expect(box(page)).toHaveValue(/\[sales\.csv\]\nمنتج,كمية\nجزمة,3/);
  expect(api.sent.length).toBe(0);
});

test("the file text lands under what was already typed", async ({ page }) => {
  await open(page);
  await box(page).fill("حلل الملف ده");
  await page.getByTestId("assistant-file-input").setInputFiles({ name: "a.txt", mimeType: "text/plain", buffer: Buffer.from("محتوى") });
  const v = await box(page).inputValue();
  expect(v.startsWith("حلل الملف ده")).toBe(true);
  expect(v).toContain("محتوى");
});

test("a file of the wrong kind is refused with a message and the box is untouched", async ({ page }) => {
  await open(page);
  await box(page).fill("سؤال");
  await page.getByTestId("assistant-file-input").setInputFiles({ name: "x.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF") });
  await expect(page.getByTestId("assistant-attach-error")).toBeVisible();
  await expect(box(page)).toHaveValue("سؤال");
});

test("a file that is too big is refused", async ({ page }) => {
  await open(page);
  await page.getByTestId("assistant-file-input").setInputFiles({ name: "big.txt", mimeType: "text/plain", buffer: Buffer.from("a".repeat(20000)) });
  await expect(page.getByTestId("assistant-attach-error")).toBeVisible();
  await expect(box(page)).toHaveValue("");
});

test("the attach error disappears when the owner types", async ({ page }) => {
  await open(page);
  await page.getByTestId("assistant-file-input").setInputFiles({ name: "x.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF") });
  await expect(page.getByTestId("assistant-attach-error")).toBeVisible();
  await box(page).fill("س");
  await expect(page.getByTestId("assistant-attach-error")).toHaveCount(0);
});

test("the same file can be attached twice in a row", async ({ page }) => {
  await open(page);
  const f = { name: "a.txt", mimeType: "text/plain", buffer: Buffer.from("واحد") };
  await page.getByTestId("assistant-file-input").setInputFiles(f);
  await box(page).fill("");
  await page.getByTestId("assistant-file-input").setInputFiles(f);
  await expect(box(page)).toHaveValue(/واحد/);
  // a browser only fires "change" for a file it has not just seen, so the input must be reset
  expect(await page.getByTestId("assistant-file-input").evaluate((n) => n.value)).toBe("");
});

test("the attach button opens the file picker", async ({ page }) => {
  await open(page);
  const [chooser] = await Promise.all([page.waitForEvent("filechooser"), page.getByTestId("assistant-attach").click()]);
  expect(chooser.isMultiple()).toBe(false);
});

test("the picker only offers the supported kinds", async ({ page }) => {
  await open(page);
  const accept = await page.getByTestId("assistant-file-input").getAttribute("accept");
  for (const e of [".txt", ".csv", ".md", ".json"]) expect(accept).toContain(e);
  expect(accept).not.toContain("pdf");
});

test("mobile: the bar fits the screen with nothing overflowing", async ({ page }) => {
  await open(page, { width: 390, height: 800 });
  const b = await field(page).boundingBox();
  expect(b.x).toBeGreaterThanOrEqual(0);
  expect(b.x + b.width).toBeLessThanOrEqual(390);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
});

test("a failed send still gives the text back (the bar keeps working)", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 800 });
  await mockAssistantDay(page, { lang: "ar", empty: true, createStatus: 500 });
  await page.goto("/sales-assistant");
  await page.waitForLoadState("networkidle");
  await box(page).fill("سؤال");
  await page.getByTestId("assistant-send").click();
  await expect(page.getByTestId("assistant-send-error")).toBeVisible();
  await expect(box(page)).toHaveValue("سؤال");
});
