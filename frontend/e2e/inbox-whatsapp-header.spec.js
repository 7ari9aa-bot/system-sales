import { expect, test } from "@playwright/test";

// The WhatsApp chat header over mocked HTTP.
const ORIGIN = process.env.BASE_URL || "http://127.0.0.1:4173";

async function boot(page, { lastCustomerMessageAt }) {
  const calls = [];
  const row = { id: "c1", channel: "whatsapp", status: "open", customer_id: "cust-1", customer_name: "Sara", customer_phone: "201001234567", unread_count: 0, assignee_user_id: null, last_message_at: new Date().toISOString(), last_customer_message_at: lastCustomerMessageAt, last_message_preview: "hi", last_message_content_type: "text", pinned_at: null, muted_until: null, archived_at: null, marked_unread: false };
  await page.context().addCookies([{ name: "csrf_token", value: "ui-test", url: new URL(ORIGIN).origin }]);
  await page.route("**/api/v1/**", async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const send = (data) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(data) });
    if (url.pathname === "/api/v1/auth/me") return send({ id: "u", email: "m@example.com", full_name: "M", is_platform_admin: false, tenants: [{ id: "t", name: "Shop", slug: "shop", role_code: "owner" }] });
    if (url.pathname === "/api/v1/inbox") return send({ items: url.searchParams.get("archived") === "true" ? [] : [row], next_cursor: null });
    if (url.pathname === "/api/v1/conversations/c1/list-state") {
      const body = req.postDataJSON();
      calls.push(body);
      if (body.pinned !== undefined) row.pinned_at = body.pinned ? new Date().toISOString() : null;
      return send({ id: "c1", pinned_at: row.pinned_at, muted_until: row.muted_until, archived_at: row.archived_at, marked_unread: row.marked_unread });
    }
    return send({ items: [], next_cursor: null });
  });
  await page.goto("/inbox", { waitUntil: "domcontentloaded", timeout: 30_000 });
  await expect(page.getByTestId("chat-header")).toBeVisible();
  return { calls };
}

const hoursAgo = (h) => new Date(Date.now() - h * 3600_000).toISOString();

test("shows the name and number, and says nothing about a window that is comfortably open", async ({ page }) => {
  await boot(page, { lastCustomerMessageAt: hoursAgo(1) });
  await expect(page.getByTestId("header-name")).toHaveText("Sara");
  await expect(page.getByTestId("header-subtitle")).toHaveText("+20 100 123 4567");
  await expect(page.getByTestId("header-subtitle")).toHaveAttribute("data-window", "open");
});

test("warns when the reply window is about to close, and when it has closed", async ({ page }) => {
  await boot(page, { lastCustomerMessageAt: hoursAgo(23) });
  await expect(page.getByTestId("header-subtitle")).toContainText(/Reply window ends in 5\dm|Reply window ends in 1h/);
  await expect(page.getByTestId("header-subtitle")).toHaveAttribute("data-window", "closing");
});

test("a closed window is stated plainly", async ({ page }) => {
  await boot(page, { lastCustomerMessageAt: hoursAgo(30) });
  await expect(page.getByTestId("header-subtitle")).toContainText("Reply window closed");
  await expect(page.getByTestId("header-subtitle")).toHaveAttribute("data-window", "closed");
});

test("the name opens contact info", async ({ page }) => {
  await boot(page, { lastCustomerMessageAt: hoursAgo(1) });
  await page.getByTestId("header-identity").click();
  await expect(page.getByTestId("contact-info")).toBeVisible();
});

test("the search button opens and closes message search", async ({ page }) => {
  await boot(page, { lastCustomerMessageAt: hoursAgo(1) });
  const search = page.getByTestId("header-search");
  await expect(search).toHaveAttribute("aria-pressed", "false");
  await search.click();
  await expect(search).toHaveAttribute("aria-pressed", "true");
  await search.click();
  await expect(search).toHaveAttribute("aria-pressed", "false");
});

test("the more menu pins the chat through the shared call and shows the pin", async ({ page }) => {
  const { calls } = await boot(page, { lastCustomerMessageAt: hoursAgo(1) });
  await page.getByTestId("header-more").click();
  await page.getByTestId("act-pin").click();
  await expect.poll(() => calls.length).toBe(1);
  expect(calls[0]).toEqual({ pinned: true });
  await expect(page.getByTestId("chat-header").getByRole("img", { name: /Pinned chat/ })).toBeVisible();
});

test("the more menu closes with Escape and gives focus back to its button", async ({ page }) => {
  await boot(page, { lastCustomerMessageAt: hoursAgo(1) });
  await page.getByTestId("header-more").click();
  await expect(page.getByTestId("chat-list-menu")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("chat-list-menu")).toHaveCount(0);
  await expect(page.getByTestId("header-more")).toBeFocused();
});
