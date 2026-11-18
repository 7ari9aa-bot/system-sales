import { expect, test } from "@playwright/test";

// Each Instagram section is its own page with its own address. A direct link, a refresh and the
// back button must all land on the same place.
const ORIGIN = process.env.BASE_URL || "http://127.0.0.1:4173";
const NOW = Date.now();
const iso = (mins) => new Date(NOW - mins * 60_000).toISOString();

function row(id, name, customerId, over = {}) {
  return { id, channel: "instagram", status: "open", customer_id: customerId, customer_name: name, customer_avatar_url: null, unread_count: 0, last_message_at: iso(20), last_message_preview: `hello from ${name}`, last_message_direction: "inbound", last_message_content_type: "text", ...over };
}
const ROWS = [row("c1", "Sara Ahmed", "cu1"), row("c2", "Omar Ali", "cu2"), row("c3", "Mona Zaki", "cu3", { folder: "requests" })];
const POSTS = [
  { id: "p1", caption: "New shoes", media_url: null, permalink: "https://www.instagram.com/p/a/", comments_count: 0, timestamp: iso(500), media_type: "IMAGE" },
  { id: "p2", caption: "Summer bags", media_url: null, permalink: "https://www.instagram.com/p/b/", comments_count: 0, timestamp: iso(900), media_type: "IMAGE" },
];

async function mock(page) {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.context().addCookies([{ name: "csrf_token", value: "x", url: new URL(ORIGIN).origin }]);
  await page.route("**/api/v1/**", async (route) => {
    const u = new URL(route.request().url());
    const p = u.pathname.replace("/api/v1", "");
    const send = (d, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(d) });
    if (p === "/auth/me") return send({ id: "u", email: "owner@shop.com", full_name: "Owner", is_platform_admin: false, tenants: [{ id: "t", name: "T", role: "owner" }] });
    if (p === "/channels/status") return send([{ provider: "instagram", connected: true, enabled_for_me: true, locked: false, lifecycle: "connected", webhook_status: "active", account_name: "shop" }]);
    if (p === "/inbox") return send({ items: u.searchParams.get("archived") === "true" ? [] : ROWS, next_cursor: null });
    if (/^\/conversations\/c\d\/messages$/.test(p)) return send({ items: [], next_cursor: null });
    if (p === "/customers/cu1") return send({ id: "cu1", name: "Sara Ahmed", phone: null, email: null, lifetime_value: "250.00", is_blocked: false, created_at: iso(100000), tags: [], identities: [], addresses: [], notes: [], extra: {}, version: 1 });
    if (p === "/customers/missing") return send({ detail: "not found" }, 404);
    if (p === "/social/instagram/posts" || p.endsWith("/posts")) return send({ items: POSTS });
    if (p.startsWith("/social/")) return send({ items: [] });
    return send({ items: [], next_cursor: null });
  });
}

test.beforeEach(async ({ page }) => { await mock(page); });

test("/inbox with only Instagram connected moves to /instagram/direct", async ({ page }) => {
  await page.goto("/inbox", { waitUntil: "domcontentloaded" });
  await expect(page).toHaveURL(/\/instagram\/direct$/);
});

test("picking the Instagram tile on /inbox lands on /instagram/direct", async ({ page }) => {
  // WhatsApp is connected too, so /inbox stays put until the person chooses Instagram.
  await page.route("**/api/v1/channels/status", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([
    { provider: "whatsapp", connected: true, enabled_for_me: true, locked: false, lifecycle: "connected", webhook_status: "active", account_name: "shop" },
    { provider: "instagram", connected: true, enabled_for_me: true, locked: false, lifecycle: "connected", webhook_status: "active", account_name: "shop" },
  ]) }));
  await page.goto("/inbox", { waitUntil: "domcontentloaded" });
  await expect(page).toHaveURL(/\/inbox$/);
  await page.getByRole("button", { name: "Instagram", exact: true }).click();
  await expect(page).toHaveURL(/\/instagram\/direct$/);
  // The rail on the Instagram pages leads back to all channels.
  await page.getByRole("link", { name: /All channels|كل القنوات/ }).click();
  await expect(page).toHaveURL(/\/inbox$/);
});

test("a direct link to a chat opens it, and a refresh keeps it", async ({ page }) => {
  await page.goto("/instagram/direct/c2", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("button", { name: /Omar Ali/ }).first()).toHaveAttribute("aria-pressed", "true");
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page).toHaveURL(/\/instagram\/direct\/c2$/);
  await expect(page.getByRole("button", { name: /Omar Ali/ }).first()).toHaveAttribute("aria-pressed", "true");
});

test("choosing a chat puts it in the address and Back returns to the previous one", async ({ page }) => {
  await page.goto("/instagram/direct/c1", { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: /Omar Ali/ }).first().click();
  await expect(page).toHaveURL(/\/instagram\/direct\/c2$/);
  await page.goBack();
  await expect(page).toHaveURL(/\/instagram\/direct\/c1$/);
  await expect(page.getByRole("button", { name: /Sara Ahmed/ }).first()).toHaveAttribute("aria-pressed", "true");
});

test("the section links move between pages and mark the current one", async ({ page }) => {
  await page.goto("/instagram/direct", { waitUntil: "domcontentloaded" });
  const nav = page.getByRole("navigation", { name: /Instagram sections|أقسام إنستغرام/ });
  for (const [name, path] of [["Requests", "requests"], ["Comments", "comments"], ["Posts", "posts"], ["Messages", "direct"]]) {
    await nav.getByRole("link", { name }).click();
    await expect(page).toHaveURL(new RegExp(`/instagram/${path}$`));
    await expect(nav.getByRole("link", { name })).toHaveAttribute("aria-current", "page");
  }
});

test("requests shows only the Requests folder", async ({ page }) => {
  await page.goto("/instagram/requests", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("button", { name: /Mona Zaki/ }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: /Sara Ahmed/ })).toHaveCount(0);
});

test("a direct link to a post opens that post", async ({ page }) => {
  await page.goto("/instagram/posts/p2", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("button", { name: /Summer bags/ }).first()).toHaveAttribute("aria-pressed", "true");
});

test("the profile page shows the customer and links to their chat", async ({ page }) => {
  await page.goto("/instagram/profile/cu1", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Sara Ahmed" })).toBeVisible();
  await expect(page.getByText("250.00")).toBeVisible();
  await page.getByRole("link", { name: /hello from Sara Ahmed/ }).click();
  await expect(page).toHaveURL(/\/instagram\/direct\/c1$/);
});

test("an unknown customer says so instead of showing an empty page", async ({ page }) => {
  await page.goto("/instagram/profile/missing", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("alert")).toBeVisible();
});

test("/instagram alone goes to the messages page", async ({ page }) => {
  await page.goto("/instagram", { waitUntil: "domcontentloaded" });
  await expect(page).toHaveURL(/\/instagram\/direct$/);
});
