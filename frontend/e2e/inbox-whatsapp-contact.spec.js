import { expect, test } from "@playwright/test";

// The WhatsApp "Contact info" panel over mocked HTTP: real data only, and the
// settings it changes go through the same list-state call as the chat list.
const ORIGIN = process.env.BASE_URL || "http://127.0.0.1:4173";

async function boot(page, { customerBlocked = false } = {}) {
  const calls = [];
  const customer = { id: "cust-1", name: "Sara", phone: "201001234567", email: "sara@example.com", lifetime_value: "1250.00", is_blocked: customerBlocked, tags: [], identities: [], addresses: [], notes: [], extra: {} };
  const row = { id: "c1", channel: "whatsapp", status: "open", customer_id: "cust-1", customer_name: "Sara", customer_phone: "201001234567", unread_count: 0, assignee_user_id: null, last_message_at: "2026-11-17T09:00:00+00:00", last_message_preview: "see https://shop.example.com/p/1", last_message_content_type: "text", pinned_at: null, muted_until: null, archived_at: null, marked_unread: false };
  const messages = [
    { id: "m1", direction: "inbound", sender_type: "customer", body: "see https://shop.example.com/p/1", content_type: "text", status: "received", created_at: "2026-11-17T08:00:00+00:00", reactions: [], reply_to: null },
    { id: "m2", direction: "inbound", sender_type: "customer", body: null, media_url: "https://cdn.example.com/a.jpg", media_type: "image", content_type: "image", status: "received", created_at: "2026-11-17T08:30:00+00:00", reactions: [], reply_to: null },
  ];
  await page.context().addCookies([{ name: "csrf_token", value: "ui-test", url: new URL(ORIGIN).origin }]);
  await page.route("**/api/v1/**", async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const send = (data) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(data) });
    if (url.pathname === "/api/v1/auth/me") return send({ id: "u", email: "m@example.com", full_name: "M", is_platform_admin: false, tenants: [{ id: "t", name: "Shop", slug: "shop", role_code: "owner" }] });
    if (url.pathname === "/api/v1/inbox") return send({ items: url.searchParams.get("archived") === "true" ? [] : [row], next_cursor: null });
    if (url.pathname === "/api/v1/conversations/c1/messages") return send({ items: messages, next_cursor: null });
    if (url.pathname === "/api/v1/customers/cust-1" && req.method() === "GET") return send(customer);
    const buy = url.pathname.match(/\/customers\/cust-1\/(block|unblock)$/);
    if (buy) { calls.push(buy[1]); customer.is_blocked = buy[1] === "block"; return send({ id: "cust-1", is_blocked: customer.is_blocked }); }
    if (url.pathname === "/api/v1/conversations/c1/list-state") {
      const body = req.postDataJSON();
      calls.push(body);
      if (body.pinned !== undefined) row.pinned_at = body.pinned ? new Date().toISOString() : null;
      return send({ id: "c1", pinned_at: row.pinned_at, muted_until: row.muted_until, archived_at: row.archived_at, marked_unread: row.marked_unread });
    }
    return send({ items: [], next_cursor: null });
  });
  await page.goto("/inbox", { waitUntil: "domcontentloaded", timeout: 30_000 });
  await expect(page.getByTestId("chat-row")).toHaveCount(1);
  await page.getByTestId("chat-row").getByRole("button").first().click();
  await page.getByTestId("header-info").click();
  await expect(page.getByTestId("contact-info")).toBeVisible();
  return { calls };
}

test("shows the customer's real name, number and email, with no invented claims", async ({ page }) => {
  await boot(page);
  const panel = page.getByTestId("contact-info");
  await expect(panel.getByTestId("contact-name")).toHaveText("Sara");
  await expect(panel.getByTestId("contact-phone")).toHaveText("+20 100 123 4567");
  await expect(panel).toContainText("sara@example.com");
  await expect(panel).not.toContainText(/encrypt|disappearing|starred|Hey there|التشفير|بنجمة/i);
});

test("lists what was shared: photos, links and counts", async ({ page }) => {
  await boot(page);
  const panel = page.getByTestId("contact-info");
  await expect(panel.getByTestId("info-media")).toHaveCount(1);
  await panel.getByTestId("info-tab-links").click();
  await expect(panel.getByTestId("info-link")).toContainText("shop.example.com");
  await panel.getByTestId("info-tab-docs").click();
  await expect(panel.getByTestId("info-body")).toContainText(/No documents|لا توجد مستندات/);
});

test("pinning from the panel uses the same shared-state call and the list follows", async ({ page }) => {
  const { calls } = await boot(page);
  await page.getByTestId("info-pin").click();
  await expect.poll(() => calls.length).toBe(1);
  expect(calls[0]).toEqual({ pinned: true });
  await expect(page.getByTestId("info-pin")).toContainText(/Unpin|إلغاء التثبيت/);
  await expect(page.getByTestId("chat-row").first()).toHaveAttribute("data-pinned", "true");
});

test("shows the store record and can block purchases, saying messages are not affected", async ({ page }) => {
  const { calls } = await boot(page);
  const panel = page.getByTestId("contact-info");
  await expect(panel.getByTestId("info-spend")).toBeVisible();
  await expect(panel.getByTestId("info-blocked")).toHaveCount(0);
  await panel.getByTestId("info-buyblock").click();
  await expect.poll(() => calls).toContain("block");
  await expect(panel.getByTestId("info-blocked")).toContainText(/Messages are not affected|لا يؤثر على الرسائل/);
});

test("closes with the close button and with Escape", async ({ page }) => {
  await boot(page);
  await page.getByTestId("contact-close").click();
  await expect(page.getByTestId("contact-info")).toHaveCount(0);
  await page.getByTestId("header-info").click();
  await expect(page.getByTestId("contact-info")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("contact-info")).toHaveCount(0);
});
