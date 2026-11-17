import { expect, test } from "@playwright/test";

// Measured fidelity to WhatsApp Web. These are the things a screenshot hides: a panel
// quietly inheriting the app's font or brown ink, a 1px gap above the header, or the
// list stopping short of the bottom. Each was found by measuring the real page.
const ORIGIN = process.env.BASE_URL || "http://127.0.0.1:4173";
const now = () => new Date().toISOString();

async function boot(page, theme, size) {
  await page.setViewportSize(size);
  const row = { id: "c1", channel: "whatsapp", status: "open", customer_id: "cu1", customer_name: "Sara", customer_phone: "201001234560", unread_count: 0, last_message_at: now(), last_customer_message_at: now(), last_message_preview: "x", last_message_content_type: "text", pinned_at: null, muted_until: null, archived_at: null, marked_unread: false };
  await page.context().addCookies([{ name: "csrf_token", value: "x", url: new URL(ORIGIN).origin }]);
  await page.addInitScript((t) => localStorage.setItem("salesos.theme", t), theme);
  await page.route("**/api/v1/**", async (route) => {
    const u = new URL(route.request().url());
    const send = (d) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(d) });
    if (u.pathname === "/api/v1/auth/me") return send({ id: "u", email: "m@e.com", full_name: "M", is_platform_admin: false, tenants: [{ id: "t", name: "Shop", slug: "shop", role_code: "owner" }] });
    if (u.pathname === "/api/v1/channels/status") return send([{ provider: "whatsapp", connected: true, enabled_for_me: true, locked: false, lifecycle: "connected", webhook_status: "active", account_name: "Shop" }]);
    if (u.pathname === "/api/v1/inbox") return send({ items: [row], next_cursor: null });
    if (u.pathname.endsWith("/messages")) return send({ items: [{ id: "m1", direction: "inbound", body: "مرحبا", content_type: "text", status: "received", created_at: now(), reactions: [] }], next_cursor: null });
    return send({ items: [], next_cursor: null });
  });
  await page.goto("/inbox", { waitUntil: "domcontentloaded", timeout: 30_000 });
  await expect(page.getByTestId("chat-list")).toBeVisible();
  await page.getByText("Sara").first().click();
  await expect(page.getByTestId("chat-header")).toBeVisible();
  // let /channels/status land, so the "connect a channel" hint is judged in its settled state
  await page.waitForResponse((r) => r.url().includes("/channels/status")).catch(() => {});
  await page.waitForTimeout(300);
}

const style = (page, id) => page.getByTestId(id).evaluate((el) => { const c = getComputedStyle(el); const b = el.getBoundingClientRect(); return { font: c.fontFamily, color: c.color, y: Math.round(b.y), bottom: Math.round(b.bottom) }; });

for (const theme of ["light", "dark"]) {
  test(`${theme}: the list, header and input all use WhatsApp's own font and ink`, async ({ page }) => {
    await boot(page, theme, { width: 1280, height: 780 });
    const ink = theme === "light" ? "rgb(17, 27, 33)" : "rgb(233, 237, 239)";
    for (const id of ["chat-list", "chat-header", "composer-input"]) {
      const s = await style(page, id);
      expect(s.font, `${id} font`).toContain("Segoe UI");
      expect(s.color, `${id} ink`).toBe(ink);
    }
  });
}

test("the header sits on the very top edge, with no 1px gap above it", async ({ page }) => {
  await boot(page, "light", { width: 1280, height: 780 });
  expect((await style(page, "chat-header")).y).toBe(0);
  expect((await style(page, "chat-list")).y).toBe(0);
});

test("with the channel connected, the list runs to the bottom of the screen", async ({ page }) => {
  await boot(page, "light", { width: 1280, height: 780 });
  expect((await style(page, "chat-list")).bottom).toBe(780);
});


