import { expect, test } from "@playwright/test";
import { mockAssistantDay, realExchange } from "./support/assistantDay.js";

const ANSWER = "أهلاً بيك! تحب نبدأ بإيه؟";

async function open(page, extra = {}) {
  await page.setViewportSize({ width: 1366, height: 800 });
  const api = await mockAssistantDay(page, { lang: "ar" });
  api.state.custom = extra.custom ?? realExchange(ANSWER);
  await page.goto("/sales-assistant");
  await page.waitForLoadState("networkidle");
  await page.getByText("محادثة رقم 1", { exact: true }).first().click();
  await page.waitForTimeout(300);
  return api;
}

test("the question is above its answer, whatever order the server lists them in", async ({ page }) => {
  await open(page);
  const q = await page.getByTestId("user-message").last().boundingBox();
  const a = await page.getByTestId("assistant-message").last().boundingBox();
  expect(q.y, "the answer is shown ABOVE the question").toBeLessThan(a.y);
});

test("many turns read oldest at the top, newest at the bottom", async ({ page }) => {
  const turns = [];
  for (let i = 4; i >= 1; i--) {
    turns.push({ id: `a${i}`, sequence_no: i * 2, role: "assistant", status: "completed", content: `رد ${i}`, structured_content: null, created_at: "2026-11-14T16:00:00Z" });
    turns.push({ id: `u${i}`, sequence_no: i * 2 - 1, role: "user", status: "completed", content: `سؤال ${i}`, structured_content: null, created_at: "2026-11-14T16:00:00Z" });
  }
  await open(page, { custom: turns });
  const text = await page.getByTestId("assistant-column").innerText();
  const order = ["سؤال 1", "رد 1", "سؤال 2", "رد 2", "سؤال 3", "رد 3", "سؤال 4", "رد 4"].map((t) => text.indexOf(t));
  expect(order.every((v) => v >= 0)).toBe(true);
  expect([...order].sort((x, y) => x - y)).toEqual(order);
});

test("an answer is shown ONCE, not again as a raw text block", async ({ page }) => {
  await open(page);
  const text = await page.getByTestId("assistant-message").last().innerText();
  expect(text.split(ANSWER).length - 1, "the answer text is repeated").toBe(1);
});

test("a markdown answer is rendered once, as formatted text", async ({ page }) => {
  await open(page, { custom: realExchange("**الإيراد** ارتفع\n\n- أول نقطة\n- تاني نقطة") });
  const msg = page.getByTestId("assistant-message").last();
  expect(await msg.locator("li").count()).toBe(2);
  expect(await msg.innerText()).not.toContain("**");
  expect((await msg.innerText()).split("أول نقطة").length - 1).toBe(1);
});

test("no internal run id or 'run log' button is shown to the owner", async ({ page }) => {
  await open(page);
  const text = await page.getByTestId("assistant-message").last().innerText();
  expect(text).not.toContain("c26f61a9");
  expect(text).not.toMatch(/سجل تشغيل|run log|run_id/i);
});

test("the copy button copies the answer once", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await open(page);
  await page.getByTestId("assistant-message").last().locator("..").getByRole("button", { name: /نسخ|copy/i }).click();
  const clip = await page.evaluate(() => navigator.clipboard.readText());
  expect(clip.split(ANSWER).length - 1).toBe(1);
});
