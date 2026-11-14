import { expect, test } from "@playwright/test";
import { mockAssistantDay, threads } from "./support/assistantDay.js";

// The assistant page is a full-screen chat workspace, like ChatGPT: the PAGE never scrolls, the
// thread sidebar scrolls on its own, the conversation scrolls on its own, and the two fill the
// screen edge to edge (no gaps, no floating cards). Only HTTP is mocked.
const DESKTOP = { width: 1366, height: 800 };

const open = async (page, opts, size = DESKTOP) => {
  await page.setViewportSize(size);
  const api = await mockAssistantDay(page, opts);
  await page.goto("/sales-assistant");
  await page.waitForLoadState("networkidle");
  return api;
};
const openThread = async (page) => {
  await page.getByText(threads[0].title, { exact: true }).first().click();
  await expect(page.getByText("سؤال رقم 30 عن المبيعات")).toBeVisible({ timeout: 8000 });
};
const box = (page, sel) => page.locator(sel).first().boundingBox();

test("the page itself never scrolls, with a long thread open", async ({ page }) => {
  await open(page, { lang: "ar" });
  await openThread(page);
  const m = await page.evaluate(() => ({
    doc: document.documentElement.scrollHeight - document.documentElement.clientHeight,
    body: document.body.scrollHeight - window.innerHeight,
  }));
  expect(m.doc, "the document scrolls").toBeLessThanOrEqual(0);
  expect(m.body, "the body is taller than the window").toBeLessThanOrEqual(0);
});

test("the sidebar and the chat each scroll on their own", async ({ page }) => {
  await open(page, { lang: "ar" });
  await openThread(page);
  const sb = page.getByTestId("assistant-threads-scroll");
  const chat = page.getByTestId("assistant-chat-scroll");
  for (const [name, el] of [["sidebar", sb], ["chat", chat]]) {
    const m = await el.evaluate((n) => ({ overflowY: getComputedStyle(n).overflowY, tall: n.scrollHeight > n.clientHeight + 50 }));
    expect(m.overflowY, `${name} is not its own scroller`).toMatch(/auto|scroll/);
    expect(m.tall, `${name} has nothing to scroll (the mock is long enough)`).toBe(true);
  }
  // scrolling the sidebar must not move the chat, and the other way round
  const chatBefore = await chat.evaluate((n) => n.scrollTop);
  await sb.evaluate((n) => { n.scrollTop = 400; });
  expect(await chat.evaluate((n) => n.scrollTop), "scrolling the sidebar moved the chat").toBe(chatBefore);
  const sbBefore = await sb.evaluate((n) => n.scrollTop);
  await chat.evaluate((n) => { n.scrollTop = 0; });
  expect(await sb.evaluate((n) => n.scrollTop), "scrolling the chat moved the sidebar").toBe(sbBefore);
});

test("the chat opens at the newest message", async ({ page }) => {
  await open(page, { lang: "ar" });
  await openThread(page);
  const gap = await page.getByTestId("assistant-chat-scroll").evaluate((n) => n.scrollHeight - n.clientHeight - n.scrollTop);
  expect(gap).toBeLessThanOrEqual(2);
});

test("the sidebar and the chat fill the screen edge to edge", async ({ page }) => {
  await open(page, { lang: "ar" });
  await openThread(page);
  const ws = await box(page, '[data-testid="assistant-workspace"]');
  expect(ws.y, "a gap above the workspace").toBeLessThanOrEqual(1);
  expect(Math.round(ws.y + ws.height), "a gap below the workspace").toBe(DESKTOP.height);
  const sb = await box(page, '[data-testid="assistant-sidebar"]');
  const chat = await box(page, '[data-testid="assistant-chat"]');
  expect(Math.round(sb.height), "the sidebar is not full height").toBe(Math.round(ws.height));
  expect(Math.round(chat.height), "the chat is not full height").toBe(Math.round(ws.height));
  // no gutter between the two panes, and together they reach the right edge of the window
  const [a, b] = sb.x < chat.x ? [sb, chat] : [chat, sb];
  expect(Math.round(b.x - (a.x + a.width)), "a gap between sidebar and chat").toBeLessThanOrEqual(1);
  expect(Math.round(Math.max(sb.x + sb.width, chat.x + chat.width)), "a gap at the window edge").toBe(DESKTOP.width);
  // the panes are flat panels, not rounded floating cards
  for (const id of ["assistant-sidebar", "assistant-chat"]) {
    const r = await page.getByTestId(id).evaluate((n) => getComputedStyle(n).borderRadius);
    expect(r, `${id} is a rounded card`).toMatch(/^0(px)?$/);
  }
});

test("no scroll and no gaps in English (LTR) either", async ({ page }) => {
  await open(page, { lang: "en" });
  await page.getByText(threads[0].title, { exact: true }).first().click();
  await expect(page.getByText("سؤال رقم 30 عن المبيعات")).toBeVisible({ timeout: 8000 });
  expect(await page.evaluate(() => document.documentElement.scrollHeight - document.documentElement.clientHeight)).toBeLessThanOrEqual(0);
  const ws = await box(page, '[data-testid="assistant-workspace"]');
  expect(Math.round(ws.y + ws.height)).toBe(DESKTOP.height);
});

test("the empty state (no thread open) does not scroll the page either", async ({ page }) => {
  await open(page, { lang: "ar", empty: true });
  expect(await page.evaluate(() => document.documentElement.scrollHeight - document.documentElement.clientHeight)).toBeLessThanOrEqual(0);
});

test("a short window still never scrolls the page", async ({ page }) => {
  await open(page, { lang: "ar" }, { width: 1280, height: 560 });
  await openThread(page);
  expect(await page.evaluate(() => document.documentElement.scrollHeight - document.documentElement.clientHeight)).toBeLessThanOrEqual(0);
});

test("mobile: no page scroll, and the chat fills the screen", async ({ page }) => {
  await open(page, { lang: "ar" }, { width: 390, height: 800 });
  expect(await page.evaluate(() => document.documentElement.scrollHeight - document.documentElement.clientHeight)).toBeLessThanOrEqual(0);
  const chat = await box(page, '[data-testid="assistant-chat"]');
  expect(Math.round(chat.width), "the chat does not span the screen").toBe(390);
});

test("the memory panel opens inside the workspace: full height, no page scroll, its own scroller", async ({ page }) => {
  await open(page, { lang: "ar" });
  await openThread(page);
  await page.getByRole("button", { name: /ذاكرة المساعد/ }).click();
  const panel = page.locator("aside", { hasText: "ذاكرة" }).last();
  await expect(panel).toBeVisible();
  // the panel slides in: measure it once its entrance animation has finished
  await panel.evaluate((n) => Promise.all(n.parentElement.getAnimations().map((a) => a.finished)));
  const ws = await box(page, '[data-testid="assistant-workspace"]');
  const pb = await panel.boundingBox();
  expect(Math.round(pb.y), "the memory panel does not start at the top").toBeLessThanOrEqual(Math.round(ws.y) + 1);
  expect(Math.round(pb.y + pb.height), "the memory panel does not reach the bottom").toBe(DESKTOP.height);
  expect(await page.evaluate(() => document.documentElement.scrollHeight - document.documentElement.clientHeight), "the page scrolls with the panel open").toBeLessThanOrEqual(0);
  // beside the chat it is a flat side panel (like the thread sidebar), not a floating card
  const flat = await panel.evaluate((n) => { const c = getComputedStyle(n); return { radius: c.borderTopLeftRadius, shadow: c.boxShadow, top: c.borderTopWidth, bottom: c.borderBottomWidth }; });
  expect(flat.radius, "the memory panel is a rounded card").toMatch(/^0(px)?$/);
  expect(flat.shadow, "the memory panel floats on a shadow").toBe("none");
  expect(`${flat.top}/${flat.bottom}`, "the memory panel has a box border on top and bottom").toBe("0px/0px");
  // it sits in the flow beside the chat (not fixed over it): the chat gave up exactly its width
  const pos = await panel.evaluate((n) => getComputedStyle(n.parentElement).position);
  expect(pos, "the memory panel overlays the chat instead of sitting beside it").not.toBe("fixed");
  const chatBox = await box(page, '[data-testid="assistant-chat"]');
  const sbBox = await box(page, '[data-testid="assistant-sidebar"]');
  expect(Math.round(chatBox.width + sbBox.width + pb.width), "the three panes do not add up to the workspace").toBe(Math.round(ws.width));
  // the chat is still full height beside it
  const chat = await box(page, '[data-testid="assistant-chat"]');
  expect(Math.round(chat.height)).toBe(Math.round(ws.height));
});
