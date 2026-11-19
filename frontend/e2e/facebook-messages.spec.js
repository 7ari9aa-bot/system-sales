import { expect, test } from "@playwright/test";

// The Page's Messenger inbox. No test opened this page before, and it crashed on open
// (the data hook never handed the chat list to the page), so these open it for real.
const ORIGIN = process.env.BASE_URL || "http://127.0.0.1:4173";
const iso = (min) => new Date(Date.now() - min * 60000).toISOString();

function api({ chats, inboxStatus = 200 }) {
  return async (route) => {
    const req = route.request();
    const p = new URL(req.url()).pathname.replace("/api/v1", "");
    const send = (d, s = 200) => route.fulfill({ status: s, contentType: "application/json", body: JSON.stringify(d) });
    if (p === "/auth/me") return send({ id: "u", email: "o@shop.com", full_name: "O", is_platform_admin: false, tenants: [{ id: "t", name: "T", role: "owner" }] });
    if (p === "/channels/status") return send([{ provider: "facebook", connected: true, enabled_for_me: true, locked: false, lifecycle: "connected", webhook_status: "active" }]);
    if (p === "/facebook/page") return send({ id: "111", name: "My Shop" });
    if (p === "/inbox") {
      if (inboxStatus !== 200) return send({ detail: "down" }, inboxStatus);
      return send({ items: new URL(req.url()).searchParams.get("archived") === "true" ? [] : chats, next_cursor: null });
    }
    if (/^\/conversations\/[^/]+\/messages$/.test(p)) {
      return send({ items: [{ id: "m1", conversation_id: "c1", direction: "inbound", content_type: "text", content: "هل المقاس 42 متوفر؟", created_at: iso(10), status: "delivered" }], next_cursor: null });
    }
    return send({ items: [], next_cursor: null });
  };
}

const CHAT = { id: "c1", channel: "facebook", status: "open", customer_id: "cu1", customer_name: "Sara Ahmed", customer_avatar_url: null, unread_count: 1, last_message_at: iso(10), last_message_preview: "هل المقاس 42 متوفر؟", last_message_direction: "inbound", last_message_content_type: "text" };

async function open(page, handler, path = "/facebook/messages") {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.context().addCookies([{ name: "csrf_token", value: "x", url: new URL(ORIGIN).origin }]);
  await page.route("**/api/v1/**", handler);
  await page.goto(path, { waitUntil: "domcontentloaded", timeout: 30_000 });
  return errors;
}

test("the Messages page opens and lists the Page's chats instead of crashing", async ({ page }) => {
  const errors = await open(page, api({ chats: [CHAT] }));
  await expect(page.getByTestId("facebook-messages")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("Sara Ahmed").first()).toBeVisible();
  expect(errors).toEqual([]);
});

test("opening a chat shows its messages at its own address", async ({ page }) => {
  const errors = await open(page, api({ chats: [CHAT] }));
  await page.getByText("Sara Ahmed").first().click();
  await expect(page).toHaveURL(/\/facebook\/messages\/c1$/);
  await expect(page.getByText("هل المقاس 42 متوفر؟").last()).toBeVisible({ timeout: 15_000 });
  expect(errors).toEqual([]);
});

test("a Page with no chats says so, and a failed load shows a message with Retry", async ({ page }) => {
  const errors = await open(page, api({ chats: [] }));
  await expect(page.getByText("No chats yet.")).toBeVisible({ timeout: 15_000 });
  expect(errors).toEqual([]);
});

test("a failed chat list is reported, not a blank page", async ({ page }) => {
  const errors = await open(page, api({ chats: [], inboxStatus: 500 }));
  await expect(page.getByRole("alert")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole("button", { name: "Retry" })).toBeVisible();
  expect(errors).toEqual([]);
});
