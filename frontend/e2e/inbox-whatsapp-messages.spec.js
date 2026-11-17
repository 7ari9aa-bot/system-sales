import { expect, test } from "@playwright/test";

// Each kind of WhatsApp message, rendered from what the API really sends.
const ORIGIN = process.env.BASE_URL || "http://127.0.0.1:4173";
const NOW = Date.now();
const at = (min) => new Date(NOW - min * 60000).toISOString();

const MESSAGES = [
  { id: "m1", direction: "inbound", sender_type: "customer", content_type: "location", body: "📍 Cairo Tower, Gezira, Cairo", status: "delivered", created_at: at(60) },
  { id: "m2", direction: "inbound", sender_type: "customer", content_type: "contact", body: "Ali Hassan +20 100 123 4567", status: "delivered", created_at: at(55) },
  { id: "m3", direction: "inbound", sender_type: "customer", content_type: "file", media_type: "document", media_url: "https://files.example.com/a/Invoice%20May.pdf", body: null, status: "delivered", created_at: at(50) },
  { id: "m4", direction: "inbound", sender_type: "customer", content_type: "buttons", body: "Yes, confirm", status: "delivered", created_at: at(45) },
  { id: "m5", direction: "inbound", sender_type: "customer", content_type: "list", body: "Size M", status: "delivered", created_at: at(40) },
  { id: "m6", direction: "inbound", sender_type: "customer", content_type: "unsupported", body: '{"type":"order","order":{"catalog_id":"SECRET-RAW"}}', status: "delivered", created_at: at(35) },
  { id: "m7", direction: "inbound", sender_type: "customer", content_type: "video", media_type: "video", media_url: "https://files.example.com/v/clip.mp4", body: "the product", status: "delivered", created_at: at(30) },
  { id: "m8", direction: "inbound", sender_type: "customer", content_type: "image", media_type: "sticker", media_url: "https://files.example.com/s/happy.webp", body: null, status: "delivered", created_at: at(25) },
  { id: "m9", direction: "inbound", sender_type: "customer", content_type: "image", media_type: "image", media_url: "https://files.example.com/expired/photo.jpg", body: "my order", status: "delivered", created_at: at(20) },
  { id: "m10", direction: "inbound", sender_type: "customer", content_type: "text", body: "plain text", status: "delivered", created_at: at(5) },
];

async function boot(page) {
  const row = { id: "c1", channel: "whatsapp", status: "open", customer_id: "cust-1", customer_name: "Sara", customer_phone: "201001234567", unread_count: 0, assignee_user_id: null, last_message_at: at(5), last_customer_message_at: at(5), last_message_preview: "plain text", last_message_content_type: "text", pinned_at: null, muted_until: null, archived_at: null, marked_unread: false };
  await page.context().addCookies([{ name: "csrf_token", value: "ui-test", url: new URL(ORIGIN).origin }]);
  // Every media URL fails to load: a photo link from the customer has expired.
  await page.route("https://files.example.com/**", (route) => route.abort());
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const send = (data) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(data) });
    if (url.pathname === "/api/v1/auth/me") return send({ id: "u", email: "m@example.com", full_name: "M", is_platform_admin: false, tenants: [{ id: "t", name: "Shop", slug: "shop", role_code: "owner" }] });
    if (url.pathname === "/api/v1/inbox") return send({ items: url.searchParams.get("archived") === "true" ? [] : [row], next_cursor: null });
    if (url.pathname === "/api/v1/conversations/c1/messages") return send({ items: MESSAGES, next_cursor: null });
    return send({ items: [], next_cursor: null });
  });
  await page.goto("/inbox", { waitUntil: "domcontentloaded", timeout: 30_000 });
  await expect(page.getByTestId("chat-header")).toBeVisible();
  await expect(page.getByTestId("whatsapp-bubble").filter({ hasText: "plain text" })).toBeVisible();
}

test("a location shows its place and address", async ({ page }) => {
  await boot(page);
  const loc = page.getByTestId("location");
  await expect(loc).toContainText("Cairo Tower");
  await expect(loc).toContainText("Gezira, Cairo");
});

test("a shared contact shows the name and number", async ({ page }) => {
  await boot(page);
  const card = page.getByTestId("contact-card");
  await expect(card).toContainText("Ali Hassan");
  await expect(card).toContainText("+20 100 123 4567");
});

test("a document shows its file name and a download link that opens safely", async ({ page }) => {
  await boot(page);
  const doc = page.getByTestId("document");
  await expect(doc).toContainText("Invoice May.pdf");
  await expect(doc).toContainText("PDF");
  const link = page.getByTestId("document-download");
  await expect(link).toHaveAttribute("href", "https://files.example.com/a/Invoice%20May.pdf");
  await expect(link).toHaveAttribute("rel", /noopener/);
  await expect(link).toHaveAttribute("target", "_blank");
});

test("a button tap and a list choice show the customer's choice, labelled", async ({ page }) => {
  await boot(page);
  await expect(page.getByTestId("button-reply")).toContainText("Yes, confirm");
  await expect(page.getByTestId("list-reply")).toContainText("Size M");
});

test("an unsupported type says so and never shows the raw provider data", async ({ page }) => {
  await boot(page);
  await expect(page.getByTestId("unsupported")).toContainText(/not supported|غير مدعومة/);
  await expect(page.getByText("SECRET-RAW")).toHaveCount(0);
  await expect(page.getByText("catalog_id")).toHaveCount(0);
});

test("a video does not load until it is tapped, and keeps its caption", async ({ page }) => {
  await boot(page);
  await expect(page.getByTestId("play-video")).toBeVisible();
  await expect(page.getByTestId("video")).toHaveCount(0);
  await expect(page.getByText("the product")).toBeVisible();
});

test("a sticker is shown as a bare image", async ({ page }) => {
  await boot(page);
  // The sticker URL is blocked in this test, so it falls back to its label.
  await expect(page.getByTestId("media-failed").filter({ hasText: /Sticker|ملصق/ })).toBeVisible();
});

test("a photo whose link has expired says so instead of a broken image, and keeps its caption", async ({ page }) => {
  await boot(page);
  await expect(page.getByTestId("media-failed").filter({ hasText: /Could not load the photo|تعذّر تحميل الصورة/ })).toBeVisible();
  await expect(page.getByText("my order")).toBeVisible();
});
