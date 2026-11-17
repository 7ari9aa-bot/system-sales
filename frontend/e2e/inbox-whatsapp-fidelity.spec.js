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



test("dark mode: nothing bright is painted anywhere in the inbox", async ({ page }) => {
  await boot(page, "dark", { width: 1280, height: 780 });
  const bright = await page.evaluate(() => {
    const out = [];
    for (const el of document.querySelectorAll("body *")) {
      const b = el.getBoundingClientRect();
      if (b.width < 6 || b.height < 6 || b.bottom < 0 || b.top > innerHeight) continue;
      const c = getComputedStyle(el).backgroundColor.match(/[\d.]+/g)?.map(Number);
      if (!c || (c[3] ?? 1) < 0.5) continue;
      if (c[0] > 150 && c[1] > 150 && c[2] > 150) out.push(`${el.tagName}[${el.dataset.testid || ""}] rgb(${c[0]},${c[1]},${c[2]})`);
    }
    return out;
  });
  expect(bright).toEqual([]);
});

test("the WhatsApp avatar is the grey person disc, in both themes", async ({ page }) => {
  for (const theme of ["light", "dark"]) {
    await boot(page, theme, { width: 1280, height: 780 });
    const want = theme === "light" ? "rgb(223, 229, 231)" : "rgb(106, 113, 117)";
    const bg = await page.getByTestId("chat-header").locator("div,span").first().evaluate((el) => getComputedStyle(el).backgroundColor);
    const list = await page.getByTestId("chat-row").first().locator("div").first().evaluate((el) => getComputedStyle(el.querySelector("[aria-hidden]") || el).backgroundColor);
    expect([bg, list]).toContain(want);
  }
});

test("the list uses WhatsApp Web's own type sizes and 72px rows", async ({ page }) => {
  await boot(page, "light", { width: 1440, height: 900 });
  const m = await page.evaluate(() => {
    const row = document.querySelector("[data-testid=chat-row]");
    const px = (e) => parseFloat(getComputedStyle(e).fontSize);
    return {
      rowHeight: Math.round(row.getBoundingClientRect().height),
      name: px(row.querySelector("span[dir=auto]")),
      preview: px(row.querySelector("p")),
      search: px(document.querySelector("[data-testid=chat-list] input")),
      tab: px(document.querySelector("[data-testid=tab-all]")),
    };
  });
  expect(m).toMatchObject({ name: 17, preview: 14, search: 15, tab: 14 });
  expect(m.rowHeight).toBeGreaterThanOrEqual(72);
  expect(m.rowHeight).toBeLessThanOrEqual(73);
});

test("the chat header has no video or call controls, only search and more", async ({ page }) => {
  await boot(page, "light", { width: 1440, height: 900 });
  const labels = await page.getByTestId("chat-header").locator("button").evaluateAll((b) => b.map((x) => x.dataset.testid));
  expect(labels.filter((l) => l !== "header-back")).toEqual(["header-identity", "header-search", "header-more"]);
});
