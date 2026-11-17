import { expect, test } from "@playwright/test";

// The WhatsApp inbox on a phone: one pane at a time, thumb-sized controls and
// nothing wider than the screen.
const ORIGIN = process.env.BASE_URL || "http://127.0.0.1:4173";
const now = () => new Date().toISOString();

async function boot(browser, { width = 390, height = 780 } = {}) {
  const ctx = await browser.newContext({ viewport: { width, height }, hasTouch: true, isMobile: true });
  const page = await ctx.newPage();
  const rows = ["Sara", "أحمد علي"].map((name, i) => ({ id: `c${i + 1}`, channel: "whatsapp", status: "open", customer_id: `cu${i}`, customer_name: name, customer_phone: `2010012345${i}0`, unread_count: i === 0 ? 2 : 0, last_message_at: now(), last_customer_message_at: now(), last_message_preview: "مرحبا، عايز أسأل عن الطلب", last_message_content_type: "text", pinned_at: null, muted_until: null, archived_at: null, marked_unread: false }));
  await ctx.addCookies([{ name: "csrf_token", value: "x", url: new URL(ORIGIN).origin }]);
  await page.route("**/api/v1/**", async (route) => {
    const u = new URL(route.request().url());
    const send = (d) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(d) });
    if (u.pathname === "/api/v1/auth/me") return send({ id: "u", email: "m@e.com", full_name: "M", is_platform_admin: false, tenants: [{ id: "t", name: "Shop", slug: "shop", role_code: "owner" }] });
    if (u.pathname === "/api/v1/inbox") return send({ items: rows, next_cursor: null });
    if (u.pathname.endsWith("/messages")) return send({ items: [{ id: "m1", direction: "inbound", body: "مرحبا", content_type: "text", status: "received", created_at: now(), reactions: [] }], next_cursor: null });
    return send({ items: [], next_cursor: null });
  });
  await page.goto("/inbox", { waitUntil: "domcontentloaded", timeout: 30_000 });
  await expect(page.getByTestId("chat-list")).toBeVisible();
  return { page, ctx };
}

// Interactive controls inside the inbox that are visible and too small to tap.
const tooSmall = (page, scope) => page.evaluate((sel) => {
  const root = document.querySelector(sel);
  return [...root.querySelectorAll("button, [role=tab], textarea, input, a")].filter((el) => {
    const r = el.getBoundingClientRect(); const cs = getComputedStyle(el);
    return r.width && r.height && cs.visibility !== "hidden" && cs.display !== "none" && (r.height < 36 || r.width < 36);
  }).map((el) => `${el.dataset.testid || el.getAttribute("aria-label") || el.tagName} ${Math.round(el.getBoundingClientRect().width)}x${Math.round(el.getBoundingClientRect().height)}`);
}, scope);

test("the list fits a phone with thumb-sized controls and no sideways scroll", async ({ browser }) => {
  const { page, ctx } = await boot(browser);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  expect(await tooSmall(page, '[data-testid="chat-list"]')).toEqual([]);
  await ctx.close();
});

test("opening a chat shows only the chat, with a way back to the list", async ({ browser }) => {
  const { page, ctx } = await boot(browser);
  await page.getByText("Sara").first().click();
  await expect(page.getByTestId("chat-header")).toBeVisible();
  await expect(page.getByTestId("chat-list")).toBeHidden();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.getByRole("button", { name: /back|رجوع/i }).click();
  await expect(page.getByTestId("chat-list")).toBeVisible();
  await ctx.close();
});

test("the chat's input bar keeps tappable controls and the field stays usable", async ({ browser }) => {
  const { page, ctx } = await boot(browser);
  await page.getByText("Sara").first().click();
  await expect(page.getByTestId("composer-input")).toBeVisible();
  const bar = await page.evaluate(() => ["composer-emoji", "composer-attach", "composer-voice"].map((id) => { const r = document.querySelector(`[data-testid=${id}]`).getBoundingClientRect(); return [Math.round(r.width), Math.round(r.height)]; }));
  for (const [w, h] of bar) { expect(w).toBeGreaterThanOrEqual(40); expect(h).toBeGreaterThanOrEqual(40); }
  expect((await page.getByTestId("composer-input").boundingBox()).width).toBeGreaterThan(140);
  await ctx.close();
});

test("the attach menu and the preview fit inside a phone", async ({ browser }) => {
  const { page, ctx } = await boot(browser);
  await page.getByText("Sara").first().click();
  await page.getByTestId("composer-attach").click();
  const menu = await page.getByTestId("attach-menu").boundingBox();
  expect(menu.x).toBeGreaterThanOrEqual(0);
  expect(menu.x + menu.width).toBeLessThanOrEqual(390);
  await page.getByTestId("attach-input-media").setInputFiles({ name: "a.png", mimeType: "image/png", buffer: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==", "base64") });
  const prev = await page.getByTestId("attach-preview").boundingBox();
  expect(prev.width).toBeLessThanOrEqual(390);
  expect(await tooSmall(page, '[data-testid="attach-preview"]')).toEqual([]);
  await ctx.close();
});

test("a narrow tablet still shows list and chat without overflow", async ({ browser }) => {
  const { page, ctx } = await boot(browser, { width: 820, height: 1000 });
  await page.getByText("Sara").first().click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(820);
  await expect(page.getByTestId("chat-header")).toBeVisible();
  await ctx.close();
});
