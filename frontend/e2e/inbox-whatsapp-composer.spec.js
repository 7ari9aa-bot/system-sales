import { expect, test } from "@playwright/test";

// The WhatsApp input bar over mocked HTTP.
const ORIGIN = process.env.BASE_URL || "http://127.0.0.1:4173";
const hoursAgo = (h) => new Date(Date.now() - h * 3600_000).toISOString();

async function boot(page, { lastCustomerMessageAt = hoursAgo(1), uploadStatus = 201, uploadError = "" } = {}) {
  const sent = [];
  const uploads = [];
  const row = { id: "c1", channel: "whatsapp", status: "open", customer_id: "cust-1", customer_name: "Sara", customer_phone: "201001234567", unread_count: 0, assignee_user_id: null, last_message_at: new Date().toISOString(), last_customer_message_at: lastCustomerMessageAt, last_message_preview: "hi", last_message_content_type: "text", pinned_at: null, muted_until: null, archived_at: null, marked_unread: false };
  await page.context().addCookies([{ name: "csrf_token", value: "ui-test", url: new URL(ORIGIN).origin }]);
  await page.route("**/api/v1/**", async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const send = (data, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(data) });
    if (url.pathname === "/api/v1/auth/me") return send({ id: "u", email: "m@example.com", full_name: "M", is_platform_admin: false, tenants: [{ id: "t", name: "Shop", slug: "shop", role_code: "owner" }] });
    if (url.pathname === "/api/v1/inbox") return send({ items: url.searchParams.get("archived") === "true" ? [] : [row], next_cursor: null });
    if (url.pathname === "/api/v1/conversations/c1/media" && req.method() === "POST") {
      const h = req.headers();
      uploads.push({ type: h["content-type"], name: decodeURIComponent(h["x-filename"] || ""), sticker: h["x-as-sticker"], size: req.postDataBuffer()?.length || 0 });
      if (uploadStatus !== 201) return send({ error: { code: "validation_error", message: uploadError } }, uploadStatus);
      const ct = h["content-type"] || "";
      const kind = /pdf|word|sheet/.test(ct) ? "document" : ct.startsWith("audio") ? "audio" : ct.startsWith("video") ? "video" : h["x-as-sticker"] ? "sticker" : "image";
      return send({ media_id: `media-${uploads.length}`, kind, content_type: ct, size: 10, filename: uploads.at(-1).name }, 201);
    }
    if (url.pathname === "/api/v1/conversations/c1/messages" && req.method() === "POST") { sent.push(req.postDataJSON()); return send({ id: `m${sent.length}`, status: "queued", created_at: new Date().toISOString() }, 201); }
    return send({ items: [], next_cursor: null });
  });
  await page.goto("/inbox", { waitUntil: "domcontentloaded", timeout: 30_000 });
  await expect(page.getByTestId("chat-header")).toBeVisible();
  return { sent, uploads };
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

const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==", "base64");
const PDF = Buffer.from("%PDF-1.7\n" + "0".repeat(64));
const WEBP = Buffer.concat([Buffer.from("RIFF\0\0\0\0WEBP"), Buffer.alloc(40)]);

async function attach(page, which, file) {
  await page.getByTestId("composer-attach").click();
  await expect(page.getByTestId("attach-menu")).toBeVisible();
  await page.getByTestId(`attach-input-${which}`).setInputFiles(file);
}

test("the + menu offers document, photos and videos, and sticker", async ({ page }) => {
  await boot(page);
  await page.getByTestId("composer-attach").click();
  for (const id of ["attach-document", "attach-media", "attach-sticker"]) await expect(page.getByTestId(id)).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("attach-menu")).toHaveCount(0);
});

test("a photo is previewed first, then uploaded and sent with its caption", async ({ page }) => {
  const { sent, uploads } = await boot(page);
  await attach(page, "media", { name: "shop.png", mimeType: "image/png", buffer: PNG });
  await expect(page.getByTestId("preview-image")).toBeVisible();
  expect(uploads).toHaveLength(0); // nothing has left the browser yet
  expect(sent).toHaveLength(0);
  await page.getByTestId("attach-caption").fill("طلبك جاهز");
  await page.getByTestId("attach-send").click();
  await expect.poll(() => sent.length).toBe(1);
  expect(uploads).toEqual([{ type: "image/png", name: "shop.png", sticker: undefined, size: PNG.length }]);
  expect(sent[0]).toEqual({ body: "طلبك جاهز", media_id: "media-1" });
  await expect(page.getByTestId("attach-preview")).toHaveCount(0);
});

test("cancelling the preview uploads and sends nothing", async ({ page }) => {
  const { sent, uploads } = await boot(page);
  await attach(page, "media", { name: "shop.png", mimeType: "image/png", buffer: PNG });
  await page.getByTestId("attach-cancel").click();
  await expect(page.getByTestId("attach-preview")).toHaveCount(0);
  await page.waitForTimeout(250);
  expect(uploads).toHaveLength(0);
  expect(sent).toHaveLength(0);
});

test("a document shows its name, a caption is optional, and it lands in the chat as a document", async ({ page }) => {
  const { sent } = await boot(page);
  await attach(page, "document", { name: "فاتورة مايو.pdf", mimeType: "application/pdf", buffer: PDF });
  await expect(page.getByTestId("preview-document")).toContainText("فاتورة مايو.pdf");
  await page.getByTestId("attach-send").click();
  await expect.poll(() => sent.length).toBe(1);
  expect(sent[0]).toEqual({ media_id: "media-1" });
  await expect(page.getByTestId("document").first()).toContainText("فاتورة مايو.pdf");
});

test("a sticker is a WebP, sent without a caption", async ({ page }) => {
  const { sent, uploads } = await boot(page);
  await attach(page, "sticker", { name: "s.webp", mimeType: "image/webp", buffer: WEBP });
  await expect(page.getByTestId("preview-sticker")).toBeVisible();
  await expect(page.getByTestId("attach-caption")).toBeDisabled();
  await page.getByTestId("attach-send").click();
  await expect.poll(() => sent.length).toBe(1);
  expect(uploads[0].sticker).toBe("true");
  expect(sent[0]).toEqual({ media_id: "media-1" });
});

test("a file WhatsApp cannot carry is refused before any upload", async ({ page }) => {
  const { sent, uploads } = await boot(page);
  await attach(page, "document", { name: "archive.zip", mimeType: "application/zip", buffer: Buffer.from("PK\x03\x04") });
  await expect(page.getByTestId("attach-pick-error")).toContainText(/cannot be sent|لا يمكن إرساله/);
  await expect(page.getByTestId("attach-preview")).toHaveCount(0);
  expect(uploads).toHaveLength(0);
  expect(sent).toHaveLength(0);
});

test("a photo over WhatsApp's 5 MB limit is refused with the limit named", async ({ page }) => {
  const { uploads } = await boot(page);
  await attach(page, "media", { name: "big.png", mimeType: "image/png", buffer: Buffer.concat([PNG, Buffer.alloc(5 * 1024 * 1024)]) });
  await expect(page.getByTestId("attach-pick-error")).toContainText(/5 MB|5 ميجابايت/);
  expect(uploads).toHaveLength(0);
});

test("an upload the server refuses shows its reason and keeps the preview to retry", async ({ page }) => {
  const { sent } = await boot(page, { uploadStatus: 400, uploadError: "the file's content does not match its type" });
  await attach(page, "media", { name: "fake.png", mimeType: "image/png", buffer: PNG });
  await page.getByTestId("attach-send").click();
  await expect(page.getByTestId("attach-error")).toContainText("does not match its type");
  await expect(page.getByTestId("attach-preview")).toBeVisible();
  expect(sent).toHaveLength(0);
});

test("a caption over 1024 characters blocks sending", async ({ page }) => {
  await boot(page);
  await attach(page, "media", { name: "shop.png", mimeType: "image/png", buffer: PNG });
  await page.getByTestId("attach-caption").fill("x".repeat(1025));
  await expect(page.getByTestId("attach-caption-over")).toBeVisible();
  await expect(page.getByTestId("attach-send")).toBeDisabled();
});

test("a voice note is recorded, previewed and sent as audio", async ({ page, context }) => {
  // A real MediaRecorder fed by Chromium's fake microphone. Chromium records
  // mp4/aac, which WhatsApp accepts, so nothing here is faked but the microphone.
  await context.grantPermissions(["microphone"], { origin: new URL(ORIGIN).origin });
  const { sent, uploads } = await boot(page);
  await page.getByTestId("composer-voice").click();
  await expect(page.getByTestId("voice-recorder")).toBeVisible();
  await page.waitForTimeout(1500);
  await page.getByTestId("voice-stop").click();
  await expect(page.getByTestId("preview-audio")).toBeVisible();
  await expect(page.getByTestId("attach-caption")).toBeDisabled();
  await page.getByTestId("attach-send").click();
  await expect.poll(() => sent.length).toBe(1);
  expect(uploads[0].type).toMatch(/^audio\//);
  expect(uploads[0].type).toBe("audio/mp4");
  expect(uploads[0].name).toMatch(/^voice-\d+\.m4a$/);
  expect(sent[0]).toEqual({ media_id: "media-1" });
});

test("a recording cancelled mid-way sends nothing", async ({ page, context }) => {
  await context.grantPermissions(["microphone"], { origin: new URL(ORIGIN).origin });
  const { sent, uploads } = await boot(page);
  await page.getByTestId("composer-voice").click();
  await page.waitForTimeout(600);
  await page.getByTestId("voice-cancel").click();
  await expect(page.getByTestId("voice-recorder")).toHaveCount(0);
  await expect(page.getByTestId("composer-voice")).toBeVisible();
  expect(sent).toHaveLength(0);
  expect(uploads).toHaveLength(0);
});

test("a browser that cannot record in a WhatsApp format says so", async ({ page, context }) => {
  await context.grantPermissions(["microphone"], { origin: new URL(ORIGIN).origin });
  await page.addInitScript(`const real = window.MediaRecorder; window.MediaRecorder = class extends real { static isTypeSupported() { return false; } };`);
  await boot(page);
  await page.getByTestId("composer-voice").click();
  await expect(page.getByTestId("attach-pick-error")).toContainText(/cannot record|لا يسجّل/);
  await expect(page.getByTestId("voice-recorder")).toHaveCount(0);
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
