import { expect, test } from "@playwright/test";
import { mockAssistantDay } from "./support/assistantDay.js";

// The chat list can be folded away and dragged wider or narrower with the mouse; the choice is
// kept for next time. Arabic puts the list on the right, English on the left, and dragging towards
// the conversation widens it in both.
const KEY = "salesos.assistant.sidebar";

async function open(page, { lang = "ar", saved = null } = {}) {
  await page.setViewportSize({ width: 1366, height: 800 });
  if (saved) await page.addInitScript(([k, v]) => localStorage.setItem(k, v), [KEY, JSON.stringify(saved)]);
  await mockAssistantDay(page, { lang });
  await page.goto("/sales-assistant");
  await page.waitForLoadState("networkidle");
}
const side = (page) => page.getByTestId("assistant-sidebar");
const handle = (page) => page.getByTestId("assistant-sidebar-handle");
const grab = (page) => page.getByTestId("assistant-sidebar-grab");
const width = async (page) => Math.round((await side(page).boundingBox()).width);
const saved = (page) => page.evaluate((k) => JSON.parse(localStorage.getItem(k) || "null"), KEY);

async function drag(page, dx) {
  const b = await grab(page).boundingBox();
  const x = b.x + b.width / 2;
  const y = b.y + 200;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x + dx / 2, y, { steps: 4 });
  await page.mouse.move(x + dx, y, { steps: 4 });
  await page.mouse.up();
}

test("starts open at the default width", async ({ page }) => {
  await open(page);
  await expect(side(page)).toBeVisible();
  expect(await width(page)).toBe(280);
});

// The product keeps the page layout left-to-right in BOTH languages (only the text changes), so the
// list is on the left and dragging its edge towards the conversation (right) widens it.
for (const lang of ["ar", "en"]) {
  test(`${lang}: the list is on the left and dragging the handle RIGHT makes it wider`, async ({ page }) => {
    await open(page, { lang });
    const s = await side(page).boundingBox();
    const c = await page.getByTestId("assistant-chat").boundingBox();
    expect(s.x).toBeLessThan(c.x);
    await drag(page, 60);
    expect(await width(page)).toBe(340);
    await drag(page, -40);
    expect(await width(page)).toBe(300);
  });
}

test("it cannot be dragged past the limits", async ({ page }) => {
  await open(page);
  await drag(page, 900);
  expect(await width(page)).toBe(480);
  await drag(page, -1200);
  expect(await width(page)).toBe(220);
});

test("the handle works with the keyboard and says its size", async ({ page }) => {
  await open(page, { lang: "ar" });
  await handle(page).focus();
  await page.keyboard.press("ArrowRight"); // towards the conversation = wider
  expect(await width(page)).toBe(296);
  await expect(handle(page)).toHaveAttribute("aria-valuenow", "296");
  await page.keyboard.press("ArrowLeft");
  await page.keyboard.press("ArrowLeft");
  expect(await width(page)).toBe(264);
  await page.keyboard.press("End");
  expect(await width(page)).toBe(480);
  await page.keyboard.press("Home");
  expect(await width(page)).toBe(220);
});

test("double-clicking the handle puts the width back to the default", async ({ page }) => {
  await open(page);
  await drag(page, 80);
  expect(await width(page)).toBe(360);
  await grab(page).dblclick();
  expect(await width(page)).toBe(280);
});

test("the button folds the list away and brings it back, and the chat takes the room", async ({ page }) => {
  await open(page);
  const chat = page.getByTestId("assistant-chat");
  const before = (await chat.boundingBox()).width;
  await page.getByTestId("assistant-sidebar-toggle").click();
  await expect(side(page)).toHaveCount(0);
  await expect(handle(page)).toHaveCount(0);
  expect((await chat.boundingBox()).width).toBeGreaterThan(before + 250);
  await expect(page.getByTestId("assistant-sidebar-toggle")).toHaveAttribute("aria-expanded", "false");
  await page.getByTestId("assistant-sidebar-toggle").click();
  await expect(side(page)).toBeVisible();
  expect(await width(page)).toBe(280);
});

test("the width and the fold are remembered after a reload", async ({ page }) => {
  await open(page);
  await drag(page, 70);
  expect(await saved(page)).toEqual({ width: 350, collapsed: false });
  await page.reload();
  await page.waitForLoadState("networkidle");
  expect(await width(page)).toBe(350);
  await page.getByTestId("assistant-sidebar-toggle").click();
  await page.reload();
  await page.waitForLoadState("networkidle");
  await expect(side(page)).toHaveCount(0);
  expect(await saved(page)).toEqual({ width: 350, collapsed: true });
});

test("a damaged saved value is ignored instead of breaking the page", async ({ page }) => {
  await page.addInitScript(([k]) => localStorage.setItem(k, "{{not json"), [KEY]);
  await open(page);
  await expect(side(page)).toBeVisible();
  expect(await width(page)).toBe(280);
});

test("dragging does not select text, and the page keeps working afterwards", async ({ page }) => {
  await open(page);
  await drag(page, 50);
  const selected = await page.evaluate(() => String(window.getSelection()));
  expect(selected).toBe("");
  await expect(page.getByTestId("assistant-composer-field").locator("textarea")).toBeEnabled();
});

test("below the large-screen breakpoint there is no handle and no fold button, only the drawer", async ({ page }) => {
  await page.setViewportSize({ width: 800, height: 800 });
  await mockAssistantDay(page, { lang: "ar" });
  await page.goto("/sales-assistant");
  await page.waitForLoadState("networkidle");
  await expect(handle(page)).toBeHidden();
  await expect(page.getByTestId("assistant-sidebar-toggle")).toBeHidden();
});

test("the handle takes no room: the list and the chat touch edge to edge", async ({ page }) => {
  await open(page);
  const s = await side(page).boundingBox();
  const c = await page.getByTestId("assistant-chat").boundingBox();
  expect(Math.abs(c.x - (s.x + s.width))).toBeLessThanOrEqual(1);
  // and the strip you grab is centred on that edge, wide enough to hit with a mouse
  const g = await grab(page).boundingBox();
  expect(g.width).toBeGreaterThanOrEqual(6);
  expect(Math.abs(g.x + g.width / 2 - (s.x + s.width))).toBeLessThanOrEqual(2);
});
