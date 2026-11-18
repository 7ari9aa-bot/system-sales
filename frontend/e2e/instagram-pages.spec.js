import { expect, test } from "@playwright/test";

// Instagram on the web is a set of pages, each with its own address. A direct link, a refresh and
// the back button must all land on the same place, and each page must be drawn like Instagram.
const ORIGIN = process.env.BASE_URL || "http://127.0.0.1:4173";
const NOW = Date.now();
const iso = (mins) => new Date(NOW - mins * 60_000).toISOString();
const GIF = Buffer.from("R0lGODlhAQABAIAAAAUEBAAAACwAAAAAAQABAAACAkQBADs=", "base64");

function row(id, name, customerId, over = {}) {
  return { id, channel: "instagram", status: "open", customer_id: customerId, customer_name: name, customer_handle: name.toLowerCase().replace(" ", "."), customer_avatar_url: null, unread_count: 0, last_message_at: iso(20), last_message_preview: `hello from ${name}`, last_message_direction: "inbound", last_message_content_type: "text", ...over };
}
const ROWS = [row("c1", "Sara Ahmed", "cu1", { unread_count: 2 }), row("c2", "Omar Ali", "cu2"), row("c3", "Mona Zaki", "cu3", { folder: "requests" }), row("c4", "Hana Gad", "cu4", { folder: "general" })];
const POSTS = [0, 1, 2].map((i) => ({ id: `p${i + 1}`, caption: ["New shoes", "Summer bags", "Winter sale"][i], media_url: `https://cdn.test/p${i}.jpg`, media_type: "IMAGE", permalink: `https://www.instagram.com/p/${i}/`, like_count: [3, 9, 120][i], comments_count: i === 0 ? 2 : 0, timestamp: iso(500 + i * 900) }));
const COMMENTS = [
  { id: "k1", post_id: "p1", parent_id: null, username: "sara.a", body: "how much?", status: "visible", is_page_reply: false, commented_at: iso(30), like_count: 1 },
  { id: "k2", post_id: "p1", parent_id: "k1", username: "shop", body: "450 EGP", status: "visible", is_page_reply: true, commented_at: iso(20), like_count: 0 },
  { id: "k3", post_id: "p1", parent_id: null, username: "omar_ali", body: "do you ship to Alex?", status: "visible", is_page_reply: false, commented_at: iso(3000), like_count: 0 },
];
const ACCOUNT = { username: "fihrist.store", name: "Fihrist Store", profile_picture_url: "https://cdn.test/av.jpg", followers_count: 15230, follows_count: 87, media_count: 3, biography: "Bags and shoes", website: "https://fihrist.store" };

async function mock(page, { account = ACCOUNT } = {}) {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.context().addCookies([{ name: "csrf_token", value: "x", url: new URL(ORIGIN).origin }]);
  await page.route("https://cdn.test/**", (route) => route.fulfill({ status: 200, contentType: "image/gif", body: GIF }));
  await page.route("**/api/v1/**", async (route) => {
    const u = new URL(route.request().url());
    const p = u.pathname.replace("/api/v1", "");
    const send = (d, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(d) });
    if (p === "/auth/me") return send({ id: "u", email: "owner@shop.com", full_name: "Owner", is_platform_admin: false, tenants: [{ id: "t", name: "T", role: "owner" }] });
    if (p === "/channels/status") return send([{ provider: "instagram", connected: true, enabled_for_me: true, locked: false, lifecycle: "connected", webhook_status: "active", account_name: "shop" }]);
    if (p === "/inbox") return send({ items: u.searchParams.get("archived") === "true" ? [] : ROWS, next_cursor: null });
    if (/^\/conversations\/c\d\/messages$/.test(p)) return send({ items: [], next_cursor: null });
    if (p === "/social/account") return account ? send(account) : send({ detail: "no" }, 502);
    if (p === "/social/posts") return send({ items: POSTS });
    const m = p.match(/^\/social\/posts\/([^/]+)\/comments$/);
    if (m) return send({ items: COMMENTS.filter((c) => c.post_id === m[1]) });
    if (p === "/customers/cu1") return send({ id: "cu1", name: "Sara Ahmed", phone: null, email: null, lifetime_value: "250.00", is_blocked: false, created_at: iso(100000), tags: [], identities: [{ id: "i1", channel: "instagram", external_id: "1784", username: "sara.a", verified: true, follower_count: 980, follows_you: true }], addresses: [], notes: [], extra: {}, version: 1 });
    if (p === "/customers/missing") return send({ detail: "not found" }, 404);
    return send({ items: [], next_cursor: null });
  });
}

test.beforeEach(async ({ page }) => { await mock(page); });

test("/instagram and the old /instagram/direct go to the messages page", async ({ page }) => {
  await page.goto("/instagram", { waitUntil: "domcontentloaded" });
  await expect(page).toHaveURL(/\/instagram\/direct\/inbox$/);
  await page.goto("/instagram/direct", { waitUntil: "domcontentloaded" });
  await expect(page).toHaveURL(/\/instagram\/direct\/inbox$/);
});

test("picking the Instagram tile on /inbox lands on the messages page, and All channels comes back", async ({ page }) => {
  await page.route("**/api/v1/channels/status", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([
    { provider: "whatsapp", connected: true, enabled_for_me: true, locked: false, lifecycle: "connected", webhook_status: "active", account_name: "shop" },
    { provider: "instagram", connected: true, enabled_for_me: true, locked: false, lifecycle: "connected", webhook_status: "active", account_name: "shop" },
  ]) }));
  await page.goto("/inbox", { waitUntil: "domcontentloaded" });
  await expect(page).toHaveURL(/\/inbox$/);
  await page.getByRole("button", { name: "Instagram", exact: true }).click();
  await expect(page).toHaveURL(/\/instagram\/direct\/inbox$/);
  await page.getByRole("link", { name: /All channels|كل القنوات/ }).click();
  await expect(page).toHaveURL(/\/inbox$/);
});

test("the side menu is Instagram's, limited to what the API allows", async ({ page }) => {
  await page.goto("/instagram/direct/inbox", { waitUntil: "domcontentloaded" });
  const nav = page.getByRole("navigation", { name: /Instagram navigation|تنقل إنستغرام/ });
  for (const name of [/Messages|الرسائل/, /Notifications|الإشعارات/, /Profile|الملف الشخصي/]) await expect(nav.getByRole("link", { name })).toBeVisible();
  await expect(nav.getByRole("button", { name: /Create|إنشاء/ })).toBeVisible();
  // no Home, Explore or Reels: Instagram's API gives a shop none of them.
  await expect(nav.getByRole("link", { name: /^(Home|Explore|Reels)$/ })).toHaveCount(0);
});

test("messages are split into Primary, General and Requests like Instagram", async ({ page }) => {
  await page.goto("/instagram/direct/inbox", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("button", { name: "Sara Ahmed" })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole("button", { name: "Omar Ali" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Mona Zaki" })).toHaveCount(0);
  await page.getByRole("link", { name: /General|العامة/ }).click();
  await expect(page).toHaveURL(/\/instagram\/direct\/general$/);
  await expect(page.getByRole("button", { name: "Hana Gad" })).toBeVisible();
  await page.getByRole("link", { name: /Requests|الطلبات/ }).click();
  await expect(page).toHaveURL(/\/instagram\/direct\/requests$/);
  await expect(page.getByRole("button", { name: "Mona Zaki" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Sara Ahmed" })).toHaveCount(0);
});

test("a direct link to a chat opens it, and a refresh keeps it", async ({ page }) => {
  await page.goto("/instagram/direct/t/c2", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("button", { name: "Omar Ali", exact: true })).toHaveAttribute("aria-pressed", "true", { timeout: 15_000 });
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page).toHaveURL(/\/instagram\/direct\/t\/c2$/);
  await expect(page.getByRole("button", { name: "Omar Ali", exact: true })).toHaveAttribute("aria-pressed", "true", { timeout: 15_000 });
});

test("a chat in the Requests folder opens from its own link", async ({ page }) => {
  await page.goto("/instagram/direct/t/c3", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: /Message requests|طلبات المراسلة/ })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole("button", { name: "Mona Zaki", exact: true })).toHaveAttribute("aria-pressed", "true");
});

test("choosing a chat puts it in the address and Back returns to the previous one", async ({ page }) => {
  await page.goto("/instagram/direct/inbox", { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "Sara Ahmed", exact: true }).click();
  await expect(page).toHaveURL(/\/instagram\/direct\/t\/c1$/);
  await page.getByRole("button", { name: "Omar Ali", exact: true }).click();
  await expect(page).toHaveURL(/\/instagram\/direct\/t\/c2$/);
  await page.goBack();
  await expect(page).toHaveURL(/\/instagram\/direct\/t\/c1$/);
  await expect(page.getByRole("button", { name: "Sara Ahmed", exact: true })).toHaveAttribute("aria-pressed", "true");
});

test("an unknown chat says so instead of showing an empty page", async ({ page }) => {
  await page.goto("/instagram/direct/t/nope", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("alert")).toContainText(/isn't available|غير موجودة/, { timeout: 15_000 });
});

test("the profile shows the shop's own account and a grid of its posts", async ({ page }) => {
  await page.goto("/instagram/profile", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "fihrist.store" })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("15.2K").first()).toBeVisible();
  await expect(page.getByText("Bags and shoes")).toBeVisible();
  await expect(page.getByTestId("ig-grid-tile")).toHaveCount(3);
});

test("a post opens over the grid from its own link, Back closes it, and the arrows move between posts", async ({ page }) => {
  await page.goto("/instagram/profile", { waitUntil: "domcontentloaded" });
  await page.getByTestId("ig-grid-tile").first().click();
  await expect(page).toHaveURL(/\/instagram\/p\/p1$/);
  await expect(page.getByTestId("ig-post-card")).toBeVisible();
  await expect(page.getByTestId("ig-comment")).toHaveCount(3); // sara, omar and the shop's reply under sara
  await page.getByRole("button", { name: /Next|التالي/ }).click();
  await expect(page).toHaveURL(/\/instagram\/p\/p2$/);
  await page.goBack(); // the arrows replace the entry, so one Back leaves the post view
  await expect(page).toHaveURL(/\/instagram\/profile$/);
  await expect(page.getByTestId("ig-post-card")).toHaveCount(0);
});

test("a direct link to a post opens it, and Escape closes it", async ({ page }) => {
  await page.goto("/instagram/p/p2", { waitUntil: "domcontentloaded" });
  await expect(page.getByTestId("ig-post-card")).toContainText("Summer bags", { timeout: 15_000 });
  await page.keyboard.press("Escape");
  await expect(page).toHaveURL(/\/instagram\/profile$/);
});

test("the shop's own reply carries its username, not 'page'", async ({ page }) => {
  await page.goto("/instagram/p/p1", { waitUntil: "domcontentloaded" });
  await expect(page.getByTestId("ig-post-card")).toContainText("450 EGP", { timeout: 15_000 });
  await expect(page.getByTestId("ig-post-card").locator("bdi", { hasText: /^fihrist\.store$/ }).first()).toBeVisible();
});

test("notifications list customers' comments and flag the ones still unanswered", async ({ page }) => {
  await page.goto("/instagram/activity", { waitUntil: "domcontentloaded" });
  await expect(page.getByTestId("ig-activity-row")).toHaveCount(2, { timeout: 15_000 });
  await expect(page.getByTestId("ig-activity-row").filter({ hasText: "omar_ali" })).toContainText(/Needs reply|بدون رد/);
  await expect(page.getByTestId("ig-activity-row").filter({ hasText: "sara.a" })).not.toContainText(/Needs reply|بدون رد/);
  await page.getByTestId("ig-activity-row").first().click();
  await expect(page).toHaveURL(/\/instagram\/p\/p1$/);
});

test("a customer's profile shows their Instagram details and what the shop knows", async ({ page }) => {
  await page.goto("/instagram/u/cu1", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "sara.a" })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("980")).toBeVisible();
  await expect(page.getByText(/Follows you|يتابعك/)).toBeVisible();
  await expect(page.getByRole("link", { name: /^(Message|مراسلة)$/ })).toHaveAttribute("href", "/instagram/direct/t/c1");
});

test("an unknown customer says so instead of showing an empty page", async ({ page }) => {
  await page.goto("/instagram/u/missing", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("alert")).toBeVisible({ timeout: 15_000 });
});

test("when Instagram refuses the account details, the page still works and says so", async ({ page }) => {
  await mock(page, { account: null });
  await page.goto("/instagram/profile", { waitUntil: "domcontentloaded" });
  await expect(page.getByTestId("ig-grid-tile")).toHaveCount(3, { timeout: 15_000 });
  await expect(page.getByRole("alert")).toContainText(/account|الحساب/);
});
