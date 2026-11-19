import { expect, test } from "@playwright/test";

const ORIGIN = process.env.BASE_URL || "http://127.0.0.1:4173";
const PNG = Buffer.from("89504e470d0a1a0a0000000d49484452", "hex");

async function open(page, calls, { mediaStatus = 201 } = {}) {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.context().addCookies([{ name: "csrf_token", value: "x", url: new URL(ORIGIN).origin }]);
  await page.route("**/api/v1/**", async (route) => {
    const req = route.request();
    const u = new URL(req.url());
    const p = u.pathname.replace("/api/v1", "");
    const send = (d, s = 200) => route.fulfill({ status: s, contentType: "application/json", body: JSON.stringify(d) });
    if (req.method() !== "GET") calls.push({ method: req.method(), path: p, body: req.postData() || "", type: req.headers()["content-type"] || "" });
    if (p === "/auth/me") return send({ id: "u", email: "o@s.com", full_name: "O", is_platform_admin: false, tenants: [{ id: "t", name: "T", role: "owner" }] });
    if (p === "/channels/status") return send([{ provider: "instagram", connected: true, enabled_for_me: true, locked: false, lifecycle: "connected", webhook_status: "active" }]);
    if (p === "/inbox") return send({ items: [{ id: "c1", channel: "instagram", status: "open", customer_id: "cu1", customer_name: "Sara Ahmed", last_message_at: new Date().toISOString(), last_customer_message_at: new Date().toISOString(), unread_count: 0, last_message_preview: "hi" }], next_cursor: null });
    if (p === "/conversations/c1/messages" && req.method() === "GET") return send({ items: [], next_cursor: null });
    if (p === "/conversations/c1/messages") return send({ id: "m9", status: "queued" }, 201);
    if (p === "/conversations/c1/media") {
      if (mediaStatus !== 201) return send({ error: { code: "validation_error", message: "a image is at most 8 MB on Instagram; this one is 9.0 MB" } }, mediaStatus);
      return send({ media_id: "med-1", kind: "image", content_type: "image/png", size: 16, filename: "shoes.png" }, 201);
    }
    if (p === "/ai/agents") return send([]);
    return send({ items: [], next_cursor: null });
  });
  await page.goto("/instagram/direct/inbox", { waitUntil: "domcontentloaded", timeout: 30_000 });
  await page.getByText("Sara Ahmed").first().click();
}

const pick = (page, file) => page.getByTestId("ig-chat-file-input").setInputFiles(file);

test("a picked picture is uploaded, then sent by its media id with no text beside it", async ({ page }) => {
  const calls = [];
  await open(page, calls);
  await pick(page, { name: "shoes.png", mimeType: "image/png", buffer: PNG });
  await expect(page.getByTestId("ig-attach-preview")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId("ig-preview-image")).toBeVisible();
  // looking at the preview sends nothing yet
  expect(calls.filter((c) => c.path.endsWith("/media") || c.path.endsWith("/messages"))).toHaveLength(0);
  await page.getByTestId("ig-attach-send").click();
  await expect(page.getByTestId("ig-attach-preview")).toHaveCount(0, { timeout: 10_000 });
  const upload = calls.find((c) => c.path === "/conversations/c1/media");
  expect(upload.type).toBe("image/png");
  const sent = calls.find((c) => c.path === "/conversations/c1/messages");
  const body = JSON.parse(sent.body);
  expect(body.media_id).toBe("med-1");
  expect(body.body ?? "").toBe(""); // Instagram cannot carry text beside a file
  expect(sent.body).not.toContain("shoes.png"); // the old bug: the file NAME went out as text
});

test("a file Instagram refuses is stopped in the browser, nothing is uploaded", async ({ page }) => {
  const calls = [];
  await open(page, calls);
  await pick(page, { name: "sticker.webp", mimeType: "image/webp", buffer: Buffer.from("RIFF0000WEBP") });
  await expect(page.getByTestId("ig-attach-pick-error")).toContainText("JPG and PNG", { timeout: 10_000 });
  await expect(page.getByTestId("ig-attach-preview")).toHaveCount(0);
  await pick(page, { name: "report.docx", mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document", buffer: Buffer.from("PK") });
  await expect(page.getByTestId("ig-attach-pick-error")).toBeVisible();
  expect(calls.filter((c) => c.path.endsWith("/media"))).toHaveLength(0);
});

test("a picture over 8 MB is refused here, a PDF of the same size is allowed", async ({ page }) => {
  const calls = [];
  await open(page, calls);
  await pick(page, { name: "big.jpg", mimeType: "image/jpeg", buffer: Buffer.alloc(8 * 1024 * 1024 + 1, 1) });
  await expect(page.getByTestId("ig-attach-pick-error")).toContainText("8 MB", { timeout: 10_000 });
  await pick(page, { name: "menu.pdf", mimeType: "application/pdf", buffer: Buffer.alloc(9 * 1024 * 1024, 1) });
  await expect(page.getByTestId("ig-attach-preview")).toBeVisible();
  await expect(page.getByTestId("ig-preview-file")).toContainText("menu.pdf");
});

test("when the server refuses the upload, its reason is shown and nothing is sent", async ({ page }) => {
  const calls = [];
  await open(page, calls, { mediaStatus: 422 });
  await pick(page, { name: "shoes.png", mimeType: "image/png", buffer: PNG });
  await page.getByTestId("ig-attach-send").click();
  await expect(page.getByTestId("ig-attach-error")).toContainText("8 MB", { timeout: 10_000 });
  await expect(page.getByTestId("ig-attach-preview")).toBeVisible(); // kept, so the agent can cancel or retry
  expect(calls.filter((c) => c.path.endsWith("/messages"))).toHaveLength(0);
});

test("cancelling the preview uploads and sends nothing", async ({ page }) => {
  const calls = [];
  await open(page, calls);
  await pick(page, { name: "shoes.png", mimeType: "image/png", buffer: PNG });
  await page.getByTestId("ig-attach-cancel").click();
  await expect(page.getByTestId("ig-attach-preview")).toHaveCount(0);
  expect(calls.filter((c) => c.path.endsWith("/media") || c.path.endsWith("/messages"))).toHaveLength(0);
});

test("the photo button no longer opens the old menu with its dead Contact and Poll rows", async ({ page }) => {
  const calls = [];
  await open(page, calls);
  await page.getByRole("button", { name: "Media attachment" }).click({ trial: true });
  await expect(page.getByRole("menu")).toHaveCount(0);
  await expect(page.getByText("Poll", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Contact", { exact: true })).toHaveCount(0);
});

test("Messenger's attachment menu keeps its real rows and no longer sends a made-up contact or poll", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.context().addCookies([{ name: "csrf_token", value: "x", url: new URL(ORIGIN).origin }]);
  const sent = [];
  await page.route("**/api/v1/**", async (route) => {
    const req = route.request();
    const p = new URL(req.url()).pathname.replace("/api/v1", "");
    const send = (d, s = 200) => route.fulfill({ status: s, contentType: "application/json", body: JSON.stringify(d) });
    if (req.method() === "POST" && p.endsWith("/messages")) sent.push(req.postData());
    if (p === "/auth/me") return send({ id: "u", email: "o@s.com", full_name: "O", is_platform_admin: false, tenants: [{ id: "t", name: "T", role: "owner" }] });
    if (p === "/channels/status") return send([{ provider: "messenger", connected: true, enabled_for_me: true, locked: false, lifecycle: "connected", webhook_status: "active" }]);
    if (p === "/inbox") return send({ items: [{ id: "c2", channel: "messenger", status: "open", customer_id: "cu2", customer_name: "Omar Ali", last_message_at: new Date().toISOString(), last_customer_message_at: new Date().toISOString(), unread_count: 0, last_message_preview: "hi" }], next_cursor: null });
    if (p === "/conversations/c2/messages" && req.method() === "GET") return send({ items: [], next_cursor: null });
    if (p === "/ai/agents") return send([]);
    return send({ items: [], next_cursor: null });
  });
  await page.goto("/inbox", { waitUntil: "domcontentloaded", timeout: 30_000 });
  await page.getByText("Omar Ali").first().click();
  await page.getByTitle(/Attach media|إرفاق ملف أو صورة/).click();
  const menu = page.getByRole("menu");
  await expect(menu.getByText("Document")).toBeVisible({ timeout: 10_000 });
  await expect(menu.getByText("Photos & videos")).toBeVisible();
  await expect(menu.getByText("Camera")).toBeVisible();
  await expect(menu.getByText("Contact", { exact: true })).toHaveCount(0);
  await expect(menu.getByText("Poll", { exact: true })).toHaveCount(0);
  expect(sent).toHaveLength(0);
});
