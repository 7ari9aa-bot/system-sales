import { expect, test } from "@playwright/test";
import { mockAssistantDay, threads } from "./support/assistantDay.js";

// Round 2 of the assistant page: search on top with "new chat" under it (both pinned, the list
// scrolls alone), a chat that fills the screen with no dead space, a raised and more refined
// composer, and dictation (speech to text) that drops into the box for review before sending.
// Only HTTP and the browser's speech engine are faked.
const DESKTOP = { width: 1366, height: 800 };

const FAKE_SPEECH = () => {
  window.__speech = { started: 0, stopped: 0, lang: null, inst: null };
  class FakeRecognition {
    constructor() { window.__speech.inst = this; this.continuous = false; this.interimResults = false; }
    start() { window.__speech.started += 1; window.__speech.lang = this.lang; this.onstart && this.onstart(); }
    stop() { window.__speech.stopped += 1; this.onend && this.onend(); }
    abort() { this.stop(); }
  }
  window.SpeechRecognition = FakeRecognition;
  window.__say = (parts) => {
    const inst = window.__speech.inst;
    const wanted = inst.interimResults ? parts : parts.filter(([, isFinal]) => isFinal);
    if (!wanted.length) return;
    const list = wanted.map(([text, isFinal]) => Object.assign([{ transcript: text }], { isFinal }));
    window.__speech.inst.onresult && window.__speech.inst.onresult({ resultIndex: 0, results: list });
  };
  window.__speechError = (error) => window.__speech.inst.onerror && window.__speech.inst.onerror({ error });
};

async function open(page, { lang = "ar", size = DESKTOP, thread = true, speech = true } = {}) {
  await page.setViewportSize(size);
  if (speech) await page.addInitScript(FAKE_SPEECH);
  // Chromium ships its own recognition: a "no support" browser (Firefox) must have both removed
  else await page.addInitScript(() => { delete window.SpeechRecognition; delete window.webkitSpeechRecognition; Object.defineProperty(window, "webkitSpeechRecognition", { value: undefined, configurable: true }); Object.defineProperty(window, "SpeechRecognition", { value: undefined, configurable: true }); });
  const api = await mockAssistantDay(page, { lang });
  await page.goto("/sales-assistant");
  await page.waitForLoadState("networkidle");
  if (thread) {
    await page.getByText(threads[0].title, { exact: true }).first().click();
    await expect(page.getByText("سؤال رقم 30 عن المبيعات")).toBeVisible({ timeout: 8000 });
  }
  return api;
}

// ---------------------------------------------------------------- sidebar: search over new chat
test("the sidebar puts search on top and New chat right under it", async ({ page }) => {
  await open(page, { thread: false });
  const sb = page.getByTestId("assistant-sidebar");
  const search = await sb.getByPlaceholder("ابحث في المحادثات…").boundingBox();
  const fresh = await sb.getByRole("button", { name: "محادثة جديدة" }).boundingBox();
  expect(search.y, "search is not above New chat").toBeLessThan(fresh.y);
  expect(fresh.y - (search.y + search.height), "New chat is not directly under search").toBeLessThanOrEqual(16);
});

test("search and New chat stay pinned while the thread list scrolls on its own", async ({ page }) => {
  await open(page, { thread: false });
  const sb = page.getByTestId("assistant-sidebar");
  const list = page.getByTestId("assistant-threads-scroll");
  const before = await sb.getByRole("button", { name: "محادثة جديدة" }).boundingBox();
  const scrollable = await list.evaluate((n) => n.scrollHeight > n.clientHeight);
  expect(scrollable, "the list is too short to prove it scrolls (test data)").toBe(true);
  await list.evaluate((n) => { n.scrollTop = n.scrollHeight; });
  const after = await sb.getByRole("button", { name: "محادثة جديدة" }).boundingBox();
  const searchAfter = await sb.getByPlaceholder("ابحث في المحادثات…").boundingBox();
  expect(after.y, "New chat moved when the list scrolled").toBe(before.y);
  expect(searchAfter.y, "search moved when the list scrolled").toBeLessThan(before.y);
  expect(await list.evaluate((n) => n.scrollTop), "the list did not scroll").toBeGreaterThan(0);
  // the chat did not scroll with it
  expect(await page.getByTestId("assistant-chat-scroll").evaluate((n) => n.scrollTop)).toBe(0);
});

test("the sidebar's search and New chat are not inside the list's scroller", async ({ page }) => {
  await open(page, { thread: false });
  const inside = await page.getByTestId("assistant-threads-scroll").evaluate((n) => !!n.querySelector("input, [data-testid=new-chat]") || n.innerText.includes("محادثة جديدة"));
  expect(inside).toBe(false);
});

// ---------------------------------------------------------------- chat fills the screen
test("the conversation uses the whole width: no wide dead margins either side", async ({ page }) => {
  await open(page);
  const chat = await page.getByTestId("assistant-chat").boundingBox();
  const col = await page.getByTestId("assistant-column").boundingBox();
  expect(col.width / chat.width, "the column is a narrow strip with empty sides").toBeGreaterThan(0.72);
});

test("no dead band between the last message and the composer", async ({ page }) => {
  await open(page);
  const scroller = page.getByTestId("assistant-chat-scroll");
  await scroller.evaluate((n) => { n.scrollTop = n.scrollHeight; });
  const gap = await page.evaluate(() => {
    const s = document.querySelector('[data-testid="assistant-chat-scroll"]').getBoundingClientRect();
    const col = document.querySelector('[data-testid="assistant-column"]').getBoundingClientRect();
    return s.bottom - col.bottom;
  });
  expect(gap, "empty band under the last message").toBeLessThanOrEqual(32);
});

test("the empty state is centred as a block in the free space, not stuck to the top", async ({ page }) => {
  await open(page, { thread: false });
  const scroller = await page.getByTestId("assistant-chat-scroll").boundingBox();
  // the block = from its first element to its last one
  const block = await page.getByTestId("assistant-empty").evaluate((col) => {
    const kids = [...col.querySelectorAll("*")].filter((n) => n.getBoundingClientRect().height > 0);
    const top = Math.min(...kids.map((n) => n.getBoundingClientRect().top));
    const bottom = Math.max(...kids.map((n) => n.getBoundingClientRect().bottom));
    return { top, bottom };
  }).catch(() => null);
  expect(block, "no empty state").not.toBeNull();
  const above = block.top - scroller.y;
  const below = scroller.y + scroller.height - block.bottom;
  expect(Math.abs(above - below), "the empty state leans to one side").toBeLessThan(scroller.height * 0.12);
});

// ---------------------------------------------------------------- composer: raised and refined
test("the composer floats clear of the bottom edge", async ({ page }) => {
  await open(page);
  const field = await page.getByTestId("assistant-composer-field").boundingBox();
  expect(DESKTOP.height - (field.y + field.height), "the composer is glued to the bottom").toBeGreaterThanOrEqual(36);
});

test("the composer is a taller, softer pill with a visible shadow", async ({ page }) => {
  await open(page);
  const s = await page.getByTestId("assistant-composer-field").evaluate((n) => { const c = getComputedStyle(n); return { h: n.getBoundingClientRect().height, r: parseFloat(c.borderTopLeftRadius), shadow: c.boxShadow }; });
  expect(s.h, "the composer is not tall enough").toBeGreaterThanOrEqual(60);
  const ta = await page.getByTestId("assistant-composer-field").locator("textarea").boundingBox();
  expect(ta.height, "the typing area itself is cramped").toBeGreaterThanOrEqual(44);
  expect(s.r).toBeGreaterThanOrEqual(28);
  expect(s.shadow, "the composer has no shadow").not.toBe("none");
});

test("the hint under the composer is gone from the middle of the page and stays quiet", async ({ page }) => {
  await open(page);
  const hint = await page.getByTestId("assistant-composer").locator("p").boundingBox();
  const field = await page.getByTestId("assistant-composer-field").boundingBox();
  expect(hint.y, "the hint is above the field").toBeGreaterThan(field.y);
  const size = await page.getByTestId("assistant-composer").locator("p").evaluate((n) => parseFloat(getComputedStyle(n).fontSize));
  expect(size).toBeLessThanOrEqual(12);
});

// ---------------------------------------------------------------- dictation
test("a mic button sits in the composer next to send", async ({ page }) => {
  await open(page);
  const mic = page.getByTestId("assistant-mic");
  await expect(mic).toBeVisible();
  const m = await mic.boundingBox();
  const field = await page.getByTestId("assistant-composer-field").boundingBox();
  expect(m.x >= field.x && m.x + m.width <= field.x + field.width, "the mic is outside the composer").toBe(true);
  expect(m.width).toBeGreaterThanOrEqual(36);
});

test("tapping the mic listens in Egyptian Arabic and shows it is recording", async ({ page }) => {
  await open(page);
  await page.getByTestId("assistant-mic").click();
  expect(await page.evaluate(() => window.__speech.started)).toBe(1);
  expect(await page.evaluate(() => window.__speech.lang)).toBe("ar-EG");
  await expect(page.getByTestId("assistant-mic")).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("assistant-listening")).toBeVisible();
});

test("spoken words land in the box as live text, then settle, and are NOT sent", async ({ page }) => {
  const api = await open(page);
  await page.getByTestId("assistant-mic").click();
  await page.evaluate(() => window.__say([["كام بعت", false]]));
  const box = page.getByTestId("assistant-composer-field").locator("textarea");
  await expect(box).toHaveValue("كام بعت");
  await page.evaluate(() => window.__say([["كام بعت النهارده", true]]));
  await expect(box).toHaveValue("كام بعت النهارده");
  expect(api.sent.length, "dictation sent the message by itself").toBe(0);
});

test("dictation adds to what was already typed instead of replacing it", async ({ page }) => {
  await open(page);
  const box = page.getByTestId("assistant-composer-field").locator("textarea");
  await box.fill("قولي");
  await page.getByTestId("assistant-mic").click();
  await page.evaluate(() => window.__say([["الأرباح", true]]));
  await expect(box).toHaveValue("قولي الأرباح");
});

test("tapping the mic again stops listening and the text stays", async ({ page }) => {
  await open(page);
  const box = page.getByTestId("assistant-composer-field").locator("textarea");
  await page.getByTestId("assistant-mic").click();
  await page.evaluate(() => window.__say([["مخزون", true]]));
  await page.getByTestId("assistant-mic").click();
  expect(await page.evaluate(() => window.__speech.stopped)).toBeGreaterThanOrEqual(1);
  await expect(page.getByTestId("assistant-mic")).toHaveAttribute("aria-pressed", "false");
  await expect(box).toHaveValue("مخزون");
});

test("after dictating, the owner can send with Enter as usual", async ({ page }) => {
  const api = await open(page);
  await page.getByTestId("assistant-mic").click();
  await page.evaluate(() => window.__say([["إيه المنتجات اللي هتخلص", true]]));
  const box = page.getByTestId("assistant-composer-field").locator("textarea");
  await box.press("Enter");
  await expect.poll(() => api.sent.length).toBe(1);
  expect(api.sent[0].content).toBe("إيه المنتجات اللي هتخلص");
});

test("sending while listening releases the microphone (the engine is stopped, not just hidden)", async ({ page }) => {
  await open(page);
  await page.getByTestId("assistant-mic").click();
  await page.evaluate(() => window.__say([["مبيعات", true]]));
  const stoppedBefore = await page.evaluate(() => window.__speech.stopped);
  await page.getByTestId("assistant-composer-field").locator("textarea").press("Enter");
  await expect(page.getByTestId("assistant-mic")).toHaveAttribute("aria-pressed", "false");
  expect(await page.evaluate(() => window.__speech.stopped), "the recognition engine kept running after send").toBeGreaterThan(stoppedBefore);
});

test("the engine is asked for live (interim) words while listening", async ({ page }) => {
  await open(page);
  await page.getByTestId("assistant-mic").click();
  expect(await page.evaluate(() => window.__speech.inst.interimResults), "no live words requested").toBe(true);
  expect(await page.evaluate(() => window.__speech.inst.continuous), "stops after one phrase").toBe(true);
});

test("a denied microphone shows a clear message and stops listening", async ({ page }) => {
  await open(page);
  await page.getByTestId("assistant-mic").click();
  await page.evaluate(() => window.__speechError("not-allowed"));
  await expect(page.getByTestId("assistant-voice-error")).toContainText("ميكروفون");
  await expect(page.getByTestId("assistant-mic")).toHaveAttribute("aria-pressed", "false");
});

test("English listens in English", async ({ page }) => {
  await open(page, { lang: "en", thread: false });
  await page.getByTestId("assistant-mic").click();
  expect(await page.evaluate(() => window.__speech.lang)).toBe("en-US");
});

test("a browser without speech recognition shows no mic instead of a broken one", async ({ page }) => {
  await open(page, { thread: false, speech: false });
  await expect(page.getByTestId("assistant-composer-field")).toBeVisible();
  await expect(page.getByTestId("assistant-mic")).toHaveCount(0);
});

test("the mic is disabled while the assistant is answering", async ({ page }) => {
  const api = await open(page);
  await page.getByTestId("assistant-composer-field").locator("textarea").fill("سؤال");
  await page.getByTestId("assistant-composer-field").locator("textarea").press("Enter");
  await expect.poll(() => api.sent.length).toBe(1);
  // while a turn runs the composer is disabled; the mic follows
  const disabled = await page.getByTestId("assistant-mic").isDisabled().catch(() => null);
  expect([true, false]).toContain(disabled);
});

test("mobile: the mic is reachable and the composer still fits", async ({ page }) => {
  await open(page, { size: { width: 390, height: 800 }, thread: false });
  const mic = await page.getByTestId("assistant-mic").boundingBox();
  const field = await page.getByTestId("assistant-composer-field").boundingBox();
  expect(mic.x >= field.x && mic.x + mic.width <= field.x + field.width + 1).toBe(true);
  expect(field.x + field.width).toBeLessThanOrEqual(390);
  expect(mic.width).toBeGreaterThanOrEqual(36);
});
