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

test("the channel strip stays on every Instagram page, and the app sidebar is not forced shut", async ({ page }) => {
  await mock(page);
  for (const path of ["/instagram/direct/inbox", "/instagram/profile", "/instagram/activity"]) {
    await page.goto(path, { waitUntil: "domcontentloaded", timeout: 30_000 });
    const strip = page.locator("aside nav").last();
    await expect(strip.getByRole("button", { name: /whatsapp/i })).toBeVisible({ timeout: 15_000 });
    await expect(strip.getByRole("button", { name: /instagram/i })).toHaveAttribute("aria-pressed", "true");
  }
  for (const lang of ["ar", "en"]) {
    await page.addInitScript((l) => localStorage.setItem("lang", l), lang);
    await page.goto("/instagram/direct/inbox", { waitUntil: "domcontentloaded", timeout: 30_000 });
    const box = await page.locator("aside nav").last().boundingBox();
    const viewport = page.viewportSize();
    expect(box.x + box.width).toBeGreaterThan(viewport.width - 4);
  }
  const sidebar = page.locator("aside").first();
  expect((await sidebar.boundingBox()).width).toBeGreaterThan(200);
});

test("the channel strip takes you from Instagram to another channel", async ({ page }) => {
  await mock(page);
  await page.route("**/api/v1/channels/status", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([
    { provider: "instagram", connected: true, enabled_for_me: true, locked: false, lifecycle: "connected", webhook_status: "active", account_name: "shop" },
    { provider: "whatsapp", connected: true, enabled_for_me: true, locked: false, lifecycle: "connected", webhook_status: "active", account_name: "shop" },
  ]) }));
  await page.goto("/instagram/profile", { waitUntil: "domcontentloaded", timeout: 30_000 });
  await page.locator("aside nav").last().getByRole("button", { name: /whatsapp/i }).click();
  await expect(page).toHaveURL(/\/inbox$/);
});

// Pin, mute, archive and "mark unread" are real store-wide flags saved through /list-state. Each button must
// send exactly that change, and the list must show it (pinned first, mute badge, an archive you can come back from).
test("pin, mute, mark unread and archive reach the API and show in the list; archived chats can be restored", async ({ page }) => {
  const calls = [];
  const flags = {};
  await page.route("**/api/v1/**", async (route) => {
    const u = new URL(route.request().url());
    const p = u.pathname.replace("/api/v1", "");
    const send = (d, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(d) });
    const m = p.match(/^\/conversations\/(c\d)\/list-state$/);
    if (m) {
      const body = route.request().postDataJSON();
      calls.push({ id: m[1], body });
      const f = (flags[m[1]] ||= { pinned_at: null, muted_until: null, archived_at: null, marked_unread: false });
      if ("pinned" in body) f.pinned_at = body.pinned ? iso(0) : null;
      if ("archived" in body) f.archived_at = body.archived ? iso(0) : null;
      if ("marked_unread" in body) f.marked_unread = body.marked_unread;
      if (body.mute) f.muted_until = body.mute === "off" ? null : new Date(Date.now() + 8 * 3600e3).toISOString();
      return send(f);
    }
    if (p === "/inbox") {
      const all = ROWS.map((r) => ({ ...r, ...(flags[r.id] || {}) }));
      return send({ items: all.filter((r) => Boolean(r.archived_at) === (u.searchParams.get("archived") === "true")), next_cursor: null });
    }
    return route.fallback();
  });
  await page.goto("/instagram/direct/inbox", { waitUntil: "domcontentloaded" });
  const list = page.getByRole("region", { name: "Chats" });
  const names = async () => (await list.getByRole("button").allTextContents()).map((t) => t.trim().split("\n")[0]);
  await expect(list.getByRole("button", { name: "Omar Ali" })).toBeVisible({ timeout: 15_000 });

  // open Omar, pin him: he jumps above Sara and shows the pin
  await list.getByRole("button", { name: "Omar Ali" }).click();
  await page.getByRole("button", { name: "Conversation information" }).click();
  await page.getByTestId("ig-action-pin").click();
  await expect.poll(() => calls.at(-1)).toEqual({ id: "c2", body: { pinned: true } });
  await expect(list.getByRole("button", { name: "Omar Ali" }).getByLabel("Pinned")).toBeVisible();
  expect((await names())[0]).toMatch(/Omar Ali/);

  // mute for a week: badge appears; the button turns into "Unmute"
  await page.getByTestId("ig-action-mute-1w").click();
  await expect.poll(() => calls.at(-1)).toEqual({ id: "c2", body: { mute: "1w" } });
  await expect(list.getByRole("button", { name: "Omar Ali" }).getByLabel("Muted")).toBeVisible();
  await expect(page.getByTestId("ig-action-unmute")).toBeVisible();
  await page.getByTestId("ig-action-unmute").click();
  await expect.poll(() => calls.at(-1)).toEqual({ id: "c2", body: { mute: "off" } });
  await expect(list.getByRole("button", { name: "Omar Ali" }).getByLabel("Muted")).toHaveCount(0);

  // mark unread: sends the flag, the drawer closes and the row shows the unread dot
  await page.getByTestId("ig-action-unread").click();
  await expect.poll(() => calls.at(-1)).toEqual({ id: "c2", body: { marked_unread: true } });
  await expect(list.getByRole("button", { name: "Omar Ali" }).getByLabel("Unread")).toBeVisible();
  await page.getByRole("button", { name: "Conversation information" }).click();

  // archive: leaves the list, the Archived chats link appears with a count, and he can be restored from there
  await page.getByTestId("ig-action-archive").click();
  await expect.poll(() => calls.at(-1)).toEqual({ id: "c2", body: { archived: true } });
  await page.goto("/instagram/direct/inbox", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("region", { name: "Chats" }).getByRole("button", { name: "Omar Ali" })).toHaveCount(0);
  await page.getByTestId("ig-archive-link").click();
  await expect(page).toHaveURL(/\/instagram\/direct\/archived$/);
  await page.getByRole("region", { name: "Chats" }).getByRole("button", { name: "Omar Ali" }).click();
  await page.getByRole("button", { name: "Conversation information" }).click();
  await page.getByTestId("ig-action-archive").click();
  await expect.poll(() => calls.at(-1)).toEqual({ id: "c2", body: { archived: false } });
});

// The row's own "..." menu does the same real changes as the info drawer, without opening the chat.
test("the chat row menu pins and archives without opening the chat", async ({ page }) => {
  const calls = [];
  await page.route("**/api/v1/conversations/*/list-state", async (route) => {
    const body = route.request().postDataJSON();
    calls.push(body);
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ pinned_at: body.pinned ? iso(0) : null, muted_until: null, archived_at: body.archived ? iso(0) : null, marked_unread: Boolean(body.marked_unread) }) });
  });
  await page.goto("/instagram/direct/inbox", { waitUntil: "domcontentloaded" });
  const list = page.getByRole("region", { name: "Chats" });
  await expect(list.getByRole("button", { name: "Omar Ali" })).toBeVisible({ timeout: 15_000 });
  await list.getByTestId("ig-row-more").nth(1).click({ force: true });
  await expect(page.getByTestId("ig-row-menu")).toBeVisible();
  await page.getByTestId("ig-row-pin").click();
  await expect.poll(() => calls.at(-1)).toEqual({ pinned: true });
  await expect(page).toHaveURL(/\/instagram\/direct\/inbox$/);
  await list.getByTestId("ig-row-more").first().click({ force: true });
  await page.getByTestId("ig-row-archive").click();
  await expect.poll(() => calls.at(-1)).toEqual({ archived: true });
});

// Instagram's Share sheet: pick a chat and the post goes into it as a card (the Send API's MEDIA_SHARE).
test("a post can be shared into a chat from the post window", async ({ page }) => {
  const sent = [];
  await page.route("**/api/v1/conversations/*/messages", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    sent.push({ chat: route.request().url().match(/conversations\/([^/]+)\/messages/)[1], body: route.request().postDataJSON() });
    await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ id: "n1", status: "queued", created_at: iso(0) }) });
  });
  await page.goto("/instagram/p/p1", { waitUntil: "domcontentloaded" });
  await page.getByTestId("ig-share").click();
  const panel = page.getByTestId("ig-share-panel");
  await expect(panel).toBeVisible({ timeout: 15_000 });
  // only chats a shop can talk into: not requests, general or archived ones
  await expect(panel.getByText("Sara Ahmed")).toBeVisible();
  await expect(panel.getByText("Mona Zaki")).toHaveCount(0);
  await expect(panel.getByText("Hana Gad")).toHaveCount(0);
  await panel.getByPlaceholder("Search").fill("omar");
  await expect(panel.getByText("Sara Ahmed")).toHaveCount(0);
  await panel.getByTestId("ig-share-send").click();
  await expect.poll(() => sent.at(-1)).toEqual({ chat: "c2", body: { instagram_share_post_id: "p1" } });
  await expect(panel.getByText("Sent")).toBeVisible();
  await page.keyboard.press("Escape");
});
