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

async function open(page, rowExtra = {}) {
  await page.route(PX, (r) => r.fulfill({ status: 200, contentType: "image/gif", body: Buffer.from("R0lGODlhAQABAIAAAAUEBAAAACwAAAAAAQABAAACAkQBADs=", "base64") }));
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.context().addCookies([{ name: "csrf_token", value: "x", url: new URL(ORIGIN).origin }]);
  await page.route("**/api/v1/**", async (route) => {
    const u = new URL(route.request().url());
    const p = u.pathname.replace("/api/v1", "");
    const send = (d) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(d) });
    if (p === "/auth/me") return send({ id: "u", email: "owner@shop.com", full_name: "Owner", is_platform_admin: false, tenants: [{ id: "t", name: "T", role: "owner" }] });
    if (p === "/channels/status") return send([{ provider: "instagram", connected: true, enabled_for_me: true, locked: false, lifecycle: "connected", webhook_status: "active", account_name: "shop" }]);
    if (p === "/inbox") return send({ items: u.searchParams.get("archived") === "true" ? [] : [{ ...rowExtra, id: "c1", channel: "instagram", status: "open", customer_id: "cu1", customer_name: "Sara Ahmed", customer_avatar_url: null, unread_count: 0, last_message_at: iso(20), last_message_preview: "x", last_message_direction: "outbound", last_message_content_type: "text" }], next_cursor: null });
    if (p === "/conversations/c1/messages") return send({ items: MESSAGES, next_cursor: null });
    if (p.endsWith("/refresh-profile")) return send({ updated: false });
    if (p === "/ai/agents") return send([]);
    return send({ items: [], next_cursor: null });
  });
  await page.goto("/inbox", { waitUntil: "domcontentloaded", timeout: 30_000 });
  await page.getByRole("button", { name: "Instagram", exact: true }).click();
  await page.getByRole("tab", { name: /Direct messages|الرسائل الخاصة/ }).click();
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

const rowOf = (page, text) => page.getByTestId("ig-bubble").filter({ hasText: text }).locator("xpath=ancestor::div[contains(@class,'group/ig')]");

test("hovering a message offers react, reply and more; a reaction is sent to the server", async ({ page }) => {
  await open(page);
  const reactions = [];
  await page.route("**/api/v1/conversations/c1/messages/m1/reaction", async (r) => {
    reactions.push(r.request().postDataJSON());
    await r.fulfill({ status: 201, contentType: "application/json", body: "{}" });
  });
  const row = rowOf(page, "hello there");
  await expect(row).toBeVisible({ timeout: 15_000 });
  await row.hover();
  await expect(row.getByTestId("ig-react")).toBeVisible();
  await expect(row.getByTestId("ig-reply")).toBeVisible();
  await row.getByTestId("ig-react").click();
  await expect(page.getByTestId("ig-reaction-strip").getByRole("menuitem")).toHaveCount(6);
  await page.getByTestId("ig-reaction-strip").getByRole("menuitem", { name: "😂" }).click();
  await expect.poll(() => reactions.length).toBe(1);
  expect(reactions[0]).toEqual({ emoji: "😂" });
  await expect(page.getByTestId("ig-reactions")).toContainText("😂");
});

test("Reply shows the Replying-to bar and the send carries the quoted message", async ({ page }) => {
  await open(page);
  const sends = [];
  await page.route("**/api/v1/conversations/c1/messages", async (r) => {
    if (r.request().method() !== "POST") return r.fallback();
    sends.push(r.request().postDataJSON());
    await r.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ id: "n1", status: "queued" }) });
  });
  const row = rowOf(page, "hello there");
  await expect(row).toBeVisible({ timeout: 15_000 });
  await row.hover();
  await row.getByTestId("ig-reply").click();
  const bar = page.getByTestId("ig-replying-to");
  await expect(bar).toBeVisible();
  await expect(bar).toContainText("hello there");
  await page.getByRole("textbox").last().fill("yes we are open");
  await page.keyboard.press("Enter");
  await expect.poll(() => sends.length).toBe(1);
  expect(sends[0]).toMatchObject({ body: "yes we are open", reply_to_message_id: "m1" });
  await expect(bar).toBeHidden();
});

test("Cancel removes the Replying-to bar", async ({ page }) => {
  await open(page);
  const row = rowOf(page, "hello there");
  await expect(row).toBeVisible({ timeout: 15_000 });
  await row.hover();
  await row.getByTestId("ig-reply").click();
  await page.getByTestId("ig-cancel-reply").click();
  await expect(page.getByTestId("ig-replying-to")).toBeHidden();
});

test("the heart button sends a heart alone and disappears once you type", async ({ page }) => {
  await open(page);
  const sends = [];
  await page.route("**/api/v1/conversations/c1/messages", async (r) => {
    if (r.request().method() !== "POST") return r.fallback();
    sends.push(r.request().postDataJSON());
    await r.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ id: "n2", status: "queued" }) });
  });
  const heart = page.getByTestId("ig-send-heart");
  await expect(heart).toBeVisible({ timeout: 15_000 });
  await heart.click();
  await expect.poll(() => sends.length).toBe(1);
  expect(sends[0]).toEqual({ heart: true });
  await page.getByRole("textbox").last().fill("hi");
  await expect(heart).toBeHidden();
});

test("a deleted message offers no actions", async ({ page }) => {
  await open(page);
  await expect(page.getByTestId("ig-deleted")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId("ig-deleted").locator("xpath=ancestor::div[contains(@class,'group/ig')]").getByTestId("ig-actions")).toHaveCount(0);
});

test("a verified account with known followers shows the tick, the count and who follows whom", async ({ page }) => {
  await open(page, { customer_verified: true, customer_follower_count: 12500, customer_follows_you: true, customer_you_follow: false });
  await expect(page.getByText("hello there")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId("ig-verified").first()).toBeVisible();
  await page.locator('[title="View contact details"], [title="عرض تفاصيل جهة الاتصال"]').first().click();
  await expect(page.getByTestId("ig-follower-count")).toContainText("12.5K");
  await expect(page.getByTestId("ig-relation")).toHaveText("Follows you");
});

test("nothing is invented when Instagram told us nothing about the person", async ({ page }) => {
  await open(page);
  await expect(page.getByText("hello there")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId("ig-verified")).toHaveCount(0);
  await page.locator('[title="View contact details"], [title="عرض تفاصيل جهة الاتصال"]').first().click();
  await expect(page.getByTestId("ig-profile-facts")).toHaveCount(0);
});
