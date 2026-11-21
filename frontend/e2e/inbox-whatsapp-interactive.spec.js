import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";

// Buttons, a list and a link button in the inbox: shown from what the SERVER returns, and composed
// and sent from a dialog, over mocked HTTP. The messages are the server's real output.
const ORIGIN = process.env.BASE_URL || "http://127.0.0.1:4173";
const at = (m) => new Date(Date.now() - m * 60_000).toISOString();
const SERVER = JSON.parse(readFileSync(new URL("../src/components/inbox/whatsapp/__fixtures__/interactive_server.json", import.meta.url), "utf8"));
const out = (id, name, minutes) => ({ id, direction: "outbound", sender_type: "agent", content_type: "interactive", body: name, status: "delivered", created_at: at(minutes), interactive: SERVER[name].server });
const MESSAGES = [
  { id: "m0", direction: "inbound", sender_type: "customer", content_type: "text", body: "hello", status: "delivered", created_at: at(30) },
  out("m1", "buttons_full", 20),
  out("m2", "list_full", 15),
  out("m3", "cta", 10),
  // An old row whose spec no longer passes: the server sends no spec, so it is plain text.
  { id: "m4", direction: "outbound", sender_type: "agent", content_type: "interactive", body: "plain fallback", status: "delivered", created_at: at(5), interactive: null },
];

async function boot(page, { lastCustomerMessageAt = at(5), sendStatus = 201, sendError = "" } = {}) {
  const sent = [];
  const row = { id: "c1", channel: "whatsapp", status: "open", customer_id: "cust-1", customer_name: "Sara", customer_phone: "201001234567", unread_count: 0, assignee_user_id: null, last_message_at: at(5), last_customer_message_at: lastCustomerMessageAt, last_message_preview: "x", tags: [], is_pinned: false, is_muted: false, is_archived: false };
  await page.context().addCookies([{ name: "csrf_token", value: "ui-test", url: new URL(ORIGIN).origin }]);
  await page.route("**/api/v1/**", async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const send = (data, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(data) });
    if (url.pathname === "/api/v1/auth/me") return send({ id: "u", email: "m@example.com", full_name: "M", is_platform_admin: false, tenants: [{ id: "t", name: "Shop", slug: "shop", role_code: "owner" }] });
    if (url.pathname === "/api/v1/inbox") return send({ items: url.searchParams.get("archived") === "true" ? [] : [row], next_cursor: null });
    if (url.pathname === "/api/v1/conversations/c1/messages" && req.method() === "POST") {
      sent.push(req.postDataJSON());
      if (sendStatus !== 201) return send({ error: { code: "validation_error", message: sendError } }, sendStatus);
      return send({ id: `n${sent.length}`, status: "queued", created_at: new Date().toISOString() }, 201);
    }
    if (url.pathname === "/api/v1/conversations/c1/messages") return send({ items: MESSAGES, next_cursor: null });
    return send({ items: [], next_cursor: null });
  });
  await page.goto("/inbox", { waitUntil: "domcontentloaded", timeout: 30_000 });
  await expect(page.getByTestId("chat-header")).toBeVisible();
  return { sent };
}

test("what we sent is drawn as real buttons, a list and a link, in order", async ({ page }) => {
  await boot(page);
  await expect(page.getByTestId("interactive-button")).toBeVisible();
  const buttons = page.getByTestId("interactive-button");
  await expect(buttons.getByTestId("interactive-choice")).toHaveText(["تأكيد", "إلغاء"]);
  await expect(buttons).toContainText("Order #7");
  await expect(buttons).toContainText("شكرًا");
  const link = page.getByTestId("interactive-link");
  await expect(link).toHaveAttribute("href", "https://fihrist.world/o/1?a=1&b=2");
  await expect(link).toHaveAttribute("target", "_blank");
});

test("a list's rows are really hidden until opened, then really visible", async ({ page }) => {
  await boot(page);
  const rows = page.getByTestId("interactive-row");
  await expect(rows.first()).toBeHidden();
  await page.getByTestId("interactive-list").locator("summary").click();
  await expect(rows).toHaveCount(3);
  await expect(rows.first()).toBeVisible();
  await expect(page.getByTestId("interactive-list").first()).toContainText("يوم");
});

test("a message whose spec is gone shows its text, not an empty bubble", async ({ page }) => {
  await boot(page);
  await expect(page.getByText("plain fallback")).toBeVisible();
});

test("the reply buttons are not clickable and send nothing", async ({ page }) => {
  const { sent } = await boot(page);
  await page.getByTestId("interactive-button").getByTestId("interactive-choice").first().click({ force: true });
  expect(sent).toHaveLength(0);
});

test("compose reply buttons: wrong fields say why, then the exact request reaches the server", async ({ page }) => {
  const { sent } = await boot(page);
  await page.getByTestId("composer-attach").click();
  await page.getByTestId("attach-interactive").click();
  await expect(page.getByTestId("interactive-composer")).toBeVisible();

  await page.getByTestId("interactive-send").click();
  await expect(page.getByTestId("err-body")).toHaveText(/Required|مطلوب/);
  await expect(page.getByTestId("err-buttons.0.title")).toBeVisible();
  expect(sent).toHaveLength(0);

  await page.getByTestId("f-body").fill("Confirm your order?");
  await page.getByTestId("f-button-0").fill("Yes");
  await page.getByTestId("add-button").click();
  await page.getByTestId("f-button-1").fill("No");
  await expect(page.getByTestId("interactive-preview")).toContainText("Confirm your order?");
  await expect(page.getByTestId("interactive-preview").getByTestId("interactive-choice")).toHaveText(["Yes", "No"]);

  await page.getByTestId("interactive-send").click();
  await expect(page.getByTestId("interactive-composer")).toBeHidden();
  expect(sent).toEqual([{ interactive: { kind: "buttons", body: "Confirm your order?", buttons: [{ id: "btn_1", title: "Yes" }, { id: "btn_2", title: "No" }] } }]);
  // It shows at once, before any reload.
  await expect(page.getByTestId("interactive-button").last()).toContainText("Confirm your order?");
});

test("every Add button stops exactly at its limit", async ({ page }) => {
  await boot(page);
  await page.getByTestId("composer-attach").click();
  await page.getByTestId("attach-interactive").click();
  await page.getByTestId("add-button").click();
  await page.getByTestId("add-button").click();
  await expect(page.getByTestId("add-button")).toBeDisabled();
  await page.getByTestId("kind-list").click();
  for (let i = 0; i < 9; i += 1) await page.getByTestId("add-row-0").click();
  await expect(page.getByTestId("add-row-0")).toBeDisabled();
  await expect(page.getByTestId("add-section")).toBeDisabled();
});

test("a list goes out with its sections and rows", async ({ page }) => {
  const { sent } = await boot(page);
  await page.getByTestId("composer-attach").click();
  await page.getByTestId("attach-interactive").click();
  await page.getByTestId("kind-list").click();
  await page.getByTestId("f-body").fill("Pick shipping");
  await page.getByTestId("f-list-button").fill("Options");
  await page.getByTestId("f-section-0").fill("Shipping");
  await page.getByTestId("f-row-0-0").fill("Express");
  await page.getByTestId("f-desc-0-0").fill("1 day");
  await page.getByTestId("interactive-send").click();
  await expect(page.getByTestId("interactive-composer")).toBeHidden();
  expect(sent[0].interactive).toEqual({ kind: "list", body: "Pick shipping", button: "Options", sections: [{ title: "Shipping", rows: [{ id: "row_1_1", title: "Express", description: "1 day" }] }] });
});

test("a link button refuses a bad address and sends a good one", async ({ page }) => {
  const { sent } = await boot(page);
  await page.getByTestId("composer-attach").click();
  await page.getByTestId("attach-interactive").click();
  await page.getByTestId("kind-cta_url").click();
  await page.getByTestId("f-body").fill("Track it");
  await page.getByTestId("f-label").fill("Track");
  await page.getByTestId("f-url").fill("javascript:alert(1)");
  await page.getByTestId("interactive-send").click();
  await expect(page.getByTestId("err-url")).toBeVisible();
  expect(sent).toHaveLength(0);
  await page.getByTestId("f-url").fill("https://fihrist.world/o/9");
  await page.getByTestId("interactive-send").click();
  await expect(page.getByTestId("interactive-composer")).toBeHidden();
  expect(sent[0].interactive).toEqual({ kind: "cta_url", body: "Track it", label: "Track", url: "https://fihrist.world/o/9" });
});

test("when the server refuses, the dialog stays open, keeps the text and says why", async ({ page }) => {
  const { sent } = await boot(page, { sendStatus: 422, sendError: "Meta says no" });
  await page.getByTestId("composer-attach").click();
  await page.getByTestId("attach-interactive").click();
  await page.getByTestId("f-body").fill("Keep me");
  await page.getByTestId("f-button-0").fill("Ok");
  await page.getByTestId("interactive-send").click();
  await expect(page.getByTestId("interactive-send-error")).toHaveText("Meta says no");
  await expect(page.getByTestId("f-body")).toHaveValue("Keep me");
  expect(sent).toHaveLength(1);
});

test("Escape closes it and nothing is sent", async ({ page }) => {
  const { sent } = await boot(page);
  await page.getByTestId("composer-attach").click();
  await page.getByTestId("attach-interactive").click();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("interactive-composer")).toBeHidden();
  expect(sent).toHaveLength(0);
});

test("outside the 24-hour window there is no way in: only the template button", async ({ page }) => {
  await boot(page, { lastCustomerMessageAt: at(60 * 30) });
  await expect(page.getByTestId("composer-closed")).toBeVisible();
  await expect(page.getByTestId("composer-attach")).toHaveCount(0);
  await expect(page.getByTestId("attach-interactive")).toHaveCount(0);
});
