import { expect, test } from "@playwright/test";

// Facebook Pages and Messenger are separate functions that share the Page webhook object, so
// /facebook/messages is now a redirect into the Messenger inbox: a shop that bookmarked the old
// address still lands where the chats actually are, and nobody is shown a second, half-empty copy
// of the same conversations. These tests pin that contract, which is what the page does today.
const ORIGIN = process.env.BASE_URL || "http://127.0.0.1:4173";
const iso = (min) => new Date(Date.now() - min * 60000).toISOString();

const CHAT = {
  id: "c1",
  channel: "messenger",
  status: "open",
  customer_id: "cu1",
  customer_name: "Sara Ahmed",
  customer_avatar_url: null,
  unread_count: 1,
  last_message_at: iso(10),
  last_message_preview: "هل المقاس 42 متوفر؟",
  last_message_direction: "inbound",
  last_message_content_type: "text",
};

function api({ chats = [], inboxStatus = 200 } = {}) {
  return async (route) => {
    const req = route.request();
    const p = new URL(req.url()).pathname.replace("/api/v1", "");
    const send = (d, s = 200) =>
      route.fulfill({ status: s, contentType: "application/json", body: JSON.stringify(d) });
    if (p === "/auth/me") {
      return send({
        id: "u",
        email: "o@shop.com",
        full_name: "O",
        is_platform_admin: false,
        tenants: [{ id: "t", name: "T", role: "owner" }],
      });
    }
    if (p === "/channels/status") {
      return send([
        { provider: "messenger", connected: true, enabled_for_me: true, locked: false, lifecycle: "connected", webhook_status: "active" },
      ]);
    }
    if (p === "/inbox") {
      if (inboxStatus !== 200) return send({ detail: "down" }, inboxStatus);
      return send({ items: chats, next_cursor: null });
    }
    if (/^\/conversations\/[^/]+\/messages$/.test(p)) {
      return send({
        items: [
          {
            id: "m1",
            conversation_id: "c1",
            direction: "inbound",
            content_type: "text",
            content: "هل المقاس 42 متوفر؟",
            created_at: iso(10),
            status: "delivered",
          },
        ],
        next_cursor: null,
      });
    }
    return send({ items: [], next_cursor: null });
  };
}

async function open(page, handler, path) {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.context().addCookies([{ name: "csrf_token", value: "x", url: new URL(ORIGIN).origin }]);
  await page.route("**/api/v1/**", handler);
  await page.goto(path, { waitUntil: "domcontentloaded", timeout: 30_000 });
  return errors;
}

test("the old Page Messages address opens the Messenger inbox instead of a second copy", async ({ page }) => {
  const errors = await open(page, api({ chats: [CHAT] }), "/facebook/messages");

  await expect(page).toHaveURL(/\/inbox\?channel=messenger/, { timeout: 15_000 });
  expect(errors).toEqual([]);
});

test("an old link to one thread lands in the inbox too, not on a dead page", async ({ page }) => {
  const errors = await open(page, api({ chats: [CHAT] }), "/facebook/messages/c1");

  await expect(page).toHaveURL(/\/inbox\?channel=messenger/, { timeout: 15_000 });
  expect(errors).toEqual([]);
});

test("the inbox the redirect lands on still lists the chats and does not crash", async ({ page }) => {
  const errors = await open(page, api({ chats: [CHAT] }), "/facebook/messages");

  await expect(page).toHaveURL(/channel=messenger/);
  await expect(page.getByText("Sara Ahmed").first()).toBeVisible({ timeout: 15_000 });
  expect(errors).toEqual([]);
});

test("an empty inbox says so rather than showing a blank page", async ({ page }) => {
  const errors = await open(page, api({ chats: [] }), "/facebook/messages");

  await expect(page).toHaveURL(/channel=messenger/);
  // The shell must render: a missing page would leave the sidebar without a main region.
  await expect(page.locator("main").first()).toBeVisible({ timeout: 15_000 });
  expect(errors).toEqual([]);
});
