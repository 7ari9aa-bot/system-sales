import { expect, test } from "@playwright/test";

// UI contract test over mocked HTTP: what the inbox row shows under a name.
const ORIGIN = process.env.BASE_URL || "http://127.0.0.1:4173";

const rows = [
  {
    id: "c-text",
    channel: "whatsapp",
    status: "open",
    customer_id: "cust-1",
    customer_name: "Sarah",
    customer_phone: "+201000000001",
    unread_count: 0,
    assignee_user_id: null,
    last_message_at: "2026-11-05T10:00:00+00:00",
    last_message_preview: "هل يوجد مقاس L؟",
    last_message_content_type: "text",
  },
  {
    id: "c-photo",
    channel: "whatsapp",
    status: "open",
    customer_id: "cust-2",
    customer_name: "Omar",
    customer_phone: "+201000000002",
    unread_count: 1,
    assignee_user_id: null,
    last_message_at: "2026-11-05T11:00:00+00:00",
    // The newest message is a photo: the server sends no text for it.
    last_message_preview: null,
    last_message_content_type: "image",
  },
];

test("a media message names itself instead of leaving the row blank", async ({ page }) => {
  await page.context().addCookies([{ name: "csrf_token", value: "ui-test", url: new URL(ORIGIN).origin }]);
  await page.route("**/api/v1/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    const send = (data) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(data) });
    if (path === "/api/v1/auth/me") {
      return send({ id: "u", email: "merchant@example.com", full_name: "Merchant", is_platform_admin: false, tenants: [{ id: "t", name: "Shop", slug: "shop", role_code: "owner" }] });
    }
    if (path.startsWith("/api/v1/inbox")) return send({ items: rows, next_cursor: null });
    return send({ items: [], next_cursor: null });
  });

  await page.goto("/inbox");
  const row = (name) => page.locator("button[aria-pressed]").filter({ hasText: name });
  await expect(row("Omar")).toBeVisible();
  await expect(row("Omar")).toContainText("Photo");
  await expect(row("Sarah")).toContainText("هل يوجد مقاس L؟");
});
