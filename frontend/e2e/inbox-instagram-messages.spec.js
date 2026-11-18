import { expect, test } from "@playwright/test";

const ORIGIN = process.env.BASE_URL || "http://127.0.0.1:4173";
const NOW = Date.now();
const iso = (mins) => new Date(NOW - mins * 60_000).toISOString();
const PX = "https://cdn.example.com/photo.jpg";

function msg(id, mins, over = {}) {
  return { id, direction: "inbound", sender_type: "customer", body: null, media_url: null, media_type: null, filename: null, content_type: "text", card: null, status: "delivered", edited: false, deleted: false, created_at: iso(mins), reply_to: null, reactions: [], my_reaction: "", ...over };
}

const MESSAGES = [
  msg("m1", 60, { body: "hello there" }),
  msg("m2", 55, { direction: "outbound", sender_type: "agent", body: "hi! how can I help?", status: "read" }),
  msg("m3", 50, { content_type: "share", body: "check this", card: { type: "share", kind: "ig_post", url: "https://www.instagram.com/p/abc/", title: "New shoes" } }),
  msg("m4", 45, { content_type: "story_reply", body: "love it", card: { type: "story_reply", kind: "story_reply", url: null, title: null } }),
  msg("m5", 40, { content_type: "sticker", body: "❤️" }),
  msg("m6", 35, { content_type: "image", media_type: "image", media_url: PX }),
  msg("m7", 30, { deleted: true, body: null, content_type: "deleted" }),
  msg("m8", 20, { direction: "outbound", sender_type: "agent", body: "sent you the details", status: "read" }),
];

async function open(page) {
  await page.route(PX, (r) => r.fulfill({ status: 200, contentType: "image/gif", body: Buffer.from("R0lGODlhAQABAIAAAAUEBAAAACwAAAAAAQABAAACAkQBADs=", "base64") }));
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.context().addCookies([{ name: "csrf_token", value: "x", url: new URL(ORIGIN).origin }]);
  await page.route("**/api/v1/**", async (route) => {
    const u = new URL(route.request().url());
    const p = u.pathname.replace("/api/v1", "");
    const send = (d) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(d) });
    if (p === "/auth/me") return send({ id: "u", email: "owner@shop.com", full_name: "Owner", is_platform_admin: false, tenants: [{ id: "t", name: "T", role: "owner" }] });
    if (p === "/channels/status") return send([{ provider: "instagram", connected: true, enabled_for_me: true, locked: false, lifecycle: "connected", webhook_status: "active", account_name: "shop" }]);
    if (p === "/inbox") return send({ items: u.searchParams.get("archived") === "true" ? [] : [{ id: "c1", channel: "instagram", status: "open", customer_id: "cu1", customer_name: "Sara Ahmed", customer_avatar_url: null, unread_count: 0, last_message_at: iso(20), last_message_preview: "x", last_message_direction: "outbound", last_message_content_type: "text" }], next_cursor: null });
    if (p === "/conversations/c1/messages") return send({ items: MESSAGES, next_cursor: null });
    if (p.endsWith("/refresh-profile")) return send({ updated: false });
    if (p === "/ai/agents") return send([]);
    return send({ items: [], next_cursor: null });
  });
  await page.goto("/instagram/direct/inbox", { waitUntil: "domcontentloaded", timeout: 30_000 });
  await page.getByText("Sara Ahmed").first().click();
}

test("every Instagram message type is drawn, not just text", async ({ page }) => {
  await open(page);
  await expect(page.getByText("hello there")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId("ig-card-share")).toBeVisible();
  await expect(page.getByText("New shoes")).toBeVisible();
  await expect(page.getByRole("link", { name: "Open on Instagram" })).toHaveAttribute("href", "https://www.instagram.com/p/abc/");
  await expect(page.getByTestId("ig-card-story_reply")).toBeVisible();
  await expect(page.getByText("Story no longer available")).toBeVisible();
  await expect(page.getByTestId("ig-heart")).toBeVisible();
  await expect(page.getByTestId("ig-image")).toBeVisible();
  await expect(page.getByTestId("ig-deleted")).toBeVisible();
});

test("bubbles use Instagram's own colours and 18px corners", async ({ page }) => {
  await open(page);
  const mine = page.getByTestId("ig-bubble").filter({ hasText: "sent you the details" });
  const theirs = page.getByTestId("ig-bubble").filter({ hasText: "hello there" });
  await expect(mine).toBeVisible({ timeout: 15_000 });
  expect(await mine.evaluate((e) => getComputedStyle(e).backgroundColor)).toBe("rgb(74, 93, 249)");
  expect(await mine.evaluate((e) => getComputedStyle(e).borderTopLeftRadius)).toBe("18px");
  expect(await theirs.evaluate((e) => getComputedStyle(e).backgroundColor)).toBe("rgb(243, 245, 247)");
});

test("Seen appears once, under the newest message we sent, never on the older one", async ({ page }) => {
  await open(page);
  await expect(page.getByText("sent you the details")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId("ig-seen")).toHaveCount(1);
  const newest = page.getByTestId("ig-bubble").filter({ hasText: "sent you the details" });
  const box = await newest.boundingBox();
  const seen = await page.getByTestId("ig-seen").boundingBox();
  expect(seen.y).toBeGreaterThan(box.y + box.height - 2); // below it, not above
});

test("nothing in the chat spills past the window", async ({ page }) => {
  await open(page);
  await expect(page.getByTestId("ig-card-share")).toBeVisible({ timeout: 15_000 });
  const over = await page.evaluate(() => [...document.querySelectorAll('[data-testid^="ig-"]')].filter((e) => e.getBoundingClientRect().right > innerWidth + 1).length);
  expect(over).toBe(0);
});

test("a photo opens in the viewer", async ({ page }) => {
  await open(page);
  await page.getByTestId("ig-image").click();
  await expect(page.getByRole("dialog")).toBeVisible({ timeout: 5_000 });
});

// Instagram's Send API lets a business react with a heart only, so the heart is the one reaction offered, and only on
// what the customer wrote. It goes through /reaction like WhatsApp's, and a second tap withdraws it.
test("a customer's message can be hearted and un-hearted; our own cannot", async ({ page }) => {
  await open(page);
  const calls = [];
  await page.route("**/api/v1/conversations/c1/messages/*/reaction", async (route) => {
    calls.push({ id: route.request().url().match(/messages\/([^/]+)\/reaction/)[1], body: route.request().postDataJSON() });
    await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ id: "r1", target_id: "m1", emoji: "❤️" }) });
  });
  await page.getByText("Sara Ahmed").first().click();
  const hello = page.getByTestId("ig-bubble").filter({ hasText: "hello there" });
  await expect(hello).toBeVisible({ timeout: 15_000 });
  await hello.hover();
  const heart = page.getByTestId("ig-react-heart").first();
  await heart.click({ force: true });
  await expect.poll(() => calls.at(-1)).toEqual({ id: "m1", body: { emoji: "❤️" } });
  await expect(heart).toHaveAttribute("aria-pressed", "true");
  await heart.click({ force: true });
  await expect.poll(() => calls.at(-1)).toEqual({ id: "m1", body: { emoji: "" } });
  // our own message offers no reaction
  const mine = page.getByTestId("ig-bubble").filter({ hasText: "hi! how can I help?" });
  await expect(mine.locator("xpath=..").getByTestId("ig-react-heart")).toHaveCount(0);
});

// Instagram has a heart where WhatsApp has a microphone. The old microphone recorded, threw the recording away and sent
// the text "voice message (0:07)", so it is gone; the heart is a real Send API message (`like_heart`).
test("the composer offers a heart, not a microphone, and the heart is sent as a heart", async ({ page }) => {
  await open(page);
  const sent = [];
  await page.route("**/api/v1/conversations/c1/messages", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    sent.push(route.request().postDataJSON());
    await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ id: "new1", status: "queued", created_at: new Date().toISOString() }) });
  });
  await page.getByText("Sara Ahmed").first().click();
  await expect(page.getByTestId("ig-send-heart")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole("button", { name: /Voice note|تسجيل رسالة صوتية/ })).toHaveCount(0);
  await page.getByTestId("ig-send-heart").click();
  await expect.poll(() => sent.at(-1)).toEqual({ instagram_heart: true });
  // it shows at once as the same heart an incoming one draws
  await expect(page.getByTestId("ig-heart")).toHaveCount(2);
  // typing text swaps the heart for Send, like Instagram
  await page.getByRole("textbox").last().fill("hello");
  await expect(page.getByTestId("ig-send-heart")).toHaveCount(0);
});
