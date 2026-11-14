import { expect, test } from "@playwright/test";
import { mockAssistantDay, threads } from "./support/assistantDay.js";

// The conversation reads like ChatGPT: the assistant's answer is plain text beside its avatar (no
// bubble, no card), the owner's question is a soft rounded bubble on one side, everything sits in
// one centred column, and the composer is a big rounded pill that floats at the bottom of that
// same column. Only HTTP is mocked.
const DESKTOP = { width: 1366, height: 800 };

async function open(page, { lang = "ar", size = DESKTOP, thread = true } = {}) {
  await page.setViewportSize(size);
  const api = await mockAssistantDay(page, { lang });
  await page.goto("/sales-assistant");
  await page.waitForLoadState("networkidle");
  if (thread) {
    await page.getByText(threads[0].title, { exact: true }).first().click();
    await expect(page.getByText("سؤال رقم 30 عن المبيعات")).toBeVisible({ timeout: 8000 });
  }
  return api;
}

test("the assistant's answer is plain text: no bubble, no border, no card", async ({ page }) => {
  await open(page);
  const answer = page.getByTestId("assistant-message").last();
  const s = await answer.evaluate((n) => { const c = getComputedStyle(n); return { border: c.borderTopWidth, bg: c.backgroundColor, radius: c.borderTopLeftRadius, shadow: c.boxShadow }; });
  expect(s.border, "the answer has a border").toBe("0px");
  expect(s.bg, "the answer has a background").toBe("rgba(0, 0, 0, 0)");
  expect(s.shadow, "the answer has a shadow").toBe("none");
});

test("the owner's question is a rounded bubble", async ({ page }) => {
  await open(page);
  const q = page.getByTestId("user-message").last();
  const s = await q.evaluate((n) => { const c = getComputedStyle(n); return { bg: c.backgroundColor, radius: parseFloat(c.borderTopLeftRadius) }; });
  expect(s.bg, "the question has no bubble background").not.toBe("rgba(0, 0, 0, 0)");
  expect(s.radius, "the bubble is not rounded").toBeGreaterThanOrEqual(12);
});

test("the answer takes the full column width, not a narrow slice", async ({ page }) => {
  await open(page);
  const col = await page.getByTestId("assistant-column").boundingBox();
  const a = await page.getByTestId("assistant-message").last().boundingBox();
  expect(a.width / col.width, "the answer is squeezed").toBeGreaterThan(0.8);
});

test("everything sits in one centred column, the composer included", async ({ page }) => {
  await open(page);
  const col = await page.getByTestId("assistant-column").boundingBox();
  const comp = await page.getByTestId("assistant-composer").boundingBox();
  const chat = await page.getByTestId("assistant-chat").boundingBox();
  expect(col.width, "the column is wider than a readable measure").toBeLessThanOrEqual(900);
  expect(Math.abs(col.x + col.width / 2 - (chat.x + chat.width / 2)), "the column is off-centre").toBeLessThanOrEqual(2);
  expect(Math.abs(comp.x + comp.width / 2 - (chat.x + chat.width / 2)), "the composer is off-centre").toBeLessThanOrEqual(2);
  // the composer's pill lines up with the text column (the column's own side padding is the same)
  const pill = await page.getByTestId("assistant-composer-field").boundingBox();
  expect(Math.abs(pill.width - col.width), "the composer pill is not the column's width").toBeLessThanOrEqual(2);
});

test("the composer is a big rounded pill pinned to the bottom, with no top rule", async ({ page }) => {
  await open(page);
  const field = page.getByTestId("assistant-composer-field");
  const s = await field.evaluate((n) => ({ radius: parseFloat(getComputedStyle(n).borderTopLeftRadius), h: n.getBoundingClientRect().height }));
  expect(s.radius, "the composer is not pill-rounded").toBeGreaterThanOrEqual(20);
  expect(s.h, "the composer is cramped").toBeGreaterThanOrEqual(52);
  const comp = await page.getByTestId("assistant-composer").boundingBox();
  expect(comp.y + comp.height, "the composer is not at the bottom").toBeGreaterThan(DESKTOP.height - 40);
  const top = await page.getByTestId("assistant-composer").evaluate((n) => getComputedStyle(n).borderTopWidth);
  expect(top, "the composer has a top rule").toBe("0px");
});

test("Enter sends and the box clears; Shift+Enter makes a new line", async ({ page }) => {
  const api = await open(page);
  const box = page.getByTestId("assistant-composer-field").locator("textarea");
  await box.fill("كام بعت النهارده؟");
  await box.press("Enter");
  await expect.poll(() => api.sent.length).toBe(1);
  expect(api.sent[0].content).toBe("كام بعت النهارده؟");
  await expect(box).toHaveValue("");
  await box.fill("سطر أول");
  await box.press("Shift+Enter");
  await box.type("سطر تاني");
  await expect(box).toHaveValue("سطر أول\nسطر تاني");
  expect(api.sent.length, "Shift+Enter sent the message").toBe(1);
});

test("the send button is disabled until there is text", async ({ page }) => {
  await open(page);
  const send = page.getByTestId("assistant-composer-field").getByRole("button", { name: "إرسال" });
  await expect(send).toBeDisabled();
  await page.getByTestId("assistant-composer-field").locator("textarea").fill("سؤال");
  await expect(send).toBeEnabled();
});

test("the empty state shows the starter prompts and a prompt sends", async ({ page }) => {
  const api = await open(page, { thread: false });
  await expect(page.getByTestId("assistant-chat").getByRole("button", { name: "قارن مبيعات الشهر ده باللي فات." })).toBeVisible();
  await page.getByRole("button", { name: "قارن مبيعات الشهر ده باللي فات." }).click();
  await expect.poll(() => api.sent.length).toBe(1);
});

test("English: the page title is Fihrist Agent, in the page and in the main menu", async ({ page }) => {
  await open(page, { lang: "en", thread: false });
  await expect(page.getByTestId("assistant-chat").getByRole("heading", { name: "Fihrist Agent" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Fihrist Agent" }).first()).toBeVisible();
});

test("English reads left to right and the sidebar sits on the left", async ({ page }) => {
  await open(page, { lang: "en", thread: false });
  const sb = await page.getByTestId("assistant-sidebar").boundingBox();
  const chat = await page.getByTestId("assistant-chat").boundingBox();
  expect(sb.x, "the sidebar is not left of the chat in English").toBeLessThan(chat.x);
});

test("mobile: the composer stays at the bottom and the thread drawer opens", async ({ page }) => {
  await open(page, { size: { width: 390, height: 800 }, thread: false });
  const comp = await page.getByTestId("assistant-composer").boundingBox();
  expect(comp.y + comp.height).toBeGreaterThan(740);
  await page.getByRole("button", { name: "المحادثات" }).first().click();
  // two copies of the list exist (the desktop sidebar is display:none here): look at the visible one
  await expect(page.locator(`text="${threads[0].title}" >> visible=true`)).toHaveCount(1);
});
