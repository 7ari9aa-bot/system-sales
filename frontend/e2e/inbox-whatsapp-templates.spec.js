import { expect, test } from "@playwright/test";

// Sending a WhatsApp template from the inbox (the only message possible after the 24-hour window), over mocked HTTP.
const ORIGIN = process.env.BASE_URL || "http://127.0.0.1:4173";
const hoursAgo = (h) => new Date(Date.now() - h * 3600_000).toISOString();

const ORDER = {
  id: "t1", name: "order_ready", language: "en", provider: "whatsapp", status: "approved", category: "UTILITY", meta_managed: true,
  body_text: "Hi {{1}}, order {{2}} is ready",
  components: [
    { type: "HEADER", format: "TEXT", text: "Order {{1}}" },
    { type: "BODY", text: "Hi {{1}}, order {{2}} is ready" },
    { type: "FOOTER", text: "Thanks for shopping" },
    { type: "BUTTONS", buttons: [{ type: "QUICK_REPLY", text: "Got it" }, { type: "URL", text: "Track", url: "https://shop.example/t/{{1}}" }] },
  ],
};
const HELLO = { id: "t2", name: "hello_plain", language: "ar", provider: "whatsapp", status: "approved", body_text: "أهلا بك", components: [{ type: "BODY", text: "أهلا بك" }] };
const PROMO = { id: "t3", name: "promo_image", language: "en", provider: "whatsapp", status: "approved", body_text: "Sale!", components: [{ type: "HEADER", format: "IMAGE" }, { type: "BODY", text: "Sale!" }] };

async function boot(page, { lastCustomerMessageAt = hoursAgo(30), templates = [ORDER, HELLO, PROMO], templatesFail = 0, sendStatus = 201, sendError = "" } = {}) {
  const sent = [];
  const loads = [];
  let failures = templatesFail;
  const row = { id: "c1", channel: "whatsapp", status: "open", customer_id: "cust-1", customer_name: "Sara", customer_phone: "201001234567", unread_count: 0, assignee_user_id: null, last_message_at: new Date().toISOString(), last_customer_message_at: lastCustomerMessageAt, last_message_preview: "hi", last_message_content_type: "text", pinned_at: null, muted_until: null, archived_at: null, marked_unread: false };
  await page.context().addCookies([{ name: "csrf_token", value: "ui-test", url: new URL(ORIGIN).origin }]);
  await page.route("**/api/v1/**", async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const send = (data, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(data) });
    if (url.pathname === "/api/v1/auth/me") return send({ id: "u", email: "m@example.com", full_name: "M", is_platform_admin: false, tenants: [{ id: "t", name: "Shop", role: "owner" }] });
    if (url.pathname === "/api/v1/inbox") return send({ items: url.searchParams.get("archived") === "true" ? [] : [row], next_cursor: null });
    if (url.pathname === "/api/v1/message-templates" && req.method() === "GET") {
      loads.push(url.search);
      if (failures > 0) { failures -= 1; return send({ error: { code: "internal", message: "boom" } }, 500); }
      return send({ items: templates });
    }
    if (url.pathname === "/api/v1/conversations/c1/messages" && req.method() === "POST") {
      sent.push(req.postDataJSON());
      if (sendStatus !== 201) return send({ error: { code: "validation_error", message: sendError } }, sendStatus);
      return send({ id: `m${sent.length}`, status: "queued", created_at: new Date().toISOString() }, 201);
    }
    return send({ items: [], next_cursor: null });
  });
  await page.goto("/inbox", { waitUntil: "domcontentloaded", timeout: 30_000 });
  await expect(page.getByTestId("chat-header")).toBeVisible();
  return { sent, loads };
}

test("after the window closes the bar offers a way out: send a template", async ({ page }) => {
  await boot(page);
  await expect(page.getByTestId("composer-closed")).toBeVisible();
  await expect(page.getByTestId("composer-send-template")).toBeVisible();
});

test("fill a template, see it rendered, and the exact request reaches the server", async ({ page }) => {
  const { sent, loads } = await boot(page);
  await page.getByTestId("composer-send-template").click();
  await expect(page.getByTestId("template-picker")).toBeVisible();
  expect(loads[0]).toContain("status=approved");
  expect(loads[0]).toContain("provider=whatsapp");

  await page.getByTestId("template-option-order_ready").click();
  await page.getByTestId("template-header-1").fill("#7");
  await page.getByTestId("template-body-1").fill("Ali");
  await page.getByTestId("template-body-2").fill("7");
  await page.getByTestId("template-button-1").fill("7");
  await expect(page.getByTestId("template-preview")).toHaveText("Hi Ali, order 7 is ready");

  await page.getByTestId("template-send").click();
  await expect.poll(() => sent.length).toBe(1);
  expect(sent[0]).toEqual({
    template_name: "order_ready",
    template_language: "en",
    template_vars: {
      header_params: ["#7"],
      body_params: ["Ali", "7"],
      button_params: [{ index: 0, type: "quick_reply", payload: "Got it" }, { index: 1, type: "url", text: "7" }],
    },
  });
  await expect(page.getByTestId("template-picker")).toHaveCount(0);
  // the customer's bubble shows the filled text at once
  await expect(page.getByText("Hi Ali, order 7 is ready").first()).toBeVisible();
});

test("nothing is sent while a field is empty, and each empty field says so", async ({ page }) => {
  const { sent } = await boot(page);
  await page.getByTestId("composer-send-template").click();
  await page.getByTestId("template-option-order_ready").click();
  await page.getByTestId("template-body-1").fill("Ali");
  await page.getByTestId("template-send").click();
  await expect(page.getByTestId("template-picker").getByRole("alert").first()).toBeVisible();
  await page.waitForTimeout(250);
  expect(sent).toHaveLength(0);
  await expect(page.getByTestId("template-send")).toBeDisabled();
});

test("a template with nothing to fill sends in one tap, in its own language", async ({ page }) => {
  const { sent } = await boot(page);
  await page.getByTestId("composer-send-template").click();
  await page.getByTestId("template-option-hello_plain").click();
  await page.getByTestId("template-send").click();
  await expect.poll(() => sent.length).toBe(1);
  expect(sent[0]).toEqual({ template_name: "hello_plain", template_vars: {}, template_language: "ar" });
});

test("a media header needs an https link and goes out as header_media", async ({ page }) => {
  const { sent } = await boot(page);
  await page.getByTestId("composer-send-template").click();
  await page.getByTestId("template-option-promo_image").click();
  await page.getByTestId("template-header-media").fill("http://insecure.example/a.png");
  await page.getByTestId("template-send").click();
  await expect(page.getByTestId("template-picker").getByRole("alert").first()).toBeVisible();
  expect(sent).toHaveLength(0);
  await page.getByTestId("template-header-media").fill("https://cdn.example/a.png");
  await expect(page.getByTestId("template-send")).toBeEnabled();
  await page.getByTestId("template-send").click();
  await expect.poll(() => sent.length).toBe(1);
  expect(sent[0].template_vars).toEqual({ header_media: { type: "image", link: "https://cdn.example/a.png" } });
});

test("a refusal from the server keeps the dialog open with what was typed", async ({ page }) => {
  const { sent } = await boot(page, { sendStatus: 422, sendError: "template is not approved in this language" });
  await page.getByTestId("composer-send-template").click();
  await page.getByTestId("template-option-order_ready").click();
  await page.getByTestId("template-header-1").fill("#7");
  await page.getByTestId("template-body-1").fill("Ali");
  await page.getByTestId("template-body-2").fill("7");
  await page.getByTestId("template-button-1").fill("7");
  await page.getByTestId("template-send").click();
  await expect.poll(() => sent.length).toBe(1);
  await expect(page.getByTestId("template-picker")).toBeVisible();
  await expect(page.getByTestId("template-body-1")).toHaveValue("Ali");
  await expect(page.getByText("template is not approved in this language")).toBeVisible();
});

test("a failed load says so and retry works", async ({ page }) => {
  await boot(page, { templatesFail: 1 });
  await page.getByTestId("composer-send-template").click();
  await expect(page.getByTestId("template-error")).toBeVisible();
  await page.getByTestId("template-retry").click();
  await expect(page.getByTestId("template-option-order_ready")).toBeVisible();
});

test("no approved template: the dialog explains instead of showing an empty list", async ({ page }) => {
  await boot(page, { templates: [] });
  await page.getByTestId("composer-send-template").click();
  await expect(page.getByTestId("template-empty")).toBeVisible();
});

test("only approved WhatsApp templates are offered, and search narrows them", async ({ page }) => {
  await boot(page, { templates: [ORDER, { ...HELLO, id: "x", name: "draft_one", status: "draft" }, { ...HELLO, id: "y", name: "sms_one", provider: "sms" }, HELLO] });
  await page.getByTestId("composer-send-template").click();
  await expect(page.getByTestId("template-option-order_ready")).toBeVisible();
  await expect(page.getByTestId("template-option-draft_one")).toHaveCount(0);
  await expect(page.getByTestId("template-option-sms_one")).toHaveCount(0);
  await page.getByTestId("template-search").fill("hello");
  await expect(page.getByTestId("template-option-order_ready")).toHaveCount(0);
  await expect(page.getByTestId("template-option-hello_plain")).toBeVisible();
  await page.getByTestId("template-search").fill("zzz");
  await expect(page.getByTestId("template-no-match")).toBeVisible();
});

test("Escape closes the dialog and sends nothing", async ({ page }) => {
  const { sent } = await boot(page);
  await page.getByTestId("composer-send-template").click();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("template-picker")).toHaveCount(0);
  expect(sent).toHaveLength(0);
});

test("while the window is open a template can still be sent from the + menu", async ({ page }) => {
  const { sent } = await boot(page, { lastCustomerMessageAt: hoursAgo(1) });
  await expect(page.getByTestId("composer-closed")).toHaveCount(0);
  await page.getByTestId("composer-attach").click();
  await page.getByTestId("attach-template").click();
  await page.getByTestId("template-option-hello_plain").click();
  await page.getByTestId("template-send").click();
  await expect.poll(() => sent.length).toBe(1);
  expect(sent[0].template_name).toBe("hello_plain");
});
