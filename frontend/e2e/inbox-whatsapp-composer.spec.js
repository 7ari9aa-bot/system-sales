import { expect, test } from "@playwright/test";

// The WhatsApp input bar over mocked HTTP.
const ORIGIN = process.env.BASE_URL || "http://127.0.0.1:4173";
const hoursAgo = (h) => new Date(Date.now() - h * 3600_000).toISOString();

async function boot(page, { lastCustomerMessageAt = hoursAgo(1) } = {}) {
  const sent = [];
  const row = { id: "c1", channel: "whatsapp", status: "open", customer_id: "cust-1", customer_name: "Sara", customer_phone: "201001234567", unread_count: 0, assignee_user_id: null, last_message_at: new Date().toISOString(), last_customer_message_at: lastCustomerMessageAt, last_message_preview: "hi", last_message_content_type: "text", pinned_at: null, muted_until: null, archived_at: null, marked_unread: false };
  await page.context().addCookies([{ name: "csrf_token", value: "ui-test", url: new URL(ORIGIN).origin }]);
  await page.route("**/api/v1/**", async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const send = (data, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(data) });
    if (url.pathname === "/api/v1/auth/me") return send({ id: "u", email: "m@example.com", full_name: "M", is_platform_admin: false, tenants: [{ id: "t", name: "Shop", slug: "shop", role_code: "owner" }] });
    if (url.pathname === "/api/v1/inbox") return send({ items: url.searchParams.get("archived") === "true" ? [] : [row], next_cursor: null });
    if (url.pathname === "/api/v1/conversations/c1/messages" && req.method() === "POST") { sent.push(req.postDataJSON()); return send({ id: `m${sent.length}`, status: "queued", created_at: new Date().toISOString() }, 201); }
    return send({ items: [], next_cursor: null });
  });
  await page.goto("/inbox", { waitUntil: "domcontentloaded", timeout: 30_000 });
  await expect(page.getByTestId("chat-header")).toBeVisible();
  return { sent };
}

test("Enter sends the text, Shift+Enter adds a line", async ({ page }) => {
  const { sent } = await boot(page);
  const input = page.getByTestId("composer-input");
  await input.fill("first");
  await input.press("Shift+Enter");
  await input.pressSequentially("second");
  await expect(input).toHaveValue("first\nsecond");
  await input.press("Enter");
  await expect.poll(() => sent.length).toBe(1);
  expect(sent[0]).toEqual({ body: "first\nsecond" });
  await expect(input).toHaveValue("");
});

test("the field grows with the text and the send button replaces the mic", async ({ page }) => {
  await boot(page);
  const input = page.getByTestId("composer-input");
  await expect(page.getByTestId("composer-voice")).toBeVisible();
  const before = (await input.boundingBox()).height;
  await input.fill("1\n2\n3\n4");
  await expect(page.getByTestId("composer-send")).toBeVisible();
  await expect(page.getByTestId("composer-voice")).toHaveCount(0);
  expect((await input.boundingBox()).height).toBeGreaterThan(before + 20);
});

test("a blank message is not sent", async ({ page }) => {
  const { sent } = await boot(page);
  const input = page.getByTestId("composer-input");
  await input.fill("   ");
  await input.press("Enter");
  await page.waitForTimeout(250);
  expect(sent).toHaveLength(0);
});

test("attach and voice say they are unavailable and send nothing to the customer", async ({ page }) => {
  const { sent } = await boot(page);
  await page.getByTestId("composer-attach").click();
  await expect(page.getByTestId("composer-notice")).toContainText(/not available from the inbox yet|غير متاح بعد/);
  await page.getByTestId("composer-voice").click();
  await expect(page.getByTestId("composer-notice")).toBeVisible();
  await page.waitForTimeout(250);
  expect(sent).toHaveLength(0);
});

test("the emoji picker offers emoji only, with no sticker tab, and inserts into the text", async ({ page }) => {
  await boot(page);
  await page.getByTestId("composer-emoji").click();
  const picker = page.getByRole("dialog", { name: /Emoji|الرموز/ });
  await expect(picker).toBeVisible();
  await expect(picker.getByRole("button", { name: /Stickers|ملصقات/ })).toHaveCount(0);
  await picker.locator("button").filter({ hasText: /^😀$/ }).first().click();
  await expect(page.getByTestId("composer-input")).toHaveValue(/😀/);
});

test("once the 24-hour window has closed the bar says why instead of offering a field", async ({ page }) => {
  await boot(page, { lastCustomerMessageAt: hoursAgo(30) });
  await expect(page.getByTestId("composer-closed")).toContainText(/approved template is required|قالب معتمد/);
  await expect(page.getByTestId("composer-input")).toHaveCount(0);
});
